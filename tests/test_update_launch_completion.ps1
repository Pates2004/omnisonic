. (Join-Path $PSScriptRoot '..\project_materials.ps1')

$ErrorActionPreference = 'Stop'
$testProject = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $testProject 'desktop_launcher.ps1'
$tokens = $null
$errors = $null
$tree = [Management.Automation.Language.Parser]::ParseFile($launcher, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$sessions = @($tree.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Invoke-LauncherSession'
}, $true))
if ($sessions.Count -ne 1) { throw 'Expected exactly one real launcher session function.' }
$sessionDefinition = [ScriptBlock]::Create($sessions[0].Extent.Text)
$profileHelpers = @($tree.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Test-DesktopProfileConfigured'
}, $true))
if ($profileHelpers.Count -ne 1) { throw 'Expected exactly one profile configuration helper.' }
$profileDefinition = [ScriptBlock]::Create($profileHelpers[0].Extent.Text)

function Assert-UpdateLaunch {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Update launch completion regression: $Message" }
}

& {
    # Validate the real read-only helper against owned config files, never the
    # developer's current profile or a migrated user-profile settings location.
    . $profileDefinition
    $profileFixture = Join-ProjectMaterialPath $testProject (
        'Trash\update-launch-completion-profiles-' + [Guid]::NewGuid().ToString('N')
    )
    $profileFixture = Assert-ProjectTestPath $profileFixture $testProject
    [IO.Directory]::CreateDirectory((Join-Path $profileFixture 'config')) | Out-Null
    $settingsFile = Join-Path $profileFixture 'config\settings.json'
    Assert-UpdateLaunch (-not (Test-DesktopProfileConfigured $profileFixture)) 'Missing owned profile is not configured'
    foreach ($case in @(
        @{Json='{}';Configured=$false},
        @{Json='{"first_run_done":false}';Configured=$false},
        @{Json='{"first_run_done":"true"}';Configured=$false},
        @{Json='{"first_run_done":1}';Configured=$false},
        @{Json='{"first_run_done":null}';Configured=$false},
        @{Json='{"first_run_done":{}}';Configured=$false},
        @{Json='true';Configured=$false},
        @{Json='[]';Configured=$false},
        @{Json='{"FIRST_RUN_DONE":true}';Configured=$false},
        @{Json='{"first_run_done":';Configured=$false},
        @{Json='{"first_run_done":true}';Configured=$true}
    )) {
        [IO.File]::WriteAllText($settingsFile, $case.Json, (New-Object Text.UTF8Encoding($false)))
        Assert-UpdateLaunch ((Test-DesktopProfileConfigured $profileFixture) -eq $case.Configured) ('Strict boolean profile readiness: ' + $case.Json)
        Assert-UpdateLaunch ([IO.File]::ReadAllText($settingsFile) -ceq $case.Json) 'Profile readiness never modifies the settings file'
    }
    [IO.File]::WriteAllText($settingsFile, '{"first_run_done":true}', (New-Object Text.UTF8Encoding($true)))
    Assert-UpdateLaunch (Test-DesktopProfileConfigured $profileFixture) 'UTF-8 BOM profile is supported'
    [IO.File]::WriteAllBytes($settingsFile, [byte[]]@(0xFF, 0x7B, 0x7D))
    Assert-UpdateLaunch (-not (Test-DesktopProfileConfigured $profileFixture)) 'Invalid UTF-8 is conservatively unconfigured'
}

# Load only the actual function being exercised. All runtime, hardware and GUI
# operations below are test doubles; generated writes are guarded central fixtures.
$coreStub = @'
param([string]$ProjectRoot)
$state.Events.Add('core-import')
if ($state.FailCoreImport) { throw 'EXPECTED_CORE_IMPORT_FAILURE' }
function Complete-DesktopUpdateAfterLaunch {
    param([string]$ProjectRoot, [switch]$LockHeld)
    $state.Events.Add('complete')
    $state.CompletionCount++
    $state.CompletionRoot = $ProjectRoot
    $state.LockHeld = [bool]$LockHeld
    if (-not $state.StartReturned) { throw 'COMPLETION_RAN_BEFORE_GUI_SUCCESS' }
    if ($state.FailCleanup) { throw 'EXPECTED_COMPLETION_CLEANUP_FAILURE' }
}
'@

