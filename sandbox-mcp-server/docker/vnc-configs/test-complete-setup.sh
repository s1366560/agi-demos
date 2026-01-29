#!/bin/bash
# Complete XFCE 4.20 + VNC Setup Verification Script
# Tests all components of the remote desktop setup

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

log_pass() {
    echo -e "${GREEN}[✓ PASS]${NC} $1"
    ((PASS_COUNT++))
}

log_fail() {
    echo -e "${RED}[✗ FAIL]${NC} $1"
    ((FAIL_COUNT++))
}

log_warn() {
    echo -e "${YELLOW}[⚠ WARN]${NC} $1"
    ((WARN_COUNT++))
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║     XFCE 4.20 + VNC Remote Desktop Setup Verification     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Test 1: Ubuntu 25.04 Version
log_info "Test 1: Checking Ubuntu version..."
if [ -f /etc/os-release ]; then
    VERSION=$(grep "VERSION_ID" /etc/os-release | cut -d'"' -f2)
    if [[ "$VERSION" == "25.04"* ]]; then
        log_pass "Ubuntu 25.04 detected: $VERSION"
    else
        log_warn "Ubuntu version: $VERSION (expected 25.04)"
    fi
else
    log_fail "Cannot determine Ubuntu version"
fi

# Test 2: XFCE 4.20 Installation
log_info "Test 2: Checking XFCE 4.20 installation..."
if command -v xfce4-about >/dev/null 2>&1; then
    XFCE_VERSION=$(xfce4-about --version 2>/dev/null | grep "xfce4-about" | head -1 || echo "4.20")
    if [[ "$XFCE_VERSION" == *"4.20"* ]] || [[ "$XFCE_VERSION" == *"4.2"* ]]; then
        log_pass "XFCE 4.20 detected: $XFCE_VERSION"
    else
        log_warn "XFCE version: $XFCE_VERSION (may not be 4.20)"
    fi
else
    log_fail "XFCE not installed"
fi

# Test 3: XFCE Components
log_info "Test 3: Checking XFCE components..."
for component in xfce4-panel xfwm4 xfdesktop xfce4-session thunar xfce4-terminal; do
    if command -v "$component" >/dev/null 2>&1; then
        log_pass "$component installed"
    else
        log_fail "$component not found"
    fi
done

# Test 4: VNC Servers
log_info "Test 4: Checking VNC servers..."
if command -v vncserver >/dev/null 2>&1; then
    VNC_VERSION=$(vncserver --version 2>&1 | head -1 || echo "TigerVNC")
    log_pass "TigerVNC installed: $VNC_VERSION"
else
    log_fail "TigerVNC not found"
fi

if command -v x11vnc >/dev/null 2>&1; then
    log_pass "x11vnc installed (fallback)"
else
    log_warn "x11vnc not found"
fi

# Test 5: noVNC
log_info "Test 5: Checking noVNC..."
if [ -d /opt/noVNC ]; then
    log_pass "noVNC installed at /opt/noVNC"
    if [ -f /opt/noVNC/defaults.json ]; then
        log_pass "noVNC defaults.json configured"
    else
        log_warn "noVNC defaults.json not found"
    fi
else
    log_fail "noVNC not installed"
fi

# Test 6: Fonts
log_info "Test 6: Checking fonts..."
if fc-list | grep -q "Noto.*CJK"; then
    log_pass "Noto CJK fonts installed"
else
    log_warn "Noto CJK fonts not found"
fi

if fc-list | grep -q "Noto.*Color.*Emoji"; then
    log_pass "Noto Color Emoji fonts installed"
else
    log_warn "Noto Color Emoji fonts not found"
fi

# Test 7: XFCE Configuration Files
log_info "Test 7: Checking XFCE configuration files..."
for config in xfce4-panel.xml xfce4-desktop.xml xfwm4.xml xsettings.xml; do
    if [ -f "/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/$config" ]; then
        log_pass "$config configured"
    else
        log_warn "$config not found in /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/"
    fi
done

if [ -f "/etc/xdg/xfce4/panel/whiskermenu-1.rc" ]; then
    log_pass "whiskermenu-1.rc configured"
else
    log_warn "whiskermenu-1.rc not found"
fi

# Test 8: VNC Configuration
log_info "Test 8: Checking VNC configuration..."
if [ -f /etc/vnc/xstartup.template ]; then
    log_pass "VNC xstartup template exists"
    if grep -q "xfce4-session" /etc/vnc/xstartup.template; then
        log_pass "xstartup uses xfce4-session"
    else
        log_warn "xstartup may not use xfce4-session"
    fi
else
    log_fail "VNC xstartup template not found"
fi

# Test 9: TigerVNC Config Directory
log_info "Test 9: Checking TigerVNC config directory..."
if [ -d /home/sandbox/.config/tigervnc ]; then
    log_pass "TigerVNC config directory exists"
else
    log_warn "TigerVNC config directory not created yet (will be created on first run)"
fi

# Test 10: Display and X11
log_info "Test 10: Checking X11 setup..."
if [ -n "$DISPLAY" ]; then
    log_pass "DISPLAY variable set: $DISPLAY"
else
    log_warn "DISPLAY variable not set (will be set by VNC server)"
fi

if command -v Xvfb >/dev/null 2>&1; then
    log_pass "Xvfb installed (for x11vnc mode)"
else
    log_warn "Xvfb not found"
fi

# Test 11: D-Bus
log_info "Test 11: Checking D-Bus..."
if command -v dbus-daemon >/dev/null 2>&1; then
    log_pass "D-Bus daemon installed"
else
    log_fail "D-Bus daemon not found"
fi

# Test 12: Themes
log_info "Test 12: Checking themes..."
if [ -d /usr/share/themes/Greybird ]; then
    log_pass "Greybird theme installed"
else
    log_warn "Greybird theme not found"
fi

if [ -d /usr/share/themes/Adwaita ]; then
    log_pass "Adwaita theme installed"
else
    log_warn "Adwaita theme not found"
fi

# Summary
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                      Test Summary                          ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${GREEN}Passed:${NC}   $PASS_COUNT tests"
echo -e "${YELLOW}Warnings:${NC} $WARN_COUNT tests"
echo -e "${RED}Failed:${NC}   $FAIL_COUNT tests"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo -e "${GREEN}✓ All critical tests passed!${NC}"
    if [ $WARN_COUNT -gt 0 ]; then
        echo -e "${YELLOW}⚠ Some warnings detected, check output above.${NC}"
    fi
    exit 0
else
    echo -e "${RED}✗ Some tests failed. Please check the output above.${NC}"
    exit 1
fi
