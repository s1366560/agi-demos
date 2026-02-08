#!/bin/bash
# Sandbox MCP Server Entrypoint
# Starts all services: MCP server, KasmVNC (remote desktop), ttyd (web terminal)

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configuration from environment
MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_PORT="${MCP_PORT:-8765}"
DESKTOP_ENABLED="${DESKTOP_ENABLED:-true}"
DESKTOP_RESOLUTION="${DESKTOP_RESOLUTION:-1920x1080}"
DESKTOP_PORT="${DESKTOP_PORT:-6080}"
TERMINAL_PORT="${TERMINAL_PORT:-7681}"
SKIP_MCP_SERVER="${SKIP_MCP_SERVER:-false}"
CONTAINER_HOSTNAME="${HOSTNAME:-mcp-sandbox}"
VNC_DISPLAY=":1"

# Configure hostname in /etc/hosts at runtime
configure_hostname() {
    log_info "Configuring hostname: $CONTAINER_HOSTNAME"
    
    if ! grep -q "$CONTAINER_HOSTNAME" /etc/hosts 2>/dev/null; then
        echo "127.0.0.1 $CONTAINER_HOSTNAME" >> /etc/hosts
        echo "::1 $CONTAINER_HOSTNAME" >> /etc/hosts
    fi
    
    hostname "$CONTAINER_HOSTNAME" 2>/dev/null || true
    
    log_success "Hostname configured: $CONTAINER_HOSTNAME"
}

# PID tracking
PIDS=()
MCP_PID=""

# Cleanup function
cleanup() {
    log_info "Shutting down services..."

    # Stop MCP server
    if [ -n "$MCP_PID" ] && kill -0 "$MCP_PID" 2>/dev/null; then
        kill "$MCP_PID" 2>/dev/null || true
    fi

    # Stop KasmVNC
    vncserver -kill "$VNC_DISPLAY" 2>/dev/null || true

    # Stop ttyd
    killall ttyd 2>/dev/null || true

    log_info "All services stopped"
}

# Trap signals
trap cleanup EXIT TERM INT

# Start KasmVNC (Remote Desktop with built-in web client)
start_kasmvnc() {
    log_info "Starting KasmVNC on display $VNC_DISPLAY..."

    # Set up runtime directory
    mkdir -p /run/user/0
    chmod 700 /run/user/0

    # Set up KasmVNC user config
    mkdir -p /root/.vnc
    chmod 700 /root/.vnc

    # Ensure KasmVNC user exists with write permissions (non-interactive)
    # KasmVNC reads $HOME/.kasmpasswd (NOT .vnc/kasmpasswd)
    if [ ! -f /root/.kasmpasswd ]; then
        echo "root:kasmvnc:ow" > /root/.kasmpasswd
        chmod 600 /root/.kasmpasswd
    fi

    # Copy xstartup from template (BEFORE KasmVNC starts)
    cp /etc/kasmvnc/xstartup.template /root/.vnc/xstartup
    chmod +x /root/.vnc/xstartup

    # Mark DE as selected to skip interactive select-de.sh
    touch /root/.vnc/.de-was-selected

    # Copy KasmVNC config to user dir (vncserver reads ~/.vnc/kasmvnc.yaml)
    cp /etc/kasmvnc/kasmvnc.yaml /root/.vnc/kasmvnc.yaml

    # Set up KDE Plasma configs
    export DISPLAY="$VNC_DISPLAY"
    export XDG_RUNTIME_DIR=/run/user/0

    mkdir -p /root/.config

    [ -f /root/.config/kdeglobals ] || \
        cp /etc/xdg/kdeglobals /root/.config/ 2>/dev/null || true
    [ -f /root/.config/kwinrc ] || \
        cp /etc/xdg/kwinrc /root/.config/ 2>/dev/null || true

    # Start KasmVNC server
    # KasmVNC provides: X server + VNC + WebSocket + Web client (all-in-one)
    # -SecurityTypes None: skip VNC auth (API proxy handles authentication)
    vncserver "$VNC_DISPLAY" \
        -geometry "${DESKTOP_RESOLUTION}" \
        -depth 24 \
        -websocketPort "$DESKTOP_PORT" \
        -interface 0.0.0.0 \
        -disableBasicAuth \
        -SecurityTypes None \
        2>&1 | tee /tmp/kasmvnc.log &

    # Wait for KasmVNC to start
    local timeout=15
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if netstat -tln 2>/dev/null | grep -q ":$DESKTOP_PORT "; then
            log_success "KasmVNC started on port $DESKTOP_PORT (display $VNC_DISPLAY)"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_warn "KasmVNC may not be running properly (check: cat /tmp/kasmvnc.log)"
    return 1
}

# Start ttyd (Web Terminal) as root
start_ttyd() {
    log_info "Starting ttyd (Web Terminal) on port $TERMINAL_PORT..."

    ttyd -p "$TERMINAL_PORT" -- /bin/bash &
    PIDS+=($!)

    sleep 1

    if netstat -tln 2>/dev/null | grep -q ":$TERMINAL_PORT "; then
        log_success "ttyd started on ws://localhost:$TERMINAL_PORT"
    else
        log_warn "ttyd may not be running properly on port $TERMINAL_PORT"
    fi
}

# Start MCP Server
start_mcp_server() {
    if [ "$SKIP_MCP_SERVER" = "true" ]; then
        log_warn "Skipping MCP Server (SKIP_MCP_SERVER=true)"
        return 0
    fi

    log_info "Starting MCP Server on $MCP_HOST:$MCP_PORT..."

    cd /app
    python -m src.server.main &
    MCP_PID=$!

    sleep 2

    if netstat -tln 2>/dev/null | grep -q ":$MCP_PORT "; then
        log_success "MCP Server started on http://$MCP_HOST:$MCP_PORT"
    else
        log_warn "MCP Server may not be running properly on port $MCP_PORT"
    fi
}

# Main startup sequence
main() {
    echo ""
    echo "========================================================"
    echo "     Sandbox MCP Server - Starting Services (KasmVNC)"
    echo "========================================================"
    echo ""

    # Configure hostname first
    configure_hostname

    # Start MCP Server first (always required)
    start_mcp_server

    # Start Desktop if enabled (KasmVNC = single process for VNC + Web)
    if [ "$DESKTOP_ENABLED" = "true" ]; then
        start_kasmvnc || log_warn "Desktop will not be available"
    fi

    # Start Terminal
    start_ttyd

    echo ""
    echo "========================================================"
    echo "                 All Services Started"
    echo "========================================================"
    echo ""
    log_info "Service Endpoints:"
    echo "  * MCP Server:     http://localhost:$MCP_PORT"
    echo "  * Health Check:   http://localhost:$MCP_PORT/health"
    if [ "$DESKTOP_ENABLED" = "true" ]; then
        echo "  * Remote Desktop: http://localhost:$DESKTOP_PORT"
        echo ""
        log_info "Desktop: KasmVNC (WebP + dynamic resize + clipboard + audio)"
    fi
    echo "  * Web Terminal:   ws://localhost:$TERMINAL_PORT"
    echo ""
    log_info "Container ready. Waiting for signals..."

    # Wait for MCP server
    if [ -n "$MCP_PID" ] && kill -0 "$MCP_PID" 2>/dev/null; then
        wait $MCP_PID
        exit_code=$?
        log_info "MCP server exited with code $exit_code"
    else
        log_warn "MCP server not running, entering standby mode"
        while true; do
            sleep 60
        done
    fi
}

# Run main function
main "$@"
