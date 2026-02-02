#!/bin/bash
# Sandbox MCP Server Entrypoint
# Starts all services: MCP server, VNC (remote desktop), ttyd (web terminal)
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
DESKTOP_RESOLUTION="${DESKTOP_RESOLUTION:-1920x1080}"
DESKTOP_PORT="${DESKTOP_PORT:-6080}"
TERMINAL_PORT="${TERMINAL_PORT:-7681}"
SANDBOX_USER="${SANDBOX_USER:-sandbox}"
VNC_SERVER_TYPE="${VNC_SERVER_TYPE:-tigervnc}"  # Options: tigervnc (default, high-performance), x11vnc (fallback, stable)
SKIP_MCP_SERVER="${SKIP_MCP_SERVER:-false}"  # Set to true to skip MCP server (for desktop testing)
CONTAINER_HOSTNAME="${HOSTNAME:-mcp-sandbox}"

# Configure hostname in /etc/hosts at runtime
configure_hostname() {
    log_info "Configuring hostname: $CONTAINER_HOSTNAME"
    
    # Add hostname to /etc/hosts if not already present
    if ! grep -q "$CONTAINER_HOSTNAME" /etc/hosts 2>/dev/null; then
        echo "127.0.0.1 $CONTAINER_HOSTNAME" >> /etc/hosts
        echo "::1 $CONTAINER_HOSTNAME" >> /etc/hosts
    fi
    
    # Set hostname (may fail if not privileged, that's OK)
    hostname "$CONTAINER_HOSTNAME" 2>/dev/null || true
    
    log_success "Hostname configured: $CONTAINER_HOSTNAME"
}

# PID tracking
PIDS=()
XVFB_PID=""
VNC_PID=""
MCP_PID=""

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

    # Stop VNC server (TigerVNC or x11vnc)
    if [ -n "$VNC_PID" ] && kill -0 "$VNC_PID" 2>/dev/null; then
        kill "$VNC_PID" 2>/dev/null || true
    fi

    # Kill any remaining VNC processes (both TigerVNC and x11vnc)
    killall vncserver Xvnc x11vnc 2>/dev/null || true

    # Stop noVNC/websockify
    killall websockify 2>/dev/null || true

    # Stop ttyd
    killall ttyd 2>/dev/null || true

    log_info "All services stopped"
}

# Trap signals
trap cleanup EXIT TERM INT

