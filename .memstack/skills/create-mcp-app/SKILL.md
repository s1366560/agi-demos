---
name: create-mcp-app
description: This skill should be used when the user asks to "create an MCP App", "build an MCP server", "add a UI to an MCP tool", "develop an interactive dashboard", "register an MCP server", or needs guidance on building MCP servers in the MemStack sandbox with optional Canvas UI rendering. Covers the full lifecycle from development to registration to UI activation.
tools:
  - register_mcp_server
  - bash
  - read
  - write
  - edit
  - glob
  - grep
---

# Create MCP App in MemStack Sandbox

Build MCP servers in the sandbox environment with optional interactive UI that renders in the Canvas panel. This guide covers the complete lifecycle: develop, register, and activate.

## Architecture Overview

```
You (Agent) write code in /workspace
    |
    v
register_mcp_server(server_name, server_type="stdio", command="python", args=["server.py"])
    |
    v
Platform starts your server as a child process (stdio transport)
    |
    v
Platform discovers tools via tools/list JSON-RPC call
    |
    v
Tools with _meta.ui.resourceUri → Platform auto-detects as "MCP App"
    |
    v
When tool is called → Platform fetches HTML via resources/read → Renders in Canvas panel
```

**Key insight**: The platform handles ALL the wiring. You just write a correct MCP server, register it, and the UI appears automatically.

## Step-by-Step Workflow

### Step 1: Create the MCP Server Code

Write a Python MCP server in `/workspace/{server_name}/server.py` using the `mcp` package.

**Minimal example with UI:**

```python
"""MCP Server: my-dashboard - Interactive Dashboard."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio

server = Server("my-dashboard")


@server.list_tools()
async def list_tools():
    """List available tools."""
    return [
        {
            "name": "render_dashboard",
            "description": "Render the dashboard with current data",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Data query"}
                }
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://my-dashboard/dashboard",
                    "title": "My Dashboard"
                }
            }
        }
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    if name == "render_dashboard":
        return {"content": [{"type": "text", "text": "Dashboard rendered"}]}
    raise ValueError(f"Unknown tool: {name}")


@server.list_resources()
async def list_resources():
    """List available resources."""
    return [
        {
            "uri": "ui://my-dashboard/dashboard",
            "name": "Dashboard UI",
            "mimeType": "text/html"
        }
    ]


@server.read_resource()
async def read_resource(uri):
    """Read resource content - serves HTML for the Canvas panel."""
    uri = str(uri)
    if uri == "ui://my-dashboard/dashboard":
        html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>My Dashboard</title>
    <style>
        body { font-family: system-ui, sans-serif; padding: 20px; }
    </style>
</head>
<body>
    <h1>My Dashboard</h1>
    <div id="content">Dashboard content here</div>
</body>
</html>"""
        return {"contents": [{"uri": uri, "mimeType": "text/html", "text": html}]}
    raise ValueError(f"Unknown resource: {uri}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)


if __name__ == "__main__":
    asyncio.run(main())
```

### Step 2: Create pyproject.toml

```toml
[project]
name = "my-dashboard"
version = "0.1.0"
dependencies = ["mcp"]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
```

### Step 3: Install Dependencies

```bash
cd /workspace/my-dashboard && pip install -e .
```

### Step 4: Test the Server Locally (Optional but Recommended)

Before registering, verify the server starts without errors:

```bash
cd /workspace/my-dashboard && timeout 5 python server.py 2>&1 || true
```

If the server starts and waits for input (no error output), it is working correctly. The `timeout` command prevents it from hanging.

### Step 5: Register the Server

Use the `register_mcp_server` tool:

```
register_mcp_server(
    server_name="my-dashboard",
    server_type="stdio",
    command="python",
    args=["/workspace/my-dashboard/server.py"]
)
```

After registration:
- Platform starts your server process
- Discovers tools via `tools/list`
- Auto-detects `_meta.ui` on tools → marks as MCP App
- Tools become available as `mcp__my_dashboard__render_dashboard`

### Step 6: Verify and Use

Call the registered tool. If it has `_meta.ui`, the Canvas panel will automatically render the HTML from your `read_resource` handler.

## Critical Rules

### 1. `read_resource` Return Format (MUST be exact)

The `read_resource` handler MUST return a **dict** with this exact structure:

```python
# CORRECT - dict with "contents" list
return {"contents": [{"uri": uri, "mimeType": "text/html", "text": html_string}]}
```

**Common mistakes:**

```python
# WRONG - returning a tuple
return (uri, "text/html", html_string)

# WRONG - returning just the HTML string
return html_string

# WRONG - returning without "contents" wrapper
return {"uri": uri, "mimeType": "text/html", "text": html_string}

# WRONG - using "content" instead of "contents"
return {"content": [{"uri": uri, "mimeType": "text/html", "text": html_string}]}
```

