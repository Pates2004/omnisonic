$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\project_materials.ps1')
$testProject = Split-Path -Parent $PSScriptRoot
$batchSourcePath = Join-Path $testProject 'start_desktop.bat'
$batchSource = [IO.File]::ReadAllText($batchSourcePath)
$guardPattern = '(?m)^    if not errorlevel 0 goto updater_failed\r?\n'
if ([regex]::Matches($batchSource, $guardPattern).Count -ne 2) {
    throw 'Both recovery and updater require signed-exit guards in the real bootstrap.'
}
$legacySource = [regex]::Replace($batchSource, $guardPattern, '')
$fixtureRoot = Join-ProjectMaterialPath $testProject (
    'Trash\updater-batch-' + [Guid]::NewGuid().ToString('N')
)
$fixtureRoot = Assert-ProjectTestPath $fixtureRoot $testProject
[IO.Directory]::CreateDirectory($fixtureRoot) | Out-Null

function Assert-UpdaterBatch {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Updater batch regression: $Message" }
}

$updaterStub = @'
$settings = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'scenario.json')) | ConvertFrom-Json
[IO.File]::AppendAllText((Join-Path $PSScriptRoot 'trace.txt'), "updater`n")
exit ([int]$settings.updater)
'@
$recoveryStub = @'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$settings = [IO.File]::ReadAllText((Join-Path $root 'scenario.json')) | ConvertFrom-Json
[IO.File]::AppendAllText((Join-Path $root 'trace.txt'), "recovery`n")
exit ([int]$settings.recovery)
'@
$launcherStub = @'
$trace = Join-Path $PSScriptRoot 'trace.txt'
if ($args -contains '-QueryHiddenLaunch') {
    [IO.File]::AppendAllText($trace, "query`n")
    Write-Output 'SHOW'
    exit 0
}
[IO.File]::AppendAllText($trace, "launcher`n")
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'launcher-args.json'), (ConvertTo-Json -InputObject @($args) -Compress))
exit 0
'@

function Invoke-OwnedBatchFixture {
    param($Scenario)
    $noArguments = $Scenario.ContainsKey('NoArguments') -and [bool]$Scenario.NoArguments
    $program = Join-Path $fixtureRoot ($Scenario.Name + ' space & percent%')
    [IO.Directory]::CreateDirectory($program) | Out-Null
    $batch = Join-Path $program 'start_desktop.bat'
    if ($Scenario.ContainsKey('Legacy') -and $Scenario.Legacy) {
        [IO.File]::WriteAllText($batch, $legacySource, (New-Object Text.UTF8Encoding($false)))
    } else {
        # Exact, announced test-only executable source copy; no application,
        # Python distribution, private profile or runtime is copied.
        [IO.File]::Copy($batchSourcePath, $batch)
        Assert-UpdaterBatch ((Get-FileHash -LiteralPath $batch -Algorithm SHA256).Hash -ceq
            (Get-FileHash -LiteralPath $batchSourcePath -Algorithm SHA256).Hash) 'Owned bootstrap copy matches the real source bytes'
    }
    [IO.File]::WriteAllText((Join-Path $program 'scenario.json'), (
        ConvertTo-Json -InputObject @{ updater = $Scenario.Updater; recovery = $Scenario.Recovery }
    ))
    if ($Scenario.HasUpdater) {
        [IO.File]::WriteAllText((Join-Path $program 'desktop_updater.ps1'), $updaterStub)
    }
    if ($Scenario.HasRecovery) {
        $recovery = Join-Path $program '.launcher\update-recovery\recover.ps1'
        [IO.Directory]::CreateDirectory((Split-Path -Parent $recovery)) | Out-Null
        [IO.File]::WriteAllText($recovery, $recoveryStub)
    }
    [IO.File]::WriteAllText((Join-Path $program 'desktop_launcher.ps1'), $launcherStub)
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = Join-Path ([Environment]::SystemDirectory) 'cmd.exe'
    $info.WorkingDirectory = $program
    $suffix = if ($noArguments) { '' } else { ' -Backend CPU -Mode Portable' }
    $info.Arguments = '/d /s /c ""' + $batch + '"' + $suffix + '"'
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    $started = $false
    try {
        Assert-UpdaterBatch ($process.Start()) 'Owned CMD child starts'
        $started = $true
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        # Error paths intentionally execute PAUSE. Supply input and close the
        # owned pipe so tests cannot wait for a user or consume real keyboard input.
        $process.StandardInput.WriteLine('')
        $process.StandardInput.Close()
        Assert-UpdaterBatch ($process.WaitForExit(20000)) ('Owned CMD child exceeds 20 seconds: ' + $Scenario.Name)
        $output = $stdout.GetAwaiter().GetResult() + $stderr.GetAwaiter().GetResult()
        $tracePath = Join-Path $program 'trace.txt'
        $trace = if (Test-Path -LiteralPath $tracePath) { ([IO.File]::ReadAllLines($tracePath) -join ',') } else { '' }
        Assert-UpdaterBatch ($process.ExitCode -eq $Scenario.Exit) (
            $Scenario.Name + ' expected exit=' + $Scenario.Exit + ', actual=' + $process.ExitCode + '; output=' + $output
        )
        Assert-UpdaterBatch ($trace -ceq $Scenario.Trace) (
            $Scenario.Name + ' expected trace=' + $Scenario.Trace + ', actual=' + $trace
        )
        if ($Scenario.Exit -eq 1) {
            Assert-UpdaterBatch ($output.Contains('The source update or recovery could not finish')) (
                $Scenario.Name + ' reports failure instead of attempting the live launcher'
            )
        }
        if ($trace -match '(?:^|,)launcher$') {
            $received = @([IO.File]::ReadAllText((Join-Path $program 'launcher-args.json')) | ConvertFrom-Json | ForEach-Object { $_ })
            $expected = if ($noArguments) { @() } else { @('-Backend', 'CPU', '-Mode', 'Portable') }
            Assert-UpdaterBatch (($received -join '|') -ceq ($expected -join '|')) ($Scenario.Name + ' forwards launcher arguments unchanged')
        }
    }
    finally {
        if ($started -and -not $process.HasExited) {
            $stopInfo = New-Object Diagnostics.ProcessStartInfo
            $stopInfo.FileName = Join-Path ([Environment]::SystemDirectory) 'taskkill.exe'
            $stopInfo.Arguments = '/PID ' + $process.Id + ' /T /F'
            $stopInfo.UseShellExecute = $false
            $stopInfo.CreateNoWindow = $true
            $stopInfo.RedirectStandardOutput = $true
            $stopInfo.RedirectStandardError = $true
            $stopper = [Diagnostics.Process]::Start($stopInfo)
            try {
                if (-not $stopper.WaitForExit(5000)) { $stopper.Kill() }
            } finally { $stopper.Dispose() }
        }
        $process.Dispose()
    }
}

