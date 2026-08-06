# ============================================================
#  Castorice Agent - Single Instance Launcher
#  Features: anti-duplicate, frontend+backend bound, process cleanup
# ============================================================

param([switch]$SkipDeps = $false)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# ---------- Config ----------
$BackendPort = 5477
$FrontendPort = 1420
$BackendLog = Join-Path $ProjectRoot "backend_stderr.log"
$FrontendLog = Join-Path $ProjectRoot "frontend.log"
$PidFile = Join-Path $ProjectRoot ".castorice_running.pid"
$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"

$children = @()

# ---------- Helpers ----------
function Write-Step($msg) { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] WARN: $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ERR: $msg" -ForegroundColor Red }

function Test-PortInUse($port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        return [bool]$conn
    } catch { return $false }
}

function Stop-ChildProcesses {
    Write-Warn "Cleaning up child processes..."
    foreach ($childPid in $children) {
        try {
            $proc = Get-Process -Id $childPid -ErrorAction SilentlyContinue
            if ($proc -and !$proc.HasExited) {
                Stop-Process -Id $childPid -Force -ErrorAction SilentlyContinue
                Write-Host "  Stopped PID=$childPid" -ForegroundColor Gray
            }
        } catch {}
    }
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
    Write-Warn "Cleanup done"
}

# Register exit event
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Stop-ChildProcesses }
try { [Console]::TreatControlCAsInput = $false } catch {}

# ---------- 1. Anti-duplicate check ----------
Write-Step "Checking for existing instances..."

$portConflict = $false
if (Test-PortInUse $BackendPort) {
    Write-Warn "Backend port $BackendPort already in use"
    $portConflict = $true
}
if (Test-PortInUse $FrontendPort) {
    Write-Warn "Frontend port $FrontendPort already in use"
    $portConflict = $true
}

if ($portConflict) {
    Write-Err "An instance is already running! Please close it first."
    Write-Host "Tip: End python.exe and node.exe in Task Manager"
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Ok "No port conflicts"

# ---------- 2. Environment check ----------
Write-Step "Checking runtime environment..."

if (-not (Test-Path $VenvPython)) {
    Write-Err "Virtual environment not found: $VenvPython"
    Write-Host "Please run install.bat or start.bat first"
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Ok "Virtual environment ready"

$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    Write-Err "Node.js not found, please install it first"
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Ok "Node.js ready"

# ---------- 3. Load .env (contains API keys) ----------
Write-Step "Loading .env..."
$envFile = Join-Path $ProjectRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $idx = $line.IndexOf("=")
            $k = $line.Substring(0, $idx).Trim()
            $v = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
            Set-Item -Path "env:$k" -Value $v
        }
    }
    Write-Ok ".env loaded"
} else {
    Write-Warn ".env not found, backend may fail to call LLM providers"
}

# ---------- 4. Start backend ----------
Write-Step "Starting backend (port $BackendPort)..."
$backendArgs = @("-m", "castorice.main", "--mode", "http")
$backendProc = Start-Process -FilePath $VenvPython -ArgumentList $backendArgs `
    -RedirectStandardError $BackendLog -NoNewWindow -PassThru -WorkingDirectory $ProjectRoot
$children += $backendProc.Id
Write-Ok "Backend started (PID=$($backendProc.Id)), log: backend_stderr.log"

# Wait for backend ready (up to 5 min for ChromaDB)
Write-Step "Waiting for backend (ChromaDB may take 3-5 min on first load)..."
$backendReady = $false
$maxWait = 300
$waited = 0
while ($waited -lt $maxWait -and !$backendProc.HasExited) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/status" -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) {
            $backendReady = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 3
    $waited += 3
    if ($waited % 30 -eq 0) {
        Write-Host "  Waited ${waited}s, backend still initializing..." -ForegroundColor Gray
    }
}

if ($backendProc.HasExited) {
    Write-Err "Backend exited unexpectedly (code: $($backendProc.ExitCode))"
    Write-Host "Check backend_stderr.log for details"
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not $backendReady) {
    Write-Warn "Backend readiness timeout, continuing (backend may still be loading)"
} else {
    Write-Ok "Backend is ready"
}

# ---------- 4. Start frontend ----------
Write-Step "Starting frontend (port $FrontendPort)..."
$frontendDir = Join-Path $ProjectRoot "castorice-desktop"
# Install frontend deps if needed
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Step "First launch, installing frontend dependencies..."
    Push-Location $frontendDir
    & npm install 2>&1 | Out-Null
    Pop-Location
    Write-Ok "Frontend dependencies installed"
}

$vitePath = Join-Path $frontendDir "node_modules\.bin\vite.cmd"
if (-not (Test-Path $vitePath)) {
    Write-Warn "vite not found, running npm install first..."
    Push-Location $frontendDir
    & cmd /c "npm install" 2>&1 | Out-Null
    Pop-Location
}
$frontendProc = Start-Process -FilePath "cmd" -ArgumentList @("/c", "`"$vitePath`"") `
    -RedirectStandardOutput $FrontendLog `
    -NoNewWindow -PassThru -WorkingDirectory $frontendDir
$children += $frontendProc.Id
Write-Ok "Frontend started (PID=$($frontendProc.Id)), log: frontend.log"

# Wait for frontend ready
Write-Step "Waiting for frontend..."
$frontendReady = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$FrontendPort" -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) {
            $frontendReady = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 2
}

if (-not $frontendReady) {
    Write-Warn "Frontend readiness timeout, but will try to open browser anyway"
} else {
    Write-Ok "Frontend is ready"
}

# ---------- 5. Save PID + open browser ----------
$pidData = @{
    timestamp = Get-Date -Format "o"
    backend_pid = $backendProc.Id
    frontend_pid = $frontendProc.Id
    launcher_pid = $PID
}
$pidData | ConvertTo-Json | Set-Content $PidFile -Encoding UTF8

Write-Step "Opening browser: http://127.0.0.1:$FrontendPort"
Start-Process "http://127.0.0.1:$FrontendPort"

# ---------- 7. Keep running ----------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "  Castorice Agent started" -ForegroundColor Magenta
Write-Host "  Backend:  http://127.0.0.1:$BackendPort  (PID=$($backendProc.Id))" -ForegroundColor Gray
Write-Host "  Frontend: http://127.0.0.1:$FrontendPort  (PID=$($frontendProc.Id))" -ForegroundColor Gray
Write-Host "" -ForegroundColor Gray
Write-Host "  Press Ctrl+C or close this window to stop all services" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host ""

# Monitor processes
try {
    while ($true) {
        if ($backendProc.HasExited) {
            Write-Err "Backend process exited (PID=$($backendProc.Id))"
            break
        }
        if ($frontendProc.HasExited) {
            Write-Err "Frontend process exited (PID=$($frontendProc.Id))"
            break
        }
        Start-Sleep -Seconds 5
    }
} finally {
    Write-Warn "Exit signal received, cleaning up..."
    Stop-ChildProcesses
}
