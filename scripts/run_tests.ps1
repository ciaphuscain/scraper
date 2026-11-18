# Run backend and frontend test suites.
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location (Join-Path $Root "backend"); & "$Root\.venv\Scripts\python.exe" -m pytest -q; $b = $LASTEXITCODE; Pop-Location
Push-Location (Join-Path $Root "frontend"); npm test; $f = $LASTEXITCODE; Pop-Location
if ($b -ne 0 -or $f -ne 0) { exit 1 }
