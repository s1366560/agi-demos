#!/bin/bash
# TigerVNC startup script with optimal settings
# This script starts VNC server with best performance configuration

set -e

# Configuration
DISPLAY="${DISPLAY:-:1}"
GEOMETRY="${GEOMETRY:-1280x720}"
DEPTH="${DEPTH:-24}"
VNC_PORT="${VNC_PORT:-5901}"
ENCODING="${ENCODING:-Tight}"
COMPRESSION="${COMPRESSION:-5}"
QUALITY="${QUALITY:-8}"

# Get display number (remove leading colon)
DISPLAY_NUM="${DISPLAY#:}"

# Calculate VNC port (5900 + display number)
if [ -z "$VNC_PORT" ]; then
    VNC_PORT=$((5900 + DISPLAY_NUM))
fi

# Create VNC directory
VNC_DIR="$HOME/.vnc"
mkdir -p "$VNC_DIR"

# Create xstartup if it doesn't exist
XSTARTUP="$VNC_DIR/xstartup"
if [ ! -f "$XSTARTUP" ]; then
    cat > "$XSTARTUP" << 'EOF'
#!/bin/bash
# TigerVNC session startup script
export DISPLAY

# Start XFCE desktop environment
if [ -x /usr/bin/xfce4-session ]; then
    dbus-launch --exit-with-session xfce4-session &
elif [ -x /usr/bin/startxfce4 ]; then
    startxfce4 &
else
    # Fallback - just start a terminal
    xfce4-terminal &
fi

# Keep the session alive
wait
EOF
    chmod +x "$XSTARTUP"
fi

# Start TigerVNC with optimal settings
vncserver "$DISPLAY" \
    -geometry "$GEOMETRY" \
    -depth "$DEPTH" \
    -encoding "$ENCODING" \
    -compression "$COMPRESSION" \
    -quality "$QUALITY" \
    -noxstartup \
    -rfbport "$VNC_PORT" \
    -localhost no \
    -securitytypes None

echo "TigerVNC started on display $DISPLAY, port $VNC_PORT"
echo "Connect via: vncviewer localhost:$VNC_PORT"
echo "Or via noVNC: http://localhost:6080/vnc.html"
