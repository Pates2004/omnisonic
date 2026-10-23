$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../project_materials.ps1')
. (Join-Path $PSScriptRoot '../desktop_update_runtime.ps1')
$sourceProject = Split-Path -Parent $PSScriptRoot
$fixture = Join-ProjectMaterialPath $sourceProject ('Trash/source-update-runtime-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($fixture) | Out-Null
$script:Checks = 0

function Assert-UpdateTest {
    param([bool]$Condition, [string]$Message)
    $script:Checks++
    if (-not $Condition) { throw "Source updater regression: $Message" }
}
function Assert-UpdateRejected {
    param([scriptblock]$Body, [string]$Pattern)
    try { & $Body | Out-Null }
    catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        $script:Checks++
        return
    }
    throw "Expected source updater refusal: $Pattern"
}
function Write-UpdateTestFile {
    param([string]$Path, [string]$Text)
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path)) | Out-Null
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}
function New-UpdateTestTree {
    param([string]$Name, [string]$Version, [hashtable]$Files)
    $root = Join-Path $fixture $Name
    [IO.Directory]::CreateDirectory($root) | Out-Null
    $entries = @()
    foreach ($path in @($Files.Keys | Sort-Object)) {
        $full = Join-Path $root $path.Replace('/', '\')
        Write-UpdateTestFile $full $Files[$path]
        $entries += [ordered]@{ path = $path; sha256 = Get-DesktopUpdateFileHash $full }
    }
    Write-DesktopUpdateJson (Join-Path $root 'update_manifest.json') ([ordered]@{ schema = 1; algorithm = 'sha256-lf'; version = $Version; files = $entries })
    return $root
}
function New-UpdateTestPair {
    param([string]$Name)
    $old = New-UpdateTestTree ($Name + '/old') '1.0' @{ 'start_desktop.bat' = "@echo off`r`n"; 'app.py' = "old`r`n"; 'obsolete.py' = "remove me`n" }
    $new = New-UpdateTestTree ($Name + '/new') '2.0' @{ 'start_desktop.bat' = "@echo off`n"; 'app.py' = "new`n"; 'package/new.py' = "addition`n" }
    return [pscustomobject]@{ Old = $old; New = $new }
}
$script:OwnedProcesses = @()
function Get-CimInstance { return $script:OwnedProcesses }
$processRoot = Join-Path $fixture 'process-root'
foreach ($case in @(
    @{ ExecutablePath = (Join-Path $processRoot 'env/pythonw.exe'); Name = 'pythonw.exe'; CommandLine = 'pythonw -m omnisonic.startup'; Block = $true },
    @{ ExecutablePath = (Join-Path $processRoot 'venv/Scripts/omnisonic.exe'); Name = 'omnisonic.exe'; CommandLine = 'omnisonic.exe'; Block = $true },
    @{ ExecutablePath = 'C:\Python\python.exe'; Name = 'python.exe'; CommandLine = 'python -m omnisonic.app'; Block = $true },
    @{ ExecutablePath = 'C:\Python\python.exe'; Name = 'python.exe'; CommandLine = 'python wx_app.py'; Block = $true },
    @{ ExecutablePath = 'C:\Python\python.exe'; Name = 'python.exe'; CommandLine = 'python ".\wx_app.py"'; Block = $true },
    @{ Name = 'omnisonic.exe'; CommandLine = 'omnisonic.exe'; Block = $true },
    @{ ExecutablePath = 'C:\Python\python.exe'; Name = 'python.exe'; CommandLine = ('python "' + $processRoot.Replace('\', '/') + '/wx_app.py"'); Block = $true },
    @{ ExecutablePath = 'C:\OtherInstall\env\pythonw.exe'; Name = 'pythonw.exe'; CommandLine = 'pythonw -m omnisonic.startup'; Block = $false },
    @{ ExecutablePath = 'C:\OtherInstall\venv\Scripts\omnisonic.exe'; Name = 'omnisonic.exe'; CommandLine = 'omnisonic.exe'; Block = $false },
    @{ ExecutablePath = 'C:\Python\python.exe'; Name = 'python.exe'; CommandLine = 'python "C:\OtherInstall\wx_app.py"'; Block = $false },
    @{ ExecutablePath = 'C:\Python\python.exe'; Name = 'python.exe'; CommandLine = 'python -m unrelated.app'; Block = $false }
)) {
    $script:OwnedProcesses = @([pscustomobject]$case)
    if ($case.Block) { Assert-UpdateRejected { Assert-DesktopUpdateAppClosed $processRoot } 'Close OmniSonic' }
    else { Assert-DesktopUpdateAppClosed $processRoot; $script:Checks++ }
}
$script:OwnedProcesses = @()

foreach ($unsafe in @('../escape.py', '/root.py', 'dir\file.py', 'x:stream', 'NUL.txt', 'dir/COM1.py', 'x./file', 'x /file', 'a//b.py', 'a/../b.py', 'config/a.py', 'presets/x.py', 'env.retained-abc/a.py', '.launcher/x.py', 'Workspace/x.py', 'omnivoice-local-launcher/x.py', 'AGENTS.md', 'a/AGENTS.override.md')) {
    Assert-UpdateRejected { Assert-DesktopUpdateRelativePath $unsafe } 'Unsafe|Protected'
}
Assert-UpdateRejected { Assert-DesktopUpdateRelativePath ('COM' + [char]0xB9 + '.py') } 'Unsafe'
Assert-UpdateRejected { Assert-DesktopUpdateRelativePath 'nested/.git/index' } 'Unsafe'
$malformed = Join-Path $fixture 'malformed-manifest.json'
Write-DesktopUpdateJson $malformed @{ schema = 1; algorithm = 'sha256-lf'; version = '1'; files = @(@{ path = 'start_desktop.bat'; sha256 = 'a' * 64 }, @{ path = 'START_DESKTOP.BAT'; sha256 = 'b' * 64 }) }
Assert-UpdateRejected { Read-DesktopUpdateManifest $malformed } 'Duplicate'
Write-DesktopUpdateJson $malformed @{ schema = $true; algorithm = 'sha256-lf'; version = '1'; files = @(@{ path = 'start_desktop.bat'; sha256 = 'a' * 64 }) }
Assert-UpdateRejected { Read-DesktopUpdateManifest $malformed } 'Unsupported'
$binary = Join-Path $fixture 'binary.py'
[IO.File]::WriteAllBytes($binary, [byte[]]@(65, 0, 66))
Assert-UpdateRejected { Get-DesktopUpdateFileHash $binary } 'Binary'
$outside = Join-Path $fixture 'junction-target'
[IO.Directory]::CreateDirectory($outside) | Out-Null
Write-UpdateTestFile (Join-Path $outside 'sentinel.txt') 'owned target sentinel'
$linkRoot = Join-Path $fixture 'junction-root'
[IO.Directory]::CreateDirectory($linkRoot) | Out-Null
$junction = Join-Path $linkRoot 'link'
New-Item -ItemType Junction -Path $junction -Target $outside | Out-Null
try { Assert-UpdateRejected { Assert-DesktopUpdateLocalPath $linkRoot (Join-Path $junction 'sentinel.txt') } 'links or reparse' }
finally { [IO.Directory]::Delete($junction, $false) }
Assert-UpdateTest ([IO.File]::ReadAllText((Join-Path $outside 'sentinel.txt')) -ceq 'owned target sentinel') 'Junction rejection never touches its target'
$pair = New-UpdateTestPair 'canonical'
Assert-UpdateTest ((Get-DesktopUpdateFileHash (Join-Path $pair.Old 'start_desktop.bat')) -ceq (Get-DesktopUpdateFileHash (Join-Path $pair.New 'start_desktop.bat'))) 'Canonical hashes normalize CRLF only'
Assert-UpdateTest ((Get-DesktopUpdateFileHash (Join-Path $pair.Old 'start_desktop.bat') -Raw) -cne (Get-DesktopUpdateFileHash (Join-Path $pair.New 'start_desktop.bat') -Raw)) 'Raw backups preserve byte distinctions'
$plan = New-DesktopUpdatePlan $pair.Old $pair.New
Assert-UpdateTest (@($plan.Entries | Where-Object { $_.Path -eq 'start_desktop.bat' }).Count -eq 0) 'Frozen bootstrap is never replaced for newline differences'
Assert-UpdateTest ($plan.Entries.Count -eq 4) 'Plan includes add, replace, delete and manifest'
Write-UpdateTestFile (Join-Path $pair.Old 'app.py') 'local edit'
Assert-UpdateRejected { New-DesktopUpdatePlan $pair.Old $pair.New } 'modified or deleted'

$pair = New-UpdateTestPair 'unknown'
Write-UpdateTestFile (Join-Path $pair.Old 'package/new.py') 'private collision'
Assert-UpdateRejected { New-DesktopUpdatePlan $pair.Old $pair.New } 'Unknown existing'
$pair = New-UpdateTestPair 'bootstrap'
Write-UpdateTestFile (Join-Path $pair.New 'start_desktop.bat') 'changed bootstrap'
$manifest = Read-DesktopUpdateManifest (Join-Path $pair.New 'update_manifest.json')
($manifest.files | Where-Object path -eq 'start_desktop.bat').sha256 = Get-DesktopUpdateFileHash (Join-Path $pair.New 'start_desktop.bat')
Write-DesktopUpdateJson (Join-Path $pair.New 'update_manifest.json') $manifest
Assert-UpdateRejected { New-DesktopUpdatePlan $pair.Old $pair.New } 'frozen'

$pair = New-UpdateTestPair 'success'
foreach ($relative in @('config/settings.json', 'presets/private.pt', 'env/python.exe', 'Workspace/launcher-logs/log.txt', 'omnivoice-local-launcher/private.txt', 'unknown.txt')) { Write-UpdateTestFile (Join-Path $pair.Old $relative) ('private sentinel:' + $relative) }
$privateHashes = @{}
foreach ($relative in @('config/settings.json', 'presets/private.pt', 'env/python.exe', 'Workspace/launcher-logs/log.txt', 'omnivoice-local-launcher/private.txt', 'unknown.txt')) { $privateHashes[$relative] = Get-DesktopUpdateFileHash (Join-Path $pair.Old $relative) -Raw }
$bootstrapHash = Get-DesktopUpdateFileHash (Join-Path $pair.Old 'start_desktop.bat') -Raw
$result = Invoke-DesktopSourceUpdate $pair.Old $pair.New ('a' * 40)
Assert-UpdateTest ($result.Updated -and $result.Mode -eq 'zip') 'ZIP activation succeeds without Git/Python'
Assert-UpdateTest ([IO.File]::ReadAllText((Join-Path $pair.Old 'app.py')) -ceq "new`n") 'New source activated'
Assert-UpdateTest (-not (Test-Path -LiteralPath (Join-Path $pair.Old 'obsolete.py'))) 'Only baseline-owned obsolete source deleted'
Assert-UpdateTest ((Get-DesktopUpdateFileHash (Join-Path $pair.Old 'start_desktop.bat') -Raw) -ceq $bootstrapHash) 'Actual running bootstrap byte-identical'
foreach ($relative in $privateHashes.Keys) { Assert-UpdateTest ((Get-DesktopUpdateFileHash (Join-Path $pair.Old $relative) -Raw) -ceq $privateHashes[$relative]) "Private file untouched: $relative" }
Assert-UpdateTest (Test-Path -LiteralPath (Join-Path $pair.Old '.launcher/update-recovery/pending.json')) 'Committed backup retained until confirmed launch'
Assert-UpdateTest (Repair-DesktopInterruptedUpdate $pair.Old) 'Committed recovery is safe and retains pending backup'

# Simulate interruption after all writes, before durable commit. The frozen
# recovery module uses only recorded exact owned files, not the staged source.
$pending = Get-DesktopUpdateRecoveryPaths $pair.Old
$record = Read-DesktopUpdateJournal $pending
$record.Journal.status = 'applying'
Write-DesktopUpdateJson $record.Path $record.Journal
Assert-UpdateTest (Repair-DesktopInterruptedUpdate $pair.Old) 'Interrupted committed-like source state rolls back'
Assert-UpdateTest ([IO.File]::ReadAllText((Join-Path $pair.Old 'app.py')) -ceq "old`r`n") 'Recovery restores exact original bytes'
Assert-UpdateTest (-not (Test-Path -LiteralPath (Join-Path $pair.Old 'package/new.py'))) 'Recovery removes only its newly added file'
Assert-UpdateTest (Test-Path -LiteralPath (Join-Path $pair.Old 'obsolete.py')) 'Recovery restores its deletion'
Assert-UpdateTest (Complete-DesktopUpdateAfterLaunch $pair.Old) 'Confirmed restored-app launch releases its generated backups'
Assert-UpdateTest (-not (Test-Path -LiteralPath $result.BackupPath)) 'Old source backup removed after explicit successful-launch confirmation'
Assert-UpdateTest (-not (Test-Path -LiteralPath (Join-Path $pair.Old '.launcher/update-state.json'))) 'First-install rollback removes only its own new version state'

$pair = New-UpdateTestPair 'concurrent'
$result = Invoke-DesktopSourceUpdate $pair.Old $pair.New ('b' * 40)
$paths = Get-DesktopUpdateRecoveryPaths $pair.Old
$record = Read-DesktopUpdateJournal $paths
$record.Journal.status = 'applying'
Write-DesktopUpdateJson $record.Path $record.Journal
Write-UpdateTestFile (Join-Path $pair.Old 'app.py') 'concurrent user edit'
Assert-UpdateRejected { Repair-DesktopInterruptedUpdate $pair.Old } 'concurrently changed'
Assert-UpdateTest ([IO.File]::ReadAllText((Join-Path $pair.Old 'app.py')) -ceq 'concurrent user edit') 'Recovery never overwrites divergent user edits'
Assert-UpdateTest (Test-Path -LiteralPath $result.BackupPath) 'Conflict keeps exact recovery backup'

$pair = New-UpdateTestPair 'cleanup'
$result = Invoke-DesktopSourceUpdate $pair.Old $pair.New ('c' * 40)
Write-UpdateTestFile (Join-Path $result.TransactionPath 'unknown-private.txt') 'not generated by updater'
Assert-UpdateRejected { Complete-DesktopUpdateAfterLaunch $pair.Old } 'Unknown recovery file'
Assert-UpdateTest (Test-Path -LiteralPath $result.BackupPath) 'Cleanup preflights every file before deleting any backup'
[IO.File]::Delete((Join-Path $result.TransactionPath 'unknown-private.txt'))
Assert-UpdateTest (Complete-DesktopUpdateAfterLaunch $pair.Old) 'Confirmed new-app launch deletes only owned current transaction'
Assert-UpdateTest (-not (Test-Path -LiteralPath $result.TransactionPath)) 'Successful transaction directory gone'
Assert-UpdateTest (-not (Test-Path -LiteralPath (Join-Path $pair.Old '.launcher/update-recovery/recover.ps1'))) 'Recovery executable copy removed after successful startup'
Assert-UpdateTest ([IO.File]::ReadAllText((Join-Path $pair.Old 'app.py')) -ceq "new`n") 'Cleanup never removes installed source'

# Fail each source operation exactly once. Recovery must restore every original
# byte, including an already deleted source and the original manifest.
$setFileImplementation = ${function:Set-DesktopUpdateFile}
foreach ($failAt in 1..5) {
    $pair = New-UpdateTestPair ('failure-' + $failAt)
    $script:WriteNumber = 0
    $script:FailureOrdinal = $failAt + 1 # Runner copy precedes source activation.
    function Set-DesktopUpdateFile {
        param($Root, $Destination, $Source, $ExpectedHash, $SourceHash = $null)
        $script:WriteNumber++
        if ($script:WriteNumber -eq $script:FailureOrdinal) { throw 'INJECTED_SOURCE_WRITE_FAILURE' }
        & $setFileImplementation $Root $Destination $Source $ExpectedHash -SourceHash $SourceHash
    }
    try { Assert-UpdateRejected { Invoke-DesktopSourceUpdate $pair.Old $pair.New ('d' * 40) } 'original source restored' }
    finally { Set-Item Function:Set-DesktopUpdateFile $setFileImplementation }
    Assert-UpdateTest ([IO.File]::ReadAllText((Join-Path $pair.Old 'app.py')) -ceq "old`r`n") "Failed write $failAt restores source bytes"
    Assert-UpdateTest (Test-Path -LiteralPath (Join-Path $pair.Old 'obsolete.py')) "Failed write $failAt restores deleted source"
    Assert-UpdateTest (-not (Test-Path -LiteralPath (Join-Path $pair.Old 'package/new.py'))) "Failed write $failAt removes only its owned addition"
}

# A backup failure can happen before the pending pointer is durable. Preserve
# its diagnostic copy, but never start another source transaction over it.
$pair = New-UpdateTestPair 'prejournal-backup-failure'
$copyBackupImplementation = ${function:Copy-DesktopUpdateBackup}
function Copy-DesktopUpdateBackup {
    param($Source, $Destination)
    & $copyBackupImplementation $Source $Destination
    throw 'INJECTED_PREJOURNAL_BACKUP_FAILURE'
}
try { Assert-UpdateRejected { Invoke-DesktopSourceUpdate $pair.Old $pair.New ('1' * 40) } 'INJECTED_PREJOURNAL_BACKUP_FAILURE' }
finally { Set-Item Function:Copy-DesktopUpdateBackup $copyBackupImplementation }
$orphanPaths = Get-DesktopUpdateRecoveryPaths $pair.Old
Assert-UpdateTest (-not (Test-Path -LiteralPath $orphanPaths.Pending)) 'Injected backup failure occurs before pending pointer'
$orphanTransactions = Join-Path $orphanPaths.Recovery 'transactions'
$orphanDirectories = @(Get-ChildItem -LiteralPath $orphanTransactions -Directory)
Assert-UpdateTest ($orphanDirectories.Count -eq 1) 'Prejournal failure retains one exact diagnostic backup'
$orphanHash = Get-DesktopUpdateFileHash (Join-Path $orphanDirectories[0].FullName 'backup/app.py') -Raw
Assert-UpdateRejected { Invoke-DesktopSourceUpdate $pair.Old $pair.New ('2' * 40) } 'Unrecorded update recovery data'
Assert-UpdateTest (@(Get-ChildItem -LiteralPath $orphanTransactions -Directory).Count -eq 1) 'Refused retry creates no extra source-copy transaction'
Assert-UpdateTest ((Get-DesktopUpdateFileHash (Join-Path $orphanDirectories[0].FullName 'backup/app.py') -Raw) -ceq $orphanHash) 'Unrecorded diagnostic backup never deleted or overwritten'
Assert-UpdateTest ([IO.File]::ReadAllText((Join-Path $pair.Old 'app.py')) -ceq "old`r`n") 'Refused orphan retry leaves installed source unchanged'

$pair = New-UpdateTestPair 'locked'
$held = Enter-DesktopUpdateLock $pair.Old
try { Assert-UpdateRejected { Enter-DesktopUpdateLock $pair.Old } 'busy' }
finally { $held.Dispose() }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$pair = New-UpdateTestPair 'archive'
$archiveRoot = Join-Path $fixture 'archive-outer'
[IO.Directory]::CreateDirectory($archiveRoot) | Out-Null
[IO.Directory]::Move($pair.New, (Join-Path $archiveRoot 'omnisonic-immutable'))
Write-UpdateTestFile (Join-Path $archiveRoot 'omnisonic-immutable/config/private.json') 'unlisted archive data must not be extracted'
$archive = Join-Path $fixture 'source.zip'
$zip = [IO.Compression.ZipFile]::Open($archive, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in Get-ChildItem -LiteralPath $archiveRoot -File -Recurse) {
        $relative = $file.FullName.Substring($archiveRoot.Length + 1).Replace('\', '/')
        $entry = $zip.CreateEntry($relative)
        $stream = $entry.Open()
        try { $bytes = [IO.File]::ReadAllBytes($file.FullName); $stream.Write($bytes, 0, $bytes.Length) }
        finally { $stream.Dispose() }
    }
} finally { $zip.Dispose() }
$expanded = Expand-DesktopUpdateArchive $archive (Join-Path $fixture 'expanded')
Assert-UpdateTest ($expanded.Manifest.version -eq '2.0') 'Pinned archive extraction verifies manifest'
Assert-UpdateTest (Test-Path -LiteralPath (Join-Path $expanded.Root 'package/new.py')) 'Manifest-owned source extracted'
Assert-UpdateTest (-not (Test-Path -LiteralPath (Join-Path $expanded.Root 'config'))) 'Unlisted private archive entries never extracted/applied'
Assert-UpdateRejected { Expand-DesktopUpdateArchive $archive (Join-Path $fixture 'expanded') } 'already exists'
$evil = Join-Path $fixture 'traversal.zip'
$zip = [IO.Compression.ZipFile]::Open($evil, [IO.Compression.ZipArchiveMode]::Create)
try { $entry = $zip.CreateEntry('root/../escape.py'); $writer = New-Object IO.StreamWriter($entry.Open()); try { $writer.Write('bad') } finally { $writer.Dispose() } }
finally { $zip.Dispose() }
Assert-UpdateRejected { Expand-DesktopUpdateArchive $evil (Join-Path $fixture 'evil-expanded') } 'Unsafe archive'
$duplicate = Join-Path $fixture 'duplicate.zip'
$zip = [IO.Compression.ZipFile]::Open($duplicate, [IO.Compression.ZipArchiveMode]::Create)
try { $zip.CreateEntry('root/a.py') | Out-Null; $zip.CreateEntry('root/A.py') | Out-Null }
finally { $zip.Dispose() }
Assert-UpdateRejected { Expand-DesktopUpdateArchive $duplicate (Join-Path $fixture 'duplicate-expanded') } 'Duplicate archive'
Assert-UpdateRejected { Expand-DesktopUpdateEntry ([pscustomobject]@{ Length = 9MB }) (Join-Path $fixture 'never-created') } 'too large'

# Real Git objects/index/reference transitions in an owned, unpushed repository.
# Per-command project identity avoids changing global/system Git configuration.
$pair = New-UpdateTestPair 'git'
$gitExe = (Get-Command git.exe -CommandType Application).Source
Invoke-DesktopUpdateGit $gitExe $pair.Old @('init', '--initial-branch=master', '--quiet') | Out-Null
Invoke-DesktopUpdateGit $gitExe $pair.Old @('remote', 'add', 'origin', 'https://github.com/Pates2004/omnisonic.git') | Out-Null
Invoke-DesktopUpdateGit $gitExe $pair.Old @('-c', 'core.autocrlf=false', 'add', '--all') | Out-Null
Invoke-DesktopUpdateGit $gitExe $pair.Old @('config', 'user.name', 'Patryk (Pates2004)') | Out-Null
Invoke-DesktopUpdateGit $gitExe $pair.Old @('config', 'user.email', '255875083+Pates2004@users.noreply.github.com') | Out-Null
Assert-UpdateTest (((Invoke-DesktopUpdateGit $gitExe $pair.Old @('var', 'GIT_AUTHOR_IDENT')).Lines -join '') -match '^Patryk \(Pates2004\) <255875083\+Pates2004@users\.noreply\.github\.com>') 'Synthetic commit author uses required project identity'
Assert-UpdateTest (((Invoke-DesktopUpdateGit $gitExe $pair.Old @('var', 'GIT_COMMITTER_IDENT')).Lines -join '') -match '^Patryk \(Pates2004\) <255875083\+Pates2004@users\.noreply\.github\.com>') 'Synthetic committer uses required project identity'
Invoke-DesktopUpdateGit $gitExe $pair.Old @('commit', '--quiet', '-m', 'Owned baseline') | Out-Null
$oldCommit = (Invoke-DesktopUpdateGit $gitExe $pair.Old @('rev-parse', 'HEAD')).Lines -join ''
$indexEnvironment = $env:GIT_INDEX_FILE
try {
    $env:GIT_INDEX_FILE = Join-Path $fixture 'fixture-target-index'
    Invoke-DesktopUpdateGit $gitExe $pair.Old @('--work-tree', $pair.New, '-c', 'core.autocrlf=false', 'add', '--all') | Out-Null
    $tree = (Invoke-DesktopUpdateGit $gitExe $pair.Old @('write-tree')).Lines -join ''
    $targetCommit = (Invoke-DesktopUpdateGit $gitExe $pair.Old @('commit-tree', $tree, '-p', $oldCommit, '-m', 'Owned update')).Lines -join ''
} finally { $env:GIT_INDEX_FILE = $indexEnvironment }
Assert-UpdateTest ($null -ne (Get-DesktopUpdateGitContext $pair.Old -TargetSha $targetCommit)) 'Clean expected-origin master with fetched FF target accepted'
Write-UpdateTestFile (Join-Path $pair.Old '.git/info/attributes') 'update_manifest.json filter=must-not-run'
Assert-UpdateRejected { Get-DesktopUpdateGitContext $pair.Old } 'content transformations'
[IO.File]::Delete((Join-Path $pair.Old '.git/info/attributes'))
$result = Invoke-DesktopSourceUpdate $pair.Old $pair.New $targetCommit
Assert-UpdateTest ($result.Mode -eq 'git') 'Git update uses coherent source/index/reference transaction'
Assert-UpdateTest (((Invoke-DesktopUpdateGit $gitExe $pair.Old @('rev-parse', 'HEAD')).Lines -join '') -ceq $targetCommit) 'HEAD advances to exact approved commit'
Assert-UpdateTest (@((Invoke-DesktopUpdateGit $gitExe $pair.Old @('status', '--porcelain=v1', '--untracked-files=no')).Lines).Count -eq 0) 'Updated Git index and tracked source remain clean'
Assert-UpdateRejected { Get-DesktopUpdateGitContext $pair.Old -TargetSha $oldCommit } 'fast-forward'
Write-UpdateTestFile (Join-Path $pair.Old '.git/hooks/post-merge') '# custom hook'
Assert-UpdateRejected { Get-DesktopUpdateGitContext $pair.Old } 'Custom Git hooks'
[IO.File]::Delete((Join-Path $pair.Old '.git/hooks/post-merge'))
Assert-UpdateTest (Complete-DesktopUpdateAfterLaunch $pair.Old) 'Git cleanup tolerates semantic-only stat-cache index refresh'

$third = New-UpdateTestTree 'git/third' '3.0' @{ 'start_desktop.bat' = "@echo off`n"; 'app.py' = "third`n"; 'package/new.py' = "addition`n" }
$indexEnvironment = $env:GIT_INDEX_FILE
try {
    $env:GIT_INDEX_FILE = Join-Path $fixture 'fixture-third-index'
    Invoke-DesktopUpdateGit $gitExe $pair.Old @('--work-tree', $third, '-c', 'core.autocrlf=false', 'add', '--all') | Out-Null
    $tree = (Invoke-DesktopUpdateGit $gitExe $pair.Old @('write-tree')).Lines -join ''
    $thirdCommit = (Invoke-DesktopUpdateGit $gitExe $pair.Old @('commit-tree', $tree, '-p', $targetCommit, '-m', 'Owned third version')).Lines -join ''
} finally { $env:GIT_INDEX_FILE = $indexEnvironment }
$oldIndexHash = Get-DesktopUpdateFileHash (Join-Path $pair.Old '.git/index') -Raw
$result = Invoke-DesktopSourceUpdate $pair.Old $third $thirdCommit
$paths = Get-DesktopUpdateRecoveryPaths $pair.Old
$record = Read-DesktopUpdateJournal $paths
$record.Journal.status = 'applying'
Write-DesktopUpdateJson $record.Path $record.Journal
Assert-UpdateTest (Repair-DesktopInterruptedUpdate $pair.Old) 'Interrupted Git source/index/reference activation recovers'
Assert-UpdateTest (((Invoke-DesktopUpdateGit $gitExe $pair.Old @('rev-parse', 'HEAD')).Lines -join '') -ceq $targetCommit) 'Git recovery restores exact original branch commit'
Assert-UpdateTest ((Get-DesktopUpdateFileHash (Join-Path $pair.Old '.git/index') -Raw) -ceq $oldIndexHash) 'Git recovery restores byte-exact index backup'
Assert-UpdateTest ([IO.File]::ReadAllText((Join-Path $pair.Old 'app.py')) -ceq "new`n") 'Git recovery restores prior source and version state'
Assert-UpdateTest (Complete-DesktopUpdateAfterLaunch $pair.Old) 'Confirmed restored Git version releases its recovery-only copies'
Write-UpdateTestFile (Join-Path $pair.Old 'app.py') 'user change'
Assert-UpdateRejected { Get-DesktopUpdateGitContext $pair.Old } 'Local Git changes'

# The copied recovery module executes in a new Windows PowerShell process even
# if the live updater has already been removed or is partially replaced.
$pair = New-UpdateTestPair "recovery child ' & Unicode"
$result = Invoke-DesktopSourceUpdate $pair.Old $pair.New ('f' * 40)
$paths = Get-DesktopUpdateRecoveryPaths $pair.Old
$record = Read-DesktopUpdateJournal $paths
$record.Journal.status = 'applying'
Write-DesktopUpdateJson $record.Path $record.Journal
$runner = Join-Path $paths.Recovery 'recover.ps1'
$escapedRunner = $runner.Replace("'", "''")
$childCommand = '$ErrorActionPreference=''Stop''; function Get-CimInstance { return @() }; & ''' + $escapedRunner + ''' -Recover; exit $LASTEXITCODE'
& (Join-Path $PSHOME 'powershell.exe') -NoLogo -NoProfile -ExecutionPolicy Bypass -Command $childCommand
Assert-UpdateTest ($LASTEXITCODE -eq 0) 'Standalone frozen recovery process succeeds without live updater'
Assert-UpdateTest ([IO.File]::ReadAllText((Join-Path $pair.Old 'app.py')) -ceq "old`r`n") 'Standalone recovery resolves its own program root safely'
Assert-UpdateTest (Complete-DesktopUpdateAfterLaunch $pair.Old) 'Standalone-recovered version can finalize backup cleanup'

# The downloaded ZIP and prepared new sources are real additional copies and
# are retained on failure, then removed only after successful startup.
$pair = New-UpdateTestPair 'download-session'
$session = Join-Path $pair.Old ('.launcher/updates/' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory((Join-Path $session 'prepared')) | Out-Null
[IO.Directory]::Move($pair.New, (Join-Path $session 'prepared/source'))
Write-UpdateTestFile (Join-Path $session 'source.zip') 'synthetic archive sentinel; archive decoder tested separately'
$result = Invoke-DesktopSourceUpdate $pair.Old (Join-Path $session 'prepared/source') ('e' * 40) -DownloadSession $session
Write-UpdateTestFile (Join-Path $session 'private.txt') 'unexpected user data'
Assert-UpdateRejected { Complete-DesktopUpdateAfterLaunch $pair.Old } 'Unknown recovery file'
Assert-UpdateTest (Test-Path -LiteralPath $result.BackupPath) 'Unknown staging data prevents backup deletion too'
[IO.File]::Delete((Join-Path $session 'private.txt'))
Assert-UpdateTest (Complete-DesktopUpdateAfterLaunch $pair.Old) 'Owned download ZIP/prepared tree cleaned after confirmed launch'
Assert-UpdateTest (-not (Test-Path -LiteralPath $session)) 'No additional previous/new-source download copy remains'

$global:LASTEXITCODE = 0
Write-Host "Desktop source-update runtime tests: OK ($script:Checks checks; synthetic fixtures only)"
