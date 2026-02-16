# MCP Protocol Quick Reference

## Overview

This reference guide covers the newly implemented MCP protocol capabilities in the MemStack codebase.

## Implemented Features (Phase 1)

### 1. Connection Health Check

```python
# WebSocket client
from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

async with MCPWebSocketClient(url="ws://localhost:8765") as client:
    if await client.ping():
        print("Connection healthy")
    else:
        print("Connection unhealthy")
```

```python
# Subprocess client
from src.infrastructure.mcp.clients.subprocess_client import MCPSubprocessClient

client = MCPSubprocessClient(command="uvx", args=["mcp-server-fetch"])
await client.connect()
if await client.ping():
    print("Server responsive")
await client.disconnect()
```

### 2. Prompts API

```python
# List all available prompts
prompts = await client.list_prompts()
for prompt in prompts:
    print(f"- {prompt['name']}: {prompt.get('description', 'No description')}")

# Get a specific prompt
result = await client.get_prompt("code_review", {"code": "def foo(): pass"})
for message in result.get("messages", []):
    print(f"{message['role']}: {message['content']['text']}")
```

### 3. Resource Subscriptions

```python
# Define notification handler
async def handle_resource_update(params):
    uri = params.get("uri")
    print(f"Resource updated: {uri}")
    # Fetch updated content
    content = await client.read_resource(uri)
    print(f"New content: {content}")

# Register handler and subscribe
client.on_resource_updated = handle_resource_update
await client.subscribe_resource("file:///project/config.json")

# Later, when done
await client.unsubscribe_resource("file:///project/config.json")
```

### 4. Progress Tracking

```python
# Track progress of long-running operations
async def handle_progress(params):
    token = params.get("progressToken")
    progress = params.get("progress", 0)
    total = params.get("total", 100)

    percent = (progress / total) * 100
    print(f"[{token}] {percent:.1f}% complete")

client.on_progress = handle_progress

# Progress notifications are automatically dispatched during tool calls
result = await client.call_tool("long_running_task", {"param": "value"})
```

### 5. Logging Control

```python
# Set server logging level
levels = ["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]

success = await client.set_logging_level("debug")
if success:
    print("Server logging set to debug mode")
```

### 6. Cancellation Handling

```python
# Handle request cancellations
async def handle_cancellation(params):
    request_id = params.get("requestId")
    reason = params.get("reason", "No reason provided")
    print(f"Request {request_id} cancelled: {reason}")
    # Clean up resources associated with request

client.on_cancelled = handle_cancellation
```

### 7. Resource List Changes

```python
# Handle resource list changes
async def handle_resource_list_change(params):
    print("Resource list changed, refreshing...")
    resources = await client.list_resources()
    print(f"Available resources: {len(resources.get('resources', []))}")

client.on_resource_list_changed = handle_resource_list_change
```

### 8. Prompts List Changes

```python
# Handle prompt list changes
async def handle_prompts_list_change(params):
    print("Prompts list changed, refreshing...")
    prompts = await client.list_prompts()
    print(f"Available prompts: {len(prompts)}")

client.on_prompts_list_changed = handle_prompts_list_change
```

## Complete Example: Monitoring System

