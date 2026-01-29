#!/bin/bash
# noVNC Configuration Validation Test
# Tests that noVNC configuration files are properly set up

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAILED=0

test_pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
}

test_fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    FAILED=$((FAILED + 1))
}

echo "noVNC Configuration Validation Test"
echo "===================================="

# defaults.json location (websockify serves from /opt/noVNC/)
DEFAULTS_JSON="/opt/noVNC/defaults.json"

# Test 1: defaults.json should exist
echo ""
echo "Testing: defaults.json exists"
if [ -f "$DEFAULTS_JSON" ]; then
    test_pass "defaults.json found at $DEFAULTS_JSON"
else
    test_fail "defaults.json not found at $DEFAULTS_JSON"
fi

# Test 2: defaults.json should be valid JSON
echo ""
echo "Testing: defaults.json is valid JSON"
if [ -f "$DEFAULTS_JSON" ]; then
    if python3 -m json.tool "$DEFAULTS_JSON" > /dev/null 2>&1; then
        test_pass "defaults.json is valid JSON"
    else
        test_fail "defaults.json is not valid JSON"
    fi
else
    test_fail "defaults.json not found, cannot validate"
fi

# Test 3: defaults.json should have required keys
echo ""
echo "Testing: defaults.json has required keys"
if [ -f "$DEFAULTS_JSON" ]; then
    REQUIRED_KEYS=("host" "port" "path")
    for key in "${REQUIRED_KEYS[@]}"; do
        if grep -q "\"${key}\"" "$DEFAULTS_JSON" 2>/dev/null; then
            test_pass "Key '$key' found in defaults.json"
        else
            test_fail "Key '$key' not found in defaults.json"
        fi
    done
else
    test_fail "defaults.json not found, cannot check keys"
fi

# Test 4: defaults.json should not be empty
echo ""
echo "Testing: defaults.json is not empty"
if [ -f "$DEFAULTS_JSON" ]; then
    SIZE=$(wc -c < "$DEFAULTS_JSON")
    if [ "$SIZE" -gt 10 ]; then
        test_pass "defaults.json has content (${SIZE} bytes)"
    else
        test_fail "defaults.json is empty or too small"
    fi
else
    test_fail "defaults.json not found"
fi

# Summary
echo ""
echo "===================================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAILED test(s) failed!${NC}"
    exit 1
fi
