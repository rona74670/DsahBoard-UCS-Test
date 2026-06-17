# install_service.ps1
# ─────────────────────────────────────────────────────────────────────────────
# Registers the UCS Dashboard as a Windows Service via NSSM.
# Run as Administrator.
#
# NSSM (Non-Sucking Service Manager) keeps the process alive 24/7,
# restarts it automatically on crash, and starts it on Windows boot.
#
# Usage:
#   Right-click → "Run with PowerShell as Administrator"
#   Or: powershell -ExecutionPolicy Bypass -File install_service.ps1
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

# ── Configuration ─────────────────────────────────────────────────────────────
$ServiceName  = "UcsDashboard"
$DisplayName  = "UCS Dashboard (FastAPI)"
$Description  = "UCS Manager monitoring dashboard – FastAPI on port 9000"
$Port         = 9000
$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir   = Join-Path $ScriptDir "backend"
$NssmDir      = Join-Path $ScriptDir "tools\nssm"
$NssmExe      = Join-Path $NssmDir "nssm.exe"
$NssmUrl      = "https://nssm.cc/release/nssm-2.24.zip"
$NssmZip      = Join-Path $NssmDir "nssm.zip"
$LogDir       = Join-Path $ScriptDir "logs"
$StdoutLog    = Join-Path $LogDir "dashboard_stdout.log"
$StderrLog    = Join-Path $LogDir "dashboard_stderr.log"

# Detect Python launcher
$PythonExe = (Get-Command "py.exe" -ErrorAction SilentlyContinue)?.Source
if (-not $PythonExe) {
    $PythonExe = (Get-Command "python.exe" -ErrorAction SilentlyContinue)?.Source
}
if (-not $PythonExe) {
    Write-Error "Python not found. Install Python 3 and ensure it is in PATH."
    exit 1
}

Write-Host "`n=== UCS Dashboard – Windows Service Installer ===" -ForegroundColor Cyan
Write-Host "  Backend dir : $BackendDir"
Write-Host "  Python      : $PythonExe"
Write-Host "  Service name: $ServiceName"
Write-Host "  Port        : $Port`n"

# ── Download NSSM if not present ─────────────────────────────────────────────
if (-not (Test-Path $NssmExe)) {
    Write-Host "[1/4] Downloading NSSM..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $NssmDir | Out-Null
    Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip -UseBasicParsing
    Expand-Archive -Path $NssmZip -DestinationPath $NssmDir -Force
    # NSSM extracts as nssm-2.24\win64\nssm.exe
    $extracted = Get-ChildItem -Path $NssmDir -Recurse -Filter "nssm.exe" |
                 Where-Object { $_.FullName -match "win64" } |
                 Select-Object -First 1
    if (-not $extracted) {
        $extracted = Get-ChildItem -Path $NssmDir -Recurse -Filter "nssm.exe" |
                     Select-Object -First 1
    }
    Copy-Item $extracted.FullName -Destination $NssmExe -Force
    Remove-Item $NssmZip -Force
    Write-Host "   NSSM downloaded to $NssmExe" -ForegroundColor Green
} else {
    Write-Host "[1/4] NSSM already present." -ForegroundColor Green
}

# ── Remove existing service if present ───────────────────────────────────────
Write-Host "[2/4] Removing old service (if any)..." -ForegroundColor Yellow
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    & $NssmExe remove $ServiceName confirm | Out-Null
    Start-Sleep -Seconds 1
    Write-Host "   Old service removed." -ForegroundColor Green
} else {
    Write-Host "   No existing service found." -ForegroundColor Green
}

# ── Create logs directory ─────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ── Install service ───────────────────────────────────────────────────────────
Write-Host "[3/4] Installing service..." -ForegroundColor Yellow

$uvicornArgs = "-m uvicorn app:app --host 0.0.0.0 --port $Port --workers 1"

& $NssmExe install      $ServiceName $PythonExe $uvicornArgs
& $NssmExe set          $ServiceName AppDirectory    $BackendDir
& $NssmExe set          $ServiceName DisplayName     $DisplayName
& $NssmExe set          $ServiceName Description     $Description
& $NssmExe set          $ServiceName Start           SERVICE_AUTO_START
& $NssmExe set          $ServiceName AppStdout       $StdoutLog
& $NssmExe set          $ServiceName AppStderr       $StderrLog
& $NssmExe set          $ServiceName AppRotateFiles  1
& $NssmExe set          $ServiceName AppRotateBytes  10485760   # 10 MB
& $NssmExe set          $ServiceName AppRestartDelay 5000       # 5 s before restart

Write-Host "   Service installed." -ForegroundColor Green

# ── Start service ─────────────────────────────────────────────────────────────
Write-Host "[4/4] Starting service..." -ForegroundColor Yellow
& $NssmExe start $ServiceName
Start-Sleep -Seconds 4

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "`n✅  Service '$ServiceName' is RUNNING on port $Port" -ForegroundColor Green
    Write-Host "    Dashboard: http://localhost:$Port" -ForegroundColor Cyan
} else {
    Write-Warning "Service may not have started. Check logs:`n  $StdoutLog`n  $StderrLog"
}

Write-Host "`nTo manage the service:"
Write-Host "  Stop  : Stop-Service  $ServiceName"
Write-Host "  Start : Start-Service $ServiceName"
Write-Host "  Remove: & '$NssmExe' remove $ServiceName confirm`n"
