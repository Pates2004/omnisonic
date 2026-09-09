[CmdletBinding()]
param(
    [ValidateSet('Menu', 'Switch', 'Export', 'Import')]
    [string]$Action = 'Menu',
    [ValidateSet('Auto', 'CUDA', 'ROCm', 'XPU', 'CPU')]
    [string]$Backend = 'Auto',
    [string]$ProfilePath,
    [switch]$IncludeAudio,
    [switch]$Yes
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$SwitchRoot = $PSScriptRoot
$SwitchBackups = Join-Path $SwitchRoot 'power-switch-backups'
$SwitchData = if ($env:OMNISONIC_DATA_DIR) {
    [IO.Path]::GetFullPath($env:OMNISONIC_DATA_DIR)
} else { Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'OmniSonic' }
$SwitchDocuments = [Environment]::GetFolderPath('MyDocuments')
if (-not $SwitchDocuments) {
    $SwitchDocuments = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Documents'
}
$SwitchDocuments = Join-Path $SwitchDocuments 'OmniSonic'

function Assert-SwitchPath {
    param([string]$Path)
    # Never traverse junctions/symlinks, including ancestors of the destination.
    $full = [IO.Path]::GetFullPath($Path)
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Symbolic links/junctions are not supported: $cursor"
            }
        }
        $cursor = Split-Path -Parent $cursor
    }
    return $full
}

