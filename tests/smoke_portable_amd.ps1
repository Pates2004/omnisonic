[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$testProject = Split-Path -Parent $PSScriptRoot
. (Join-Path $testProject 'desktop_launcher.ps1')

$sampleRoot = Assert-ProjectChildPath (Join-Path $ProjectRoot 'Workspace\amd-portable-validation')
$stagingRoot = Join-Path $sampleRoot 'env.new'
$activeRoot = Join-Path $sampleRoot 'env'
$WorkDir = Join-Path $sampleRoot '.launcher'
foreach ($path in @($stagingRoot, $activeRoot, $WorkDir)) {
    Assert-ProjectChildPath $path | Out-Null
}
if ((Test-Path -LiteralPath $stagingRoot) -or (Test-Path -LiteralPath $activeRoot)) {
    throw "Portable AMD validation already exists; preserving it at $sampleRoot."
}
$matrix = Get-BackendMatrix
$profile = Get-BackendProfile $matrix 'rocm'
$controllers = Get-VideoControllers
$processorName = Get-ProcessorName
$inventory = Get-HardwareInventory $controllers $processorName $matrix
if (@($inventory | Where-Object { $_.Backend -eq 'rocm' -and $_.Supported }).Count -eq 0) {
    throw 'This test requires a supported AMD Radeon device and driver.'
}
$hardwareFingerprint = Get-HardwareFingerprint $controllers $processorName
New-Item -ItemType Directory -Path $sampleRoot -Force | Out-Null
$python = Install-PortablePythonAt $stagingRoot
Install-BackendRuntime $python 'rocm' 'rocm' $profile $hardwareFingerprint $stagingRoot
if (-not (Test-Runtime $python 'rocm' $profile $hardwareFingerprint $stagingRoot)) {
    throw "The staged portable ROCm environment failed validation: $script:LastRuntimeError"
}
$sampleRootPath = [IO.Path]::GetFullPath($sampleRoot).TrimEnd('\')
foreach ($path in @($stagingRoot, $activeRoot)) {
    $validatedPath = [IO.Path]::GetFullPath($path)
    if (-not $validatedPath.StartsWith($sampleRootPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to move a Python environment outside $sampleRoot"
    }
}
Move-Item -LiteralPath $stagingRoot -Destination $activeRoot
$python = Get-EnvironmentPython 'Portable' $activeRoot
if (-not (Test-Runtime $python 'rocm' $profile $hardwareFingerprint $activeRoot)) {
    throw "The activated portable ROCm environment failed validation: $script:LastRuntimeError"
}
Write-Host "Portable AMD ROCm installation, activation, desktop imports and GPU tensor: OK"
Write-Host "Environment: $activeRoot"
