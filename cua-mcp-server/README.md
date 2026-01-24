# CUA MCP Server (WebSocket)

WebSocket-based MCP server that exposes CUA tools over JSON-RPC 2.0.

## Build

```bash
docker build -t cua-mcp-server -f cua-mcp-server/Dockerfile .
```

## Run

```bash
docker run -p 18766:18766 \
  -e CUA_ENABLED=true \
  -e CUA_MCP_HOST=0.0.0.0 \
  -e CUA_MCP_PORT=18766 \
  cua-mcp-server
```

## MCP URL

Default URL: ws://localhost:18766

Configure in MemStack with MCP server:
- server_type: websocket
- transport_config.url: ws://localhost:18766

The server implements:
- initialize
- tools/list
- tools/call
