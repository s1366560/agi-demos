#!/bin/bash
# Sandbox MCP Server Entrypoint
# Starts all services: MCP server, noVNC (remote desktop), ttyd (web terminal)
# This script runs as root and uses sudo to run services as appropriate users

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
DESKTOP_RESOLUTION="${DESKTOP_RESOLUTION:-1280x720}"
DESKTOP_PORT="${DESKTOP_PORT:-6080}"
TERMINAL_PORT="${TERMINAL_PORT:-7681}"
SANDBOX_USER="${SANDBOX_USER:-sandbox}"

# PID tracking
PIDS=()
XVFB_PID=""

# Cleanup function
cleanup() {
    log_info "Shutting down services..."

    # Stop MCP server (running as sandbox user)
    if [ -n "$MCP_PID" ] && kill -0 "$MCP_PID" 2>/dev/null; then
        kill "$MCP_PID" 2>/dev/null || true
    fi

    # Stop Xvfb
    if [ -n "$XVFB_PID" ] && kill -0 "$XVFB_PID" 2>/dev/null; then
        kill "$XVFB_PID" 2>/dev/null || true
    fi

    # Stop x11vnc
    killall x11vnc 2>/dev/null || true

    # Stop noVNC/websockify
    killall websockify 2>/dev/null || true

    # Stop ttyd
    killall ttyd 2>/dev/null || true

    log_info "All services stopped"
}

# Trap signals
trap cleanup EXIT TERM INT

# Start Xvfb (Virtual X Server) as root
start_xvfb() {
    log_info "Starting Xvfb (Virtual X Server)..."

    export DISPLAY=:99
    Xvfb "$DISPLAY" -screen 0 "${DESKTOP_RESOLUTION}x24" -ac +extension GLX +render -noreset &
    XVFB_PID=$!

    # Wait for Xvfb to be ready
    sleep 3

    if ! kill -0 "$XVFB_PID" 2>/dev/null; then
        log_error "Xvfb failed to start"
        return 1
    fi

    # Make X socket accessible to sandbox user
    mkdir -p /tmp/.X11-unix
    chmod 777 /tmp/.X11-unix

    log_success "Xvfb started (PID: $XVFB_PID, DISPLAY: $DISPLAY)"
}

# Start Desktop Environment (GNOME) as sandbox user
start_desktop() {
    log_info "Starting GNOME desktop environment..."

    # Set up runtime directory for sandbox user
    mkdir -p /run/user/1001
    chown sandbox:sandbox /run/user/1001
    chmod 700 /run/user/1001

    # Run gnome components as sandbox user with proper environment
    sudo -u "$SANDBOX_USER" sh -c "
        export DISPLAY=:99
        export XDG_RUNTIME_DIR=/run/user/1001
        export XDG_DATA_HOME=/home/sandbox/.local/share
        export XDG_CONFIG_HOME=/home/sandbox/.config
        export XDG_CACHE_HOME=/home/sandbox/.cache
        export XDG_STATE_HOME=/home/sandbox/.local/state
        export GDK_BACKEND=x11
        export CLUTTER_BACKEND=x11
        export GNOME_SHELL_SESSION_MODE=gnome-classic
        export NO_AT_BRIDGE=1

        # Create necessary directories
        mkdir -p \$XDG_DATA_HOME
        mkdir -p \$XDG_CONFIG_HOME
        mkdir -p \$XDG_CACHE_HOME

        # Start D-Bus session
        dbus-daemon --session --address=unix:path=/run/user/1001/bus --nofork --syslog &
        sleep 1

        # Load dconf settings for GNOME
        dconf load /etc/dconf/profile/gnome &

        # Configure some basic GNOME settings
        gsettings set org.gnome.desktop.interface show-application-menu true 2>/dev/null || true

        # Start gnome-session in classic mode (non-systemd)
        dbus-launch --exit-with-session gnome-session --session=gnome-classic &
    " &

    sleep 5

    log_success "Desktop environment started (may take additional 20-30s to fully load)"
}

# Start noVNC (Remote Desktop)
start_novnc() {
    log_info "Starting noVNC (Remote Desktop) on port $DESKTOP_PORT..."

    export DISPLAY=:99

    # Wait a bit for GNOME to start initializing
    sleep 2

    # Start x11vnc (VNC server) - requires root for X11 access
    x11vnc -display "$DISPLAY" -rfbport 5900 -shared -forever -nopw -xkb -bg -o /tmp/x11vnc.log 2>/dev/null || true

    # Start noVNC with websockify
    cd /opt/noVNC
    python3 -m websockify --web=/opt/noVNC --heartbeat 30 "$DESKTOP_PORT" localhost:5900 &
    PIDS+=($!)

    sleep 2

    if netstat -tln 2>/dev/null | grep -q ":$DESKTOP_PORT "; then
        log_success "noVNC started on http://localhost:$DESKTOP_PORT"
    else
        log_warn "noVNC may not be running properly on port $DESKTOP_PORT"
    fi
}

# Start ttyd (Web Terminal) as root
start_ttyd() {
    log_info "Starting ttyd (Web Terminal) on port $TERMINAL_PORT..."

    # Start ttyd with login shell
    ttyd -p "$TERMINAL_PORT" -- /bin/bash &
    PIDS+=($!)

    sleep 1

    if netstat -tln 2>/dev/null | grep -q ":$TERMINAL_PORT "; then
        log_success "ttyd started on ws://localhost:$TERMINAL_PORT"
    else
        log_warn "ttyd may not be running properly on port $TERMINAL_PORT"
    fi
}

# Start MCP Server as sandbox user
start_mcp_server() {
    log_info "Starting MCP Server on $MCP_HOST:$MCP_PORT..."

    cd /app
    sudo -u "$SANDBOX_USER" sh -c "export MCP_HOST=$MCP_HOST MCP_PORT=$MCP_PORT && cd /app && python -m src.server.main" &
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
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║           Sandbox MCP Server - Starting Services           ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""

    # Start MCP Server first (always required)
    start_mcp_server

    # Start Desktop if enabled
    if [ "$DESKTOP_ENABLED" = "true" ]; then
        start_xvfb
        start_desktop
        start_novnc
    fi

    # Start Terminal
    start_ttyd

    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                  All Services Started                      ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    log_info "Service Endpoints:"
    echo "  • MCP Server:    http://localhost:$MCP_PORT"
    echo "  • Health Check:  http://localhost:$MCP_PORT/health"
    if [ "$DESKTOP_ENABLED" = "true" ]; then
        echo "  • Remote Desktop: http://localhost:$DESKTOP_PORT/vnc.html"
        echo ""
        log_info "Note: GNOME may take 30-60 seconds to fully load."
        log_info "If screen stays black, try pressing Ctrl+Alt+F1 or waiting longer."
    fi
    echo "  • Web Terminal:  ws://localhost:$TERMINAL_PORT"
    echo ""
    log_info "Container ready. Waiting for signals..."

    # Wait for MCP server process
    wait $MCP_PID
}

# Run main function
main "$@"
