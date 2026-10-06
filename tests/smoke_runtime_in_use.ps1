[CmdletBinding()]
param(
    [string]$SystemEnvironment = '',
    [string]$PortableEnvironment = ''
)

$ErrorActionPreference = 'Stop'
$testProject = Split-Path -Parent $PSScriptRoot
. (Join-Path $testProject 'desktop_launcher.ps1')
if (-not $SystemEnvironment) { $SystemEnvironment = Join-Path $testProject 'venv' }
if (-not $PortableEnvironment) {
    $PortableEnvironment = Join-Path $testProject 'Workspace\amd-portable-validation\env'
}

# These helpers only sleep. No imports of the application, user files or microphone.
foreach ($entry in @(
    @{ Root = $SystemEnvironment; RelativePython = 'Scripts\python.exe' },
    @{ Root = $PortableEnvironment; RelativePython = 'python.exe' }
)) {
    $runtimeRoot = Assert-ProjectChildPath $entry.Root
    $interpreter = Join-Path $runtimeRoot $entry.RelativePython
    if (-not (Test-Path -LiteralPath $interpreter -PathType Leaf)) {
        throw "Test interpreter does not exist: $interpreter"
    }
    $helper = Start-Process -FilePath $interpreter `
        -ArgumentList @('-c', '"import time; time.sleep(8)"') -WindowStyle Hidden -PassThru
    try {
        $detected = $false
        $deadline = [Diagnostics.Stopwatch]::StartNew()
        while (-not $detected -and $deadline.Elapsed.TotalSeconds -lt 4) {
            try { Assert-RuntimeNotInUse @($runtimeRoot) }
            catch {
                if (-not (Test-RuntimeInUseError $_.Exception)) { throw }
                $detected = $true
            }
            if (-not $detected) { Start-Sleep -Milliseconds 50 }
        }
        if (-not $detected) { throw "Live interpreter was not detected: $runtimeRoot" }
        Write-Host "Live interpreter correctly protected: $runtimeRoot"
    }
    finally {
        if (-not $helper.WaitForExit(12000)) {
            throw "Short-lived test helper did not exit as expected (PID $($helper.Id))."
        }
        $helper.Dispose()
    }
}
Write-Host 'Real system-venv and portable runtime usage smoke: OK (no runtime mutations)'
