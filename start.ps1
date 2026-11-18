<#
.SYNOPSIS
  Start YouTube Content Intelligence Studio (backend API, processing worker, frontend).
.PARAMETER Prod
  Serve a production build of the frontend from the backend (single URL) instead of the Vite dev server.
.PARAMETER ApiPort
  Backend port (default 8765).
#>
[CmdletBinding()]
param([switch]$Prod, [int]$ApiPort = 8765, [int]$UiPort = 5173)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Die($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function PortInUse($port) {
    try { $c = New-Object Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $port); $c.Close(); return $true } catch { return $false }
}
function StopTree($p) {
    if ($p -and -not $p.HasExited) {
        try { & taskkill.exe /PID $p.Id /T /F *> $null } catch { }
    }
}

if (-not (Test-Path $venvPy)) { Die "Python environment missing. Run .\setup.ps1 first." }
if (-not $Prod -and -not (Test-Path "frontend\node_modules")) { Die "Frontend dependencies missing. Run .\setup.ps1 first." }
if (PortInUse $ApiPort) { Die "Port $ApiPort is already in use. Is the app already running? Close it or use -ApiPort." }
if (-not $Prod -and (PortInUse $UiPort)) { Die "Port $UiPort is already in use (another Vite dev server?)." }

if ($Prod) {
    Write-Host "Building frontend..." -ForegroundColor Cyan
    Push-Location frontend; try { npm run build | Out-Host; if ($LASTEXITCODE -ne 0) { Die "Frontend build failed" } } finally { Pop-Location }
}

$env:YTCS_PORT = "$ApiPort"
$procs = @()
try {
    Write-Host "Starting backend API on http://127.0.0.1:$ApiPort ..." -ForegroundColor Cyan
    $api = Start-Process -FilePath $venvPy -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
        -WorkingDirectory (Join-Path $Root "backend") -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "api.out.log") -RedirectStandardError (Join-Path $logDir "api.err.log")
    $procs += $api

    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        if ($api.HasExited) { break }
        try { Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health" -TimeoutSec 2 | Out-Null; $ready = $true; break } catch {}
    }
    if (-not $ready) {
        Write-Host "Backend failed to start. Last log lines:" -ForegroundColor Red
        Get-Content (Join-Path $logDir "api.err.log") -Tail 25 -ErrorAction SilentlyContinue
        throw "backend did not start"
    }

    Write-Host "Starting processing worker..." -ForegroundColor Cyan
    $worker = Start-Process -FilePath $venvPy -ArgumentList @("-m", "app.workers.runner") `
        -WorkingDirectory (Join-Path $Root "backend") -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "worker.out.log") -RedirectStandardError (Join-Path $logDir "worker.err.log")
    Start-Sleep -Seconds 2
    if ($worker.HasExited) {
        if ($worker.ExitCode -eq 2) { Write-Host "A worker is already running for this archive; reusing it." -ForegroundColor Yellow }
        else { Get-Content (Join-Path $logDir "worker.err.log") -Tail 25 -ErrorAction SilentlyContinue; throw "worker failed to start" }
    } else { $procs += $worker }

    if (-not $Prod) {
        Write-Host "Starting frontend dev server..." -ForegroundColor Cyan
        $env:VITE_API_URL = "http://127.0.0.1:$ApiPort"
        $ui = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "npm", "run", "dev", "--", "--port", "$UiPort", "--strictPort") `
            -WorkingDirectory (Join-Path $Root "frontend") -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logDir "ui.out.log") -RedirectStandardError (Join-Path $logDir "ui.err.log")
        $procs += $ui
        $url = "http://localhost:$UiPort"
        for ($i = 0; $i -lt 40; $i++) { Start-Sleep -Milliseconds 500; if (PortInUse $UiPort) { break } }
    } else { $url = "http://127.0.0.1:$ApiPort" }

    try { $null = Invoke-RestMethod "http://127.0.0.1:11434/api/version" -TimeoutSec 2; $ollama = "running" } catch { $ollama = "not running (optional - start Ollama for idea extraction)" }

    Write-Host ""
    Write-Host "  YouTube Content Intelligence Studio is running" -ForegroundColor Green
    Write-Host "    App:      $url"
    Write-Host "    API:      http://127.0.0.1:$ApiPort/docs"
    Write-Host "    Ollama:   $ollama"
    Write-Host "    Logs:     $logDir"
    Write-Host "  Press Ctrl+C to stop."
    Start-Process $url | Out-Null

    while ($true) {
        Start-Sleep -Seconds 2
        if ($api.HasExited) { Write-Host "Backend stopped unexpectedly (see logs\api.err.log)." -ForegroundColor Red; break }
    }
} finally {
    Write-Host "`nStopping services..." -ForegroundColor Cyan
    foreach ($p in $procs) { StopTree $p }
    Write-Host "Stopped."
}
