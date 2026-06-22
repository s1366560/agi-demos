# MCP Protocol Capabilities Implementation

> 模块说明文档。如需方法速查与代码片段，请参阅 `mcp_protocol_quick_reference.md`（活速查）。
> 本文聚焦三个客户端实现的职责划分与能力清单。

## Summary

MCP 协议能力的客户端实现位于 `src/infrastructure/mcp/clients/`，覆盖 WebSocket、Subprocess、HTTP/SSE 三种传输方式。Protocol capabilities（ping、prompts、resource subscriptions、logging 等）目前仅在 WebSocket 客户端中完整实现，遵循 TDD（RED-GREEN-REFACTOR）流程交付。

## Client Responsibilities

| Client | Class | Transport | Capabilities |
|--------|-------|-----------|--------------|
| `websocket_client.py` | `MCPWebSocketClient` | WebSocket | Full protocol: `list_tools`, `call_tool`, `read_resource`, `list_resources`, `ping`, `list_prompts`, `get_prompt`, `subscribe_resource`, `unsubscribe_resource`, `set_logging_level`, `complete`, `set_roots` |
| `subprocess_client.py` | `MCPSubprocessClient` | stdio (子进程) | `list_tools`, `call_tool`, `ping` |
| `http_client.py` | `MCPHttpClient` | HTTP / SSE | `list_tools`, `call_tool`, `ping`（通过 `transport_type="http"` 或 `"sse"` 选择传输） |

## Implemented Protocol Capabilities (WebSocket client)

### 1. Ping Mechanism

**Purpose**: Connection health check

**Method**:
- `ping(timeout: float | None = None) -> bool`

**Implementation**（三个客户端均提供）:
- WebSocket client: `src/infrastructure/mcp/clients/websocket_client.py`
- Subprocess client: `src/infrastructure/mcp/clients/subprocess_client.py`
- HTTP client: `src/infrastructure/mcp/clients/http_client.py`

**Tests**: 5 tests covering success, timeout, not connected, and exception cases

**MCP Spec Reference**: https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/ping

### 2. Prompts API

**Purpose**: List and retrieve prompt templates

**Methods**:
- `list_prompts(timeout: float | None = None) -> list[dict[str, Any]]`
- `get_prompt(name: str, arguments: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any] | None`

**Features**:
- List available prompt templates
- Get specific prompt with arguments
- Handle empty prompt lists
- Handle None/empty arguments

**Tests**: 3 tests covering list success, get success, and empty list

**MCP Spec Reference**: https://modelcontextprotocol.io/specification/2025-11-25/server/prompts

### 3. Resource Subscriptions

**Purpose**: Subscribe/unsubscribe to resource updates

**Methods**:
- `subscribe_resource(uri: str, timeout: float | None = None) -> bool`
- `unsubscribe_resource(uri: str, timeout: float | None = None) -> bool`

**Notification Handlers**:
- `on_resource_updated`: Handles `notifications/resources/updated`
- `on_resource_list_changed`: Handles `notifications/resources/list_changed`

**Tests**: 4 tests covering subscribe, unsubscribe, and notification handling

**MCP Spec Reference**: https://modelcontextprotocol.io/specification/2025-11-25/server/resources

### 4. Progress Tracking

**Purpose**: Track progress of long-running operations

**Notification Handlers**:
- `on_progress`: Handles `notifications/progress` with progressToken, progress, and total

**Tests**: 1 test verifying progress notification dispatch

**MCP Spec Reference**: https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/progress

### 5. Logging

**Purpose**: Control server-side logging level

**Methods**:
- `set_logging_level(level: str, timeout: float | None = None) -> bool`

**Supported Levels**: debug, info, notice, warning, error, critical, alert, emergency

**Tests**: 2 tests covering success and invalid level

**MCP Spec Reference**: https://modelcontextprotocol.io/specification/2025-11-25/server/logging

### 6. Prompts List Changed Notification

**Notification Handlers**:
- `on_prompts_list_changed`: Handles `notifications/prompts/list_changed`

**Tests**: 1 test verifying notification dispatch

### 7. Cancellation (Phase 2)

**Notification Handlers**:
- `on_cancelled`: Handles `notifications/cancelled` with requestId and reason

**Tests**: 1 test verifying cancellation notification dispatch

**MCP Spec Reference**: https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation

## Test Coverage

### New Tests

**File**: `/src/tests/unit/infrastructure/mcp/clients/test_mcp_protocol_capabilities.py`

**Statistics**:
- Total tests: 29
- Test classes: 8
- All tests passing at time of writing
- Coverage: 23% overall (focused on new functionality)