$previousAppDir = $env:OMNISONIC_APP_DIR
$previousBackend = $env:OMNISONIC_ACTIVE_BACKEND
$previousRuntimeError = Get-Variable -Name LastRuntimeError -Scope Script -ErrorAction SilentlyContinue
$previousRuntimeErrorValue = if ($previousRuntimeError) { $previousRuntimeError.Value } else { $null }
$failures = New-Object 'Collections.Generic.List[string]'
try {
    foreach ($scenario in @(
        'pending-visible', 'pending-hidden', 'no-pending', 'no-core',
        'gui-failure', 'runtime-failure', 'install-only', 'bootstrap-only',
        'website-mode', 'cleanup-failure', 'core-import-failure', 'first-run-then-configured'
    )) {
        try {
            & {
                $fixture = Join-ProjectMaterialPath $testProject (
                    'Trash\update-launch-completion-' + [Guid]::NewGuid().ToString('N')
                )
                $fixture = Assert-ProjectTestPath $fixture $testProject
                [IO.Directory]::CreateDirectory($fixture) | Out-Null
                $state = @{
                    Events = New-Object 'Collections.Generic.List[string]'
                    Warnings = New-Object 'Collections.Generic.List[string]'
                    StartCount = 0
                    RuntimeCount = 0
                    CompletionCount = 0
                    CompletionRoot = ''
                    LockHeld = $false
                    StartReturned = $false
                    HideConsole = $null
                    ProfileConfigured = $scenario -ne 'first-run-then-configured'
                    ProfileReadCount = 0
                    FailCleanup = $scenario -eq 'cleanup-failure'
                    FailCoreImport = $scenario -eq 'core-import-failure'
                }
                $ProjectRoot = $fixture
                $WorkDir = Join-Path $fixture '.launcher'
                $ModeFile = Join-Path $fixture 'config\desktop-python-mode.txt'
                $BackendFile = Join-Path $fixture 'config\desktop-backend.txt'
                $Mode = 'Auto'
                $ModeWasExplicit = $false
                $Backend = 'Auto'
                $BackendWasExplicit = $false
                $InstallOnly = $scenario -eq 'install-only'
                $BootstrapOnly = $scenario -eq 'bootstrap-only'
                $script:LastRuntimeError = ''
                $pending = Join-Path $fixture '.launcher\update-recovery\pending.json'
                if ($scenario -ne 'no-pending') {
                    [IO.Directory]::CreateDirectory((Split-Path -Parent $pending)) | Out-Null
                    [IO.File]::WriteAllText($pending, '{"synthetic":true}')
                }
                if ($scenario -ne 'no-core') {
                    [IO.File]::WriteAllText((Join-Path $fixture 'desktop_update_runtime.ps1'), $coreStub)
                }

                function Assert-FixtureWrite {
                    param([string]$Path)
                    $full = [IO.Path]::GetFullPath($Path)
                    if (-not $full.StartsWith($fixture + '\', [StringComparison]::OrdinalIgnoreCase)) {
                        throw "Unexpected write outside owned completion fixture: $full"
                    }
                }
                function New-Item {
                    param([string]$ItemType, [string]$Path, [switch]$Force)
                    Assert-FixtureWrite $Path
                    Microsoft.PowerShell.Management\New-Item -ItemType $ItemType -Path $Path -Force:$Force
                }
                function Set-Content {
                    param([string]$LiteralPath, [string]$Encoding, [Parameter(ValueFromPipeline)]$Value)
                    process {
                        Assert-FixtureWrite $LiteralPath
                        Microsoft.PowerShell.Management\Set-Content -LiteralPath $LiteralPath -Encoding $Encoding -Value $Value
                    }
                }
                function Get-BackendMatrix { return @{ profiles = @{} } }
                function Get-VideoControllers { return @() }
                function Get-ProcessorName { return 'Synthetic CPU' }
                function Get-HardwareInventory { return @() }
                function Get-HardwareFingerprint { return 'SYNTHETIC_HARDWARE' }
                function Get-SavedText { return '' }
                function Resolve-RequestedBackend { return 'auto' }
                function Get-HardwareBackend { return 'cpu' }
                function Get-BackendProfile {
                    return [pscustomobject]@{ windows_min_build = 0; display_name = 'Synthetic CPU' }
                }
                function Show-HardwareSummary {}
                function Resolve-PythonMode {
                    $selected = if ($scenario -eq 'website-mode') { 'Website' } else { 'Portable' }
                    return [pscustomobject]@{ Mode = $selected; SystemPython = '' }
                }
                function Get-EnvironmentRootForMode { return Join-Path $fixture 'env' }
                function Get-EnvironmentPython { return Join-Path $fixture 'env\python.exe' }
                function Test-CompatiblePython { return $true }
                function Install-PythonBootstrapTransaction { throw 'UNEXPECTED_BOOTSTRAP_INSTALL' }
                function Get-HideConsolePreference { return $scenario -eq 'pending-hidden' }
                function Test-HiddenLaunchReady { return $false }
                function Hide-LauncherConsole { throw 'UNEXPECTED_CONSOLE_HIDE' }
                function Show-LauncherConsole {}
                function Test-Runtime {
                    $state.RuntimeCount++
                    return $scenario -ne 'runtime-failure'
                }
                function Install-WithRecoveryChoice { throw 'EXPECTED_RUNTIME_FAILURE' }
                function Save-BackendPreference { throw 'UNEXPECTED_BACKEND_PREFERENCE_WRITE' }
                function Write-Step {}
                function Write-WarningMessage {
                    param([string]$Message)
                    $state.Warnings.Add($Message)
                }
                function Test-DesktopProfileConfigured {
                    param([string]$ProjectRoot)
                    Assert-UpdateLaunch ($ProjectRoot -eq $fixture) 'Profile readiness reads only the owned project'
                    $state.ProfileReadCount++
                    return $state.ProfileConfigured
                }
                function Start-DesktopGui {
                    param([string]$Python, [bool]$HideConsole)
                    $state.Events.Add('gui-start')
                    $state.StartCount++
                    $state.HideConsole = $HideConsole
                    Assert-UpdateLaunch ($Python -eq (Join-Path $fixture 'env\python.exe')) 'Only the synthetic interpreter path is passed'
                    Assert-UpdateLaunch ($env:OMNISONIC_APP_DIR -eq $fixture) 'Application directory is synthetic'
                    Assert-UpdateLaunch ($env:OMNISONIC_ACTIVE_BACKEND -eq 'cpu') 'Selected backend reaches GUI'
                    if ($scenario -eq 'gui-failure') { throw 'EXPECTED_GUI_START_FAILURE' }
                    if ($scenario -eq 'first-run-then-configured') { $state.ProfileConfigured = $true }
                    $state.StartReturned = $true
                    $state.Events.Add('gui-success')
                }

                . $sessionDefinition
                $caught = ''
                try { Invoke-LauncherSession }
                catch { $caught = $_.Exception.Message }

                if ($scenario -in @('gui-failure', 'runtime-failure')) {
                    $expectedError = if ($scenario -eq 'gui-failure') { 'EXPECTED_GUI_START_FAILURE' } else { 'EXPECTED_RUNTIME_FAILURE' }
                    Assert-UpdateLaunch ($caught -eq $expectedError) "$scenario retains the original failure"
                } else {
                    Assert-UpdateLaunch (-not $caught) "$scenario completes without a startup failure: $caught"
                }
                $shouldComplete = $scenario -in @('pending-visible', 'pending-hidden', 'cleanup-failure')
                $expectedCompletions = if ($shouldComplete) { 1 } else { 0 }
                Assert-UpdateLaunch ($state.CompletionCount -eq $expectedCompletions) "$scenario completion count"
                if ($shouldComplete) {
                    Assert-UpdateLaunch ($state.LockHeld) "$scenario passes the held runtime lock"
                    Assert-UpdateLaunch ($state.CompletionRoot -eq $fixture) "$scenario completion uses the synthetic project root"
                    Assert-UpdateLaunch (($state.Events -join ',') -eq 'gui-start,gui-success,core-import,complete') "$scenario completes only after the actual GUI call returned successfully"
                }
                $skipsGui = $scenario -in @('runtime-failure', 'install-only', 'bootstrap-only', 'website-mode')
                Assert-UpdateLaunch ($state.StartCount -eq $(if ($skipsGui) { 0 } else { 1 })) "$scenario GUI dispatch count"
                $readsProfile = -not $skipsGui -and $scenario -ne 'no-pending'
                Assert-UpdateLaunch ($state.ProfileReadCount -eq $(if ($readsProfile) { 1 } else { 0 })) "$scenario captures the profile only before a pending-update GUI launch"
                if ($scenario -in @('install-only', 'bootstrap-only', 'website-mode', 'gui-failure', 'runtime-failure', 'no-core', 'no-pending', 'first-run-then-configured')) {
                    Assert-UpdateLaunch (-not $state.Events.Contains('core-import')) "$scenario never imports cleanup core"
                }
                if ($scenario -in @('cleanup-failure', 'core-import-failure')) {
                    Assert-UpdateLaunch ($state.Warnings.Count -eq 1) "$scenario reports one nonfatal warning"
                    $marker = if ($scenario -eq 'cleanup-failure') { 'EXPECTED_COMPLETION_CLEANUP_FAILURE' } else { 'EXPECTED_CORE_IMPORT_FAILURE' }
                    Assert-UpdateLaunch ($state.Warnings[0].Contains($marker)) "$scenario preserves cleanup failure details"
                    Assert-UpdateLaunch (Test-Path -LiteralPath $pending) "$scenario retains the recovery fixture"
                } elseif ($scenario -eq 'first-run-then-configured') {
                    Assert-UpdateLaunch ($state.Warnings.Count -eq 1) 'First-run startup reports retained recovery without failing startup'
                    Assert-UpdateLaunch (Test-Path -LiteralPath $pending) 'First-run startup retains the owned pending recovery fixture'
                } else {
                    Assert-UpdateLaunch ($state.Warnings.Count -eq 0) "$scenario has no unexpected warnings"
                }
                if ($scenario -in @('pending-hidden', 'pending-visible')) {
                    Assert-UpdateLaunch ($state.HideConsole -eq ($scenario -eq 'pending-hidden')) "$scenario preserves hidden/visible GUI preference"
                }
                Assert-UpdateLaunch (-not (Test-Path -LiteralPath (Join-Path $fixture 'env'))) "$scenario never installs or runs a real Python environment"
                if ($scenario -eq 'first-run-then-configured') {
                    Assert-UpdateLaunch $state.ProfileConfigured 'First-run dialog saved a configured profile while startup was in progress'
                    Assert-UpdateLaunch ($state.ProfileReadCount -eq 1) 'First-run readiness is captured exactly once before startup'
                    $state.Events.Clear()
                    $state.Warnings.Clear()
                    $state.StartReturned = $false
                    Invoke-LauncherSession
                    Assert-UpdateLaunch ($state.ProfileReadCount -eq 2) 'Next launch reads the already configured profile'
                    Assert-UpdateLaunch ($state.CompletionCount -eq 1 -and $state.LockHeld) 'Next configured launch completes recovery once under the existing lock'
                    Assert-UpdateLaunch (($state.Events -join ',') -eq 'gui-start,gui-success,core-import,complete') 'Next configured launch completes only after GUI success'
                    Assert-UpdateLaunch ($state.Warnings.Count -eq 0) 'Next configured launch needs no retention warning'
                }
            }
        }
        catch { $failures.Add("${scenario}: $($_.Exception.Message)") }
    }
}
finally {
    $env:OMNISONIC_APP_DIR = $previousAppDir
    $env:OMNISONIC_ACTIVE_BACKEND = $previousBackend
    if ($previousRuntimeError) {
        Set-Variable -Name LastRuntimeError -Scope Script -Value $previousRuntimeErrorValue
    } else {
        Remove-Variable -Name LastRuntimeError -Scope Script -ErrorAction SilentlyContinue
    }
}
if ($failures.Count) { throw ($failures -join "`n") }
$global:LASTEXITCODE = 0
Write-Host 'Update launch completion tests: OK (first-run retention and 13 owned mocked launcher sessions)'
