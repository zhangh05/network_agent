param(
    [switch]$NoBrowser,
    [switch]$SkipInstall,
    [switch]$ForceBuild
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendDir = Join-Path $Root "frontend"
$LogDir = if ($env:LOG_DIR) { $env:LOG_DIR } else { Join-Path $Root "logs" }
$BackendPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 8010 }
$FrontendPort = if ($env:FRONTEND_PORT) { [int]$env:FRONTEND_PORT } else { 5173 }
$BackendHost = if ($env:BACKEND_HOST) { $env:BACKEND_HOST } else { "0.0.0.0" }
$FrontendHost = if ($env:FRONTEND_HOST) { $env:FRONTEND_HOST } else { "0.0.0.0" }
$BackendPidFile = Join-Path $Root ".backend.pid"
$FrontendPidFile = Join-Path $Root ".frontend.pid"
$StateDir = Join-Path $Root ".runtime"

function Write-Step([string]$Message) {
    Write-Host "[network-agent] $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    throw $Message
}

function Test-Url([string]$Url) {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $Url | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Wait-Url([string]$Role, [string]$Url, [int]$Attempts = 60) {
    for ($i = 0; $i -lt $Attempts; $i++) {
        if (Test-Url $Url) {
            Write-Host "[$Role] Ready."
            return
        }
        Start-Sleep -Seconds 1
    }
    Fail "$Role failed to start. Check logs in $LogDir"
}

function Get-ListeningPid([int]$Port) {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($connection) { return [int]$connection.OwningProcess }
    return 0
}

function Test-ProjectProcess([int]$ProcessId, [string]$Role) {
    if ($ProcessId -le 0) { return $false }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $process) { return $false }
    $commandLine = [string]$process.CommandLine
    $rootPattern = [regex]::Escape($Root)
    if ($Role -eq "backend") {
        return $commandLine -match $rootPattern -and $commandLine -match "backend[\\/]main\.py"
    }
    return $commandLine -match $rootPattern -and $commandLine -match "vite"
}

function Assert-Port([string]$Role, [int]$Port, [string]$HealthUrl, [string]$PidFile) {
    $pidValue = Get-ListeningPid $Port
    if ($pidValue -eq 0) { return $false }
    if ((Test-ProjectProcess $pidValue $Role) -and (Test-Url $HealthUrl)) {
        Set-Content -Path $PidFile -Value $pidValue -Encoding ascii
        Write-Host "[$Role] Already running on port $Port (PID $pidValue)."
        return $true
    }
    Fail "Port $Port is occupied by another process (PID $pidValue)."
}

function Find-BasePython {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @{ File = $python.Source; Args = @() }
        }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3.12 -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @{ File = $launcher.Source; Args = @("-3.12") }
        }
    }
    Fail "Python 3.12+ was not found. Install it from python.org and enable the Python launcher."
}

function Ensure-Python {
    $venvPython = Join-Path (Join-Path $Root ".venv") "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        $base = Find-BasePython
        Write-Step "Creating isolated Python environment (.venv)..."
        & $base.File @($base.Args) -m venv (Join-Path $Root ".venv")
        if ($LASTEXITCODE -ne 0) { Fail "Failed to create .venv" }
    }
    & $venvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)"
    if ($LASTEXITCODE -ne 0) { Fail "Project .venv does not use Python 3.12+" }
    return $venvPython
}

function Ensure-PythonDependencies([string]$Python) {
    if ($SkipInstall -or $env:INSTALL_DEPS -in @("0", "false")) { return }
    $requirements = Join-Path $Root "requirements.txt"
    $stamp = Join-Path $StateDir "requirements.sha256"
    $hash = (Get-FileHash -Algorithm SHA256 $requirements).Hash
    $installedHash = if (Test-Path $stamp) { (Get-Content $stamp -Raw).Trim() } else { "" }
    & $Python -c "import flask, flask_sock, yaml, bs4, lxml, pdfplumber, scapy, paramiko" 2>$null
    if ($LASTEXITCODE -ne 0 -or $hash -ne $installedHash) {
        Write-Step "Installing Python dependencies..."
        & $Python -m pip install --disable-pip-version-check -r $requirements
        if ($LASTEXITCODE -ne 0) { Fail "Python dependency installation failed" }
        Set-Content -Path $stamp -Value $hash -Encoding ascii
    }
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { Fail "Python dependency check failed" }
}

