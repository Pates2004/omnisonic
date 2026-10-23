[CmdletBinding()]
param([switch]$Recover, [Alias('ProjectRoot')][string]$RecoveryProjectRoot = '')

# Source-only updater primitives. The caller owns runtime.lock during activation.
# A frozen copy of this file can recover an interrupted transaction independently
# of a partially replaced live launcher or updater.
$script:DesktopUpdateRuntimePath = $MyInvocation.MyCommand.Path

function Assert-DesktopUpdateRelativePath {
    param([string]$Path, [switch]$AllowManifest)
    if (-not $Path -or $Path.Length -gt 240 -or $Path.Contains('\') -or
        $Path -match '[\x00-\x1f\x7f:<>"|?*]' -or $Path.StartsWith('/')) {
        throw "Unsafe update path: $Path"
    }
    $parts = $Path.Split('/')
    foreach ($part in $parts) {
        if (-not $part -or $part -in @('.', '..') -or $part -match '[. ]$' -or
            $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])(?:\.|$)' -or
            $part -ieq '.git' -or
            $part -imatch '^AGENTS(?:\.override)?\.md$') {
            throw "Unsafe update path: $Path"
        }
    }
    if ($parts[0] -imatch '^(?:\.git|\.launcher|config|presets|Workspace|Forme|Trash|Snapshots|Installfiles|omnivoice-local-launcher|power-switch-backups|\.venv|\.cache.*|env(?:[.-].*)?|venv(?:[.-].*)?|settings\.json|start\.bat|\.gitmodules)$') {
        throw "Protected update path: $Path"
    }
    if (-not $AllowManifest -and $Path -ieq 'update_manifest.json') {
        throw 'The update manifest cannot list itself.'
    }
    return $Path
}

function Assert-DesktopUpdateLocalPath {
    param([string]$Root, [string]$Path, [switch]$AllowRoot)
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    if ($rootPath -match '^[A-Za-z]:$') { throw 'A drive root cannot be an update project or staging area.' }
    if (($full -eq $rootPath -and -not $AllowRoot) -or
        ($full -ne $rootPath -and -not $full.StartsWith($rootPath + '\', [StringComparison]::OrdinalIgnoreCase))) {
        throw "Update path escapes its owned area: $full"
    }
    # Also inspect root ancestors: a project/staging junction is not a safe root.
    $current = $full
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Update paths cannot contain links or reparse points: $current"
            }
            if ($current -ne $full -and -not $item.PSIsContainer) { throw "Update path has a file as its parent: $current" }
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
    return $full
}

function Get-DesktopUpdateFileBytes {
    param([string]$Path, [switch]$Raw)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or $item.Length -gt 8MB -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Invalid or oversized update file: $Path"
    }
    [byte[]]$bytes = [IO.File]::ReadAllBytes($item.FullName)
    if ($Raw) { return ,$bytes }
    # The manifest covers UTF-8 source text, not model/audio/binary payloads.
    $utf8 = New-Object Text.UTF8Encoding($false, $true)
    try { $source = $utf8.GetString($bytes) }
    catch { throw "Update files must be UTF-8 source text: $Path" }
    if ($source.Contains([string][char]0)) { throw "Binary update payload refused: $Path" }
    return ,$utf8.GetBytes($source.Replace("`r`n", "`n"))
}

function Get-DesktopUpdateFileHash {
    param([string]$Path, [switch]$Raw)
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        if ($Raw) {
            $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
            if ($item.PSIsContainer -or $item.Length -gt 64MB -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Invalid or oversized update file: $Path" }
            $stream = [IO.File]::OpenRead($item.FullName)
            return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
        }
        return [BitConverter]::ToString($sha.ComputeHash((Get-DesktopUpdateFileBytes $Path))).Replace('-', '').ToLowerInvariant()
    } finally { if ($stream) { $stream.Dispose() }; $sha.Dispose() }
}

function Get-DesktopUpdateOptionalHash {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return Get-DesktopUpdateFileHash $Path -Raw
}

