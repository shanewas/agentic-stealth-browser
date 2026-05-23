<#
.SYNOPSIS
    Sets up the Stealth Browser Remote Bridge (RBB) on Windows.

.DESCRIPTION
    Installs prerequisites, creates a Windows Service wrapper, and configures
    a cloudflared tunnel for remote CDP access.

.PARAMETER InstallDir
    Root directory for the RBB installation (default: $env:ProgramFiles\StealthRBB)

.PARAMETER BridgePort
    TCP port for the bridge (default: 9222)

.PARAMETER TunnelNamespace
    Cloudflare tunnel namespace (default: stealth-browser)
#>

param(
    [string]$InstallDir   = "$env:ProgramFiles\StealthRBB",
    [int]$BridgePort      = 9222,
    [string]$TunnelNamespace = "stealth-browser"
)

$ErrorActionPreference = "Stop"
$LogDir = "$env:ProgramData\StealthRBB\logs"

Write-Host ""
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host "    Stealth Browser - Remote Bridge Setup" -ForegroundColor Cyan
Write-Host "    Windows Edition" -ForegroundColor Cyan
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

# ──────────────────────────────────────────────
# 1. Check prerequisites
# ──────────────────────────────────────────────
function Test-Prerequisites {
    Write-Host "[INFO] Checking prerequisites..." -ForegroundColor Green

    $missing = $false

    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Host "[ERROR] Python not found. Install Python 3.11+ from https://python.org" -ForegroundColor Red
        $missing = $true
    } else {
        $pyver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        Write-Host "[INFO] Python $pyver OK" -ForegroundColor Green
    }

    $cf = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cf) {
        Write-Host "[WARN] cloudflared not found." -ForegroundColor Yellow
        Write-Host "[INFO] Download from: https://github.com/cloudflare/cloudflared/releases" -ForegroundColor Yellow
        $missing = $true
    } else {
        Write-Host "[INFO] cloudflared OK" -ForegroundColor Green
    }

    $pw = & python -c "import playwright" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] playwright not installed. Run: pip install playwright && playwright install chromium" -ForegroundColor Red
        $missing = $true
    } else {
        Write-Host "[INFO] playwright OK" -ForegroundColor Green
    }

    if ($missing) {
        Write-Host "[ERROR] Missing prerequisites. Please install them and re-run." -ForegroundColor Red
        exit 1
    }
}

# ──────────────────────────────────────────────
# 2. Install the bridge
# ──────────────────────────────────────────────
function Install-Bridge {
    Write-Host "[INFO] Installing bridge to $InstallDir..." -ForegroundColor Green
    New-Item -ItemType Directory -Force -Path $InstallDir, $LogDir | Out-Null
}

# ──────────────────────────────────────────────
# 3. Create run script
# ──────────────────────────────────────────────
function New-BridgeScript {
    $runScript = Join-Path $InstallDir "run_bridge.ps1"

    Write-Host "[INFO] Writing bridge run script: $runScript" -ForegroundColor Green

    @"
# Stealth Browser Remote Bridge - Runtime Script
param([int]`$Port = $BridgePort)

`$env:STEALTH_RBB_PORT = `$Port
`$env:STEALTH_MCP_SNAPSHOT_DIR = "$LogDir"

Write-Host "[RBB] Starting on port `$Port..."
Set-Location "$InstallDir"

python -c @"
import asyncio
from core.agent_browser import AgentBrowser
from production.mcp_server import StealthMCPServer

async def main():
    server = StealthMCPServer()
    await server.serve_stdio()

asyncio.run(main())
"@

"@ | Set-Content -Path $runScript -Encoding UTF8

    Write-Host "[INFO] Bridge script created." -ForegroundColor Green
}

# ──────────────────────────────────────────────
# 4. Create Windows Service wrapper (nssm-based)
# ──────────────────────────────────────────────
function New-WindowsService {
    $svcName = "StealthRBB"

    if (Get-Service $svcName -ErrorAction SilentlyContinue) {
        Write-Host "[INFO] Service $svcName already exists." -ForegroundColor Yellow
        return
    }

    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if ($nssm) {
        Write-Host "[INFO] Creating Windows Service: $svcName" -ForegroundColor Green

        & nssm install $svcName "pwsh.exe" @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $InstallDir "run_bridge.ps1")
        )
        & nssm set $svcName AppDirectory $InstallDir
        & nssm set $svcName Start SERVICE_AUTO_START
        & nssm set $svcName AppStdout "$LogDir\bridge.log"
        & nssm set $svcName AppStderr "$LogDir\bridge-error.log"

        Write-Host "[INFO] Service created. Start with: Start-Service $svcName" -ForegroundColor Green
    } else {
        Write-Host "[WARN] nssm not found. To run as a service, install nssm:" -ForegroundColor Yellow
        Write-Host "  winget install nssm" -ForegroundColor Yellow
        Write-Host "  Then re-run this script." -ForegroundColor Yellow
        Write-Host "[INFO] Manual start: Run '$InstallDir\run_bridge.ps1'" -ForegroundColor Yellow
    }
}

# ──────────────────────────────────────────────
# 5. Set up cloudflared tunnel
# ──────────────────────────────────────────────
function New-CloudflaredTunnel {
    Write-Host "[INFO] Setting up cloudflared tunnel..." -ForegroundColor Green

    $configDir = "$env:USERPROFILE\.cloudflared"
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null

    $configFile = Join-Path $configDir "config.yml"

    @"
tunnel: $TunnelNamespace
credentials-file: $configDir\$TunnelNamespace.json

ingress:
  - hostname: ${env:STEALTH_RBB_HOSTNAME}
    service: http://localhost:$BridgePort
  - service: http_status:404
"@ | Set-Content -Path $configFile -Encoding UTF8

    Write-Host "[INFO] cloudflared config written to $configFile" -ForegroundColor Green

    if ($env:STEALTH_RBB_TUNNEL_TOKEN) {
        cloudflared tunnel create $TunnelNamespace 2>$null
        Write-Host "[INFO] Tunnel created. Run: cloudflared tunnel run $TunnelNamespace" -ForegroundColor Green
    } else {
        Write-Host "[WARN] STEALTH_RBB_TUNNEL_TOKEN not set. Skipping tunnel creation." -ForegroundColor Yellow
        Write-Host "[INFO] Create a tunnel at https://one.dash.cloudflare.com/ and set STEALTH_RBB_TUNNEL_TOKEN." -ForegroundColor Yellow
    }
}

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
Test-Prerequisites
Install-Bridge
New-BridgeScript
New-WindowsService
New-CloudflaredTunnel

Write-Host ""
Write-Host "[INFO] Setup complete." -ForegroundColor Green
Write-Host "[INFO] Bridge port:    $BridgePort" -ForegroundColor Green
Write-Host "[INFO] Logs:           $LogDir\bridge.log" -ForegroundColor Green
Write-Host "[INFO] Tunnel config:  $env:USERPROFILE\.cloudflared\config.yml" -ForegroundColor Green
Write-Host "[INFO] Health check:   python scripts\health_check.py" -ForegroundColor Green
Write-Host ""
