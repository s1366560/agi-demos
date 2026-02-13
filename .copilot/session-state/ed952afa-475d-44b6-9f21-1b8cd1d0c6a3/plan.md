# MCP App UI <-> Sandbox MCP Server Communication Analysis

## Problem Statement

When an MCP App UI (running inside the Canvas sandbox iframe) needs to interact with its MCP server (running inside a Docker sandbox container), the communication must traverse a multi-layer proxy chain. The question is: does the current architecture fully support this, and what are the gaps?

## Current Architecture: Communication Flow

```
+---------------------------------------------------------------------+
|  MCP App HTML (inner iframe, sandbox_proxy.html)                    |
|  Uses @modelcontextprotocol/ext-apps client SDK                     |
|  Can call: tools/call, resources/read, resources/list, prompts/list |
+--------------------+------------------------------------------------+
                     | postMessage (JSON-RPC)
+--------------------v------------------------------------------------+
|  Sandbox Proxy (outer iframe, sandbox_proxy.html)                   |
|  Relays: inner.contentWindow <-> window.parent                      |
+--------------------+------------------------------------------------+
                     | postMessage (JSON-RPC)
+--------------------v------------------------------------------------+
|  @mcp-ui/client AppBridge (bh class)                                |
|  Routes JSON-RPC requests to registered handlers (oncalltool, etc.) |
|  TWO modes:                                                         |
|    Mode A: client prop provided -> auto-proxies to MCP SDK client   |
|    Mode B: no client -> uses prop callbacks (onCallTool, etc.)      |
|  WE USE MODE B (no MCP SDK client in browser)                       |
+--------------------+------------------------------------------------+
                     | JavaScript callback
+--------------------v------------------------------------------------+
|  StandardMCPAppRenderer.tsx handlers                                 |
|  handleCallTool -> mcpAppAPI.proxyToolCall(appId, ...)              |
|  handleReadResource -> mcpAppAPI.readResource(uri, projectId, ...)  |
|  (onListResources, onListPrompts: NOT IMPLEMENTED)                  |
+--------------------+------------------------------------------------+
                     | HTTP POST
+--------------------v------------------------------------------------+
|  Backend REST API (apps.py)                                         |
|  POST /mcp/apps/{app_id}/tool-call -> mcp_manager.call_tool()      |
|  POST /mcp/apps/resources/read -> mcp_manager.read_resource()      |
+--------------------+------------------------------------------------+
                     | WebSocket (MCP protocol)
+--------------------v------------------------------------------------+
|  Sandbox Container (Docker)                                         |
|  websocket_server.py -> mcp_manager.py -> actual MCP server process |
|  Handles: tools/call, resources/read                                |
+---------------------------------------------------------------------+
```

**Total hops per tool call: 5** (postMessage x2 + HTTP POST + WebSocket + MCP stdio)

## Gap Analysis

### What WORKS Today

- [x] **tools/call**: Full chain connected. Guest app -> proxy -> bridge -> handleCallTool -> backend -> sandbox
- [x] **resources/read** (initial load): Works via onReadResource callback
- [x] **resources/read** (runtime): Now always available (G2 fixed)
- [x] **resources/list**: Full chain implemented (G3 fixed)
- [x] **Sandbox proxy relay**: Bidirectional postMessage relay working
- [x] **Error handling**: Backend returns MCP-style error responses
- [x] **Synthetic app_id tool calls**: Direct proxy endpoint bypasses DB lookup (G1 fixed)

### What DOESN'T Work (Gaps)

| # | Gap | Severity | Description |
|---|-----|----------|-------------|
| G1 | ~~Synthetic appId breaks tool-call proxy~~ | ~~CRITICAL~~ | FIXED: Added `POST /mcp/apps/proxy/tool-call` direct endpoint |
| G2 | ~~onReadResource conditional~~ | ~~HIGH~~ | FIXED: Always pass onReadResource when effectiveUri exists |
| G3 | ~~resources/list not implemented~~ | ~~MEDIUM~~ | FIXED: Full chain implemented |
| G4 | **resources/templates/list not implemented** | LOW | Rarely used. |
| G5 | **prompts/list not implemented** | LOW | Most MCP Apps don't use prompts. |
| G6 | ~~Capability negotiation incorrect~~ | ~~MEDIUM~~ | MITIGATED: Handlers set regardless, capabilities advisory only. |
| G7 | **No WebSocket fast-path** | PERF | HTTP POST round-trip ~100-500ms per call. |
| G8 | **hh() URI scheme validation** | INFO | `@mcp-ui/client`'s `hh()` function only accepts `ui://` scheme. Our `mcp-app://` URIs bypass this via `toolResourceUri` prop, but direct `client`-based flow would reject them. Not blocking today but fragile. |

