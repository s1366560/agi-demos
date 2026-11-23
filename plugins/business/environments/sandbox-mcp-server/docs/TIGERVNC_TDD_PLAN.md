# TigerVNC Integration - TDD Implementation Plan

## Status: Phase 2 (RED) - Writing Tests

**Date**: 2026-01-28
**Objective**: Integrate TigerVNC server following strict Test-Driven Development

---

## TDD Methodology

We follow strict TDD: **RED → GREEN → REFACTOR**

### Phase 1: RED (Write Tests First) ✅ CURRENT
**Objective**: Write tests that FAIL because implementation uses x11vnc

**Test Files Created**:
- `tests/integration/test_entrypoint_vnc.py` - Full test suite
- `tests/integration/test_entrypoint_vnc_simple.py` - Baseline test
- `tests/integration/conftest.py` - Pytest configuration

**Test Cases**:
1. ✅ `test_entrypoint_starts_tigervnc_not_x11vnc()` - Verifies TigerVNC is used
2. ✅ `test_vnc_port_responsive()` - Verifies port 5901 works
3. ✅ `test_tigervnc_fallback_to_x11vnc()` - Verifies fallback mechanism
4. ✅ `test_tigervnc_configuration_file()` - Verifies config creation
5. ✅ `test_tigervnc_log_file()` - Verifies logging

**Current State (RED Phase)**:
- entrypoint.sh line 160 uses `x11vnc`
- Tests expect TigerVNC (vncserver)
- Tests will FAIL until implementation is complete ✅

---

## Phase 2: GREEN (Make Tests Pass) - NEXT

**File to Modify**: `scripts/entrypoint.sh`
**Function**: `start_vnc()` (lines 150-178)

### Implementation Steps

#### Step 1: Detect TigerVNC Availability
```bash
# Check if TigerVNC is available
if command -v vncserver >/dev/null 2>&1; then
    VNC_SERVER_TYPE="tigervnc"
else
    VNC_SERVER_TYPE="x11vnc"
fi
```

#### Step 2: Start TigerVNC
```bash
start_vnc() {
    log_info "Starting VNC server..."

    export DISPLAY=:99

    # Wait for XFCE to start initializing
    sleep 2

    # Try TigerVNC first
    if [ "${VNC_SERVER_TYPE:-auto}" = "auto" ]; then
        if command -v vncserver >/dev/null 2>&1; then
            log_info "Starting VNC server (TigerVNC)..."

            # Create TigerVNC config directory
            mkdir -p /home/sandbox/.vnc
            chown sandbox:sandbox /home/sandbox/.vnc

            # Create TigerVNC config file
            cat > /home/sandbox/.vnc/config <<EOF
geometry=${DESKTOP_RESOLUTION}
depth=24
localhost=no
EOF
            chown sandbox:sandbox /home/sandbox/.vnc/config

            # Start TigerVNC as sandbox user
            sudo -u "$SANDBOX_USER" vncserver "$DISPLAY" \
                -geometry "${DESKTOP_RESOLUTION}" \
                -depth 24 \
                -encoding Tight \
                -compression 5 \
                -quality 8 \
                -rfbport 5901 \
                -localhost no \
                -securitytypes None \
                > /tmp/tigervnc.log 2>&1 &

            VNC_PID=$!
            sleep 3

            # Check if TigerVNC started successfully
            if netstat -tln 2>/dev/null | grep -q ":5901 "; then
                log_success "VNC server started on port 5901 (TigerVNC)"
                return 0
            else
                log_warn "TigerVNC failed to start, falling back to x11vnc"
            fi
        fi
    fi

    # Fallback to x11vnc
    if [ "${VNC_SERVER_TYPE:-auto}" = "x11vnc" ] || ! command -v vncserver >/dev/null 2>&1; then
        log_info "Starting VNC server (x11vnc)..."

        x11vnc -display "$DISPLAY" \
            -rfbport 5901 \
            -shared \
            -forever \
            -nopw \
            -xkb \
            -bg \
            -o /tmp/x11vnc.log 2>/dev/null &

        VNC_PID=$!
        sleep 3

        if netstat -tln 2>/dev/null | grep -q ":5901 "; then
            log_success "VNC server started on port 5901 (x11vnc)"
        else
            log_error "VNC server failed to start"
            return 1
        fi
    fi
}
```

