$ErrorActionPreference = 'Stop'
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

$fixture = Join-Path $SwitchRoot ('trash\power-switch-tests-' + [Guid]::NewGuid().ToString('N'))
$SwitchRoot = Join-Path $fixture 'old-pc'
$SwitchData = Join-Path $fixture 'old-settings'
$SwitchDocuments = Join-Path $fixture 'old-documents'
$SwitchBackups = Join-Path $fixture 'backups'
$audioFolder = Join-Path $fixture 'custom-audio'
$sourceSettings = Join-Path $SwitchData 'settings.json'
Write-SwitchJson $sourceSettings @{
    language = 'pl'; theme = 'dark'; shortcut_bindings = @{ generate = 'Ctrl+G' }
    generated_audio_directory = $audioFolder; recorded_audio_directory = $audioFolder
}
Write-SwitchJson (Join-Path $SwitchRoot 'presets\voice.pt') @{ sample = 'new voice' }
Write-SwitchJson (Join-Path $audioFolder 'sample.wav') @{ sample = 'test audio' }
Write-SwitchJson (Join-Path $audioFolder 'not-audio.txt') @{ sample = 'must not be copied' }
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

$SwitchRoot = Join-Path $fixture 'new-pc'
$SwitchData = Join-Path $fixture 'new-settings'
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
foreach ($relative in @('../escape', 'C:/escape', 'presets/../../escape', 'presets/CON.pt', 'presets/a:stream', 'presets/a.')) {
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

# Junctions must not escape the profile boundaries, even if the target exists.
$linkTarget = Join-Path $fixture 'junction-target'
[IO.Directory]::CreateDirectory($linkTarget) | Out-Null
New-Item -ItemType Junction -Path (Join-Path $SwitchRoot 'presets\linked') -Target $linkTarget | Out-Null
Assert-Rejected { Export-SwitchProfile (Join-Path $fixture 'linked-export') $false } 'links/junctions'
Write-Host 'Power Switch tests: OK (export/import, paths, backups, rollback, corruption and links)'