## Proposed Solution

### Phase 1: Fix Critical Gaps (G1, G2, G6) - Required for basic interactivity

- [ ] **G1: Add direct sandbox proxy path for tool calls**
  - When `app_id` starts with `auto-`, skip DB lookup
  - Parse `project_id`, `server_name` from request context
  - OR: add a new endpoint `POST /mcp/apps/proxy/tool-call` that takes `project_id + server_name + tool_name` directly without requiring DB app record

- [ ] **G2: Always pass onReadResource**
  - Remove the `!effectiveHtml &&` condition
  - Guest app may need to read additional resources even when initial HTML is provided

- [ ] **G6: Declare host capabilities correctly**
  - Pass `serverTools: {}` and `serverResources: {}` to bridge constructor options
  - This tells the guest app that the host CAN proxy tool calls and resource reads

### Phase 2: Implement Missing MCP Methods (G3, G4)

- [ ] **G3: Implement onListResources handler**
  - Add `mcpAppAPI.listResources(projectId, serverName)` in frontend
  - Add `POST /mcp/apps/resources/list` backend endpoint
  - Add `sandbox_mcp_server_manager.list_resources()` method
  - Wire sandbox WebSocket to handle `resources/list`

- [ ] **G4: Implement onListResourceTemplates handler**
  - Same pattern as G3

### Phase 3: Performance Optimization (G7)

- [ ] **Evaluate WebSocket proxy for low-latency communication**
  - Option A: Direct WebSocket from Canvas to sandbox (requires CORS + auth)
  - Option B: SSE/WebSocket endpoint on backend that keeps sandbox connection open
  - Option C: Batch tool calls (less impactful for interactive apps)
  - Decision: Needs profiling first to determine if HTTP latency is actually a bottleneck

### Phase 4: Future-Proofing (G5, G8)

- [ ] **G5: Implement onListPrompts** (only if MCP Apps start using prompts)
- [ ] **G8: Monitor @mcp-ui/client URI scheme changes** (track upstream spec evolution)

## Key Technical Details

### Bridge Mode B (our architecture)

The `@mcp-ui/client` bridge has TWO modes:
- **Mode A** ("client mode"): auto-proxy via MCP SDK client passed as `client` prop
- **Mode B** ("callback mode"): uses prop callbacks (onCallTool, onReadResource, etc.)

We use Mode B because there's no MCP SDK client running in the browser. All server communication goes through our backend HTTP proxy.

The bridge's `connect()` method auto-wires handlers when `_client` is provided:
```javascript
// From @mcp-ui/client dist/index.mjs line 8407
a.tools && (this.oncalltool = async (t, n) => 
  this._client.request({ method: "tools/call", params: t }, ...))
a.resources && (this.onreadresource = async (t, n) => 
  this._client.request({ method: "resources/read", params: t }, ...))
```

In our case `_client = null`, so ALL handlers must be explicitly set via props. Any missing prop = "Method not found" error for the guest app at runtime.

### Capability Negotiation Impact

The `ui/initialize` handshake tells the guest app what the host supports:
```javascript
// Bridge constructor creates host capabilities:
{ openLinks: {}, serverTools: oe?.tools, serverResources: oe?.resources }
// When client=null, oe=undefined, so serverTools=undefined, serverResources=undefined
```

A well-behaved MCP app checks these capabilities before calling tools:
```javascript
// Guest app SDK typically does:
if (hostCapabilities.serverTools) {
  // Enable "call server tool" button
} else {
  // Hide interactive features that need server tools
}
```

Without declaring these capabilities, the guest app may self-cripple.

### Latency Analysis

| Path | Hops | Est. Latency |
|------|------|-------------|
| postMessage x2 (iframe relay) | 2 | <1ms |
| HTTP POST (frontend -> backend) | 1 | 10-50ms |
| WebSocket (backend -> sandbox) | 1 | 5-20ms |
| MCP stdio (sandbox -> server) | 1 | 10-100ms |
| **Total (simple tool call)** | **5** | **25-170ms** |
| **Total (complex tool, e.g., code execution)** | **5** | **100-5000ms** |

For form submissions and button clicks, 25-170ms is acceptable. For real-time interactions (typing, drag-and-drop), a WebSocket fast-path would be needed.
