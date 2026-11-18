<#
.SYNOPSIS
  One-time setup for YouTube Content Intelligence Studio on Windows 10/11.
.DESCRIPTION
  Verifies Python (3.12/3.13), creates .venv, installs backend dependencies,
  checks FFmpeg and Node.js, installs frontend dependencies, initialises the
  database and runs a configuration check. It never installs unrelated
  software; missing system dependencies are reported with instructions.
#>
[CmdletBinding()]
param([switch]$SkipFrontend)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$missing = New-Object System.Collections.Generic.List[string]

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "    XX  $msg" -ForegroundColor Red }

# 1-2. Python
Step "Checking Python (3.12 or 3.13)"
$python = $null
$candidates = @(@("py", "-3.13"), @("py", "-3.12"), @("python"), @("python3"))
foreach ($c in $candidates) {
    $exe = $c[0]; $pyArgs = @(); if ($c.Count -gt 1) { $pyArgs = $c[1..($c.Count - 1)] }
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    try { $ver = & $exe @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null } catch { continue }
    if ($LASTEXITCODE -ne 0 -or -not $ver) { continue }
    $parts = $ver.Trim().Split("."); $maj = [int]$parts[0]; $min = [int]$parts[1]
    if ($maj -eq 3 -and $min -ge 12) { $python = @($exe) + $pyArgs; Ok "Python $ver ($($python -join ' '))"; break }
    else { Warn "Found Python $ver via '$exe' - not supported" }
}
if (-not $python) {
    Fail "Python 3.12 or 3.13 not found."
    Write-Host "    Install it from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH'), then re-run setup.ps1."
    exit 1
}

# 3. Virtual environment
Step "Creating virtual environment (.venv)"
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    $pyExe = $python[0]; $pyRest = @(); if ($python.Count -gt 1) { $pyRest = $python[1..($python.Count - 1)] }
    & $pyExe @pyRest -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the virtual environment"; exit 1 }
}
Ok $venvPy

# 4. Backend dependencies
Step "Installing backend dependencies (this can take a few minutes)"
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r backend\requirements-dev.txt
if ($LASTEXITCODE -ne 0) { Fail "pip install failed - check your internet connection and re-run"; exit 1 }
Ok "Backend dependencies installed"

# 5. FFmpeg
Step "Checking FFmpeg"
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Ok (Get-Command ffmpeg).Source }
else {
    Warn "FFmpeg not found on PATH."
    Write-Host "    Captions work without it. For robust local transcription install FFmpeg, e.g.:"
    Write-Host "      winget install --id Gyan.FFmpeg -e" -ForegroundColor Gray
    Write-Host "    then open a new terminal."
    $missing.Add("FFmpeg (recommended)")
}

# 6-7. Node.js + frontend
if (-not $SkipFrontend) {
    Step "Checking Node.js (18+)"
    if (Get-Command node -ErrorAction SilentlyContinue) {
        $nv = (node --version).TrimStart("v"); $nmaj = [int]($nv.Split(".")[0])
        if ($nmaj -ge 18) { Ok "Node.js $nv" } else { Fail "Node.js $nv is too old (need 18+)"; $missing.Add("Node.js 18+") }
    } else {
        Fail "Node.js not found. Install the LTS version from https://nodejs.org/ (or: winget install OpenJS.NodeJS.LTS)"
        $missing.Add("Node.js 18+")
    }
    if (-not ($missing -contains "Node.js 18+")) {
        Step "Installing frontend dependencies"
        Push-Location frontend
        try {
            if (Test-Path package-lock.json) { npm ci --no-audit --no-fund } else { npm install --no-audit --no-fund }
            if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
            Ok "Frontend dependencies installed"
        } finally { Pop-Location }
    }
}

# 8. Database
Step "Initialising database"
Push-Location backend
try {
    & $venvPy -m app.database.init_db
    if ($LASTEXITCODE -ne 0) { Fail "Database initialisation failed"; exit 1 }
} finally { Pop-Location }

# 9. Configuration check
Step "Verifying configuration"
Push-Location backend
try { & $venvPy -m app.core.doctor; $doctorExit = $LASTEXITCODE } finally { Pop-Location }

# 10. Report
Step "Summary"
if ($missing.Count -gt 0) { Warn ("Missing or outdated: " + ($missing -join ", ")) }
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Warn "Ollama CLI not found. Idea extraction needs Ollama (https://ollama.com/download). Then run: ollama pull qwen2.5:7b"
}
if ($doctorExit -eq 0 -and -not ($missing -contains "Node.js 18+")) {
    Write-Host "`nSetup complete. Start the app with:  .\start.ps1" -ForegroundColor Green
} else {
    Write-Host "`nSetup finished with problems - fix the items above and re-run setup.ps1." -ForegroundColor Yellow
    exit 1
}
