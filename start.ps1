param(
    [ValidateSet('synthetic', 'live', 'replay', 'assistant')][string]$Mode = 'synthetic',
    [ValidateSet('synthetic', 'live', 'replay')][string]$MapMode = 'synthetic',
    [int]$Port = 8000,
    [switch]$InstallDependencies
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or 3.13 is required.' }
    $InstallDependencies = $true
}
if ($InstallDependencies) {
    & $projectPython -m pip install -r requirements.txt -c constraints.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; check the network and retry.' }
}
& $projectPython scripts/serve.py --mode $Mode --map-mode $MapMode --port $Port
exit $LASTEXITCODE
