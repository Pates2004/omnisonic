$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\project_materials.ps1')
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'power_switch.ps1')

function Assert-Test {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Regression failed: $Message" }
}
function Assert-Rejected {
    param([scriptblock]$Body, [string]$Pattern)
    try { & $Body | Out-Null }
    catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        return
    }
    throw "Expected failure: $Pattern"
}

Assert-Test ($SwitchData -eq (Join-Path $SwitchRoot 'config')) 'Power Switch uses program/config'
& {
    $detectedProcessName = 'pythonw.exe'
    function Get-CimInstance {
        return [pscustomobject]@{ Name = $detectedProcessName; CommandLine = $commandLine }
    }
    foreach ($commandLine in @(
        'pythonw.exe -E -s -m omnisonic.startup',
        'python.exe -E -s -m omnisonic.app',
        'python.exe "C:\OmniSonic\wx_app.py"'
    )) {
        Assert-Rejected { Assert-SwitchAppClosed } 'Close OmniSonic'
    }
    foreach ($commandLine in @('python.exe -m unrelated.app', 'python.exe -m omnisonic.application', $null)) {
        Assert-SwitchAppClosed
    }
    $detectedProcessName = 'omnisonic.exe'
    $commandLine = '"C:\synthetic-app\venv\Scripts\omnisonic.exe"'
    Assert-Rejected { Assert-SwitchAppClosed } 'Close OmniSonic'
}
$fixture = Join-ProjectMaterialPath $SwitchRoot ('trash\power-switch-tests-' + [Guid]::NewGuid().ToString('N'))
$SwitchRoot = Join-Path $fixture 'old-pc'
$SwitchData = Join-Path $SwitchRoot 'config'
$SwitchDocuments = Join-Path $fixture 'old-documents'
$SwitchBackups = Join-Path $fixture 'backups'
$audioFolder = Join-Path $fixture 'custom-audio'
$sourceSettings = Join-Path $SwitchData 'settings.json'
& {
    # Interpret the desktop's supported home-directory shorthand as a path,
    # without creating, reading or copying any actual profile/audio file.
    $profileBase = $env:USERPROFILE
    if ($profileBase) {
        foreach ($configuredPath in @('~\voices', '~/voices', '"~\voices"')) {
            $configuredSettings = [pscustomobject]@{ generated_audio_directory = $configuredPath }
            $expected = [IO.Path]::GetFullPath((Join-Path $profileBase 'voices'))
            Assert-Test ((Get-SwitchAudioSource $configuredSettings 'generated') -eq $expected) 'Home shorthand matches desktop interpretation'
        }
        Assert-Rejected { Get-SwitchAudioSource ([pscustomobject]@{ generated_audio_directory = '~' }) 'generated' } 'too broad'
    }
}
Write-SwitchJson $sourceSettings @{
    language = 'pl'; theme = 'dark'; shortcut_bindings = @{ generate = 'Ctrl+G' }
    generated_audio_directory = $audioFolder; recorded_audio_directory = $audioFolder
}
Write-SwitchJson (Join-Path $SwitchRoot 'presets\voice.pt') @{ sample = 'new voice' }
Write-SwitchJson (Join-Path $audioFolder 'sample.wav') @{ sample = 'test audio' }
Write-SwitchJson (Join-Path $audioFolder 'not-audio.txt') @{ sample = 'must not be copied' }
& {
    $variableName = 'OMNISONIC_SWITCH_PATH_TEST'
    $oldVariable = [Environment]::GetEnvironmentVariable($variableName, 'Process')
    [Environment]::SetEnvironmentVariable($variableName, $audioFolder, 'Process')
    try {
        foreach ($configuredPath in @(
            ('"' + $audioFolder + '"'),
            '%OMNISONIC_SWITCH_PATH_TEST%',
            '$OMNISONIC_SWITCH_PATH_TEST',
            '${OMNISONIC_SWITCH_PATH_TEST}'
        )) {
            $configuredSettings = [pscustomobject]@{ generated_audio_directory = $configuredPath }
            Assert-Test ((Get-SwitchAudioSource $configuredSettings 'generated') -eq $audioFolder) 'Configured audio path matches application interpretation'
        }
        $literalPath = Join-Path $fixture 'literal $(throw injected)'
        $literalSettings = [pscustomobject]@{ generated_audio_directory = $literalPath }
        Assert-Test ((Get-SwitchAudioSource $literalSettings 'generated') -eq $literalPath) 'Configured paths never execute expressions'
    } finally {
        [Environment]::SetEnvironmentVariable($variableName, $oldVariable, 'Process')
    }
}
$export = Join-Path $fixture 'export'
Export-SwitchProfile $export $true | Out-Null
Assert-Test (Test-Path -LiteralPath (Join-Path $export 'presets\voice.pt')) 'Preset exported'
Assert-Test (Test-Path -LiteralPath (Join-Path $export 'audio\generated\sample.wav')) 'Audio exported'
Assert-Test (-not (Test-Path -LiteralPath (Join-Path $export 'audio\generated\not-audio.txt'))) 'Only audio files exported'
$noAudio = Join-Path $fixture 'without-audio'
Export-SwitchProfile $noAudio $false | Out-Null
Assert-Test (-not (Test-Path -LiteralPath (Join-Path $noAudio 'audio'))) 'Audio is optional'
Assert-Rejected { Export-SwitchProfile $export $false } 'non-existing'
Assert-Rejected { Export-SwitchProfile (Join-Path $SwitchRoot 'presets\nested-export') $false } 'inside data'

