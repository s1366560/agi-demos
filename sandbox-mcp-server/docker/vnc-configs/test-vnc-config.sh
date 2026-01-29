#!/bin/bash
# VNC Configuration Validation Test
# This script tests that VNC configuration files are in the correct format
# for TigerVNC 1.10+ (INI format, not Perl)
#
# Usage: ./test-vnc-config.sh [source_config_file] [xstartup_file]
# Example: ./test-vnc-config.sh vncserver-config xstartup

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAILED=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Allow passing config files as arguments, or use defaults
CONFIG_FILE="${1:-$SCRIPT_DIR/vncserver-config}"
XSTARTUP_FILE="${2:-$SCRIPT_DIR/xstartup}"

test_section() {
    echo -e "\n${YELLOW}Testing: $1${NC}"
}

test_pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
}

test_fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    FAILED=$((FAILED + 1))
}

test_skip() {
    echo -e "${YELLOW}⊙ SKIP${NC}: $1"
}

echo "VNC Configuration Validation Test"
echo "Config file: $CONFIG_FILE"
echo "Xstartup file: $XSTARTUP_FILE"

# Test 1: Config file should exist
test_section "Config file exists"
if [ -f "$CONFIG_FILE" ]; then
    test_pass "Config file found"
elif [ -f "/etc/vnc/config" ]; then
    CONFIG_FILE="/etc/vnc/config"
    test_pass "Config file found (at /etc/vnc/config)"
elif [ -f "/home/sandbox/.vnc/config" ]; then
    CONFIG_FILE="/home/sandbox/.vnc/config"
    test_pass "Config file found (at ~/.vnc/config)"
else
    test_fail "Config file not found: $CONFIG_FILE (also checked /etc/vnc/config and ~/.vnc/config)"
    echo -e "\n${RED}========================================${NC}"
    echo -e "${RED}Cannot continue without config file${NC}"
    exit 1
fi

# Test 2: vncserver-config should NOT contain Perl-style variables
test_section "Config format (should be INI, not Perl)"
if grep -q '^\$[a-zA-Z]' "$CONFIG_FILE" 2>/dev/null; then
    test_fail "Config contains Perl-style variables (\$var = \"value\")"
    echo "  Found: $(grep '^\$[a-zA-Z]' "$CONFIG_FILE" | head -1)"
else
    test_pass "Config does not contain Perl-style variables"
fi

# Test 3: vncserver-config should use INI-style key=value
test_section "Config uses INI format (key=value)"
if grep -qE '^[a-z]+=' "$CONFIG_FILE" 2>/dev/null; then
    test_pass "Config uses INI format"
    echo "  Found: $(grep -E '^[a-z]+=' "$CONFIG_FILE" | head -3 | tr '\n' ', ')"
else
    test_fail "Config does not use INI format"
fi

# Test 4: securitytypes should be lowercase "none"
test_section "securitytypes value (should be lowercase 'none')"
if grep -qi 'securitytypes.*=.*none' "$CONFIG_FILE" 2>/dev/null; then
    if grep -q 'securitytypes.*None' "$CONFIG_FILE" 2>/dev/null; then
        test_fail "securitytypes uses capital 'None' (should be lowercase 'none')"
    else
        test_pass "securitytypes uses lowercase 'none'"
    fi
else
    test_fail "securitytypes not found in config"
fi

# Test 5: xstartup should use DISPLAY :99 (not :1)
test_section "xstartup DISPLAY variable (should be :99)"
if [ -f "$XSTARTUP_FILE" ]; then
    if grep -q 'DISPLAY=.*:99' "$XSTARTUP_FILE"; then
        test_pass "xstartup uses DISPLAY :99"
    elif grep -q 'DISPLAY=.*:1' "$XSTARTUP_FILE"; then
        test_fail "xstartup uses DISPLAY :1 (should be :99)"
    else
        test_fail "xstartup DISPLAY variable not found"
    fi
elif [ -f "/etc/vnc/xstartup.template" ]; then
    XSTARTUP_FILE="/etc/vnc/xstartup.template"
    if grep -q 'DISPLAY=.*:99' "$XSTARTUP_FILE"; then
        test_pass "xstartup uses DISPLAY :99"
    elif grep -q 'DISPLAY=.*:1' "$XSTARTUP_FILE"; then
        test_fail "xstartup uses DISPLAY :1 (should be :99)"
    else
        test_fail "xstartup DISPLAY variable not found"
    fi
else
    test_skip "xstartup file not found: $XSTARTUP_FILE"
fi

# Test 6: Check for required keys in vncserver-config
test_section "Required configuration keys"
REQUIRED_KEYS=("geometry" "depth" "securitytypes" "localhost")
for key in "${REQUIRED_KEYS[@]}"; do
    if grep -q "^${key}=" "$CONFIG_FILE" 2>/dev/null; then
        test_pass "Key '$key' found"
    else
        test_fail "Key '$key' not found"
    fi
done

# Summary
echo -e "\n${YELLOW}========================================${NC}"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAILED test(s) failed!${NC}"
    exit 1
fi
