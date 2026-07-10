# Sandbox MCP Server

A WebSocket-based MCP (Model Context Protocol) server for sandbox file system operations with **remote desktop environment support**.

## Features

- **WebSocket Transport**: Bidirectional communication via WebSocket
- **File Operations**: read, write, edit, glob, grep
- **Bash Execution**: Secure command execution
- **Web Terminal**: Browser-based terminal access via ttyd
- **Remote Desktop**: KDE Plasma 5.27 desktop environment with KasmVNC (built-in web client)
- **Docker Ready**: Isolated sandbox environment
- **Multi-Language**: Python 3.12, Node.js 22, Java 21 pre-installed

## Quick Start

### Local Development

```bash
# Install dependencies
pip install -e .

# Run server
python -m src.server.main --workspace ./workspace --debug
```

### Docker (Recommended)

```bash
# Build image
docker build -t sandbox-mcp-server .

# Run container (with desktop support)
docker run -p 8765:8765 -p 7681:7681 -p 6080:6080 \
  -v $(pwd)/workspace:/workspace \
  sandbox-mcp-server

# Or use Docker Compose
docker compose up -d
```

### Accessing Services

After starting the container:

- **MCP Server**: `ws://localhost:8765` (WebSocket)
- **Web Terminal**: `http://localhost:7681` (ttyd)
- **Remote Desktop**: `https://localhost:6080` (KasmVNC web client)

## Available Tools

### File System Tools

| Tool | Description |
|------|-------------|
| `read` | Read file contents with line numbers |
| `batch_read` | Read multiple files in one call |
| `write` | Write/create files |
| `edit` | Replace text in files |
| `glob` | Find files by pattern |
| `grep` | Search file contents with regex |
| `list` | List files/directories with recursive and detailed modes |
| `patch` | Apply unified diff patches |
| `bash` | Execute shell commands |

### Artifact Tools

| Tool | Description |
|------|-------------|
| `list_artifacts` | Discover exportable files in output directories |
| `export_artifact` | Export one file with MIME and encoding metadata |
| `batch_export_artifacts` | Export multiple files in one call |

### Code Analysis Tools

| Tool | Description |
|------|-------------|
| `ast_parse` | Parse Python files into symbol metadata |
| `ast_find_symbols` | Find classes, functions, and imports |
| `ast_extract_function` | Extract function or method source |
| `ast_get_imports` | List imports, optionally grouped by module |
| `code_index_build` | Build a Python symbol/reference index |
| `find_definition` | Locate symbol definitions in the index |
| `find_references` | Locate symbol references in the index |
| `call_graph` | Show outgoing/incoming call relationships |
| `dependency_graph` | Summarize import relationships |

### Edit and Refactor Tools

| Tool | Description |
|------|-------------|
| `edit_by_ast` | Rename Python classes/functions/methods via AST |
| `batch_edit` | Apply multiple string edits in one call |
| `preview_edit` | Preview a unified diff before editing |

### Test and Git Tools

| Tool | Description |
|------|-------------|
| `generate_tests` | Generate test skeletons from Python source |
| `run_tests` | Run pytest suites from the sandbox |
| `analyze_coverage` | Analyze file-level test coverage |
| `git_diff` | Inspect current git changes |
| `git_log` | Show recent commits |
| `generate_commit` | Draft a commit message from current changes |

### Import / Dependency Tools

| Tool | Description |
|------|-------------|
| `import_file` | Import a single file from MemStack storage |
| `import_files_batch` | Import multiple files from MemStack storage |
| `deps_check` | Check Python/system/command dependencies |
| `deps_install` | Install Python/system/npm dependencies |
| `plugin_tool_exec` | Run plugin-scoped helper commands |

### Desktop Tools

| Tool | Description |
|------|-------------|
| `start_desktop` | Start KDE Plasma remote desktop (KasmVNC) |
| `stop_desktop` | Stop remote desktop |
| `get_desktop_status` | Get desktop status and connection URL |
| `restart_desktop` | Restart desktop with new config |