# Start Xvfb (Virtual X Server) as root
# Note: Skipped if using TigerVNC (which provides its own X server)
start_xvfb() {
    # Skip Xvfb if using TigerVNC (it has built-in X server)
    if [ "$VNC_SERVER_TYPE" = "tigervnc" ] && command -v vncserver &> /dev/null; then
        log_info "Skipping Xvfb (TigerVNC provides X server)"
        export DISPLAY=:99
        return 0
    fi

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

# Start Desktop Environment (XFCE) as sandbox user
start_desktop() {
    log_info "Starting XFCE desktop environment..."

    # Fix ICE directory permission (required for XFCE session)
    mkdir -p /tmp/.ICE-unix
    chmod 777 /tmp/.ICE-unix

    # Set up runtime directory for sandbox user
    mkdir -p /run/user/1001
    chown sandbox:sandbox /run/user/1001
    chmod 700 /run/user/1001

    # Create VNC directory for session persistence
    mkdir -p /home/sandbox/.vnc
    chown sandbox:sandbox /home/sandbox/.vnc

    # Create xstartup from template if it doesn't exist
    if [ ! -f /home/sandbox/.vnc/xstartup ]; then
        cp /etc/vnc/xstartup.template /home/sandbox/.vnc/xstartup
        chmod +x /home/sandbox/.vnc/xstartup
        chown sandbox:sandbox /home/sandbox/.vnc/xstartup
    fi

    # Run XFCE components as sandbox user with proper environment
    sudo -u "$SANDBOX_USER" sh -c "
        export DISPLAY=:99
        export XDG_RUNTIME_DIR=/run/user/1001
        export XDG_DATA_HOME=/home/sandbox/.local/share
        export XDG_CONFIG_HOME=/home/sandbox/.config
        export XDG_CACHE_HOME=/home/sandbox/.cache
        export XDG_STATE_HOME=/home/sandbox/.local/state

        # Create necessary directories
        mkdir -p \$XDG_DATA_HOME
        mkdir -p \$XDG_CONFIG_HOME
        mkdir -p \$XDG_CONFIG_HOME/xfce4
        mkdir -p \$XDG_CACHE_HOME
        mkdir -p /home/sandbox/.vnc

        # Start D-Bus session
        dbus-daemon --session --address=unix:path=/run/user/1001/bus --nofork --syslog &
        sleep 1

        # Set DBUS_SESSION_BUS_ADDRESS for all child processes
        export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus

        # Start XFCE desktop environment with explicit components
        # Start window manager first
        xfwm4 --display=:99 &
        sleep 1

        # Start panel
        xfce4-panel --display=:99 &
        sleep 1

        # Start desktop
        xfdesktop --display=:99 &
        sleep 1

        # Start session (coordinates components)
        xfce4-session &
    " &

    sleep 5

    log_success "Desktop environment started (may take additional 20-30s to fully load)"
}

# Helper: Wait for VNC port to be ready
# Args: $1 = server_name (for logging), $2 = timeout (default 10s)
_wait_for_vnc_port() {
    local server_name="$1"
    local timeout="${2:-10}"
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        if netstat -tln 2>/dev/null | grep -q ":5901 "; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_error "$server_name: Port 5901 not ready after ${timeout}s"
    return 1
}

# Helper: Prepare VNC directory for sandbox user
# Ensures .vnc directory exists with correct permissions
_prepare_vnc_dir() {
    sudo -u "$SANDBOX_USER" mkdir -p /home/sandbox/.vnc
    sudo -u "$SANDBOX_USER" chmod 700 /home/sandbox/.vnc
}

# Start x11vnc (fallback VNC server)
# This is the traditional VNC server with lower performance but wider compatibility
_start_x11vnc() {
    log_info "Starting VNC server (x11vnc fallback)..."

    export DISPLAY=:99

    # Wait for X11 to be ready
    sleep 2

    # Start x11vnc with optimized settings
    # -rfbport 5901: VNC protocol port
    # -shared: Allow multiple connections
    # -forever: Keep listening after disconnect
    # -nopw: No authentication (container-safe)
    # -xkb: Handle keyboard properly
    # -bg: Run in background
    x11vnc -display "$DISPLAY" \
        -rfbport 5901 \
        -shared \
        -forever \
        -nopw \
        -xkb \
        -bg \
        -o /tmp/x11vnc.log 2>/dev/null &

    VNC_PID=$!

    # Wait for VNC to start
    if _wait_for_vnc_port "x11vnc" 10; then
        log_success "VNC server started on port 5901 (x11vnc)"
        return 0
    else
        log_error "VNC server failed to start on port 5901 (x11vnc)"
        return 1
    fi
}

# Start TigerVNC (high-performance VNC server with built-in X server)
# Features: Tight encoding (50% bandwidth reduction), session persistence
# Note: TigerVNC runs its own X server (Xvnc), replacing Xvfb for display :99
# Ubuntu 25.04 Note: TigerVNC now uses ~/.config/tigervnc for configuration
_start_tigervnc() {
    log_info "Starting VNC server (TigerVNC with built-in X server)..."

    # Stop Xvfb if running (TigerVNC provides its own X server)
    if [ -n "$XVFB_PID" ] && kill -0 "$XVFB_PID" 2>/dev/null; then
        log_info "Stopping Xvfb (TigerVNC includes X server)..."
        kill "$XVFB_PID" 2>/dev/null || true
        XVFB_PID=""
        sleep 2
    fi

    # Set up runtime directory for TigerVNC
    mkdir -p /run/user/1001
    chown sandbox:sandbox /run/user/1001
    chmod 700 /run/user/1001

    # Clean up any old .vnc directory that might cause migration issues on Ubuntu 25.04
    # New TigerVNC uses ~/.config/tigervnc instead of ~/.vnc
    sudo -u "$SANDBOX_USER" sh -c "
        export HOME=/home/sandbox
        # Remove old .vnc directory to avoid migration errors
        rm -rf /home/sandbox/.vnc
        # Create new config directory for TigerVNC
        mkdir -p /home/sandbox/.config/tigervnc
    "

    # Create xstartup in the new TigerVNC location
    sudo -u "$SANDBOX_USER" sh -c "
        export HOME=/home/sandbox
        export DISPLAY=:99
        export XDG_RUNTIME_DIR=/run/user/1001

        # Create config directory
        mkdir -p /home/sandbox/.config/tigervnc

        # Initialize XFCE configuration from system defaults
        mkdir -p /home/sandbox/.config/xfce4/xfconf/xfce-perchannel-xml
        mkdir -p /home/sandbox/.config/xfce4/panel

        # Copy default XFCE configs (only if not exists)
        [ -f /home/sandbox/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml ] || \
            cp /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml \
               /home/sandbox/.config/xfce4/xfconf/xfce-perchannel-xml/ 2>/dev/null || true
        [ -f /home/sandbox/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml ] || \
            cp /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml \
               /home/sandbox/.config/xfce4/xfconf/xfce-perchannel-xml/ 2>/dev/null || true
        [ -f /home/sandbox/.config/xfce4/panel/whiskermenu-1.rc ] || \
            cp /etc/xdg/xfce4/panel/whiskermenu-1.rc \
               /home/sandbox/.config/xfce4/panel/ 2>/dev/null || true

        chown -R sandbox:sandbox /home/sandbox/.config

        # Create xstartup file for XFCE 4.20 session
        # Copy from template for consistency
        cp /etc/vnc/xstartup.template /home/sandbox/.config/tigervnc/xstartup
        chmod +x /home/sandbox/.config/tigervnc/xstartup

        chmod +x /home/sandbox/.config/tigervnc/xstartup
    "

    # Start TigerVNC with NO authentication
    # Ubuntu 25.04 TigerVNC uses new config structure
    sudo -u "$SANDBOX_USER" sh -c "
        export DISPLAY=:99
        export XDG_RUNTIME_DIR=/run/user/1001
        export HOME=/home/sandbox

        vncserver :99 \\
            -geometry ${DESKTOP_RESOLUTION} \\
            -depth 24 \\
            -rfbport 5901 \\
            -localhost no \\
            -securitytypes none \\
            --I-KNOW-THIS-IS-INSECURE \\
            -AlwaysShared \\
            2>&1 | tee /tmp/tigervnc.log
    " &

    VNC_PID=$!

    # Wait for TigerVNC to start (longer timeout for session initialization)
    if _wait_for_vnc_port "TigerVNC" 15; then
        log_success "TigerVNC started on port 5901 (with built-in X server)"
        return 0
    else
        log_warn "TigerVNC failed to start (check logs: docker exec <container> cat /tmp/tigervnc.log)"
        # Kill failed TigerVNC process
        kill $VNC_PID 2>/dev/null || true
        # Clean up vncserver processes
        sudo -u "$SANDBOX_USER" vncserver -kill :99 2>/dev/null || true
        sleep 1
        return 1
    fi
}

# Start VNC Server (TigerVNC with x11vnc fallback)
# Priority: TigerVNC (default, better performance) > x11vnc (fallback)
# Environment variable VNC_SERVER_TYPE can force selection: "tigervnc" or "x11vnc"
# NOTE: VNC failures are non-fatal - container continues running for MCP server
start_vnc() {
    # Check if user wants to force x11vnc
    if [ "$VNC_SERVER_TYPE" = "x11vnc" ]; then
        log_info "Forcing x11vnc (VNC_SERVER_TYPE=x11vnc)..."
        if _start_x11vnc; then
            return 0
        else
            log_warn "x11vnc failed to start, desktop will not be available"
            return 1
        fi
    fi

    # Try TigerVNC first (better performance: 50% bandwidth reduction)
    if command -v vncserver &> /dev/null; then
        if _start_tigervnc; then
            return 0
        fi
        # Fall through to x11vnc if TigerVNC failed
        log_info "Falling back to x11vnc..."
    else
        log_info "TigerVNC not available, using x11vnc..."
    fi

    # Fallback to x11vnc if TigerVNC not available or failed
    if _start_x11vnc; then
        return 0
    else
        log_warn "All VNC servers failed to start, desktop will not be available"
        log_warn "MCP server will continue running"
        return 1
    fi
}

# Start noVNC (Remote Desktop)
start_novnc() {
    log_info "Starting noVNC (Remote Desktop) on port $DESKTOP_PORT..."

    # Start noVNC with websockify
    # Connects to VNC server on port 5901
    cd /opt/noVNC
    python3 -m websockify --web=/opt/noVNC --heartbeat 30 "$DESKTOP_PORT" localhost:5901 &
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
    if [ "$SKIP_MCP_SERVER" = "true" ]; then
        log_warn "Skipping MCP Server (SKIP_MCP_SERVER=true)"
        return 0
    fi

    log_info "Starting MCP Server on $MCP_HOST:$MCP_PORT..."

    cd /app
    # Start MCP server in background, continue even if it fails
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

    # Configure hostname first
    configure_hostname

    # Start MCP Server first (always required)
    start_mcp_server

    # Start Desktop if enabled
    # NOTE: VNC failure is non-fatal - we continue running for MCP server
    VNC_STARTED=false
    if [ "$DESKTOP_ENABLED" = "true" ]; then
        # Start Xvfb if needed (x11vnc mode requires it, TigerVNC has built-in X server)
        if ! ([ "$VNC_SERVER_TYPE" = "tigervnc" ] && command -v vncserver &> /dev/null); then
            start_xvfb || log_warn "Xvfb failed to start"
        fi

        # Start VNC server (TigerVNC or x11vnc)
        if start_vnc; then
            VNC_STARTED=true
            # Start desktop environment (XFCE)
            # Note: TigerVNC runs xstartup automatically, so skip start_desktop
            if [ "$VNC_SERVER_TYPE" = "tigervnc" ] && command -v vncserver &> /dev/null; then
                log_info "TigerVNC manages desktop via xstartup, skipping start_desktop"
            else
                start_desktop
            fi

            # Start noVNC web client
            start_novnc
        else
            log_warn "Desktop will not be available due to VNC startup failure"
        fi
    fi

    # Start Terminal
    start_ttyd

    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                  All Services Started                      ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    log_info "Service Endpoints:"
    echo "  • MCP Server:     http://localhost:$MCP_PORT"
    echo "  • Health Check:   http://localhost:$MCP_PORT/health"
    if [ "$DESKTOP_ENABLED" = "true" ]; then
        echo "  • Remote Desktop: http://localhost:$DESKTOP_PORT/vnc.html"
        echo ""
        log_info "VNC Server: $VNC_SERVER_TYPE"
        log_info "Note: XFCE may take 20-30 seconds to fully load."
    fi
    echo "  • Web Terminal:  ws://localhost:$TERMINAL_PORT"
    echo ""
    log_info "Container ready. Waiting for signals..."

    # Wait for MCP server - this is the primary service
    if [ -n "$MCP_PID" ] && kill -0 "$MCP_PID" 2>/dev/null; then
        # Wait for MCP server process - this is the main blocking call
        wait $MCP_PID
        exit_code=$?
        log_info "MCP server exited with code $exit_code"
    else
        # MCP server not running, but we should still keep container alive
        # This allows health checks and manual debugging
        log_warn "MCP server not running, entering standby mode"
        while true; do
            sleep 60
        done
    fi
}

# Run main function
main "$@"
