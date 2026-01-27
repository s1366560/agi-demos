# 文件系统操作实现方案（MCP Server + WebSocket）

## 概述

为 MemStack Web 应用实现远程沙箱文件系统操作能力。**沙箱作为 MCP Server 运行**，通过 **WebSocket 协议**与 MemStack 通信，复用现有 MCP 基础设施与 ReAct Agent 集成。

## 需求分析

| 需求项 | 描述 |
|-------|------|
| 使用场景 | 远程部署的 MemStack，操作沙箱文件系统 |
| 架构模式 | Web 界面 → ReAct Agent → MCP Client (WebSocket) → Sandbox MCP Server |
| 工具范围 | 所有 OpenCode 实现的工具（20个） |
| 传输协议 | **WebSocket**（双向通信、持久连接、跨网络） |

## 为什么选择 WebSocket

| 特性 | WebSocket | SSE | stdio |
|------|-----------|-----|-------|
| 双向通信 | ✅ | ❌（单向） | ✅ |
| 持久连接 | ✅ | ✅ | ✅ |
| 跨网络 | ✅ | ✅ | ❌（仅本地） |
| 服务器推送 | ✅ | ✅ | ❌ |
| 实时进度 | ✅ | ✅ | 受限 |
| MemStack 支持 | 需实现 | ✅ 已有 | ✅ 已有 |

**WebSocket 优势**：
1. **双向通信** - 沙箱可主动推送文件变更通知
2. **持久连接** - 无需每次请求重新建立连接
3. **跨网络** - 沙箱可部署在远程主机
4. **流式响应** - 支持长时间运行任务的进度反馈