The platform's MCP manager calls `result.get("contents", [])` and iterates to find `item.get("text")`. Any other format will silently fail.

### 2. `_meta.ui` Format (MUST use `ui://` scheme)

```python
"_meta": {
    "ui": {
        "resourceUri": "ui://server-name/resource-path",
        "title": "Display Title"
    }
}
```

- The `resourceUri` MUST use the `ui://` scheme
- The server name in the URI MUST match your registered server name
- The URI MUST match exactly what `list_resources` and `read_resource` handle

### 3. stdio Transport is the Default and Correct Choice

The sandbox runs MCP servers as child processes using stdio (stdin/stdout). This is:
- The standard transport for container-local MCP servers
- Well-engineered with process lifecycle management, request-response correlation, and idle timeout with auto-restart
- Used by all built-in templates

Do NOT switch to HTTP/SSE/WebSocket unless you have a specific reason (e.g., the server must be shared across multiple clients). stdio is simpler and more reliable for sandbox use.

### 4. Server Process Must Stay Alive

The `async with stdio_server()` pattern keeps the server running. Your server MUST:
- Use `asyncio.run(main())` as the entry point
- NOT exit after handling one request
- NOT print to stdout (stdout is the JSON-RPC transport)
- Use stderr for logging: `import sys; print("debug", file=sys.stderr)`

### 5. `list_resources` Must Declare All UI Resources

Every `resourceUri` referenced in `_meta.ui` must also appear in `list_resources()`:

```python
@server.list_resources()
async def list_resources():
    return [
        {
            "uri": "ui://my-server/dashboard",  # Must match _meta.ui.resourceUri
            "name": "Dashboard UI",
            "mimeType": "text/html"
        }
    ]
```

### 6. Use Absolute Paths in args

When registering, always use absolute paths for the server script:

```python
# CORRECT
register_mcp_server(server_name="my-app", server_type="stdio",
                     command="python", args=["/workspace/my-app/server.py"])

# WRONG - relative path may not resolve correctly
register_mcp_server(server_name="my-app", server_type="stdio",
                     command="python", args=["server.py"])
```

## Built-in Templates

The platform provides 3 server templates you can reference:

| Template | Description | Key Pattern |
|----------|-------------|-------------|
| `web-dashboard` | Interactive dashboard with metrics | `_meta.ui` + `read_resource` HTML |
| `api-wrapper` | REST API integration | Tool-only, no UI |
| `data-processor` | Data transformation pipeline | Tool-only, no UI |

The `web-dashboard` template is the canonical example for MCP Apps with UI.

## Debugging

### Server won't start after registration

1. Check stderr output in the registration response
2. Verify dependencies are installed: `pip list | grep mcp`
3. Test the server manually: `cd /workspace/my-server && python server.py`
4. Check for syntax errors: `python -c "import server"` (from the server directory)

### UI doesn't appear in Canvas

1. Verify `_meta.ui.resourceUri` uses `ui://` scheme
2. Verify `list_resources()` includes the same URI
3. Verify `read_resource()` handles the URI and returns the correct dict format
4. Check that the HTML is valid and non-empty

### Tools not discovered

1. Verify `list_tools()` returns a proper list of tool dicts
2. Each tool must have `name`, `description`, and `inputSchema`
3. Check that the server doesn't crash during `tools/list`

### "Unknown tool" errors

After registration, tools are namespaced as `mcp__{server_name}__{tool_name}` (with hyphens replaced by underscores). Use this full name when calling.

## Advanced Patterns

### Multiple Tools with Shared UI

Multiple tools can reference the same `resourceUri`. The Canvas will render the same HTML resource regardless of which tool triggered it:

```python
@server.list_tools()
async def list_tools():
    return [
        {
            "name": "show_chart",
            "description": "Show chart view",
            "inputSchema": {"type": "object", "properties": {}},
            "_meta": {"ui": {"resourceUri": "ui://my-app/view", "title": "Chart"}}
        },
        {
            "name": "show_table",
            "description": "Show table view",
            "inputSchema": {"type": "object", "properties": {}},
            "_meta": {"ui": {"resourceUri": "ui://my-app/view", "title": "Table"}}
        }
    ]
```

### Tools Without UI

Not every tool needs a UI. Tools without `_meta.ui` work normally as text-only tools:

```python
{
    "name": "fetch_data",
    "description": "Fetch raw data",
    "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}
    # No _meta.ui - this is a plain tool
}
```

### Dynamic HTML Content

The `read_resource` handler is called each time the UI needs to render. You can generate dynamic HTML based on server state:

```python
import json

# Server-level state
_current_data = {}

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    global _current_data
    if name == "update_data":
        _current_data = arguments.get("data", {})
        return {"content": [{"type": "text", "text": "Data updated"}]}

@server.read_resource()
async def read_resource(uri):
    uri = str(uri)
    if uri == "ui://my-app/view":
        html_content = json.dumps(_current_data, indent=2)
        html = f"""<!DOCTYPE html>
<html><body>
<pre>{html_content}</pre>
</body></html>"""
        return {"contents": [{"uri": uri, "mimeType": "text/html", "text": html}]}
```

### Bidirectional Communication (Guest UI to Agent Chat)

MCP Apps can send messages FROM the Canvas UI BACK to the agent conversation. This enables interactive workflows where the user makes choices in the UI and the agent reacts.

**Architecture:**
```
Guest iframe (your HTML)
    | window.parent.postMessage(jsonRpcMsg, '*')
    v
sandbox_proxy.html (relay)
    | window.parent.postMessage(jsonRpcMsg, '*')
    v
Host @mcp-ui/client Transport
    | Parses JSON-RPC, validates ui/message schema
    v
StandardMCPAppRenderer.handleMessage
    | Extracts text from content array
    v
CanvasPanel.onSendPrompt(text)
    | Sends as user message to conversation
    v
Agent receives and processes the message
```

**CRITICAL: Use the exact JSON-RPC format below.** The host `@mcp-ui/client` Transport validates incoming messages against the JSON-RPC schema. Any deviation will be silently dropped.

```javascript
// In your HTML served by read_resource:
let msgIdCounter = 1;

function sendToAgent(text) {
    window.parent.postMessage({
        jsonrpc: "2.0",
        id: msgIdCounter++,
        method: "ui/message",
        params: {
            role: "user",
            content: [{ type: "text", text: text }]
        }
    }, "*");
}

// Example: button click sends result to agent
document.getElementById('confirm-btn').addEventListener('click', () => {
    const value = document.getElementById('result').textContent;
    sendToAgent('User selected: ' + value);
});
```

**Key requirements:**
- `jsonrpc` MUST be `"2.0"`
- `id` MUST be a unique incrementing number (not a string)
- `method` MUST be exactly `"ui/message"`
- `params.content` MUST be an **array** of ContentBlock objects: `[{ type: "text", text: "..." }]`
- `params.role` should be `"user"`
- Use `window.parent.postMessage(msg, "*")` — NOT `window.postMessage`

**DO NOT USE these hallucinated/non-existent APIs:**
```javascript
// WRONG - window.mcpApp does not exist, never injected by platform
window.mcpApp.sendMessage('result');

// WRONG - wrong message format, host expects JSON-RPC not custom types
window.parent.postMessage({ type: 'mcp-tool-result', result: 'value' }, '*');

// WRONG - this CDN URL does not exist, returns 404
import { sendMessage } from 'https://cdn.example.com/@modelcontextprotocol/ext-apps/0.1.0/dist/index.js';
```

**Complete example with bidirectional communication:**

```python
@server.read_resource()
async def read_resource(uri):
    uri = str(uri)
    if uri == "ui://my-app/picker":
        html = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Picker</title></head>
<body>
    <h1>Pick a Value</h1>
    <div id="value">0</div>
    <button onclick="change(1)">+</button>
    <button onclick="change(-1)">-</button>
    <button onclick="confirm()">Confirm</button>
    <script>
        let val = 0, msgId = 1;
        function change(d) {
            val += d;
            document.getElementById('value').textContent = val;
        }
        function confirm() {
            window.parent.postMessage({
                jsonrpc: '2.0',
                id: msgId++,
                method: 'ui/message',
                params: {
                    role: 'user',
                    content: [{ type: 'text', text: 'Selected value: ' + val }]
                }
            }, '*');
        }
    </script>
</body>
</html>"""
        return {"contents": [{"uri": uri, "mimeType": "text/html", "text": html}]}
```

## Checklist Before Registration

- [ ] Server file exists at `/workspace/{name}/server.py`
- [ ] `pyproject.toml` lists `mcp` as dependency
- [ ] Dependencies installed via `pip install -e .`
- [ ] `list_tools()` returns valid tool definitions
- [ ] Tools with UI have `_meta.ui.resourceUri` using `ui://` scheme
- [ ] `list_resources()` declares all UI resource URIs
- [ ] `read_resource(uri)` returns `{"contents": [{"uri": ..., "mimeType": "text/html", "text": ...}]}`
- [ ] Server uses `stdio_server()` transport (default)
- [ ] No print() to stdout (use stderr for logging)
- [ ] Server tested locally without errors
- [ ] If bidirectional: HTML uses `window.parent.postMessage()` with JSON-RPC `ui/message` format
- [ ] If bidirectional: `params.content` is an **array** of `{type: "text", text: "..."}` objects