### Terminal Tools

| Tool | Description |
|------|-------------|
| `start_terminal` | Start web terminal (ttyd) |
| `stop_terminal` | Stop web terminal |
| `get_terminal_status` | Get terminal status |
| `restart_terminal` | Restart web terminal |

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_HOST` | `0.0.0.0` | Server host |
| `MCP_PORT` | `8765` | Server port |
| `MCP_WORKSPACE` | `/workspace` | Workspace directory |
| `TERMINAL_PORT` | `7681` | Web terminal port |
| `DESKTOP_ENABLED` | `true` | Enable desktop environment |
| `DESKTOP_RESOLUTION` | `1920x1080` | Desktop resolution |
| `DESKTOP_PORT` | `6080` | KasmVNC web client port |

## Remote Desktop

### Starting the Desktop

**Via MCP Tool**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "start_desktop",
    "arguments": {
      "display": ":1",
      "resolution": "1920x1080",
      "port": 6080
    }
  }
}
```

**Direct Access**:
```bash
# Start container with authenticated desktop and loopback-only publication
export SANDBOX_TOKEN="$(openssl rand -base64 32 | tr -d '\n')"
docker run --rm \
  -e MCP_STATIC_TOKEN="$SANDBOX_TOKEN" \
  -p 127.0.0.1:6080:6080 \
  sandbox-mcp-server

# Open browser and authenticate as "sandbox" with $SANDBOX_TOKEN
open https://localhost:6080
```

### Desktop Features

- **KDE Plasma 5.27 Desktop Environment**: Ubuntu 24.04 LTS desktop stack (Dolphin, Konsole, Kate, etc.)
- **KasmVNC** (all-in-one): A single process provides X server + VNC server + WebSocket server + built-in web client
- **Built-in Web Client**: No browser plugin or separate noVNC/websockify stack required
- **WebP/QOI/JPEG Encoding**: Modern encodings for efficient remote display
- **Dynamic Resize**: Live resolution changes via xrandr (no restart needed)
- **Bi-directional Clipboard**: Text and image clipboard sync
- **File Transfer**: Drag-and-drop upload/download through the web client
- **Audio Streaming**: PulseAudio-based audio to the browser
- **Multiple Resolutions**: 1920x1080 (default), 1600x900, 1280x720, and more supported

### VNC Server

The sandbox runtime is **KasmVNC-centric**. The previous TigerVNC + noVNC + websockify
stack is no longer the documented runtime path. Some repository orchestration still accepts
a `VNC_SERVER_TYPE`/`VNC` compatibility flag for older commands, but new behavior should be
validated against the KasmVNC path.

Relevant runtime details:

- Server command: `vncserver :1 -geometry 1920x1080 -depth 24 -websocketPort 6080 -interface 0.0.0.0 -SecurityTypes None`
- Display: `:1`
- Process name: `Xvnc` (KasmVNC package alternative)
- Auth file: `/home/sandbox/.kasmpasswd` (read from `$HOME`, not `~/.vnc/kasmpasswd`)
- Auth mode: KasmVNC HTTP Basic Auth with the per-sandbox runtime capability; the API proxy injects this credential without placing it in URLs
- Web port: `6080` (no 5901 VNC port is exposed; the built-in web client is served on the same port)

**Example: Run with desktop**
```bash
docker run -e MCP_STATIC_TOKEN="$SANDBOX_TOKEN" -p 127.0.0.1:6080:6080 sandbox-mcp-server
```

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

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Browser                              │
├──────────────────────┬──────────────────────────────────┤
│   Web Terminal       │      Remote Desktop              │
│   (ttyd)             │      (KasmVNC web client)        │
│   Port 7681          │      Port 6080                    │
└──────────┬───────────┴──────────────┬───────────────────┘
           │                          │