## 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web Frontend                            │
│  (React + TypeScript, 交互界面)                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket (SSE)
┌──────────────────────────▼──────────────────────────────────────┐
│                      MemStack Backend                           │
│  ┌─────────────┐    ┌──────────────────┐    ┌───────────────┐  │
│  │ ReAct Agent │───▶│ MCP Tool Loader  │───▶│ MCP Client    │  │
│  │ (现有)      │    │ (现有)           │    │ + WebSocket   │  │
│  └─────────────┘    └──────────────────┘    └───────┬───────┘  │
└──────────────────────────────────────────────────────┼──────────┘
                           │ WebSocket (ws://sandbox:8765)
┌──────────────────────────▼──────────────────────────────────────┐
│              Sandbox MCP Server (Docker Container)              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │       MCP Server Runtime (Python + WebSocket)             │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │              Tool Implementations                   │  │  │
│  │  │  read │ edit │ glob │ grep │ bash │ ... (20 tools) │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                 Workspace (挂载卷)                         │  │
│  │  /workspace/ (项目直接挂载到工作区根目录)                      │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 现有 MCP 基础设施复用

| 组件 | 路径 | 用途 | 修改需求 |
|-----|------|------|---------|
| MCP Client | `src/infrastructure/agent/mcp/client.py` | 连接沙箱 | **新增 WebSocketTransport** |
| MCP Adapter | `src/infrastructure/mcp/temporal_tool_adapter.py` | 转换为 AgentTool | 无需修改 |
| MCP Loader | `src/infrastructure/mcp/temporal_tool_loader.py` | 动态加载工具 | 无需修改 |
| MCP Config | `src/infrastructure/mcp/config.py` | 配置模型 | **新增 McpWebSocketConfig** |
| Temporal Workflow | `src/infrastructure/adapters/secondary/temporal/mcp/` | 管理生命周期 | **添加 WebSocket 支持** |

## 工具清单（20个）

### 文件操作（7个）
| 工具 | 功能 | 关键参数 |
|-----|------|---------|
| `read` | 读取文件内容 | `file_path`, `offset`, `limit` |
| `write` | 创建/覆盖文件 | `file_path`, `content` |
| `edit` | 模糊匹配编辑 | `file_path`, `old_string`, `new_string` |
| `multiedit` | 批量编辑 | `file_path`, `edits[]` |
| `apply_patch` | 应用补丁 | `patch_text` |
| `glob` | 文件模式搜索 | `pattern`, `path` |
| `list` | 目录列表 | `path`, `ignore` |

### 代码搜索（2个）
| 工具 | 功能 | 关键参数 |
|-----|------|---------|
| `grep` | 正则内容搜索 | `pattern`, `path`, `include` |
| `lsp` | LSP 操作 | `operation`, `file_path`, `line`, `character` |

### 执行工具（2个）
| 工具 | 功能 | 关键参数 |
|-----|------|---------|
| `bash` | Shell 命令执行 | `command`, `timeout`, `workdir` |
| `batch` | 并行工具调用 | `tool_calls[]` |

### 网络工具（2个）
| 工具 | 功能 | 关键参数 |
|-----|------|---------|
| `webfetch` | 获取网页内容 | `url`, `format` |
| `websearch` | 网络搜索 | `query`, `num_results` |

### 交互工具（5个）
| 工具 | 功能 | 关键参数 |
|-----|------|---------|
| `question` | 向用户提问 | `questions[]` |
| `plan_enter` | 进入计划模式 | - |
| `plan_exit` | 退出计划模式 | - |
| `todoread` | 读取待办列表 | - |
| `todowrite` | 更新待办列表 | `todos[]` |

### 专业化工具（2个）
| 工具 | 功能 | 关键参数 |
|-----|------|---------|
| `skill` | 加载技能 | `name` |
| `task` | 子任务委派 | `description`, `prompt`, `subagent_type` |

## 实现方案（基于 MCP Server）

### 阶段 1：Sandbox MCP Server

**目标**：创建独立的 MCP Server 项目，实现 OpenCode 风格的文件系统工具

#### 1.1 MCP Server 项目结构
```
sandbox-mcp-server/
├── pyproject.toml                # Python 项目配置
├── Dockerfile                    # 容器镜像
├── src/
│   ├── __init__.py
│   ├── server.py                 # MCP Server 入口
│   ├── tools/                    # 工具实现
│   │   ├── __init__.py
│   │   ├── base.py               # 工具基类
│   │   ├── read.py               # 文件读取
│   │   ├── write.py              # 文件写入
│   │   ├── edit.py               # 文件编辑（模糊匹配）
│   │   ├── multiedit.py          # 批量编辑
│   │   ├── apply_patch.py        # 补丁应用
│   │   ├── glob.py               # 文件搜索
│   │   ├── grep.py               # 内容搜索（ripgrep）
│   │   ├── list.py               # 目录列表
│   │   ├── bash.py               # Shell 执行
│   │   ├── lsp.py                # LSP 操作
│   │   └── batch.py              # 并行执行
│   └── security/
│       ├── __init__.py
│       ├── path_validator.py     # 路径安全验证
│       └── permission.py         # 权限检查
└── tests/
    └── test_tools.py
```

#### 1.2 MCP Server 实现（使用官方 SDK）
```python
# server.py
from mcp.server import Server
from mcp.types import Tool, TextContent

app = Server("sandbox-filesystem")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="read",
            description="读取文件内容，支持偏移和限制",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径"},
                    "offset": {"type": "integer", "description": "起始行号"},
                    "limit": {"type": "integer", "description": "读取行数", "default": 2000}
                },
                "required": ["file_path"]
            }
        ),
        # ... 其他 19 个工具
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    tool = TOOL_REGISTRY.get(name)
    if not tool:
        raise ValueError(f"Unknown tool: {name}")
    
    result = await tool.execute(**arguments)
    return [TextContent(type="text", text=result.output)]
```

#### 1.3 Dockerfile
```dockerfile
FROM python:3.12-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ripgrep \
    git \
    tree \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
WORKDIR /app
COPY pyproject.toml .
RUN pip install -e .

# 设置工作目录
ENV WORKSPACE_ROOT=/workspace
RUN mkdir -p /workspace && chmod 777 /workspace

# 非 root 用户
RUN useradd -m sandbox
USER sandbox

# MCP Server 入口
ENTRYPOINT ["python", "-m", "sandbox_mcp_server"]
```

### 阶段 2：核心工具实现

#### 2.1 文件读取工具（参考 OpenCode）
```python
# tools/read.py
class ReadTool:
    name = "read"
    MAX_LINES = 2000
    MAX_BYTES = 50 * 1024
    
    async def execute(self, file_path: str, offset: int = 0, limit: int = 2000) -> ToolResult:
        # 路径安全检查
        self.security.validate_path(file_path)
        
        # 读取文件
        path = Path(file_path)
        if not path.exists():
            suggestions = self._find_similar_files(path)
            raise FileNotFoundError(f"File not found: {file_path}\n\nDid you mean:\n{suggestions}")
        
        # 二进制检测
        if self._is_binary(path):
            raise ValueError(f"Cannot read binary file: {file_path}")
        
        # 图片/PDF 特殊处理
        if self._is_image(path):
            return self._read_image(path)
        
        # 文本读取（带行号）
        lines = path.read_text().split('\n')
        output_lines = []
        for i, line in enumerate(lines[offset:offset+limit], start=offset+1):
            # 截断过长行
            if len(line) > 2000:
                line = line[:2000] + "..."
            output_lines.append(f"{i:6}\t{line}")
        
        return ToolResult(
            title=path.name,
            output="\n".join(output_lines),
            metadata={"lines": len(output_lines), "truncated": len(lines) > offset + limit}
        )
```

#### 2.2 文件编辑工具（模糊匹配）
```python
# tools/edit.py
class EditTool:
    name = "edit"
    
    # 替换策略（按优先级）
    REPLACERS = [
        SimpleReplacer(),
        EscapeNormalizedReplacer(),
        LineTrimmedReplacer(),
        IndentationFlexibleReplacer(),
        WhitespaceNormalizedReplacer(),
        BlockAnchorReplacer(),
    ]
    
    async def execute(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> ToolResult:
        self.security.validate_path(file_path)
        
        content = Path(file_path).read_text()
        
        # 尝试各种替换策略
        for replacer in self.REPLACERS:
            matches = list(replacer.find(content, old_string))
            if matches:
                match = matches[0]
                if replace_all:
                    new_content = content.replace(match, new_string)
                else:
                    new_content = content.replace(match, new_string, 1)
                break
        else:
            raise ValueError(f"Could not find '{old_string[:50]}...' in file")
        
        # 写入并生成 diff
        Path(file_path).write_text(new_content)
        diff = self._create_unified_diff(file_path, content, new_content)
        
        return ToolResult(
            title=Path(file_path).name,
            output=f"Edit applied\n\n{diff}",
            metadata={"diff": diff}
        )
```

#### 2.3 Grep 工具（ripgrep 集成）
```python
# tools/grep.py
class GrepTool:
    name = "grep"
    
    async def execute(self, pattern: str, path: str = ".", include: str = None) -> ToolResult:
        self.security.validate_path(path)
        
        # 构建 ripgrep 命令
        cmd = ["rg", "-nH", "--hidden", "--follow", pattern]
        if include:
            cmd.extend(["--glob", include])
        cmd.append(path)
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 1:  # 无匹配
            return ToolResult(title=pattern, output="No matches found", metadata={"matches": 0})
        
        # 解析输出
        matches = self._parse_ripgrep_output(stdout.decode())
        
        return ToolResult(
            title=pattern,
            output=self._format_matches(matches),
            metadata={"matches": len(matches)}
        )
```

### 阶段 3：WebSocket 传输层实现

**目标**：在 MemStack 中实现 WebSocketTransport，连接沙箱 MCP Server

#### 3.1 WebSocketTransport 实现（MemStack 后端）
```python
# src/infrastructure/agent/mcp/client.py - 新增 WebSocketTransport 类

class WebSocketTransport(MCPTransport):
    """MCP transport using WebSocket for bidirectional communication."""
    
    def __init__(self, config: dict):
        self.url = config.get("url")  # ws://sandbox:8765
        self.headers = config.get("headers", {})
        self.timeout = config.get("timeout", 30)
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._receive_task: Optional[asyncio.Task] = None
        self._initialized = False
    
    async def connect(self) -> None:
        """Establish WebSocket connection."""
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(
            self.url,
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        # Start background task to receive messages
        self._receive_task = asyncio.create_task(self._receive_loop())
        # Initialize MCP session
        await self._initialize()
    
    async def _receive_loop(self) -> None:
        """Background task to receive WebSocket messages."""
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                request_id = data.get("id")
                if request_id in self._pending_requests:
                    self._pending_requests[request_id].set_result(data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    
    async def send_request(self, method: str, params: Optional[dict] = None) -> dict:
        """Send JSON-RPC request and wait for response."""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {}
        }
        
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[self._request_id] = future
        
        await self._ws.send_json(request)
        
        try:
            response = await asyncio.wait_for(future, timeout=self.timeout)
            return response.get("result", {})
        finally:
            self._pending_requests.pop(self._request_id, None)
    
    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        if self._receive_task:
            self._receive_task.cancel()
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()
```

#### 3.2 WebSocket 配置模型
```python
# src/infrastructure/mcp/config.py - 新增

class McpWebSocketConfig(BaseModel):
    """WebSocket transport configuration."""
    type: Literal["websocket"] = "websocket"
    url: str  # ws://sandbox:8765 or wss://...
    headers: Optional[Dict[str, str]] = None
    timeout: int = 30000  # ms
    reconnect_attempts: int = 3
    heartbeat_interval: int = 30  # seconds
```

#### 3.3 沙箱 MCP Server WebSocket 服务端
```python
# sandbox-mcp-server/src/server.py

import asyncio
import json
import websockets
from mcp.server import Server
from mcp.types import Tool, TextContent

app = Server("sandbox-filesystem")
TOOL_REGISTRY = {}  # 工具注册表

async def handle_websocket(websocket):
    """处理 WebSocket 连接"""
    async for message in websocket:
        request = json.loads(message)
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        
        try:
            if method == "initialize":
                result = await app.initialize(params)
            elif method == "tools/list":
                result = await list_tools()
            elif method == "tools/call":
                result = await call_tool(params["name"], params["arguments"])
            else:
                result = {"error": f"Unknown method: {method}"}
            
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as e:
            response = {"jsonrpc": "2.0", "id": request_id, "error": {"message": str(e)}}
        
        await websocket.send(json.dumps(response))

async def main():
    async with websockets.serve(handle_websocket, "0.0.0.0", 8765):
        await asyncio.Future()  # 永久运行

if __name__ == "__main__":
    asyncio.run(main())
```

#### 3.4 更新 Dockerfile
```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y ripgrep git tree \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install -e .

ENV WORKSPACE_ROOT=/workspace
RUN mkdir -p /workspace && chmod 777 /workspace

RUN useradd -m sandbox
USER sandbox

# 暴露 WebSocket 端口
EXPOSE 8765

ENTRYPOINT ["python", "-m", "sandbox_mcp_server"]
```

### 阶段 4：MemStack 集成

**目标**：通过 WebSocket 连接沙箱 MCP Server

#### 4.1 沙箱 MCP Server 配置（WebSocket）
```json
{
  "name": "sandbox-filesystem",
  "description": "沙箱文件系统操作",
  "server_type": "websocket",
  "transport_config": {
    "type": "websocket",
    "url": "ws://sandbox-container:8765",
    "timeout": 30000,
    "reconnect_attempts": 3
  },
  "enabled": true
}
```

#### 4.2 Agent 工具加载流程
```
1. 用户创建沙箱会话
   → POST /api/v1/sandbox/sessions
   → 创建 Docker 容器（暴露 8765 端口）
   → 注册 MCP Server 配置（server_type: websocket）

2. MCP Workflow 启动
   → MCPServerWorkflow.start()
   → WebSocketTransport.connect(ws://container:8765)
   → 初始化 MCP 会话
   → 发现工具列表

3. Agent 加载工具
   → MCPTemporalToolLoader.load_all_tools()
   → 工具名称：mcp__sandbox-filesystem__read, __edit, __glob, ...

4. Agent 执行工具
   → ReActAgent.execute_tool("mcp__sandbox-filesystem__edit", {...})
   → MCPTemporalAdapter.call_mcp_tool()
   → WebSocket 发送 JSON-RPC 请求
   → 沙箱内执行，返回结果
```

#### 4.3 沙箱会话管理 API
```
src/infrastructure/adapters/primary/web/routers/sandbox.py

POST   /api/v1/sandbox/sessions           # 创建沙箱会话
GET    /api/v1/sandbox/sessions           # 列出会话
GET    /api/v1/sandbox/sessions/{id}      # 获取会话详情
DELETE /api/v1/sandbox/sessions/{id}      # 销毁会话
POST   /api/v1/sandbox/sessions/{id}/upload  # 上传文件到沙箱
GET    /api/v1/sandbox/sessions/{id}/files   # 列出沙箱文件
```

### 阶段 5：沙箱容器管理

#### 5.1 沙箱管理服务
```
src/infrastructure/sandbox/
├── manager.py                    # 沙箱生命周期管理
├── container.py                  # Docker 容器操作
└── session.py                    # 会话状态管理
```

```python
# manager.py
class SandboxManager:
    async def create_session(self, tenant_id: str, config: SandboxConfig) -> SandboxSession:
        """创建沙箱会话"""
        # 1. 创建 Docker 容器（暴露 WebSocket 端口）
        container = await self.docker.create_container(
            image="memstack/sandbox-mcp-server",
            volumes={config.workspace_path: "/workspace"},
            ports={"8765/tcp": None},  # 动态分配主机端口
            resources=ResourceLimits(cpu=1, memory="512m", disk="1g")
        )
        
        # 2. 获取容器 WebSocket URL
        host_port = container.ports["8765/tcp"]
        ws_url = f"ws://{container.host}:{host_port}"
        
        # 3. 注册 MCP Server（WebSocket 类型）
        mcp_server = await self.mcp_adapter.register_server(
            tenant_id=tenant_id,
            name=f"sandbox-{container.id[:8]}",
            server_type="websocket",
            transport_config={
                "type": "websocket",
                "url": ws_url,
                "timeout": 30000
            }
        )
        
        # 4. 启动 MCP Workflow
        await self.mcp_adapter.start_mcp_server(tenant_id, mcp_server.name)
        
        return SandboxSession(
            id=container.id,
            mcp_server_id=mcp_server.id,
            workspace_path=config.workspace_path,
            websocket_url=ws_url
        )
```

## 关键文件

### 新增项目：sandbox-mcp-server
| 路径 | 描述 |
|-----|------|
| `sandbox-mcp-server/` | **独立的 MCP Server 项目** |
| `sandbox-mcp-server/src/server.py` | MCP Server 入口（WebSocket 服务） |
| `sandbox-mcp-server/src/tools/*.py` | 20 个工具实现 |
| `sandbox-mcp-server/Dockerfile` | 容器镜像（暴露 8765 端口） |

### MemStack 后端新增
| 文件 | 描述 |
|-----|------|
| `src/infrastructure/agent/mcp/client.py` | **新增 WebSocketTransport 类**（~150行） |
| `src/infrastructure/mcp/config.py` | **新增 McpWebSocketConfig**（~20行） |
| `src/infrastructure/sandbox/manager.py` | 沙箱管理服务 |
| `src/infrastructure/sandbox/container.py` | Docker 容器操作 |
| `src/infrastructure/adapters/primary/web/routers/sandbox.py` | 沙箱 API |

### MemStack 后端修改
| 文件 | 修改内容 |
|-----|---------|
| `src/infrastructure/agent/mcp/client.py:497` | 替换 `raise NotImplementedError` 为 WebSocketTransport |
| `src/infrastructure/adapters/secondary/temporal/mcp/activities.py` | 添加 WebSocket 客户端支持 |
| `src/configuration/di_container.py` | 注册沙箱相关依赖 |
| `docker-compose.yml` | 添加沙箱网络配置 |

### 前端新增（可选）
| 文件 | 描述 |
|-----|------|
| `web/src/services/sandboxService.ts` | 沙箱 API 客户端 |
| `web/src/components/sandbox/FileExplorer.tsx` | 文件浏览器 |

## 安全设计

### 容器隔离
- 资源限制：CPU 1核、内存 512MB、磁盘 1GB
- 网络隔离：仅允许 WebSocket 端口 8765
- 用户隔离：非 root 用户运行
- 只读根文件系统，仅 /workspace 可写

### WebSocket 安全
- 支持 TLS（wss://）加密传输
- 连接认证（可选：token 验证）
- 心跳检测和自动重连
- 请求超时控制

### MCP 层权限（复用现有）
- 工具命名：`mcp__sandbox-filesystem__<tool>`
- 权限规则：继承 PermissionManager
- 危险操作（bash、write）需用户确认

### 路径安全（沙箱内）
- 所有路径必须在 `/workspace` 下
- 禁止路径遍历（`..`）
- 符号链接检查

## 验证方案

### MCP Server 测试（本地）
```bash
cd sandbox-mcp-server
uv run pytest tests/ -v

# 本地启动 WebSocket Server
python -m sandbox_mcp_server

# 测试 WebSocket 连接
python -c "
import asyncio
import websockets
import json

async def test():
    async with websockets.connect('ws://localhost:8765') as ws:
        await ws.send(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list'}))
        print(await ws.recv())

asyncio.run(test())
"
```

### Docker 镜像测试
```bash
# 构建镜像
docker build -t memstack/sandbox-mcp-server sandbox-mcp-server/

# 运行容器
docker run -d -p 8765:8765 -v /tmp/workspace:/workspace memstack/sandbox-mcp-server

# 测试工具
curl -X POST http://localhost:8765 -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"read","arguments":{"file_path":"/workspace/test.txt"}}}'
```

### 集成测试
```bash
# 启动 MemStack
make dev

# 运行集成测试
uv run pytest src/tests/integration/sandbox/ -v
```

### 端到端测试
1. 启动 MemStack：`make dev`
2. 创建沙箱会话：`POST /api/v1/sandbox/sessions`
3. 验证 WebSocket 连接建立
4. 通过 Agent Chat 测试：
   - `read /workspace/README.md`
   - `edit /workspace/main.py -old "hello" -new "world"`
   - `grep "TODO" /workspace`
   - `bash ls -la /workspace`
5. 验证权限提示和结果

## 依赖项

### sandbox-mcp-server
```toml
[project]
dependencies = [
    "websockets>=12.0",     # WebSocket 服务端
    "aiofiles>=24.0.0",     # 异步文件操作
]
```

### MemStack（新增）
```toml
# 已有 aiohttp，用于 WebSocket 客户端
```

### 系统依赖（Docker 镜像内）
- ripgrep
- git
- tree

## 实施顺序

1. **阶段 1**：MemStack WebSocket 支持
   - 实现 `WebSocketTransport` 类
   - 添加 `McpWebSocketConfig` 配置
   - 更新 Temporal MCP activities

2. **阶段 2**：创建 sandbox-mcp-server
   - 实现 WebSocket 服务端
   - 实现核心工具（read、edit、glob、grep、bash）
   - 构建 Docker 镜像

3. **阶段 3**：MemStack 集成
   - 实现 SandboxManager
   - 添加沙箱 API
   - 集成测试

4. **阶段 4**：完整工具实现
   - 实现剩余 15 个工具
   - 权限控制和安全加固

5. **阶段 5**：前端 UI（可选）+ 端到端测试
