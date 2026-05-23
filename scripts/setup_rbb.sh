#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

SERVICE_NAME="stealth-rbb"
INSTALL_DIR="${STEALTH_RBB_INSTALL_DIR:-/opt/stealth-rbb}"
BRIDGE_PORT="${STEALTH_RBB_PORT:-9222}"
TUNNEL_NAMESPACE="${STEALTH_RBB_NAMESPACE:-stealth-browser}"
SYSTEMD_DIR="${XDG_RUNTIME_DIR:-$HOME/.config}"
LOG_DIR="/var/log/stealth-rbb"

# ──────────────────────────────────────────────
# 1. Check prerequisites
# ──────────────────────────────────────────────
check_prerequisites() {
    log_info "Checking prerequisites..."

    local missing=0

    if ! command -v python3 &>/dev/null; then
        log_error "python3 not found. Install Python 3.11+ from https://python.org"
        missing=1
    else
        local pyver
        pyver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        local major minor
        major=$(echo "$pyver" | cut -d. -f1)
        minor=$(echo "$pyver" | cut -d. -f2)
        if (( major < 3 || (major == 3 && minor < 11) )); then
            log_warn "Python $pyver detected. 3.11+ recommended."
        else
            log_info "Python $pyver OK"
        fi
    fi

    if ! command -v cloudflared &>/dev/null; then
        log_warn "cloudflared not found."
        log_info "Install: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared"
        missing=1
    else
        log_info "cloudflared OK"
    fi

    if ! python3 -c "import playwright" &>/dev/null; then
        log_error "playwright not installed. Run: pip install playwright && playwright install chromium"
        missing=1
    else
        log_info "playwright OK"
    fi

    if (( missing )); then
        log_error "Missing prerequisites. Please install them and re-run."
        exit 1
    fi
}

# ──────────────────────────────────────────────
# 2. Install the bridge application
# ──────────────────────────────────────────────
install_bridge() {
    log_info "Installing bridge to ${INSTALL_DIR}..."
    mkdir -p "${INSTALL_DIR}" "${LOG_DIR}"

    if [[ -f pyproject.toml ]]; then
        pip install -e . &>/dev/null
    fi
}

# ──────────────────────────────────────────────
# 3. Create systemd service file
# ──────────────────────────────────────────────
create_systemd_service() {
    local service_file
    if systemctl --user &>/dev/null; then
        mkdir -p "${SYSTEMD_DIR}/.config/systemd/user"
        service_file="${SYSTEMD_DIR}/.config/systemd/user/${SERVICE_NAME}.service"
    else
        service_file="/etc/systemd/system/${SERVICE_NAME}.service"
        if [[ $EUID -ne 0 ]]; then
            log_warn "Creating system-level unit requires root. Trying user-level..."
            mkdir -p "${SYSTEMD_DIR}/.config/systemd/user"
            service_file="${SYSTEMD_DIR}/.config/systemd/user/${SERVICE_NAME}.service"
        fi
    fi

    log_info "Writing systemd service: ${service_file}"

    cat > "${service_file}" <<EOF
[Unit]
Description=Stealth Browser Remote Bridge (RBB)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=STEALTH_RBB_PORT=${BRIDGE_PORT}
Environment=STEALTH_RBB_NAMESPACE=${TUNNEL_NAMESPACE}
Environment=STEALTH_MCP_SNAPSHOT_DIR=${LOG_DIR}
ExecStart=${INSTALL_DIR}/run_bridge.sh
Restart=on-failure
RestartSec=5
StandardOutput=append:${LOG_DIR}/bridge.log
StandardError=append:${LOG_DIR}/bridge-error.log

[Install]
WantedBy=default.target
EOF

    cat > "${INSTALL_DIR}/run_bridge.sh" <<BRIDGE
#!/usr/bin/env bash
set -euo pipefail
BRIDGE_PORT="${BRIDGE_PORT}"
echo "Starting stealth bridge on port \${BRIDGE_PORT}..."

cd "${INSTALL_DIR}"

python3 -c "
import asyncio
from core.agent_browser import AgentBrowser
from production.mcp_server import StealthMCPServer

async def main():
    server = StealthMCPServer()
    server._workflow_library_root = '${INSTALL_DIR}/workflows/library'
    await server.serve_stdio()

asyncio.run(main())
" &

echo \$! > /tmp/stealth-rbb.pid
wait
BRIDGE

    chmod +x "${INSTALL_DIR}/run_bridge.sh"
}

# ──────────────────────────────────────────────
# 4. Set up cloudflared tunnel
# ──────────────────────────────────────────────
setup_cloudflared_tunnel() {
    log_info "Setting up cloudflared tunnel..."

    local config_dir="${HOME}/.cloudflared"
    mkdir -p "${config_dir}"

    if [[ -n "${STEALTH_RBB_TUNNEL_TOKEN:-}" ]]; then
        cloudflared tunnel create "${TUNNEL_NAMESPACE}" 2>/dev/null || true

        cat > "${config_dir}/config.yml" <<EOF
tunnel: ${TUNNEL_NAMESPACE}
credentials-file: ${config_dir}/${TUNNEL_NAMESPACE}.json

ingress:
  - hostname: \${STEALTH_RBB_HOSTNAME:-stealth-browser.example.com}
    service: http://localhost:${BRIDGE_PORT}
  - service: http_status:404
EOF

        log_info "cloudflared config written to ${config_dir}/config.yml"
        log_info "Next: set STEALTH_RBB_TUNNEL_TOKEN and run: cloudflared tunnel run ${TUNNEL_NAMESPACE}"
    else
        log_warn "STEALTH_RBB_TUNNEL_TOKEN not set. Skipping tunnel creation."
        log_info "Create a tunnel at https://one.dash.cloudflare.com/ and set STEALTH_RBB_TUNNEL_TOKEN."
    fi
}

# ──────────────────────────────────────────────
# 5. Enable and start the service
# ──────────────────────────────────────────────
enable_service() {
    log_info "Enabling ${SERVICE_NAME}..."

    if systemctl --user &>/dev/null; then
        systemctl --user daemon-reload
        systemctl --user enable "${SERVICE_NAME}"
        systemctl --user start "${SERVICE_NAME}"
    else
        systemctl daemon-reload 2>/dev/null || true
        systemctl enable "${SERVICE_NAME}" 2>/dev/null || true
        systemctl start "${SERVICE_NAME}" 2>/dev/null || true
    fi

    log_info "${SERVICE_NAME} started. Check status: systemctl --user status ${SERVICE_NAME}"
}

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
main() {
    echo ""
    echo "  ╔═══════════════════════════════════════════╗"
    echo "  ║   Stealth Browser - Remote Bridge Setup   ║"
    echo "  ╚═══════════════════════════════════════════╝"
    echo ""

    check_prerequisites
    install_bridge
    create_systemd_service
    setup_cloudflared_tunnel
    enable_service

    echo ""
    log_info "Setup complete."
    log_info "Bridge port:    ${BRIDGE_PORT}"
    log_info "Logs:           ${LOG_DIR}/bridge.log"
    log_info "Tunnel config:  ${HOME}/.cloudflared/config.yml"
    echo ""
    log_info "Health check:   python scripts/health_check.py"
    echo ""
}

main "$@"
