# Plan: Sandbox MCP Server Performance Optimization

## Problem Analysis

From the logs, there are **5 performance issues** in the sandbox-mcp-server:

### Issue 1: Bash Tool Call Hung for 22.5 Minutes (Critical)
The bash tool call ran for **1353264ms (~22.5 min)** before erroring out, far exceeding
the max timeout of 600s. Root cause: **WebSocket server has NO defense-in-depth timeout**
on `_handle_call_tool` (line 512: bare `await tool.handler()`). If the tool's internal
`asyncio.wait_for()` fails (e.g. subprocess holds pipes, event loop congestion), the call
hangs indefinitely. Additionally, `process.kill()` in bash_tool.py only kills the shell,
NOT backgrounded child processes (`python ... &`), so pipe EOF never arrives.

### Issue 2: Blocking Thread for Session Cleanup (Moderate)
`security.py:302-311` uses `threading.Thread` + `time.sleep(60)` for session expiry
cleanup in an otherwise fully async server. This is a paradigm mismatch that wastes
resources and introduces up to 60s latency in session expiry detection.

### Issue 3: Unbounded Stdio Reader (Moderate)
`manager.py:629-632` - `_read_stdio_responses()` has no timeout on `readline()` and no
max_line_size. A hung MCP server can cause the reader to block forever. The task is also
fire-and-forget (no reference stored for cancellation).

### Issue 4: Manual Deadline Check in SSE Reader (Low)
`manager.py:1070-1078` - `_read_sse_endpoint()` uses manual `asyncio.get_event_loop().time()`
polling instead of `asyncio.wait_for()`. Inefficient and fragile.

### Issue 5: Health Check Log Noise (Low)
30-second health check interval generates 2 log lines/minute. Not a performance bug but
masks important logs.

---

## Workplan

### Phase 1: Fix Critical Bash Timeout Issue
- [ ] 1.1 Add `asyncio.wait_for()` wrapper in `websocket_server.py:_handle_call_tool()` with MAX_TOOL_TIMEOUT (660s = 600s tool max + 60s buffer)
- [ ] 1.2 Use `start_new_session=True` in `create_subprocess_shell()` to put subprocess in its own process group
- [ ] 1.3 Fix bash_tool.py `process.kill()` to kill entire process group (use `os.killpg`) so backgrounded children are cleaned up and pipes close

### Phase 2: Fix Session Cleanup Threading
- [ ] 2.1 Replace `threading.Thread` + `time.sleep()` in `security.py` with asyncio task (`asyncio.create_task` + `asyncio.sleep`)

### Phase 3: Fix Unbounded Stdio Reader
- [ ] 3.1 Add `asyncio.wait_for()` timeout to `_read_stdio_responses()` readline (300s idle timeout per line)
- [ ] 3.2 Store reader task reference in connection object for proper cancellation

### Phase 4: Fix SSE Deadline Pattern
- [ ] 4.1 Replace manual deadline check in `_read_sse_endpoint()` with `asyncio.wait_for()` wrapper

### Phase 5: Reduce Health Check Log Noise
- [ ] 5.1 Change health check logging to DEBUG level (or conditional: only log if unhealthy)

### Phase 6: Validation
- [ ] 6.1 Run existing tests to ensure no regressions
- [ ] 6.2 Run ruff lint on all changed files

---

## Notes
- Phase 1 is the highest priority - it directly caused the 22.5-minute hang
- All changes are in `sandbox-mcp-server/` directory
- Changes follow existing async patterns (asyncio, aiohttp)