& {
    # A launcher that is starting has not created a detectable GUI process yet.
    # Profile transfers must share its project lock, not rely only on a PID scan.
    $Action = 'Export'
    $IncludeAudio = $false
    $ProfilePath = Join-Path $fixture 'export-with-lock'
    $lockDirectory = Join-Path $SwitchRoot '.launcher'
    [IO.Directory]::CreateDirectory($lockDirectory) | Out-Null
    $held = [IO.File]::Open((Join-Path $lockDirectory 'runtime.lock'),
        [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try {
        Assert-Rejected { Invoke-PowerSwitch } 'using this project|zajety'
        Assert-Test (-not (Test-Path -LiteralPath $ProfilePath)) 'Busy launcher prevents profile writes'
    } finally { $held.Dispose() }
    Invoke-PowerSwitch
    Assert-Test (Test-Path -LiteralPath (Join-Path $ProfilePath 'manifest.json')) 'Transfer succeeds after launcher releases lock'

    function Export-SwitchProfile {
        param($Destination, $WithAudio)
        $blocked = $false
        try {
            $unexpected = [IO.File]::Open((Join-Path $lockDirectory 'runtime.lock'),
                [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            $unexpected.Dispose()
        } catch [IO.IOException] {
            $blocked = ($_.Exception.HResult -band 0xFFFF) -in @(32, 33)
        }
        Assert-Test $blocked 'Profile lock remains held throughout transfer'
        throw 'Simulated profile transfer failure'
    }
    Assert-Rejected { Invoke-PowerSwitch } 'Simulated profile transfer failure'
    $released = [IO.File]::Open((Join-Path $lockDirectory 'runtime.lock'),
        [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $released.Dispose()

    $Action = 'Import'
    $Yes = $false
    function Read-Host { return 'n' }
    function Import-SwitchProfile { throw 'Declined import must not write anything' }
    Invoke-PowerSwitch
    $released = [IO.File]::Open((Join-Path $lockDirectory 'runtime.lock'),
        [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $released.Dispose()

    $Action = 'Switch'
    $Backend = 'CPU'
    function Invoke-SwitchBackend {
        param($SelectedBackend)
        Assert-Test ($SelectedBackend -eq 'CPU') 'Backend choice reaches delegated launcher'
        $delegated = [IO.File]::Open((Join-Path $lockDirectory 'runtime.lock'),
            [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        $delegated.Dispose()
    }
    Invoke-PowerSwitch
}

$SwitchRoot = Join-Path $fixture 'new-pc'
$SwitchData = Join-Path $SwitchRoot 'config'
$SwitchDocuments = Join-Path $fixture 'new-documents'
$targetSettings = Join-Path $SwitchData 'settings.json'
$targetPreset = Join-Path $SwitchRoot 'presets\voice.pt'
Write-SwitchJson $targetSettings @{ language = 'en' }
Write-SwitchJson $targetPreset @{ sample = 'old voice' }
Write-SwitchJson (Join-Path $SwitchRoot 'presets\keep.pt') @{ sample = 'keep me' }
$oldPresetHash = (Get-FileHash -LiteralPath $targetPreset).Hash
$backup = Import-SwitchProfile $export
$settings = Read-SwitchSettings $targetSettings
Assert-Test ($settings.language -eq 'pl') 'Settings imported'
Assert-Test ($settings.shortcut_bindings.generate -eq 'Ctrl+G') 'Shortcuts preserved'
Assert-Test ($settings.generated_audio_directory -eq (Join-Path $SwitchDocuments 'generated')) 'Paths moved to new PC'
Assert-Test (Test-Path -LiteralPath (Join-Path $SwitchRoot 'presets\keep.pt')) 'Unrelated presets preserved'
Assert-Test ((Get-FileHash -LiteralPath (Join-Path $backup 'presets\voice.pt')).Hash -eq $oldPresetHash) 'Collision backup'
Assert-Test ([IO.File]::ReadAllBytes($targetSettings)[0] -eq 123) 'Settings use UTF-8 without BOM'
Assert-Test (-not (Test-Path -LiteralPath (Join-Path $SwitchRoot 'env'))) 'No Python environment copied'

$manifestPath = Join-Path $export 'manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$goodHash = $manifest.files[0].sha256
$manifest.files[0].sha256 = '0' * 64
Write-SwitchJson $manifestPath $manifest
$before = (Get-FileHash -LiteralPath $targetSettings).Hash
Assert-Rejected { Import-SwitchProfile $export } 'checksum'
Assert-Test ((Get-FileHash -LiteralPath $targetSettings).Hash -eq $before) 'Corruption rejected before mutation'
$manifest.files[0].sha256 = $goodHash
Write-SwitchJson $manifestPath $manifest
foreach ($relative in @(
    '../escape', 'C:/escape', 'presets/../../escape', 'presets/CON.pt', 'presets/a:stream', 'presets/a.',
    ('presets/COM' + [char]0x00b9 + '.pt'), ('presets/COM' + [char]0x00b2 + '.pt'),
    ('presets/LPT' + [char]0x00b2 + '.pt'), ('presets/LPT' + [char]0x00b3 + '.pt')
)) {
    Assert-Rejected { Join-SwitchChild $SwitchRoot $relative } 'Unsafe|escapes'
}
Assert-Rejected { Get-SwitchDestination 'env/python.exe' } 'Unexpected'

# Force a failure after settings were replaced; all previous data must return.
Write-SwitchJson $targetSettings @{ language = 'en'; theme = 'light' }
$before = (Get-FileHash -LiteralPath $targetSettings).Hash
& {
    $copyOriginal = (Get-Command Copy-SwitchFile).ScriptBlock
    function Copy-SwitchFile {
        param([string]$Source, [string]$Destination)
        if ($Source -eq (Join-Path $export 'presets\voice.pt')) { throw 'Simulated copy failure' }
        & $copyOriginal $Source $Destination
    }
    Assert-Rejected { Import-SwitchProfile $export } 'previous files restored'
}
Assert-Test ((Get-FileHash -LiteralPath $targetSettings).Hash -eq $before) 'Rollback restored settings'

& {
    $SwitchRoot = Join-Path $fixture 'partial-rollback-pc'
    $SwitchData = Join-Path $SwitchRoot 'config'
    $SwitchBackups = Join-Path $fixture 'partial-rollback-backups'
    $profile = Join-Path $fixture 'partial-rollback-profile'
    $files = @(
        foreach ($name in @('a', 'b', 'c')) {
            $relative = "presets/$name.pt"
            $source = Join-SwitchChild $profile $relative
            Write-SwitchJson $source @{ value = "new-$name" }
            Write-SwitchJson (Get-SwitchDestination $relative) @{ value = "old-$name" }
            @{ path = $relative; sha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash }
        }
    )
    Write-SwitchJson (Join-Path $profile 'manifest.json') @{
        format = 'omnisonic-power-switch'; version = 1; files = $files
    }
    $copyOriginal = (Get-Command Copy-SwitchFile).ScriptBlock
    $script:partialRollbackBackup = $null
    function Copy-SwitchFile {
        param([string]$Source, [string]$Destination)
        if ($Source -eq (Join-SwitchChild $profile 'presets/c.pt')) { throw 'Simulated original import failure' }
        if ($Source.StartsWith($SwitchBackups + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            $script:partialRollbackBackup = Split-Path -Parent (Split-Path -Parent $Source)
            if ((Split-Path -Leaf $Source) -in @('a.pt', 'c.pt')) {
                throw "Simulated rollback failure for $(Split-Path -Leaf $Source)"
            }
        }
        & $copyOriginal $Source $Destination
    }
    $failureMessage = $null
    try { Import-SwitchProfile $profile | Out-Null }
    catch { $failureMessage = $_.Exception.Message }
    Assert-Test ($failureMessage -match 'some files could not be restored') 'Partial rollback does not claim complete restoration'
    Assert-Test ($failureMessage -match 'Simulated original import failure') 'Partial rollback retains the original import error'
    Assert-Test ($failureMessage -match 'presets/a.pt' -and $failureMessage -match 'presets/c.pt') 'All rollback failures are listed'
    Assert-Test ([bool]$script:partialRollbackBackup) 'Exact recovery backup was captured'
    Assert-Test ($failureMessage -match [Regex]::Escape($script:partialRollbackBackup)) 'Partial rollback identifies the exact backup location'
    $recovered = Read-SwitchSettings (Get-SwitchDestination 'presets/b.pt')
    Assert-Test ($recovered.value -eq 'old-b') 'A recoverable later entry is restored after an earlier rollback error'
    $original = Read-SwitchSettings (Join-SwitchChild $script:partialRollbackBackup 'presets/a.pt')
    Assert-Test ($original.value -eq 'old-a') 'The failed restoration backup remains intact'
}

& {
    function powershell.exe { $global:LASTEXITCODE = 9 }
    $failureMessage = $null
    try { Invoke-SwitchBackend 'CPU' }
    catch { $failureMessage = $_.Exception.Message }
    Assert-Test ($failureMessage -match 'failed with code 9') 'Backend switch retains the native failure status'
    Assert-Test ($failureMessage -match 'launcher diagnostics') 'Backend switch refers to the actual recovery diagnostics'
    Assert-Test ($failureMessage -notmatch 'retained|was restored') 'Backend switch does not invent successful recovery'
}

& {
    # Appending a temporary suffix must not exceed the filename component limit.
    $longRoot = Join-Path $fixture 'long-names'
    [IO.Directory]::CreateDirectory($longRoot) | Out-Null
    $longSource = Join-Path $longRoot 'source.wav'
    [IO.File]::WriteAllText($longSource, 'Synthetic audio fixture')
    $longTarget = Join-Path $longRoot (('x' * 240) + '.wav')
    Copy-SwitchFile $longSource $longTarget
    Assert-Test ([IO.File]::ReadAllText($longTarget) -eq 'Synthetic audio fixture') 'Long legal filename copied'
    Assert-Test ([IO.File]::ReadAllText($longSource) -eq 'Synthetic audio fixture') 'Long-name copy preserves source'
}

& {
    $cleanupSource = Join-Path $fixture 'cleanup-source.wav'
    $cleanupTarget = Join-Path $fixture 'cleanup-target.wav'
    [IO.File]::WriteAllText($cleanupSource, 'Source fixture')
    [IO.File]::WriteAllText($cleanupTarget, 'Existing target fixture')
    function Move-Item {
        param([string]$LiteralPath, [string]$Destination, [switch]$Force)
        throw 'Original copy promotion failure'
    }
    function Remove-Item {
        param([string]$LiteralPath)
        throw 'Secondary temporary cleanup failure'
    }
    Assert-Rejected { Copy-SwitchFile $cleanupSource $cleanupTarget } 'Original copy promotion failure'
    Assert-Test ([IO.File]::ReadAllText($cleanupSource) -eq 'Source fixture') 'Failed copy keeps source'
    Assert-Test ([IO.File]::ReadAllText($cleanupTarget) -eq 'Existing target fixture') 'Failed copy keeps destination'
}

# Junctions must not escape the profile boundaries, even if the target exists.
$linkTarget = Join-Path $fixture 'junction-target'
[IO.Directory]::CreateDirectory($linkTarget) | Out-Null
New-Item -ItemType Junction -Path (Join-Path $SwitchRoot 'presets\linked') -Target $linkTarget | Out-Null
Assert-Rejected { Export-SwitchProfile (Join-Path $fixture 'linked-export') $false } 'links/junctions'
Write-Host 'Power Switch tests: OK (export/import, paths, backups, rollback, corruption and links)'