$scenarios = @(
    @{Name='updater-zero'; Updater=0; Recovery=0; HasUpdater=$true; HasRecovery=$false; Exit=0; Trace='updater,launcher'},
    @{Name='updater-handoff'; Updater=10; Recovery=0; HasUpdater=$true; HasRecovery=$false; Exit=0; Trace='updater'},
    @{Name='updater-recovery-required'; Updater=20; Recovery=0; HasUpdater=$true; HasRecovery=$false; Exit=1; Trace='updater'},
    @{Name='updater-positive-error'; Updater=1; Recovery=0; HasUpdater=$true; HasRecovery=$false; Exit=1; Trace='updater'},
    @{Name='updater-positive-other'; Updater=9; Recovery=0; HasUpdater=$true; HasRecovery=$false; Exit=1; Trace='updater'},
    @{Name='updater-negative-one'; Updater=-1; Recovery=0; HasUpdater=$true; HasRecovery=$false; Exit=1; Trace='updater'},
    @{Name='updater-native-status'; Updater=-1073741819; Recovery=0; HasUpdater=$true; HasRecovery=$false; Exit=1; Trace='updater'},
    @{Name='recovery-zero'; Updater=0; Recovery=0; HasUpdater=$true; HasRecovery=$true; Exit=0; Trace='recovery,updater,launcher'},
    @{Name='recovery-positive-error'; Updater=0; Recovery=1; HasUpdater=$true; HasRecovery=$true; Exit=1; Trace='recovery'},
    @{Name='recovery-negative-one'; Updater=0; Recovery=-1; HasUpdater=$true; HasRecovery=$true; Exit=1; Trace='recovery'},
    @{Name='recovery-native-status'; Updater=0; Recovery=-1073741819; HasUpdater=$true; HasRecovery=$true; Exit=1; Trace='recovery'},
    @{Name='missing-updater'; Updater=0; Recovery=0; HasUpdater=$false; HasRecovery=$false; Exit=0; Trace='launcher'},
    @{Name='ordinary-query'; Updater=0; Recovery=0; HasUpdater=$true; HasRecovery=$false; Exit=0; Trace='updater,query,launcher'; NoArguments=$true},
    @{Name='legacy-updater-negative'; Updater=-1073741819; Recovery=0; HasUpdater=$true; HasRecovery=$false; Exit=0; Trace='updater,launcher'; Legacy=$true},
    @{Name='legacy-recovery-negative'; Updater=0; Recovery=-1073741819; HasUpdater=$true; HasRecovery=$true; Exit=0; Trace='recovery,updater,launcher'; Legacy=$true}
)
foreach ($scenario in $scenarios) { Invoke-OwnedBatchFixture $scenario }
$global:LASTEXITCODE = 0
Write-Host 'Updater batch tests: OK (13 real bootstrap routes + 2 isolated pre-fix counterexamples)'