#### Step 3: Update Cleanup Function
Modify cleanup function to handle both VNC servers:
```bash
cleanup() {
    # ... existing code ...

    # Stop VNC server (TigerVNC or x11vnc)
    if [ -n "$VNC_PID" ] && kill -0 "$VNC_PID" 2>/dev/null; then
        kill "$VNC_PID" 2>/dev/null || true
    fi

    # Kill any remaining VNC processes
    killall vncserver Xvnc x11vnc 2>/dev/null || true

    # ... rest of cleanup ...
}
```

---

## Phase 3: REFACTOR (Optimize)

### Enhancements:
1. **Environment Variable Control**: `VNC_SERVER_TYPE=tigervnc|x11vnc|auto`
2. **Improved Logging**: Enhanced log messages for debugging
3. **Error Handling**: Better error recovery
4. **Configuration Management**: TigerVNC config file templating

---

## Test Execution

### Prerequisites
```bash
# Ensure correct Docker image is available
docker tag sandbox-mcp-server:xfce-final sandbox-mcp-server:latest
# OR rebuild with:
docker build -t sandbox-mcp-server:latest .
```

### Running Tests

**All Tests**:
```bash
source venv/bin/activate
pytest tests/integration/test_entrypoint_vnc.py -v
```

**Single Test**:
```bash
pytest tests/integration/test_entrypoint_vnc.py::TestEntrypointVNC::test_entrypoint_starts_tigervnc_not_x11vnc -v -s
```

**Baseline Test** (verifies current x11vnc usage):
```bash
pytest tests/integration/test_entrypoint_vnc_simple.py -v -s
```

---

## Success Criteria

### Phase 1 (RED): ✅
- [x] Tests created
- [x] Tests FAIL with current x11vnc implementation
- [x] Test infrastructure working

### Phase 2 (GREEN): TODO
- [ ] Tests PASS after TigerVNC implementation
- [ ] TigerVNC starts successfully
- [ ] Fallback to x11vnc works
- [ ] Port 5901 responsive
- [ ] Logs show correct messages

### Phase 3 (REFACTOR): TODO
- [ ] Code optimized
- [ ] Tests still PASS
- [ ] Documentation updated

---

## Rollback Plan

If implementation fails:
1. Git revert entrypoint.sh changes
2. Tag old version: `sandbox-mcp-server:x11vnc-backup`
3. Document failure in implementation notes

---

## Docker Image Issue

**Current Problem**:
- `sandbox-mcp-server:latest` (676MB) - NO desktop environment
- `sandbox-mcp-server:xfce-final` (2.28GB) - WITH desktop + x11vnc

**Solution**:
```bash
# Use xfce-final image for testing
docker tag sandbox-mcp-server:xfce-final sandbox-mcp-server:latest

# OR rebuild latest with desktop
docker build -t sandbox-mcp-server:latest .
```

---

## Next Steps

1. ✅ Phase 1 (RED) Complete - Tests written
2. **⬅️ CURRENT: Implement Phase 2 (GREEN)**
3. Implement TigerVNC in entrypoint.sh
4. Run tests - verify they PASS
5. Phase 3 (REFACTOR)
6. Documentation
7. Final validation

---

## Files Modified

### Created:
- `tests/integration/test_entrypoint_vnc.py`
- `tests/integration/test_entrypoint_vnc_simple.py`
- `tests/integration/conftest.py`
- `docs/TIGERVNC_TDD_PLAN.md` (this file)

### To Modify:
- `scripts/entrypoint.sh` (Phase 2 - GREEN)

---

## References

- [TigerVNC Documentation](https://www.tiger-vnc.org/)
- [TigerVNC Manual](https://github.com/TigerVNC/tigervnc/blob/master/doc/vncserver.man)
- Current implementation: `scripts/entrypoint.sh:150-178`
