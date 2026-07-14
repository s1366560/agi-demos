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
TERMINAL_ENABLED="${TERMINAL_ENABLED:-true}"
SKIP_MCP_SERVER="${SKIP_MCP_SERVER:-false}"
SERVICE_AUTH_USERNAME="sandbox"
SERVICE_AUTH_TOKEN="${SANDBOX_SERVICE_AUTH_TOKEN:-${MCP_STATIC_TOKEN:-}}"
CONTAINER_HOSTNAME="${SANDBOX_ID:-$(cat /etc/hostname)}"
VNC_DISPLAY=":1"

# Configure hostname in /etc/hosts at runtime
configure_hostname() {
    log_info "Configuring hostname: $CONTAINER_HOSTNAME"

    # Docker supplies --hostname and --add-host. The runtime user is deliberately
    # not allowed to mutate /etc/hosts or the kernel hostname.
    if ! grep -q "$CONTAINER_HOSTNAME" /etc/hosts 2>/dev/null; then
        log_error "Container hostname is not present in /etc/hosts"
        return 1
    fi

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

wait_for_port() {
    local port="$1"
    local timeout="$2"
    local elapsed=0

    while [ "$elapsed" -lt "$timeout" ]; do
        if netstat -tln 2>/dev/null | grep -q ":$port "; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

# Start KasmVNC (Remote Desktop with built-in web client)
start_kasmvnc() {
    log_info "Starting KasmVNC on display $VNC_DISPLAY..."

    # Set up runtime directory
    local runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    mkdir -p "$runtime_dir"
    chmod 700 "$runtime_dir"

    # Set up KasmVNC user config
    mkdir -p "$HOME/.vnc"
    chmod 700 "$HOME/.vnc"

    # KasmVNC reads $HOME/.kasmpasswd (NOT .vnc/kasmpasswd). Generate the
    # credential at runtime so every sandbox has a distinct capability.
    printf '%s\n%s\n' "$SERVICE_AUTH_TOKEN" "$SERVICE_AUTH_TOKEN" \
        | vncpasswd -u "$SERVICE_AUTH_USERNAME" -w "$HOME/.kasmpasswd" >/dev/null
    chmod 600 "$HOME/.kasmpasswd"

    # Copy xstartup from template (BEFORE KasmVNC starts)
    cp /etc/kasmvnc/xstartup.template "$HOME/.vnc/xstartup"
    chmod +x "$HOME/.vnc/xstartup"

    # Mark DE as selected to skip interactive select-de.sh
    touch "$HOME/.vnc/.de-was-selected"

    # Copy KasmVNC config to user dir (vncserver reads ~/.vnc/kasmvnc.yaml)
    cp /etc/kasmvnc/kasmvnc.yaml "$HOME/.vnc/kasmvnc.yaml"

    # Set up KDE Plasma configs
    export DISPLAY="$VNC_DISPLAY"
    export XDG_RUNTIME_DIR="$runtime_dir"

    mkdir -p "$HOME/.config"

    # Container restarts may leave stale X11 locks after an unclean exit.
    rm -f /tmp/.X1-lock /tmp/.X11-unix/X1

    [ -f "$HOME/.config/kdeglobals" ] || \
        cp /etc/xdg/kdeglobals "$HOME/.config/" 2>/dev/null || true
    [ -f "$HOME/.config/kwinrc" ] || \
        cp /etc/xdg/kwinrc "$HOME/.config/" 2>/dev/null || true

    # Start KasmVNC server
    # KasmVNC provides: X server + VNC + WebSocket + Web client (all-in-one)
    # HTTP Basic authentication gates both the web client and WebSocket upgrade.
    vncserver "$VNC_DISPLAY" \
        -geometry "${DESKTOP_RESOLUTION}" \
        -depth 24 \
        -websocketPort "$DESKTOP_PORT" \
        -interface 0.0.0.0 \
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

# Start ttyd (Web Terminal) as the unprivileged runtime user
start_ttyd() {
    log_info "Starting ttyd (Web Terminal) on port $TERMINAL_PORT..."

    ttyd -W -c "$SERVICE_AUTH_USERNAME:$SERVICE_AUTH_TOKEN" -p "$TERMINAL_PORT" -- /bin/bash &
    PIDS+=($!)

    if wait_for_port "$TERMINAL_PORT" 10; then
        log_success "ttyd started on ws://localhost:$TERMINAL_PORT"
        return 0
    else
        log_error "ttyd failed to start on port $TERMINAL_PORT"
        return 1
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

    if wait_for_port "$MCP_PORT" 30; then
        log_success "MCP Server started on http://$MCP_HOST:$MCP_PORT"
        return 0
    else
        log_error "MCP Server failed to start on port $MCP_PORT"
        return 1
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
    if ! configure_hostname; then
        exit 1
    fi

    if [ "$DESKTOP_ENABLED" = "true" ] || [ "$TERMINAL_ENABLED" = "true" ]; then
        if [ -z "$SERVICE_AUTH_TOKEN" ]; then
            log_error "Interactive services require a runtime authentication capability"
            exit 1
        fi
    fi

    # Start MCP Server first (always required)
    if ! start_mcp_server; then
        log_error "Required MCP service is unavailable"
        exit 1
    fi

    # Start Desktop if enabled (KasmVNC = single process for VNC + Web)
    if [ "$DESKTOP_ENABLED" = "true" ]; then
        if ! start_kasmvnc; then
            log_error "Required desktop service is unavailable"
            exit 1
        fi
    fi

    # Start Terminal when provided by the selected runtime profile.
    if [ "$TERMINAL_ENABLED" = "true" ]; then
        if ! start_ttyd; then
            log_error "Required terminal service is unavailable"
            exit 1
        fi
    fi

    echo ""
    echo "========================================================"
    echo "                 All Services Started"
    echo "========================================================"
    echo ""
    log_info "Service Endpoints:"
    echo "  * MCP Server:     http://localhost:$MCP_PORT"
    echo "  * Health Check:   http://localhost:$MCP_PORT/health"
    if [ "$DESKTOP_ENABLED" = "true" ]; then
        echo "  * Remote Desktop: https://localhost:$DESKTOP_PORT"
        echo ""
        log_info "Desktop: KasmVNC (WebP + dynamic resize + clipboard + audio)"
    fi
    if [ "$TERMINAL_ENABLED" = "true" ]; then
        echo "  * Web Terminal:   http://localhost:$TERMINAL_PORT"
    fi
    echo ""
    log_info "Container ready. Waiting for signals..."

    # Wait for MCP server
    if [ -n "$MCP_PID" ] && kill -0 "$MCP_PID" 2>/dev/null; then
        wait $MCP_PID
        exit_code=$?
        log_info "MCP server exited with code $exit_code"
    else
        log_error "MCP server is not running"
        exit 1
    fi
}

# Run main function
main "$@"
