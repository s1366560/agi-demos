# Sandbox MCP Server

A WebSocket-based MCP (Model Context Protocol) server for sandbox file system operations.

## Features

- **WebSocket Transport**: Bidirectional communication via WebSocket
- **File Operations**: read, write, edit, glob, grep
- **Bash Execution**: Secure command execution
- **Docker Ready**: Isolated sandbox environment

## Quick Start

### Local Development

```bash
# Install dependencies
pip install -e .

# Run server
python -m src.server.main --workspace ./workspace --debug
```

### Docker

```bash
# Build image
docker build -t sandbox-mcp-server .

# Run container
docker run -p 8765:8765 -v $(pwd)/workspace:/workspace sandbox-mcp-server

# Or use docker-compose
docker-compose up -d
```

## Available Tools

| Tool | Description |
|------|-------------|
| `read` | Read file contents with line numbers |
| `write` | Write/create files |
| `edit` | Replace text in files |
| `glob` | Find files by pattern |
| `grep` | Search file contents with regex |
| `bash` | Execute shell commands |

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_HOST` | `0.0.0.0` | Server host |
| `MCP_PORT` | `8765` | Server port |
| `MCP_WORKSPACE` | `/workspace` | Workspace directory |

## Protocol

The server implements MCP over WebSocket with JSON-RPC 2.0 messages.

### Example Connection

```python
import aiohttp
import asyncio

async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('ws://localhost:8765') as ws:
            # Initialize
            await ws.send_json({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "test", "version": "1.0"}
                }
            })
            response = await ws.receive_json()
            print(response)

            # List tools
            await ws.send_json({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {}
            })
            tools = await ws.receive_json()
            print(tools)

asyncio.run(main())
```

## Security

- Commands are executed within workspace directory
- Dangerous commands are blocked
- Non-root user in Docker
- Resource limits enforced