┌──────────▼──────────────────────────▼───────────────────┐
│                 sandbox-mcp-server                      │
├──────────────────────┬──────────────────────────────────┤
│   ttyd               │   KasmVNC :1 (all-in-one)        │
│   (shell access)     │   ├─ X server (built-in)         │
│                      │   ├─ KDE Plasma 5.27             │
│                      │   └─ VNC + WebSocket + web       │
│                      │      client on port 6080         │
├──────────────────────┴──────────────────────────────────┤
│   MCP Server (Port 8765)                                │
│   ├─ File Tools (read, write, edit, glob, grep)        │
│   ├─ Bash Tool                                          │
│   ├─ Desktop Tools (start, stop, status, restart)       │
│   └─ Terminal Tools (start, stop, status, restart)      │
└──────────────────────┬──────────────────────────────────┘
           │
    ┌──────▼──────┐
    │  Workspace  │
    │  /workspace │
    └─────────────┘
```

## Development Tools

Pre-installed in the sandbox:

- **Python 3.12**: pip, uv, virtualenv, pytest
- **Node.js 22**: npm, pnpm, yarn
- **Java 21**: OpenJDK, Maven, Gradle
- **Git**: Version control
- **Editors**: vim, nano

## Security

- Commands executed within workspace directory
- Dangerous commands blocked
- Non-root user in Docker (UID 1001)
- Resource limits enforced
- Per-sandbox KasmVNC and ttyd authentication enabled
- Session timeout management (optional)

## Troubleshooting

### Desktop Won't Start

```bash
# Check if KDE Plasma is installed
docker exec <container> dpkg -l | grep kde-plasma-desktop

# Check KasmVNC server logs
docker exec <container> ps aux | grep -i kasmvnc
docker exec <container> cat /tmp/kasmvnc.log

# Confirm the web client port is listening
docker exec <container> netstat -tln | grep 6080
```

### Connection Refused

```bash
# Verify ports are exposed
docker ps

# Check port mapping
docker port <container>

# Test KasmVNC web client (self-signed TLS)
curl -k -u "sandbox:$SANDBOX_TOKEN" https://localhost:6080
```

### Performance Issues

- **Reduce resolution**: Try 1280x720 instead of 1920x1080
- **Adjust compression**: Modify `-compression` value (0-9)
- **Check bandwidth`: Ensure >2 Mbps available

## Migration from LXDE

**Note**: This project has been migrated from LXDE to KDE Plasma 5.27 on Ubuntu 24.04 LTS with KasmVNC for a richer desktop and a single all-in-one remote display server.

Key changes:
- LXDE → KDE Plasma 5.27 desktop environment
- Earlier TigerVNC/x11vnc + noVNC + websockify stack → KasmVNC (single process)
- Improved performance and session persistence
- Better encoding options (WebP, QOI, JPEG) plus dynamic resize, clipboard, and audio

See `MIGRATION.md` for detailed migration guide.

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test suites
pytest tests/test_desktop_manager.py -v
pytest tests/integration/test_vnc_performance.py -v

# Include RED-phase Docker/KasmVNC desktop tests
RUN_SANDBOX_RED_TESTS=1 pytest tests/integration/ -v

# Run with coverage
pytest --cov=src/server --cov=src/tools --cov-report=html
```

RED-phase Docker/KasmVNC desktop tests are skipped by default in local runs because they
require the desktop container stack.

## Documentation

- `README.md` (this file) - Quick start guide
- `MIGRATION.md` - Migration guide for existing users
- `DEPLOYMENT.md` - Deployment guide for operations
- `TROUBLESHOOTING.md` - Common issues and solutions
- `PERFORMANCE.md` - Performance tuning guide
- `docs/README.md` - Index for historical desktop/VNC phase records

## Contributing

Contributions welcome! Please run tests before submitting:

```bash
# Format code
ruff format src/ tests/

# Run linter
ruff check src/ tests/

# Run tests
pytest tests/ -v
```

## License

MIT License - See LICENSE file for details

## Version History

- **v2.0** (2026-01-28): KDE Plasma + KasmVNC desktop migration
- **v1.0** (2025-01-15): Initial release with LXDE desktop

---

**Generated**: 2026-06-22
**Status**: Production Ready ✅