function Join-SwitchChild {
    param([string]$Root, [string]$Relative)
    $parts = $Relative.Replace('\', '/').Split('/')
    foreach ($part in $parts) {
        if (-not $part -or $part -in @('.', '..') -or $part -match '[<>:"|?*\x00-\x1f]' -or
            $part -match '[. ]$' -or $part -match '^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)') {
            throw "Unsafe profile path: $Relative"
        }
    }
    $rootFull = (Assert-SwitchPath $Root).TrimEnd('\')
    $full = Assert-SwitchPath (Join-Path $rootFull ($parts -join '\'))
    if (-not $full.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Profile path escapes its directory: $Relative"
    }
    return $full
}

function Write-SwitchJson {
    param([string]$Path, [object]$Value)
    $full = Assert-SwitchPath $Path
    [IO.Directory]::CreateDirectory((Split-Path -Parent $full)) | Out-Null
    [IO.File]::WriteAllText($full, ($Value | ConvertTo-Json -Depth 32),
        (New-Object Text.UTF8Encoding($false)))
}

function Copy-SwitchFile {
    param([string]$Source, [string]$Destination)
    $sourceFull = Assert-SwitchPath $Source
    $targetFull = Assert-SwitchPath $Destination
    if ((Get-Item -LiteralPath $sourceFull -Force).PSIsContainer) { throw 'Expected a file.' }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $targetFull)) | Out-Null
    $temporary = "$targetFull.power-switch-$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::Copy($sourceFull, $temporary, $false)
        Move-Item -LiteralPath $temporary -Destination $targetFull -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
}

function Get-SwitchFiles {
    param([string]$Directory)
    $directoryFull = Assert-SwitchPath $Directory
    if (-not (Test-Path -LiteralPath $directoryFull -PathType Container)) { return }
    foreach ($item in Get-ChildItem -LiteralPath $directoryFull -Force) {
        Assert-SwitchPath $item.FullName | Out-Null
        if ($item.PSIsContainer) { Get-SwitchFiles $item.FullName }
        else { $item }
    }
}

function Get-SwitchSettingsPath {
    $path = Join-Path $SwitchData 'settings.json'
    if (Test-Path -LiteralPath $path) { return $path }
    $legacy = Join-Path $SwitchRoot 'settings.json'
    if (Test-Path -LiteralPath $legacy) { return $legacy }
    return $path
}

function Read-SwitchSettings {
    param([string]$Path)
    Assert-SwitchPath $Path | Out-Null
    $settings = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($null -eq $settings -or $settings -isnot [pscustomobject]) {
        throw 'Settings must contain a JSON object.'
    }
    return $settings
}

function Get-SwitchAudioSource {
    param([object]$Settings, [string]$Kind)
    $key = if ($Kind -eq 'generated') { 'generated_audio_directory' } else { 'recorded_audio_directory' }
    $path = Join-Path $SwitchDocuments $Kind
    if ($null -ne $Settings -and $null -ne $Settings.PSObject.Properties[$key] -and
        -not [string]::IsNullOrWhiteSpace([string]$Settings.$key)) { $path = [string]$Settings.$key }
    $full = Assert-SwitchPath $path
    foreach ($broad in @([IO.Path]::GetPathRoot($full), $SwitchRoot, $SwitchData,
        [Environment]::GetFolderPath('UserProfile'), [Environment]::GetFolderPath('MyDocuments'))) {
        if ($broad -and $full.TrimEnd('\') -eq $broad.TrimEnd('\')) {
            throw "Audio directory is too broad to export safely: $full"
        }
    }
    return $full.TrimEnd('\')
}

function New-SwitchFolder {
    param([string]$Prefix)
    Assert-SwitchPath $SwitchBackups | Out-Null
    return Join-Path $SwitchBackups ("$Prefix-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([Guid]::NewGuid().ToString('N').Substring(0,8))")
}

function Export-SwitchProfile {
    param([string]$Destination, [bool]$WithAudio)
    $destinationFull = Assert-SwitchPath $Destination
    if (Test-Path -LiteralPath $destinationFull) { throw 'Choose a new, non-existing export directory.' }
    $sources = New-Object 'System.Collections.Generic.List[object]'
    $settingsPath = Get-SwitchSettingsPath
    $settings = $null
    if (Test-Path -LiteralPath $settingsPath) {
        $settings = Read-SwitchSettings $settingsPath
        $sources.Add([pscustomobject]@{ Source = $settingsPath; Path = 'settings.json' })
    }
    $roots = @([pscustomobject]@{ Root = (Join-Path $SwitchRoot 'presets'); Prefix = 'presets' })
    if ($WithAudio) {
        foreach ($kind in @('generated', 'record')) {
            $roots += [pscustomobject]@{ Root = (Get-SwitchAudioSource $settings $kind); Prefix = "audio/$kind" }
        }
    }
    foreach ($tree in $roots) {
        $sourceRoot = (Assert-SwitchPath $tree.Root).TrimEnd('\')
        if ($destinationFull.StartsWith($sourceRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'The export directory cannot be inside data being exported.'
        }
        foreach ($file in @(Get-SwitchFiles $sourceRoot)) {
            if ($tree.Prefix -like 'audio/*' -and $file.Extension -notin
                @('.wav', '.flac', '.ogg', '.opus', '.mp3', '.aif', '.aiff', '.au', '.caf', '.m4a', '.wma')) { continue }
            $relative = $file.FullName.Substring($sourceRoot.Length + 1).Replace('\', '/')
            $sources.Add([pscustomobject]@{ Source = $file.FullName; Path = "$($tree.Prefix)/$relative" })
        }
    }
    [IO.Directory]::CreateDirectory($destinationFull) | Out-Null
    $files = @(
        foreach ($entry in $sources) {
            $target = Join-SwitchChild $destinationFull $entry.Path
            Copy-SwitchFile $entry.Source $target
            [pscustomobject]@{ path = $entry.Path; sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash }
        }
    )
    # The manifest is written last; interrupted exports cannot be imported.
    Write-SwitchJson (Join-Path $destinationFull 'manifest.json') ([ordered]@{
        format = 'omnisonic-power-switch'; version = 1
        created_utc = [DateTime]::UtcNow.ToString('o'); includes_audio = $WithAudio; files = $files
    })
    Write-Host "Profile exported / Profil wyeksportowany: $destinationFull"
    return $destinationFull
}

function Get-SwitchDestination {
    param([string]$Relative)
    if ($Relative -ceq 'settings.json') { return Join-SwitchChild $SwitchData 'settings.json' }
    if ($Relative -cmatch '^presets/(.+)$') { return Join-SwitchChild (Join-Path $SwitchRoot 'presets') $Matches[1] }
    if ($Relative -cmatch '^audio/(generated|record)/(.+)$') {
        return Join-SwitchChild (Join-Path $SwitchDocuments $Matches[1]) $Matches[2]
    }
    throw "Unexpected file in profile: $Relative"
}

function Import-SwitchProfile {
    param([string]$Source)
    $sourceFull = Assert-SwitchPath $Source
    $manifestPath = Join-SwitchChild $sourceFull 'manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.format -ne 'omnisonic-power-switch' -or $manifest.version -ne 1) {
        throw 'This is not a supported OmniSonic Power Switch profile.'
    }
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $plan = @(
        foreach ($entry in @($manifest.files)) {
            $relative = [string]$entry.path
            $sourceFile = Join-SwitchChild $sourceFull $relative
            $destination = Get-SwitchDestination $relative
            if (-not $seen.Add($destination)) { throw "Duplicate profile target: $relative" }
            if ([string]$entry.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or
                (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash -ne $entry.sha256) {
                throw "Profile checksum mismatch: $relative"
            }
            if (Test-Path -LiteralPath $destination -PathType Container) { throw "A directory blocks $relative" }
            if ($relative -eq 'settings.json') { Read-SwitchSettings $sourceFile | Out-Null }
            [pscustomobject]@{ Source = $sourceFile; Destination = $destination; Relative = $relative }
        }
    )
    $backup = New-SwitchFolder 'before-import'
    # Backup every overwritten file before changing anything. Existing extra presets stay.
    foreach ($entry in $plan) {
        if (Test-Path -LiteralPath $entry.Destination) {
            Copy-SwitchFile $entry.Destination (Join-SwitchChild $backup $entry.Relative)
        }
    }
    Write-SwitchJson (Join-Path $backup 'restore-map.json') $plan
    $written = New-Object 'System.Collections.Generic.List[object]'
    try {
        foreach ($entry in $plan) {
            $written.Add($entry)
            if ($entry.Relative -eq 'settings.json') {
                $settings = Read-SwitchSettings $entry.Source
                $settings | Add-Member -Force NoteProperty generated_audio_directory (Join-Path $SwitchDocuments 'generated')
                $settings | Add-Member -Force NoteProperty recorded_audio_directory (Join-Path $SwitchDocuments 'record')
                $prepared = Join-SwitchChild $backup 'imported-settings.json'
                Write-SwitchJson $prepared $settings
                Copy-SwitchFile $prepared $entry.Destination
            } else { Copy-SwitchFile $entry.Source $entry.Destination }
        }
    } catch {
        $failure = $_
        foreach ($entry in $written) {
            $original = Join-SwitchChild $backup $entry.Relative
            if (Test-Path -LiteralPath $original) { Copy-SwitchFile $original $entry.Destination }
            elseif (Test-Path -LiteralPath $entry.Destination) {
                # Only a new file created by this import can be removed here.
                Assert-SwitchPath $entry.Destination | Out-Null
                Remove-Item -LiteralPath $entry.Destination
            }
        }
        throw "Import failed; previous files restored. Backup: $backup. $failure"
    }
    Write-Host "Imported / Zaimportowano. Backup / Kopia poprzednich plikow: $backup"
    Write-Host "Audio folders now use this user's Documents/OmniSonic. Backend preferences were not copied."
    return $backup
}

function Assert-SwitchAppClosed {
    $processes = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'"
    foreach ($process in $processes) {
        if ($process.CommandLine -match 'omnisonic\.app|wx_app\.py') {
            throw 'Close OmniSonic before using Power Switch / Najpierw zamknij OmniSonic.'
        }
    }
}

function Invoke-SwitchBackend {
    param([ValidateSet('Auto', 'CUDA', 'ROCm', 'XPU', 'CPU')][string]$SelectedBackend)
    Write-Host 'Only the runtime changes; settings, presets and audio stay in place.'
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File (
        Join-Path $SwitchRoot 'desktop_launcher.ps1'
    ) -Backend $SelectedBackend -InstallOnly
    if ($LASTEXITCODE -ne 0) { throw "Backend switch failed with code $LASTEXITCODE. Previous runtime was retained." }
}

function Invoke-PowerSwitch {
    if ($Action -eq 'Menu') {
        Write-Host 'OmniSonic Power Switch - close the app first / najpierw zamknij aplikacje'
        Write-Host '[1] Change backend / Zmien backend (Auto, CUDA, ROCm, XPU, CPU)'
        Write-Host '[2] Export settings and presets / Eksport ustawien i presetow'
        Write-Host '[3] Import a profile / Import profilu'
        Write-Host '[0] Exit / Wyjdz'
        switch (Read-Host 'Choice / Wybor') {
            '1' { $Action = 'Switch'; $Backend = Read-Host 'Backend [Auto/CUDA/ROCm/XPU/CPU]'; if (-not $Backend) { $Backend = 'Auto' } }
            '2' { $Action = 'Export'; $IncludeAudio = (Read-Host 'Include saved audio? / Dolaczyc zapisane audio? [y/N]') -match '^(y|t|yes|tak)$' }
            '3' { $Action = 'Import'; $ProfilePath = (Read-Host 'Profile folder / Folder profilu').Trim('"') }
            default { return }
        }
    }
    Assert-SwitchAppClosed
    switch ($Action) {
        'Switch' { Invoke-SwitchBackend $Backend }
        'Export' {
            if (-not $ProfilePath) { $ProfilePath = New-SwitchFolder 'export' }
            Export-SwitchProfile $ProfilePath $IncludeAudio | Out-Null
        }
        'Import' {
            if (-not $ProfilePath) { throw 'Provide -ProfilePath with the exported folder.' }
            Write-Host 'Import merges presets, replaces matching files/settings, and resets audio paths to this PC Documents.'
            Write-Host 'Import scala presety, zastepuje kolidujace pliki i ustawia foldery audio w Dokumentach tego komputera.'
            if (-not $Yes -and (Read-Host 'Continue? / Kontynuowac? [y/N]') -notmatch '^(y|t|yes|tak)$') { return }
            Import-SwitchProfile $ProfilePath | Out-Null
        }
    }
}

if ($MyInvocation.InvocationName -eq '.') { return }
try { Invoke-PowerSwitch; exit 0 }
catch { Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