function Ensure-Frontend {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $node -or -not $npm) {
        Fail "Node.js 18+ and npm are required. Install the current Node.js LTS release."
    }
    & $node.Source -e "process.exit(Number(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)"
    if ($LASTEXITCODE -ne 0) { Fail "Node.js 18+ is required" }

    $lockFile = Join-Path $FrontendDir "package-lock.json"
    $lockHash = (Get-FileHash -Algorithm SHA256 $lockFile).Hash
    $npmStamp = Join-Path $StateDir "frontend-lock.sha256"
    $installedHash = if (Test-Path $npmStamp) { (Get-Content $npmStamp -Raw).Trim() } else { "" }
    $viteScript = Join-Path $FrontendDir "node_modules\vite\bin\vite.js"
    if (-not $SkipInstall -and $env:INSTALL_DEPS -notin @("0", "false")) {
        if (-not (Test-Path $viteScript) -or $lockHash -ne $installedHash) {
            Write-Step "Installing frontend dependencies with npm ci..."
            Push-Location $FrontendDir
            try { & $npm.Source ci | Out-Host } finally { Pop-Location }
            if ($LASTEXITCODE -ne 0) { Fail "Frontend dependency installation failed" }
            Set-Content -Path $npmStamp -Value $lockHash -Encoding ascii
        }
    }
    if (-not (Test-Path $viteScript)) { Fail "Vite is not installed; rerun without -SkipInstall" }

    $distIndex = Join-Path $FrontendDir "dist\index.html"
    if ($ForceBuild -or -not (Test-Path $distIndex)) {
        Write-Step "Building the frontend..."
        Push-Location $FrontendDir
        try { & $npm.Source run build | Out-Host } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { Fail "Frontend build failed" }
    }
    return @{ Node = $node.Source; Vite = $viteScript }
}

function Get-AllowedOrigins {
    $origins = [System.Collections.Generic.List[string]]::new()
    $origins.Add("http://localhost:$FrontendPort")
    $origins.Add("http://127.0.0.1:$FrontendPort")
    $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" }
    foreach ($address in $addresses) {
        $origins.Add("http://$($address.IPAddress):$FrontendPort")
    }
    return ($origins | Select-Object -Unique) -join ","
}

New-Item -ItemType Directory -Force -Path $LogDir, $StateDir | Out-Null
Set-Location $Root
$startedProcessIds = [System.Collections.Generic.List[int]]::new()

try {
    $Python = Ensure-Python
    Ensure-PythonDependencies $Python
    $Frontend = Ensure-Frontend

    $backendHealth = "http://127.0.0.1:$BackendPort/api/health"
    $frontendHealth = "http://127.0.0.1:$FrontendPort"
    $backendRunning = Assert-Port "backend" $BackendPort $backendHealth $BackendPidFile
    if (-not $backendRunning) {
        Write-Step "Starting backend on ${BackendHost}:$BackendPort..."
        $env:NETWORK_AGENT_ALLOWED_ORIGINS = Get-AllowedOrigins
        $backend = Start-Process -FilePath $Python `
            -ArgumentList @("backend\main.py", "--host", $BackendHost, "--port", "$BackendPort") `
            -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $LogDir "backend-$BackendPort.log") `
            -RedirectStandardError (Join-Path $LogDir "backend-$BackendPort.err.log")
        $startedProcessIds.Add($backend.Id)
        Set-Content -Path $BackendPidFile -Value $backend.Id -Encoding ascii
        Wait-Url "backend" $backendHealth
    }

    $frontendRunning = Assert-Port "frontend" $FrontendPort $frontendHealth $FrontendPidFile
    if (-not $frontendRunning) {
        Write-Step "Starting frontend on ${FrontendHost}:$FrontendPort..."
        $env:VITE_DEV_API_TARGET = "http://127.0.0.1:$BackendPort"
        # Start-Process joins ArgumentList into one command line on Windows.
        # Quote the script path explicitly so release folders containing spaces work.
        $quotedViteScript = '"' + $Frontend.Vite.Replace('"', '\"') + '"'
        $frontendProcess = Start-Process -FilePath $Frontend.Node `
            -ArgumentList @($quotedViteScript, "preview", "--host", $FrontendHost, "--port", "$FrontendPort", "--strictPort") `
            -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $LogDir "frontend-$FrontendPort.log") `
            -RedirectStandardError (Join-Path $LogDir "frontend-$FrontendPort.err.log")
        $startedProcessIds.Add($frontendProcess.Id)
        Set-Content -Path $FrontendPidFile -Value $frontendProcess.Id -Encoding ascii
        Wait-Url "frontend" $frontendHealth
    }

    Write-Host ""
    Write-Host "Network Agent is ready:" -ForegroundColor Green
    Write-Host "  UI:      $frontendHealth"
    Write-Host "  API:     $backendHealth"
    Write-Host "  Logs:    $LogDir"
    Write-Host "  Stop:    stop.bat"
    if (-not $NoBrowser) { Start-Process $frontendHealth }
} catch {
    foreach ($startedId in $startedProcessIds) {
        & taskkill.exe /PID $startedId /T /F 2>$null | Out-Null
    }
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "See logs in: $LogDir"
    exit 1
}