**Test Categories**:
- Ping Mechanism: 5 tests
- Prompts API: 3 tests
- Resource Subscriptions: 4 tests
- Progress Tracking: 1 test
- Logging: 2 tests
- Cancellation: 1 test
- Prompts List Changed: 1 test
- Edge Cases: 12 tests

### Edge Cases Covered

- Server errors (RuntimeError, ConnectionError, Exception)
- None/empty responses
- Missing notification handlers
- Empty/None arguments
- Custom timeouts
- Multiple notification types
- Connection loss scenarios

## Code Quality

### Linting

All code passes `ruff check` with project standards:
- Line length: 100 characters
- Formatting: ruff format
- No linting errors

### Code Style

Follows project conventions:
- Async methods use async/await
- Dataclass-based structures
- Type hints for all public methods
- Docstrings with Args/Returns sections
- Error handling with try/except and logging

## Usage Examples

### Ping

```python
from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

client = MCPWebSocketClient(url="ws://localhost:8765")
await client.connect()

# Check connection health
if await client.ping():
    print("Server is alive")
else:
    print("Server not responding")

await client.disconnect()
```

### Prompts API

```python
# List available prompts
prompts = await client.list_prompts()
for prompt in prompts:
    print(f"{prompt['name']}: {prompt.get('description')}")

# Get specific prompt with arguments
result = await client.get_prompt("code_review", {"code": "def foo(): pass"})
for message in result.get("messages", []):
    print(f"{message['role']}: {message['content']}")
```

### Resource Subscriptions

```python
# Define handler
async def on_resource_updated(params):
    print(f"Resource updated: {params['uri']}")

# Register handler and subscribe
client.on_resource_updated = on_resource_updated
await client.subscribe_resource("file:///path/to/file.txt")

# Later, unsubscribe
await client.unsubscribe_resource("file:///path/to/file.txt")
```

### Progress Tracking

```python
# Define handler
async def on_progress(params):
    progress = params.get("progress", 0)
    total = params.get("total", 100)
    percent = (progress / total) * 100
    print(f"Progress: {percent:.1f}%")

# Register handler
client.on_progress = on_progress

# Progress notifications will be dispatched automatically
```

### Logging

```python
# Set server logging level
success = await client.set_logging_level("debug")
if success:
    print("Logging level set to debug")
```

## Implementation Notes

1. **RED Phase**: 17 failing tests written first
2. **GREEN Phase**: minimal implementation to pass all tests
3. **REFACTOR Phase**: formatting and linting applied
4. **Verification**: existing MCP tests remained green

## Remaining Work (Future Phases)

### Phase 2 - Medium Priority

- **Sampling**: Handle server-initiated `sampling/createMessage` requests
- **Completion**: Implement `completion/complete` for auto-completion

### Additional Enhancements

- Add integration tests with real MCP servers
- Add E2E tests for complete workflows
- Increase coverage to 80%+ with more edge case tests
- Add type-safe dataclasses for MCP protocol messages
- Add retry logic for transient failures

## Files

### Implementation

- `src/infrastructure/mcp/clients/websocket_client.py` — `MCPWebSocketClient`
  - Full protocol capability surface（ping、prompts、resources、logging、completion、roots）
  - 5 notification handler 属性，`_handle_message` 负责通知分发
- `src/infrastructure/mcp/clients/subprocess_client.py` — `MCPSubprocessClient`
  - `list_tools`、`call_tool`、`ping`
- `src/infrastructure/mcp/clients/http_client.py` — `MCPHttpClient`
  - `list_tools`、`call_tool`、`ping`，支持 `http` 与 `sse` 两种 `transport_type`

### Tests

- `/src/tests/unit/infrastructure/mcp/clients/test_mcp_protocol_capabilities.py` (NEW)
  - 29 comprehensive tests
  - 8 test classes
  - 12 edge case tests

## References

- MCP Specification: https://modelcontextprotocol.io/specification/2025-11-25
- Project CLAUDE.md: `/Users/tiejunsun/github/agi-demos/CLAUDE.md`
- Testing Guidelines: `~/.claude/rules/testing.md`
- Code Style Guidelines: `~/.claude/rules/coding-style.md`

## Verification Commands

```bash
# Run new tests
uv run pytest src/tests/unit/infrastructure/mcp/clients/test_mcp_protocol_capabilities.py -v

# Run all MCP tests
uv run pytest src/tests/unit/infrastructure/mcp/ -v

# Run with coverage
uv run pytest src/tests/unit/infrastructure/mcp/clients/test_mcp_protocol_capabilities.py --cov=src/infrastructure/mcp/clients --cov-report=term

# Linting
uv run ruff check src/infrastructure/mcp/clients/

# Formatting
uv run ruff format src/infrastructure/mcp/clients/
```