function Read-DesktopUpdateManifest {
    param([string]$Path)
    $file = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($file.Length -gt 1MB) { throw 'Update manifest is too large.' }
    $value = [Text.Encoding]::UTF8.GetString((Get-DesktopUpdateFileBytes $Path -Raw)) | ConvertFrom-Json -ErrorAction Stop
    if ($value.schema -is [bool] -or $value.schema -ne 1 -or $value.algorithm -cne 'sha256-lf' -or
        -not ($value.version -is [string]) -or $value.version -notmatch '^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$' -or
        -not ($value.files -is [Array]) -or
        @($value.files).Count -lt 1 -or @($value.files).Count -gt 2048) {
        throw 'Unsupported update manifest.'
    }
    $seen = @{}
    foreach ($entry in @($value.files)) {
        if (-not ($entry.path -is [string]) -or -not ($entry.sha256 -is [string]) -or
            $entry.sha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Invalid update manifest entry.' }
        $relative = Assert-DesktopUpdateRelativePath $entry.path
        if ($seen.ContainsKey($relative)) { throw "Duplicate update path: $relative" }
        $seen[$relative] = $true
    }
    foreach ($relative in @($seen.Keys)) {
        $parent = $relative
        while ($parent.Contains('/')) {
            $parent = $parent.Substring(0, $parent.LastIndexOf('/'))
            if ($seen.ContainsKey($parent)) { throw "Conflicting file/directory update paths: $relative" }
        }
    }
    if (-not $seen.ContainsKey('start_desktop.bat')) { throw 'Update manifest has no frozen bootstrap.' }
    return $value
}

function Expand-DesktopUpdateEntry {
    param($Entry, [string]$Destination, [long]$Limit = 8MB)
    if ($Entry.Length -gt $Limit) { throw 'Update archive entry is too large.' }
    $source = $Entry.Open()
    $target = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $buffer = New-Object byte[] 32768
        [long]$total = 0
        while (($read = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $total += $read
            if ($total -gt $Limit -or $total -gt $Entry.Length) { throw 'Expanded update entry exceeded its declared size.' }
            $target.Write($buffer, 0, $read)
        }
        if ($total -ne $Entry.Length) { throw 'Update archive entry is truncated.' }
        $target.Flush($true)
    } finally { $target.Dispose(); $source.Dispose() }
}

function Expand-DesktopUpdateArchive {
    param([string]$ArchivePath, [string]$Destination)
    $archiveFile = Get-Item -LiteralPath $ArchivePath -Force -ErrorAction Stop
    if ($archiveFile.Length -gt 32MB -or $archiveFile.PSIsContainer -or
        ($archiveFile.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Invalid or oversized update archive.' }
    $destinationPath = Assert-DesktopUpdateLocalPath $Destination $Destination -AllowRoot
    if (Test-Path -LiteralPath $destinationPath) { throw 'Update staging destination already exists.' }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archiveFile.FullName)
    try {
        if ($zip.Entries.Count -gt 4096) { throw 'Update archive has too many entries.' }
        $entries = @{}
        $prefix = $null
        [long]$expanded = 0
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName
            if ($name.Contains('\') -or $name.StartsWith('/') -or -not $name.Contains('/')) { throw "Invalid archive root: $name" }
            $slash = $name.IndexOf('/')
            $rootName = $name.Substring(0, $slash)
            Assert-DesktopUpdateRelativePath ('archive/' + $rootName) | Out-Null
            if ($null -eq $prefix) { $prefix = $rootName }
            if ($prefix -cne $rootName) { throw 'Update archive contains multiple roots.' }
            $relative = $name.Substring($slash + 1)
            $isDirectory = $name.EndsWith('/')
            if ($isDirectory) { $relative = $relative.TrimEnd('/') }
            if (-not $relative) { continue }
            # Validate even unlisted entries; protected files are never extracted.
            $parts = $relative.Split('/')
            foreach ($part in $parts) {
                if (-not $part -or $part -in @('.', '..') -or $part -match '[. ]$|[\x00-\x1f\x7f:<>"|?*]' -or
                    $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])(?:\.|$)') { throw "Unsafe archive path: $name" }
            }
            if ($relative.Length -gt 240) { throw 'Archive path is too long.' }
            $unixType = ($entry.ExternalAttributes -shr 16) -band 0xF000
            if ($unixType -ne 0 -and $unixType -notin @(0x8000, 0x4000)) { throw "Archive link or special entry refused: $name" }
            if ($entries.ContainsKey($relative)) { throw "Duplicate archive path: $name" }
            $expanded += $entry.Length
            if ($entry.Length -gt 8MB -or $expanded -gt 64MB) { throw 'Expanded update archive is too large.' }
            $entries[$relative] = [pscustomobject]@{ Entry = $entry; Directory = $isDirectory }
        }
        foreach ($name in @($entries.Keys)) {
            $parent = $name
            while ($parent.Contains('/')) {
                $parent = $parent.Substring(0, $parent.LastIndexOf('/'))
                if ($entries.ContainsKey($parent) -and -not $entries[$parent].Directory) { throw 'Archive file/directory collision.' }
            }
        }
        if (-not $entries.ContainsKey('update_manifest.json') -or $entries['update_manifest.json'].Directory) { throw 'Archive has no update manifest.' }
        [IO.Directory]::CreateDirectory($destinationPath) | Out-Null
        $sourceRoot = Join-Path $destinationPath 'source'
        [IO.Directory]::CreateDirectory($sourceRoot) | Out-Null
        $manifestPath = Join-Path $sourceRoot 'update_manifest.json'
        $manifestEntry = $entries['update_manifest.json'].Entry
        if ($manifestEntry.Length -gt 1MB) { throw 'Update manifest is too large.' }
        Expand-DesktopUpdateEntry $manifestEntry $manifestPath -Limit 1MB
        $manifest = Read-DesktopUpdateManifest $manifestPath
        foreach ($file in @($manifest.files)) {
            if (-not $entries.ContainsKey($file.path) -or $entries[$file.path].Directory) { throw "Archive source file missing: $($file.path)" }
            $target = Assert-DesktopUpdateLocalPath $sourceRoot (Join-Path $sourceRoot $file.path.Replace('/', '\'))
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
            Expand-DesktopUpdateEntry $entries[$file.path].Entry $target
            if ((Get-DesktopUpdateFileHash $target) -cne $file.sha256) { throw "Archive source hash mismatch: $($file.path)" }
        }
        return [pscustomobject]@{ Root = $sourceRoot; Manifest = $manifest }
    } finally { $zip.Dispose() }
}

function New-DesktopUpdatePlan {
    param([string]$ProjectRoot, [string]$PreparedRoot)
    $root = Assert-DesktopUpdateLocalPath $ProjectRoot $ProjectRoot -AllowRoot
    $prepared = Assert-DesktopUpdateLocalPath $PreparedRoot $PreparedRoot -AllowRoot
    $oldManifestPath = Assert-DesktopUpdateLocalPath $root (Join-Path $root 'update_manifest.json')
    $newManifestPath = Assert-DesktopUpdateLocalPath $prepared (Join-Path $prepared 'update_manifest.json')
    $old = Read-DesktopUpdateManifest $oldManifestPath
    $new = Read-DesktopUpdateManifest $newManifestPath
    $oldFiles = @{}
    $newFiles = @{}
    foreach ($file in @($old.files)) {
        $path = Assert-DesktopUpdateLocalPath $root (Join-Path $root $file.path.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $path) -or (Get-DesktopUpdateFileHash $path) -cne $file.sha256) { throw "Local source was modified or deleted: $($file.path)" }
        $oldFiles[$file.path] = $file.sha256
    }
    foreach ($file in @($new.files)) {
        $source = Assert-DesktopUpdateLocalPath $prepared (Join-Path $prepared $file.path.Replace('/', '\'))
        if ((Get-DesktopUpdateFileHash $source) -cne $file.sha256) { throw "Prepared source hash mismatch: $($file.path)" }
        $target = Assert-DesktopUpdateLocalPath $root (Join-Path $root $file.path.Replace('/', '\'))
        if (-not $oldFiles.ContainsKey($file.path) -and (Test-Path -LiteralPath $target)) { throw "Unknown existing file would be overwritten: $($file.path)" }
        $newFiles[$file.path] = $file.sha256
    }
    if ($oldFiles['start_desktop.bat'] -cne $newFiles['start_desktop.bat']) { throw 'The frozen start_desktop.bat changed. Install this version manually.' }
    $plan = New-Object 'Collections.Generic.List[object]'
    $paths = @(@($oldFiles.Keys) + @($newFiles.Keys) | Sort-Object -Unique)
    foreach ($relative in $paths) {
        if ($relative -ieq 'start_desktop.bat' -or
            ($oldFiles.ContainsKey($relative) -and $newFiles.ContainsKey($relative) -and $oldFiles[$relative] -ceq $newFiles[$relative])) { continue }
        $target = Join-Path $root $relative.Replace('/', '\')
        $source = if ($newFiles.ContainsKey($relative)) { Join-Path $prepared $relative.Replace('/', '\') } else { $null }
        $plan.Add([pscustomobject]@{ Path = $relative; OldHash = Get-DesktopUpdateOptionalHash $target; NewHash = if ($source) { Get-DesktopUpdateFileHash $source -Raw } else { $null } })
    }
    if ((Get-DesktopUpdateFileHash $oldManifestPath -Raw) -cne (Get-DesktopUpdateFileHash $newManifestPath -Raw)) {
        $plan.Add([pscustomobject]@{ Path = 'update_manifest.json'; OldHash = Get-DesktopUpdateFileHash $oldManifestPath -Raw; NewHash = Get-DesktopUpdateFileHash $newManifestPath -Raw })
    }
    return [pscustomobject]@{ Root = $root; PreparedRoot = $prepared; Entries = $plan.ToArray(); OldManifest = $old; NewManifest = $new }
}

function Invoke-DesktopUpdateGit {
    param([string]$Git, [string]$Root, [string[]]$Arguments, [switch]$AllowFailure)
    $output = @(& $Git -C $Root @Arguments 2>&1)
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $AllowFailure) { throw "Git update check failed ($code): $($output -join ' ')" }
    return [pscustomobject]@{ Code = $code; Lines = @($output | ForEach-Object { [string]$_ }) }
}

function Get-DesktopUpdateGitContext {
    param([string]$ProjectRoot, [string]$TargetSha = '')
    $root = Assert-DesktopUpdateLocalPath $ProjectRoot $ProjectRoot -AllowRoot
    $dotGit = Join-Path $root '.git'
    if (-not (Test-Path -LiteralPath $dotGit)) { return $null }
    if (-not (Get-Item -LiteralPath $dotGit -Force).PSIsContainer) { throw 'Git worktrees/redirection are not supported by automatic updates.' }
    Assert-DesktopUpdateLocalPath $root $dotGit | Out-Null
    foreach ($name in @('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_NAMESPACE', 'GIT_CONFIG', 'GIT_CONFIG_SYSTEM', 'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_COUNT')) {
        if ([Environment]::GetEnvironmentVariable($name, 'Process')) { throw "Git redirection environment is not supported: $name" }
    }
    $gitCommand = Get-Command git.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $git = $gitCommand.Source
    $top = (Invoke-DesktopUpdateGit $git $root @('rev-parse', '--show-toplevel')).Lines -join ''
    if ([IO.Path]::GetFullPath($top).TrimEnd('\', '/') -ine $root) { throw 'Git root does not match the application.' }
    $branch = (Invoke-DesktopUpdateGit $git $root @('symbolic-ref', '--quiet', 'HEAD')).Lines -join ''
    if ($branch -cne 'refs/heads/master') { throw 'Automatic Git updates require the master branch.' }
    $origin = (Invoke-DesktopUpdateGit $git $root @('remote', 'get-url', 'origin')).Lines -join ''
    if ($origin -notmatch '^(?i:https://github\.com/Pates2004/omnisonic(?:\.git)?/?|git@github\.com:Pates2004/omnisonic(?:\.git)?)$') { throw 'Automatic Git updates require the official OmniSonic origin.' }
    foreach ($key in @('core.hooksPath', 'core.worktree', 'core.sparseCheckout', 'core.splitIndex', 'core.fsmonitor', 'extensions.worktreeConfig', 'extensions.objectFormat')) {
        $configured = Invoke-DesktopUpdateGit $git $root @('config', '--get', $key) -AllowFailure
        if ($configured.Code -eq 0 -and (($key -eq 'core.hooksPath') -or ($configured.Lines -join '') -notin @('', 'false'))) { throw "Unsupported Git configuration for automatic updates: $key" }
    }
    $hooks = Join-Path $dotGit 'hooks'
    if (Test-Path -LiteralPath $hooks) {
        Assert-DesktopUpdateLocalPath $root $hooks | Out-Null
        foreach ($hook in Get-ChildItem -LiteralPath $hooks -Force) {
            if (-not $hook.Name.EndsWith('.sample', [StringComparison]::OrdinalIgnoreCase)) { throw 'Custom Git hooks require manual updates.' }
        }
    }
    foreach ($relative in @('index', 'HEAD', 'config', 'objects', 'info', 'info/attributes', 'packed-refs', 'refs', 'refs/heads', 'refs/heads/master')) {
        Assert-DesktopUpdateLocalPath $root (Join-Path $dotGit $relative.Replace('/', '\')) | Out-Null
    }
    if (Test-Path -LiteralPath (Join-Path $dotGit 'objects/info/alternates')) { throw 'Git alternate object databases require manual updates.' }
    if (@(Get-ChildItem -LiteralPath $dotGit -Filter 'sharedindex.*' -Force).Count) { throw 'Split Git indexes require manual updates.' }
    foreach ($relative in @('index.lock', 'HEAD.lock', 'MERGE_HEAD', 'rebase-apply', 'rebase-merge', 'CHERRY_PICK_HEAD', 'refs/heads/master.lock')) {
        if (Test-Path -LiteralPath (Join-Path $dotGit $relative)) { throw "Git operation already in progress: $relative" }
    }
    $flags = (Invoke-DesktopUpdateGit $git $root @('-c', 'core.quotepath=false', 'ls-files', '-v')).Lines
    if (@($flags | Where-Object { $_ -cmatch '^[a-zS]' }).Count) { throw 'Assume-unchanged or sparse Git indexes require manual updates.' }
    $trackedPaths = @($flags | ForEach-Object { $_.Substring(2) })
    for ($offset = 0; $offset -lt $trackedPaths.Count; $offset += 50) {
        $last = [Math]::Min($offset + 49, $trackedPaths.Count - 1)
        $batch = @($trackedPaths[$offset..$last])
        $attributes = (Invoke-DesktopUpdateGit $git $root (@('check-attr', '-a', '--') + $batch)).Lines
        if (@($attributes | Where-Object { $_ -match ': (?:filter|working-tree-encoding|ident): (?!unspecified$|unset$)' }).Count) { throw 'Git content transformations require manual updates.' }
    }
    if (@((Invoke-DesktopUpdateGit $git $root @('status', '--porcelain=v1', '--untracked-files=no')).Lines).Count) { throw 'Local Git changes require a manual update.' }
    $oldSha = (Invoke-DesktopUpdateGit $git $root @('rev-parse', 'HEAD')).Lines -join ''
    if ($TargetSha) {
        if ($TargetSha -cnotmatch '^[a-f0-9]{40}$') { throw 'Invalid update commit SHA.' }
        $resolved = (Invoke-DesktopUpdateGit $git $root @('rev-parse', ($TargetSha + '^{commit}'))).Lines -join ''
        if ($resolved -cne $TargetSha) { throw 'Fetched update commit does not match the approved SHA.' }
        if ((Invoke-DesktopUpdateGit $git $root @('merge-base', '--is-ancestor', $oldSha, $TargetSha) -AllowFailure).Code -ne 0) { throw 'Update is not a Git fast-forward.' }
    }
    return [pscustomobject]@{ Git = $git; Root = $root; OldSha = $oldSha; Ref = $branch; IndexPath = Join-Path $dotGit 'index'; HeadHash = Get-DesktopUpdateFileHash (Join-Path $dotGit 'HEAD') -Raw }
}

function Get-DesktopUpdateGitBlobHash {
    param([byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA1]::Create()
    try {
        [byte[]]$header = [Text.Encoding]::ASCII.GetBytes(('blob ' + $Bytes.Length + [char]0))
        $combined = New-Object byte[] ($header.Length + $Bytes.Length)
        [Array]::Copy($header, 0, $combined, 0, $header.Length)
        [Array]::Copy($Bytes, 0, $combined, $header.Length, $Bytes.Length)
        return [BitConverter]::ToString($sha.ComputeHash($combined)).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Test-DesktopUpdateGitTextConversion {
    param($Context, [string]$TargetSha, [string]$RelativePath)
    # Query the approved tree, not the installed .gitattributes. Never execute
    # filters or guess checkout rules when an older Git lacks --source.
    try {
        $result = Invoke-DesktopUpdateGit $Context.Git $Context.Root @(
            '-c', 'core.quotepath=false', 'check-attr', ('--source=' + $TargetSha),
            'text', 'eol', 'filter', 'working-tree-encoding', 'ident', '--', $RelativePath
        ) -AllowFailure
    } catch { throw "Cannot verify target Git text attributes; update manually: $RelativePath. $($_.Exception.Message)" }
    if ($result.Code -ne 0) { throw "Cannot verify target Git text attributes; update manually: $RelativePath" }
    $attributes = @{}
    $prefix = [Regex]::Escape($RelativePath) + ': '
    foreach ($line in $result.Lines) {
        if ($line -cnotmatch ('^' + $prefix + '(text|eol|filter|working-tree-encoding|ident): (.*)$') -or
            $attributes.ContainsKey($Matches[1])) { throw "Invalid target Git text attributes: $RelativePath" }
        $attributes[$Matches[1]] = $Matches[2]
    }
    if ($attributes.Count -ne 5) { throw "Incomplete target Git text attributes: $RelativePath" }
    foreach ($name in @('filter', 'working-tree-encoding', 'ident')) {
        if ($attributes[$name] -notin @('unset', 'unspecified')) { return $false }
    }
    if ($attributes['text'] -eq 'unset') { return $false }
    return $attributes['text'] -in @('set', 'auto') -or $attributes['eol'] -in @('lf', 'crlf')
}

function Test-DesktopUpdateGitFileBytes {
    param($Context, [string]$TargetSha, [string]$RelativePath, [string]$Path, [string]$Blob)
    [byte[]]$bytes = Get-DesktopUpdateFileBytes $Path -Raw
    if ((Get-DesktopUpdateGitBlobHash $bytes) -ceq $Blob) { return $true }
    # Codeload may honor eol=crlf even when the committed Git blob is LF.
    # Exact bytes always win first, including genuine CRLF/-text blobs.
    [byte[]]$canonical = Get-DesktopUpdateFileBytes $Path
    if ((Get-DesktopUpdateGitBlobHash $canonical) -cne $Blob) { return $false }
    return Test-DesktopUpdateGitTextConversion $Context $TargetSha $RelativePath
}

function Assert-DesktopUpdateGitTree {
    param($Context, [string]$TargetSha, $Plan, [switch]$PathsOnly)
    $files = @{}
    foreach ($entry in @($Plan.NewManifest.files)) { $files[$entry.path] = $entry }
    $files['update_manifest.json'] = $true
    $tree = (Invoke-DesktopUpdateGit $Context.Git $Context.Root @('-c', 'core.quotepath=false', 'ls-tree', '-r', '--full-tree', $TargetSha)).Lines
    if ($tree.Count -ne $files.Count) { throw 'Git tree does not match the source manifest.' }
    foreach ($line in $tree) {
        if ($line -cnotmatch '^(100644|100755) blob ([a-f0-9]{40})\t(.+)$') { throw 'Unsupported Git tree entry.' }
        $blob = $Matches[2]
        $relative = Assert-DesktopUpdateRelativePath $Matches[3] -AllowManifest
        if (-not $files.ContainsKey($relative)) { throw "Git tree contains an unowned file: $relative" }
        if ($PathsOnly) { continue }
        $path = Join-Path $Plan.PreparedRoot $relative.Replace('/', '\')
        if (-not (Test-DesktopUpdateGitFileBytes $Context $TargetSha $relative $path $blob)) {
            throw "Git/archive source mismatch: $relative"
        }
        if ($relative -ieq 'start_desktop.bat') {
            # The executing bootstrap is never replaced, even to change CRLF.
            # Its retained bytes must still represent the target indexed blob.
            $retained = Assert-DesktopUpdateLocalPath $Context.Root (Join-Path $Context.Root 'start_desktop.bat')
            if (-not (Test-DesktopUpdateGitFileBytes $Context $TargetSha $relative $retained $blob)) {
                throw 'Frozen bootstrap bytes are incompatible with the target Git attributes. Install this version manually.'
            }
        }
    }
    $attributesPaths = @($Plan.NewManifest.files | Where-Object { [IO.Path]::GetFileName($_.path) -eq '.gitattributes' } | ForEach-Object { Join-Path $Plan.PreparedRoot $_.path.Replace('/', '\') })
    foreach ($attributesPath in $attributesPaths) {
        if ((Test-Path -LiteralPath $attributesPath) -and
            ([IO.File]::ReadAllText($attributesPath) -match '(?im)(?:^|\s)(?:filter|working-tree-encoding|ident)(?:=|\s|$)')) { throw 'Git content transformations require a manual update.' }
    }
}

function Write-DesktopUpdateJson {
    param([string]$Path, $Value)
    $temporary = $Path + '.new-' + [Guid]::NewGuid().ToString('N')
    $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes(($Value | ConvertTo-Json -Depth 12).Replace("`r`n", "`n"))
    $stream = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
    else { [IO.File]::Move($temporary, $Path) }
}

function Copy-DesktopUpdateBackup {
    param([string]$Source, [string]$Destination)
    [IO.File]::Copy($Source, $Destination, $false)
    $stream = [IO.File]::Open($Destination, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try { $stream.Flush($true) } finally { $stream.Dispose() }
}

function Assert-DesktopUpdateOwnedTree {
    param([string]$Root, [hashtable]$Files, [switch]$AllowMissing)
    $rootPath = Assert-DesktopUpdateLocalPath $Root $Root -AllowRoot
    $expectedDirectories = @{}
    foreach ($relative in @($Files.Keys)) {
        $parent = $relative
        while ($parent.Contains('/')) {
            $parent = $parent.Substring(0, $parent.LastIndexOf('/'))
            $expectedDirectories[$parent] = $true
        }
    }
    $directories = New-Object 'Collections.Generic.List[string]'
    $pending = New-Object 'Collections.Generic.Stack[string]'
    if (Test-Path -LiteralPath $rootPath) { $pending.Push($rootPath) }
    elseif (-not $AllowMissing) { throw "Owned update directory is missing: $rootPath" }
    while ($pending.Count) {
        foreach ($item in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            Assert-DesktopUpdateLocalPath $rootPath $item.FullName | Out-Null
            $relative = $item.FullName.Substring($rootPath.Length + 1).Replace('\', '/')
            if ($item.PSIsContainer) {
                if (-not $expectedDirectories.ContainsKey($relative)) { throw "Unknown recovery directory preserved: $($item.FullName)" }
                $directories.Add($item.FullName)
                $pending.Push($item.FullName)
            } else {
                if (-not $Files.ContainsKey($relative)) { throw "Unknown recovery file preserved: $($item.FullName)" }
                if ($null -ne $Files[$relative] -and (Get-DesktopUpdateFileHash $item.FullName -Raw) -cne $Files[$relative]) { throw "Changed recovery file preserved: $($item.FullName)" }
            }
        }
    }
    if (-not $AllowMissing) {
        foreach ($relative in @($Files.Keys)) {
            if (-not (Test-Path -LiteralPath (Join-Path $rootPath $relative.Replace('/', '\')))) { throw "Recovery backup incomplete: $relative" }
        }
    }
    return ,$directories.ToArray()
}

function New-DesktopUpdateDownloadRecord {
    param($Plan, [string]$DownloadSession)
    $session = Assert-DesktopUpdateLocalPath $Plan.Root $DownloadSession
    $relative = $session.Substring($Plan.Root.Length + 1).Replace('\', '/')
    if ($relative -cnotmatch '^\.launcher/updates/[a-f0-9]{32}$' -or
        $Plan.PreparedRoot -ine (Join-Path $session 'prepared/source')) { throw 'Invalid owned update download session.' }
    $archive = Assert-DesktopUpdateLocalPath $session (Join-Path $session 'source.zip')
    if ((Get-Item -LiteralPath $archive).Length -gt 32MB) { throw 'Update source archive is too large.' }
    $files = @{}
    $files['source.zip'] = Get-DesktopUpdateFileHash $archive -Raw
    $files['prepared/source/update_manifest.json'] = Get-DesktopUpdateFileHash (Join-Path $Plan.PreparedRoot 'update_manifest.json') -Raw
    foreach ($entry in @($Plan.NewManifest.files)) {
        $files['prepared/source/' + $entry.path] = Get-DesktopUpdateFileHash (Join-Path $Plan.PreparedRoot $entry.path.Replace('/', '\')) -Raw
    }
    Assert-DesktopUpdateOwnedTree $session $files | Out-Null
    return [pscustomobject]@{ relative = $relative; files = @($files.Keys | Sort-Object | ForEach-Object { [pscustomobject]@{ path = $_; sha256 = $files[$_] } }) }
}

function Set-DesktopUpdateFile {
    param([string]$Root, [string]$Destination, [string]$Source, $ExpectedHash, $SourceHash = $null)
    $target = Assert-DesktopUpdateLocalPath $Root $Destination
    if ((Get-DesktopUpdateOptionalHash $target) -cne $ExpectedHash) { throw "A file changed during the update: $target" }
    if (-not $Source) {
        if ($null -ne $ExpectedHash) { [IO.File]::Delete($target) }
        return
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
    $temporary = $target + '.update-' + [Guid]::NewGuid().ToString('N')
    if ($null -eq $SourceHash) { $SourceHash = Get-DesktopUpdateFileHash $Source -Raw }
    try {
        [IO.File]::Copy($Source, $temporary, $false)
        $stream = [IO.File]::Open($temporary, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        try { $stream.Flush($true) } finally { $stream.Dispose() }
        if ((Get-DesktopUpdateFileHash $temporary -Raw) -cne $SourceHash) { throw "Prepared source changed while staging: $Source" }
        # Recheck after staging, before the atomic destination operation.
        Assert-DesktopUpdateLocalPath $Root $target | Out-Null
        if ((Get-DesktopUpdateOptionalHash $target) -cne $ExpectedHash) { throw "A file changed during the update: $target" }
        if ($null -ne $ExpectedHash) { [IO.File]::Replace($temporary, $target, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $target) }
    } finally {
        if ((Test-Path -LiteralPath $temporary) -and (Get-DesktopUpdateFileHash $temporary -Raw) -ceq $SourceHash) {
            Assert-DesktopUpdateLocalPath $Root $temporary | Out-Null
            [IO.File]::Delete($temporary)
        }
    }
}

function Enter-DesktopUpdateLock {
    param([string]$ProjectRoot)
    $lockPath = Assert-DesktopUpdateLocalPath $ProjectRoot (Join-Path $ProjectRoot '.launcher/runtime.lock')
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($lockPath)) | Out-Null
    try { return [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
    catch { throw 'OmniSonic is busy with another launcher, update or Power Switch.' }
}

function Assert-DesktopUpdateAppClosed {
    param([string]$ProjectRoot)
    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
    $rootPattern = [Regex]::Escape($root).Replace('\\', '[\\/]') + '(?:[\\/"\s]|$)'
    foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='omnisonic.exe'" -ErrorAction Stop)) {
        $commandProperty = $process.PSObject.Properties['CommandLine']
        $executableProperty = $process.PSObject.Properties['ExecutablePath']
        $command = if ($commandProperty) { [string]$commandProperty.Value } else { '' }
        $executable = if ($executableProperty) { [string]$executableProperty.Value } else { '' }
        if (-not $executable -and $command -match '^\s*"([^"\r\n]+)"') { $executable = $Matches[1] }
        $underRoot = $false
        if ($executable) {
            try { $underRoot = [IO.Path]::GetFullPath($executable).StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) }
            catch { $underRoot = $false }
        }
        $module = $command -match '\bomnisonic\.(?:app|startup)\b'
        $desktop = $module -or $command -match '(?:^|[\\/\s"])wx_app\.py(?:["\s]|$)' -or $process.Name -ieq 'omnisonic.exe'
        $explicitRoot = $command -match $rootPattern
        # A module-only external system-Python command has no observable cwd in
        # Win32_Process. Refuse that ambiguous instance, while allowing a clear
        # other installation's managed interpreter or explicit script path.
        $otherManaged = $executable -match '(?i)[\\/](?:env|venv|\.venv)[\\/](?:Scripts[\\/])?pythonw?\.exe$' -and -not $underRoot
        $ambiguousModule = $module -and -not $otherManaged -and -not $explicitRoot
        $ambiguousScript = $false
        if (-not $otherManaged -and $command -match '(?i)(?:^|\s)(?:"([^"\r\n]*wx_app\.py)"|([^"\s]*wx_app\.py))(?=\s|$)') {
            $scriptPath = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
            $ambiguousScript = -not [IO.Path]::IsPathRooted($scriptPath)
        }
        $ambiguousWrapper = $process.Name -ieq 'omnisonic.exe' -and -not $executable
        if ($underRoot -or ($desktop -and $explicitRoot) -or $ambiguousModule -or $ambiguousScript -or $ambiguousWrapper) {
            throw 'Close OmniSonic before updating or recovering its source files.'
        }
    }
}

function Get-DesktopUpdateRecoveryPaths {
    param([string]$ProjectRoot)
    $root = Assert-DesktopUpdateLocalPath $ProjectRoot $ProjectRoot -AllowRoot
    $recovery = Assert-DesktopUpdateLocalPath $root (Join-Path $root '.launcher/update-recovery')
    return [pscustomobject]@{ Root = $root; Recovery = $recovery; Pending = Join-Path $recovery 'pending.json' }
}

function Assert-DesktopUpdateRecoveryClear {
    param([string]$ProjectRoot)
    $paths = Get-DesktopUpdateRecoveryPaths $ProjectRoot
    if (Test-Path -LiteralPath $paths.Pending) { throw 'An interrupted source update requires recovery before another update.' }
    $transactions = Assert-DesktopUpdateLocalPath $paths.Root (Join-Path $paths.Recovery 'transactions')
    if (-not (Test-Path -LiteralPath $transactions)) { return }
    $item = Get-Item -LiteralPath $transactions -Force
    $entry = if ($item.PSIsContainer) { Get-ChildItem -LiteralPath $transactions -Force | Select-Object -First 1 } else { $item }
    if ($null -ne $entry) {
        # A failure before the durable pointer can still have produced a source
        # backup. Its role cannot be reconstructed safely from a folder name.
        # Preserve it for manual review instead of accumulating or deleting it.
        throw "Unrecorded update recovery data requires manual review before another update: $($entry.FullName). No source or recovery file was deleted."
    }
}

function Read-DesktopUpdateJournal {
    param($Paths)
    $pointerPath = Assert-DesktopUpdateLocalPath $Paths.Root $Paths.Pending
    if ((Get-Item -LiteralPath $pointerPath).Length -gt 4096) { throw 'Update recovery pointer is too large.' }
    $pending = [IO.File]::ReadAllText($pointerPath) | ConvertFrom-Json -ErrorAction Stop
    if ($pending.schema -ne 1 -or $pending.id -cnotmatch '^[a-f0-9]{32}$') { throw 'Invalid update recovery pointer.' }
    $directory = Assert-DesktopUpdateLocalPath $Paths.Recovery (Join-Path $Paths.Recovery ('transactions/' + $pending.id))
    $journalPath = Assert-DesktopUpdateLocalPath $directory (Join-Path $directory 'journal.json')
    if ((Get-Item -LiteralPath $journalPath).Length -gt 2MB) { throw 'Update recovery journal is too large.' }
    $journal = [IO.File]::ReadAllText($journalPath) | ConvertFrom-Json -ErrorAction Stop
    if ($journal.schema -ne 1 -or $journal.id -cne $pending.id -or $journal.root -ine $Paths.Root -or
        $journal.target -cnotmatch '^[a-f0-9]{40}$' -or $journal.status -notin @('applying', 'committed', 'rolledback', 'cleaning') -or
        $journal.recoveryHash -cnotmatch '^[a-f0-9]{64}$' -or
        ($null -ne $journal.stateOldHash -and $journal.stateOldHash -cnotmatch '^[a-f0-9]{64}$') -or $journal.stateNewHash -cnotmatch '^[a-f0-9]{64}$' -or
        @($journal.entries).Count -gt 2049) { throw 'Invalid update recovery journal.' }
    $seen = @{}
    foreach ($entry in @($journal.entries)) {
        Assert-DesktopUpdateRelativePath $entry.Path -AllowManifest | Out-Null
        if ($seen.ContainsKey($entry.Path) -or $entry.Path -ieq 'start_desktop.bat') { throw 'Unsafe recovery file entry.' }
        $seen[$entry.Path] = $true
        foreach ($hash in @($entry.OldHash, $entry.NewHash)) {
            if ($null -ne $hash -and $hash -cnotmatch '^[a-f0-9]{64}$') { throw 'Invalid recovery hash.' }
        }
    }
    return [pscustomobject]@{ Journal = $journal; Directory = $directory; Path = $journalPath; Backup = Join-Path $directory 'backup' }
}

function Restore-DesktopUpdateTransaction {
    param($Paths, $Record)
    $journal = $Record.Journal
    # Verify the complete recovery plan before changing any source. Divergent
    # files are concurrent user edits, not permission to overwrite them.
    foreach ($entry in @($journal.entries)) {
        $target = Assert-DesktopUpdateLocalPath $Paths.Root (Join-Path $Paths.Root $entry.Path.Replace('/', '\'))
        $actual = Get-DesktopUpdateOptionalHash $target
        if ($actual -cne $entry.OldHash -and $actual -cne $entry.NewHash) { throw "Recovery preserved a concurrently changed file: $target" }
        if ($null -ne $entry.OldHash) {
            $backup = Assert-DesktopUpdateLocalPath $Record.Directory (Join-Path $Record.Backup $entry.Path.Replace('/', '\'))
            if ((Get-DesktopUpdateFileHash $backup -Raw) -cne $entry.OldHash) { throw "Recovery backup hash mismatch: $backup" }
        }
    }
    $state = Assert-DesktopUpdateLocalPath $Paths.Root (Join-Path $Paths.Root '.launcher/update-state.json')
    $currentState = Get-DesktopUpdateOptionalHash $state
    if ($currentState -cne $journal.stateOldHash -and $currentState -cne $journal.stateNewHash) { throw 'Update state changed outside this transaction; recovery preserved it.' }
    $oldState = if ($null -ne $journal.stateOldHash) { Join-Path $Record.Directory 'state.old' } else { $null }
    if ($oldState -and (Get-DesktopUpdateFileHash $oldState -Raw) -cne $journal.stateOldHash) { throw 'Update state backup is damaged.' }
    $indexLock = $null
    try {
        if ($null -ne $journal.git) {
            $git = $journal.git
            if ($git.ref -cne 'refs/heads/master' -or $git.old -cnotmatch '^[a-f0-9]{40}$' -or $git.headHash -cnotmatch '^[a-f0-9]{64}$' -or
                $git.indexOldHash -cnotmatch '^[a-f0-9]{64}$' -or $git.indexNewHash -cnotmatch '^[a-f0-9]{64}$' -or
                $git.lockToken -cnotmatch '^[a-f0-9]{32}$') { throw 'Invalid Git recovery metadata.' }
            $gitCommand = (Get-Command git.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
            $index = Assert-DesktopUpdateLocalPath $Paths.Root (Join-Path $Paths.Root '.git/index')
            $head = Assert-DesktopUpdateLocalPath $Paths.Root (Join-Path $Paths.Root '.git/HEAD')
            if ((Get-DesktopUpdateFileHash $head -Raw) -cne $git.headHash) { throw 'Git HEAD changed outside this update; recovery preserved it.' }
            $lockPath = Assert-DesktopUpdateLocalPath $Paths.Root ($index + '.lock')
            if (Test-Path -LiteralPath $lockPath) {
                if ([IO.File]::ReadAllText($lockPath) -cne $git.lockToken) { throw 'An unowned Git index lock prevents recovery.' }
                $indexLock = [IO.File]::Open($lockPath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            } else {
                $indexLock = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
                $bytes = [Text.Encoding]::ASCII.GetBytes($git.lockToken)
                $indexLock.Write($bytes, 0, $bytes.Length)
                $indexLock.Flush($true)
            }
            $currentRef = (Invoke-DesktopUpdateGit $gitCommand $Paths.Root @('rev-parse', $git.ref)).Lines -join ''
            $indexHash = Get-DesktopUpdateFileHash $index -Raw
            if ($currentRef -cne $git.old -and $currentRef -cne $journal.target) { throw 'Git branch changed outside this update; recovery preserved it.' }
            if ($indexHash -cne $git.indexOldHash -and $indexHash -cne $git.indexNewHash) { throw 'Git index changed outside this update; recovery preserved it.' }
            $oldIndex = Assert-DesktopUpdateLocalPath $Record.Directory (Join-Path $Record.Directory 'index.old')
            if ((Get-DesktopUpdateFileHash $oldIndex -Raw) -cne $git.indexOldHash) { throw 'Git index backup is damaged.' }
            if ($currentRef -ceq $journal.target) { Invoke-DesktopUpdateGit $gitCommand $Paths.Root @('update-ref', $git.ref, $git.old, $journal.target) | Out-Null }
            if ($indexHash -ceq $git.indexNewHash) { Set-DesktopUpdateFile $Paths.Root $index $oldIndex $indexHash }
        }
        foreach ($entry in @($journal.entries)) {
            $target = Join-Path $Paths.Root $entry.Path.Replace('/', '\')
            $actual = Get-DesktopUpdateOptionalHash $target
            if ($actual -ceq $entry.OldHash) { continue }
            $source = if ($null -ne $entry.OldHash) { Join-Path $Record.Backup $entry.Path.Replace('/', '\') } else { $null }
            Set-DesktopUpdateFile $Paths.Root $target $source $entry.NewHash -SourceHash $entry.OldHash
        }
        $currentState = Get-DesktopUpdateOptionalHash $state
        if ($currentState -cne $journal.stateOldHash -and $currentState -cne $journal.stateNewHash) { throw 'Update state changed outside this transaction; recovery preserved it.' }
        if ($currentState -cne $journal.stateOldHash) {
            Set-DesktopUpdateFile $Paths.Root $state $oldState $currentState
        }
        $journal.status = 'rolledback'
        Write-DesktopUpdateJson $Record.Path $journal
    } finally {
        if ($indexLock) {
            $indexLock.Dispose()
            [IO.File]::Delete((Join-Path $Paths.Root '.git/index.lock'))
        }
    }
}

function Assert-DesktopUpdateRetainedState {
    param($Paths, $Record)
    $journal = $Record.Journal
    $phase = if ($journal.status -eq 'cleaning') { $journal.cleanupFrom } else { $journal.status }
    if ($phase -notin @('committed', 'rolledback')) { throw 'The source update has not reached a consistent version.' }
    New-DesktopUpdatePlan $Paths.Root $Paths.Root | Out-Null
    $newVersion = $phase -eq 'committed'
    foreach ($entry in @($journal.entries)) {
        $target = Assert-DesktopUpdateLocalPath $Paths.Root (Join-Path $Paths.Root $entry.Path.Replace('/', '\'))
        $expected = if ($newVersion) { $entry.NewHash } else { $entry.OldHash }
        if ((Get-DesktopUpdateOptionalHash $target) -cne $expected) { throw "Source changed before recovery cleanup: $target" }
    }
    $state = Assert-DesktopUpdateLocalPath $Paths.Root (Join-Path $Paths.Root '.launcher/update-state.json')
    $stateHash = if ($newVersion) { $journal.stateNewHash } else { $journal.stateOldHash }
    if ((Get-DesktopUpdateOptionalHash $state) -cne $stateHash) { throw 'Update state changed before recovery cleanup.' }
    if ($null -ne $journal.git) {
        $git = (Get-Command git.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
        $ref = (Invoke-DesktopUpdateGit $git $Paths.Root @('rev-parse', 'refs/heads/master')).Lines -join ''
        $expectedRef = if ($newVersion) { $journal.target } else { $journal.git.old }
        $index = Assert-DesktopUpdateLocalPath $Paths.Root (Join-Path $Paths.Root '.git/index')
        $head = Assert-DesktopUpdateLocalPath $Paths.Root (Join-Path $Paths.Root '.git/HEAD')
        $indexTree = Invoke-DesktopUpdateGit $git $Paths.Root @('diff-index', '--cached', '--quiet', $expectedRef, '--') -AllowFailure
        if ($ref -cne $expectedRef -or (Get-DesktopUpdateFileHash $head -Raw) -cne $journal.git.headHash -or $indexTree.Code -ne 0 -or
            (Test-Path -LiteralPath ($index + '.lock'))) { throw 'Git state changed before recovery cleanup.' }
    }
    return $phase
}

function Repair-DesktopInterruptedUpdate {
    param([string]$ProjectRoot, [switch]$LockHeld)
    $paths = Get-DesktopUpdateRecoveryPaths $ProjectRoot
    if (-not (Test-Path -LiteralPath $paths.Pending)) { return $false }
    $lock = $null
    try {
        if (-not $LockHeld) { $lock = Enter-DesktopUpdateLock $paths.Root }
        Assert-DesktopUpdateAppClosed $paths.Root
        $record = Read-DesktopUpdateJournal $paths
        if ($record.Journal.status -eq 'applying') { Restore-DesktopUpdateTransaction $paths $record }
        else { Assert-DesktopUpdateRetainedState $paths $record | Out-Null }
        return $true
    } catch { throw "Update recovery stopped without discarding its backups. Recovery: $($paths.Recovery). $($_.Exception.Message)" }
    finally { if ($lock) { $lock.Dispose() } }
}

function Invoke-DesktopSourceUpdate {
    param([string]$ProjectRoot, [string]$PreparedRoot, [string]$TargetSha, [string]$DownloadSession = '')
    if ($TargetSha -cnotmatch '^[a-f0-9]{40}$') { throw 'Invalid update commit SHA.' }
    $plan = New-DesktopUpdatePlan $ProjectRoot $PreparedRoot
    $paths = Get-DesktopUpdateRecoveryPaths $plan.Root
    Assert-DesktopUpdateRecoveryClear $plan.Root
    Assert-DesktopUpdateAppClosed $plan.Root
    $git = Get-DesktopUpdateGitContext $plan.Root -TargetSha $TargetSha
    if ($null -ne $git) {
        Assert-DesktopUpdateGitTree $git $git.OldSha ([pscustomobject]@{ NewManifest = $plan.OldManifest; PreparedRoot = $plan.Root }) -PathsOnly
        Assert-DesktopUpdateGitTree $git $TargetSha $plan
    }
    $download = if ($DownloadSession) { New-DesktopUpdateDownloadRecord $plan $DownloadSession } else { $null }
    $id = [Guid]::NewGuid().ToString('N')
    $directory = Assert-DesktopUpdateLocalPath $paths.Recovery (Join-Path $paths.Recovery ('transactions/' + $id))
    $backup = Join-Path $directory 'backup'
    [IO.Directory]::CreateDirectory($backup) | Out-Null
    $runner = Assert-DesktopUpdateLocalPath $paths.Root (Join-Path $paths.Recovery 'recover.ps1')
    # This backup is an executable recovery dependency, not an app-data export.
    Set-DesktopUpdateFile $paths.Root $runner $script:DesktopUpdateRuntimePath (Get-DesktopUpdateOptionalHash $runner) -SourceHash $script:DesktopUpdateRuntimeHash
    foreach ($entry in @($plan.Entries)) {
        if ($null -ne $entry.OldHash) {
            $source = Join-Path $plan.Root $entry.Path.Replace('/', '\')
            $destination = Assert-DesktopUpdateLocalPath $directory (Join-Path $backup $entry.Path.Replace('/', '\'))
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
            Copy-DesktopUpdateBackup $source $destination
            if ((Get-DesktopUpdateFileHash $destination -Raw) -cne $entry.OldHash) { throw "Source changed while backing it up: $source" }
        }
    }
    $statePath = Assert-DesktopUpdateLocalPath $plan.Root (Join-Path $plan.Root '.launcher/update-state.json')
    $stateOldHash = Get-DesktopUpdateOptionalHash $statePath
    if ($null -ne $stateOldHash) { Copy-DesktopUpdateBackup $statePath (Join-Path $directory 'state.old') }
    $newState = Join-Path $directory 'state.new'
    Write-DesktopUpdateJson $newState ([ordered]@{ schema = 1; sha = $TargetSha; version = $plan.NewManifest.version })
    $journal = [pscustomobject][ordered]@{
        schema = 1; id = $id; root = $plan.Root; target = $TargetSha; status = 'applying'
        entries = @($plan.Entries); git = $null; stateOldHash = $stateOldHash; stateNewHash = Get-DesktopUpdateFileHash $newState -Raw
        recoveryHash = Get-DesktopUpdateFileHash $runner -Raw
        download = $download
    }
    if ($null -ne $git) {
        Copy-DesktopUpdateBackup $git.IndexPath (Join-Path $directory 'index.old')
        $newIndex = Join-Path $directory 'index.new'
        $oldIndexEnvironment = $env:GIT_INDEX_FILE
        try {
            $env:GIT_INDEX_FILE = $newIndex
            Invoke-DesktopUpdateGit $git.Git $plan.Root @('read-tree', $TargetSha) | Out-Null
        } finally { $env:GIT_INDEX_FILE = $oldIndexEnvironment }
        $journal.git = [pscustomobject]@{ ref = $git.Ref; old = $git.OldSha; headHash = $git.HeadHash; indexOldHash = Get-DesktopUpdateFileHash (Join-Path $directory 'index.old') -Raw; indexNewHash = Get-DesktopUpdateFileHash $newIndex -Raw; lockToken = [Guid]::NewGuid().ToString('N') }
    }
    $journalPath = Join-Path $directory 'journal.json'
    Write-DesktopUpdateJson $journalPath $journal
    Write-DesktopUpdateJson $paths.Pending ([ordered]@{ schema = 1; id = $id })
    $indexLock = $null
    try {
        if ($null -ne $git) {
            $indexLock = [IO.File]::Open(($git.IndexPath + '.lock'), [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            $token = [Text.Encoding]::ASCII.GetBytes($journal.git.lockToken)
            $indexLock.Write($token, 0, $token.Length)
            $indexLock.Flush($true)
            if ((Get-DesktopUpdateFileHash $git.IndexPath -Raw) -cne $journal.git.indexOldHash) { throw 'Git index changed before source activation.' }
        }
        foreach ($entry in @($plan.Entries)) {
            $source = if ($null -ne $entry.NewHash) { Join-Path $plan.PreparedRoot $entry.Path.Replace('/', '\') } else { $null }
            Set-DesktopUpdateFile $plan.Root (Join-Path $plan.Root $entry.Path.Replace('/', '\')) $source $entry.OldHash -SourceHash $entry.NewHash
        }
        if ($null -ne $git) {
            if ((Get-DesktopUpdateFileHash (Join-Path $plan.Root '.git/HEAD') -Raw) -cne $journal.git.headHash) { throw 'Git HEAD changed during source activation.' }
            Set-DesktopUpdateFile $plan.Root $git.IndexPath (Join-Path $directory 'index.new') $journal.git.indexOldHash
            Invoke-DesktopUpdateGit $git.Git $plan.Root @('update-ref', $git.Ref, $TargetSha, $git.OldSha) | Out-Null
        }
        Set-DesktopUpdateFile $plan.Root $statePath $newState $stateOldHash
        $journal.status = 'committed'
        Write-DesktopUpdateJson $journalPath $journal
        return [pscustomobject]@{ Updated = $true; Mode = if ($null -ne $git) { 'git' } else { 'zip' }; BackupPath = $backup; TargetSha = $TargetSha; TransactionPath = $directory }
    } catch {
        $failure = $_.Exception.Message
        if ($indexLock) { $indexLock.Dispose(); $indexLock = $null }
        try {
            $record = Read-DesktopUpdateJournal $paths
            Restore-DesktopUpdateTransaction $paths $record
        } catch { throw "Source update failed: $failure. Recovery also requires attention: $($_.Exception.Message). Recovery: $directory" }
        throw "Source update failed; original source restored. Recovery: $directory. $failure"
    } finally {
        if ($indexLock) {
            $indexLock.Dispose()
            [IO.File]::Delete(($git.IndexPath + '.lock'))
        }
    }
}

function Restore-DesktopCompletedUpdate {
    param([string]$ProjectRoot, [string]$TransactionPath)
    $paths = Get-DesktopUpdateRecoveryPaths $ProjectRoot
    $directory = Assert-DesktopUpdateLocalPath $paths.Recovery $TransactionPath
    if ([IO.Path]::GetDirectoryName($directory) -ine (Join-Path $paths.Recovery 'transactions')) { throw 'Invalid completed transaction path.' }
    $lock = Enter-DesktopUpdateLock $paths.Root
    try {
        Assert-DesktopUpdateAppClosed $paths.Root
        if (-not (Test-Path -LiteralPath $paths.Pending)) { throw 'No retained completed source update is available.' }
        $id = [IO.Path]::GetFileName($directory)
        if ($id -cnotmatch '^[a-f0-9]{32}$') { throw 'Invalid completed transaction identifier.' }
        $record = Read-DesktopUpdateJournal $paths
        if ($record.Directory -ine $directory) { throw 'Only the currently retained transaction can be reverted.' }
        if ($record.Journal.status -cne 'committed') { throw 'Only a completed source update can be reverted.' }
        Assert-DesktopUpdateRetainedState $paths $record | Out-Null
        foreach ($entry in @($record.Journal.entries)) {
            $target = Join-Path $paths.Root $entry.Path.Replace('/', '\')
            if ((Get-DesktopUpdateOptionalHash $target) -cne $entry.NewHash) { throw "Source changed after this update: $target" }
        }
        $record.Journal.status = 'applying'
        Write-DesktopUpdateJson $record.Path $record.Journal
        Restore-DesktopUpdateTransaction $paths $record
    } catch { throw "Completed update rollback stopped; source/recovery data retained: $directory. $($_.Exception.Message)" }
    finally { $lock.Dispose() }
}

function Complete-DesktopUpdateAfterLaunch {
    param([string]$ProjectRoot, [switch]$LockHeld)
    $paths = Get-DesktopUpdateRecoveryPaths $ProjectRoot
    if (-not (Test-Path -LiteralPath $paths.Pending)) { return $false }
    $lock = $null
    try {
        if (-not $LockHeld) { $lock = Enter-DesktopUpdateLock $paths.Root }
        $record = Read-DesktopUpdateJournal $paths
        $journal = $record.Journal
        $phase = Assert-DesktopUpdateRetainedState $paths $record
        $runner = Assert-DesktopUpdateLocalPath $paths.Root (Join-Path $paths.Recovery 'recover.ps1')
        if ((Get-DesktopUpdateFileHash $runner -Raw) -cne $journal.recoveryHash) { throw 'Frozen recovery runner changed before cleanup.' }
        $expectedFiles = @{}
        $expectedFiles['journal.json'] = $null
        $expectedFiles['state.new'] = $journal.stateNewHash
        if ($null -ne $journal.stateOldHash) { $expectedFiles['state.old'] = $journal.stateOldHash }
        if ($null -ne $journal.git) {
            $expectedFiles['index.old'] = $journal.git.indexOldHash
            $expectedFiles['index.new'] = $journal.git.indexNewHash
        }
        foreach ($entry in @($journal.entries)) {
            if ($null -ne $entry.OldHash) { $expectedFiles['backup/' + $entry.Path] = $entry.OldHash }
        }
        $directories = Assert-DesktopUpdateOwnedTree $record.Directory $expectedFiles -AllowMissing:($journal.status -eq 'cleaning')
        $downloadRoot = $null
        $downloadFiles = @{}
        $downloadDirectories = @()
        if ($null -ne $journal.download) {
            if ($journal.download.relative -cnotmatch '^\.launcher/updates/[a-f0-9]{32}$' -or @($journal.download.files).Count -gt 2050) { throw 'Invalid owned download-session recovery record.' }
            $downloadRoot = Assert-DesktopUpdateLocalPath $paths.Root (Join-Path $paths.Root $journal.download.relative.Replace('/', '\'))
            foreach ($entry in @($journal.download.files)) {
                Assert-DesktopUpdateRelativePath $entry.path -AllowManifest | Out-Null
                if ($downloadFiles.ContainsKey($entry.path) -or $entry.sha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Invalid download-session recovery file.' }
                $downloadFiles[$entry.path] = $entry.sha256
            }
            $downloadDirectories = Assert-DesktopUpdateOwnedTree $downloadRoot $downloadFiles -AllowMissing:($journal.status -eq 'cleaning')
        }
        if ($journal.status -ne 'cleaning') {
            foreach ($relative in @($expectedFiles.Keys)) {
                if (-not (Test-Path -LiteralPath (Join-Path $record.Directory $relative.Replace('/', '\')))) { throw "Recovery backup incomplete: $relative" }
            }
            $journal | Add-Member -Force NoteProperty cleanupFrom $phase
            $journal.status = 'cleaning'
            Write-DesktopUpdateJson $record.Path $journal
        }
        # All candidates were validated before deletion. Never recurse or remove
        # unknown entries, and allow resuming a partially completed cleanup.
        foreach ($relative in @($expectedFiles.Keys | Where-Object { $_ -ne 'journal.json' })) {
            $file = Assert-DesktopUpdateLocalPath $record.Directory (Join-Path $record.Directory $relative.Replace('/', '\'))
            if (Test-Path -LiteralPath $file) {
                if ((Get-DesktopUpdateFileHash $file -Raw) -cne $expectedFiles[$relative]) { throw "Recovery file changed during cleanup: $file" }
                [IO.File]::Delete($file)
            }
        }
        foreach ($directory in @($directories | Sort-Object Length -Descending)) { [IO.Directory]::Delete($directory, $false) }
        if ($downloadRoot) {
            foreach ($relative in @($downloadFiles.Keys)) {
                $file = Assert-DesktopUpdateLocalPath $downloadRoot (Join-Path $downloadRoot $relative.Replace('/', '\'))
                if (Test-Path -LiteralPath $file) {
                    if ((Get-DesktopUpdateFileHash $file -Raw) -cne $downloadFiles[$relative]) { throw "Download file changed during cleanup: $file" }
                    [IO.File]::Delete($file)
                }
            }
            foreach ($directory in @($downloadDirectories | Sort-Object Length -Descending)) { [IO.Directory]::Delete($directory, $false) }
            if (Test-Path -LiteralPath $downloadRoot) { [IO.Directory]::Delete($downloadRoot, $false) }
        }
        # Once no previous-source backup remains, losing power between these
        # metadata removals leaves harmless state, not an unrecoverable update.
        [IO.File]::Delete($paths.Pending)
        [IO.File]::Delete($record.Path)
        [IO.Directory]::Delete($record.Directory, $false)
        if ((Get-DesktopUpdateFileHash $runner -Raw) -cne $journal.recoveryHash) { throw 'Frozen recovery runner changed during cleanup.' }
        [IO.File]::Delete($runner)
        return $true
    } catch { throw "Source update is retained because recovery cleanup could not be verified. Recovery: $($paths.Recovery). $($_.Exception.Message)" }
    finally { if ($lock) { $lock.Dispose() } }
}

$script:DesktopUpdateRuntimeHash = Get-DesktopUpdateFileHash $script:DesktopUpdateRuntimePath -Raw
if ($MyInvocation.InvocationName -eq '.') { return }
if ($Recover) {
    $ErrorActionPreference = 'Stop'
    try {
        if (-not $RecoveryProjectRoot) { $RecoveryProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..')) }
        Repair-DesktopInterruptedUpdate -ProjectRoot $RecoveryProjectRoot | Out-Null
        exit 0
    } catch { Write-Error $_; exit 1 }
}