```python
import asyncio
from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient


async def setup_monitoring():
    """Setup comprehensive MCP monitoring system."""

    client = MCPWebSocketClient(
        url="ws://localhost:8765",
        timeout=30.0,
        heartbeat_interval=15,
    )

    # Connect to server
    await client.connect()

    # Register all notification handlers
    async def on_resource_updated(params):
        uri = params["uri"]
        print(f"[UPDATE] {uri}")
        content = await client.read_resource(uri)
        # Process updated content

    async def on_progress(params):
        token = params.get("progressToken")
        progress = params.get("progress", 0)
        total = params.get("total", 100)
        print(f"[PROGRESS] {token}: {progress}/{total}")

    async def on_cancelled(params):
        request_id = params["requestId"]
        reason = params.get("reason", "Unknown")
        print(f"[CANCELLED] Request {request_id}: {reason}")

    async def on_resource_list_changed(params):
        print("[CHANGE] Resource list updated")
        resources = await client.list_resources()
        print(f"Total resources: {len(resources.get('resources', []))}")

    async def on_prompts_list_changed(params):
        print("[CHANGE] Prompts list updated")
        prompts = await client.list_prompts()
        print(f"Total prompts: {len(prompts)}")

    # Register handlers
    client.on_resource_updated = on_resource_updated
    client.on_progress = on_progress
    client.on_cancelled = on_cancelled
    client.on_resource_list_changed = on_resource_list_changed
    client.on_prompts_list_changed = on_prompts_list_changed

    # Subscribe to critical resources
    await client.subscribe_resource("file:///project/config.json")
    await client.subscribe_resource("file:///project/.env")

    # Set appropriate logging level
    await client.set_logging_level("info")

    # Verify connection
    if not await client.ping():
        raise RuntimeError("Failed to ping server")

    print("Monitoring system initialized successfully")
    return client


async def main():
    """Main monitoring loop."""
    client = await setup_monitoring()

    try:
        # Keep monitoring running
        while True:
            await asyncio.sleep(60)
            # Periodic health check
            if not await client.ping():
                print("WARNING: Server not responding")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
```

## Error Handling Best Practices

### 1. Graceful Degradation

```python
# Always handle failures gracefully
if await client.ping(timeout=5):
    # Connection is good, proceed
    result = await client.call_tool("expensive_operation", {})
else:
    # Connection failed, use fallback
    result = fallback_local_operation()
```

### 2. Timeout Management

```python
# Use appropriate timeouts for different operations
quick_check = await client.ping(timeout=2)  # Quick health check
slow_operation = await client.call_tool("analyze_large_dataset", {}, timeout=300)  # 5 minutes
```

### 3. Notification Handler Safety

```python
# Always wrap handler logic in try/except
async def safe_handler(params):
    try:
        # Process notification
        await process_update(params)
    except Exception as e:
        # Log error but don't crash
        print(f"Handler error: {e}")

client.on_resource_updated = safe_handler
```

### 4. Resource Cleanup

```python
# Always unsubscribe when done
try:
    await client.subscribe_resource(uri)
    # Use resource
    await work_with_resource(uri)
finally:
    await client.unsubscribe_resource(uri)
```

## Testing Your Integration

```python
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_ping_integration():
    """Test ping with your MCP server."""
    from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

    client = MCPWebSocketClient(url="ws://your-server:8765")

    # Mock for unit test
    with patch.object(client, "_send_request", new_callable=AsyncMock) as mock:
        mock.return_value = {}
        result = await client.ping()
        assert result is True

    # For integration test, use real connection
    # await client.connect()
    # result = await client.ping()
    # assert result is True
    # await client.disconnect()
```

## Common Patterns

### Health Check Loop

```python
async def health_monitor(client, interval=30):
    """Periodically check server health."""
    while True:
        await asyncio.sleep(interval)
        healthy = await client.ping(timeout=5)
        if not healthy:
            print("WARNING: Server unhealthy")
            # Trigger alert or reconnection logic
```

### Resource Watcher

```python
async def watch_resource(client, uri, callback):
    """Watch a resource for changes."""
    async def handler(params):
        if params.get("uri") == uri:
            content = await client.read_resource(uri)
            await callback(content)

    client.on_resource_updated = handler
    await client.subscribe_resource(uri)
```

### Progress Reporter

```python
async def track_operation(client, operation_name, coro):
    """Track operation with progress reporting."""
    progress_events = []

    async def capture_progress(params):
        progress_events.append(params)

    client.on_progress = capture_progress

    result = await coro

    print(f"{operation_name} completed with {len(progress_events)} progress events")
    return result
```

## MCP Protocol Specification Reference

For detailed protocol specifications, see:
- Official Spec: https://modelcontextprotocol.io/specification/2025-11-25
- Implementation Details: `/docs/mcp_protocol_implementation.md`

## Support

For questions or issues:
1. Check test file: `/src/tests/unit/infrastructure/mcp/clients/test_mcp_protocol_capabilities.py`
2. Review implementation: `/src/infrastructure/mcp/clients/websocket_client.py`
3. Consult MCP spec: https://modelcontextprotocol.io/specification/2025-11-25
