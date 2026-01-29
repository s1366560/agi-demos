# Sandbox 统一架构方案

## 一、架构概览

### 1.1 当前问题

| 问题类型 | 描述 | 影响 |
|---------|------|------|
| **重复实现** | DesktopTool/TerminalTool 和 REST API 功能重复 | 维护成本高 |
| **终端分叉** | MCP 工具和独立路由两套实现 | 行为不一致 |
| **事件冗余** | agent_events + sandbox_events 两套事件 | 前端处理复杂 |
| **逻辑分散** | URL 构建、状态管理分散在多处 | 难以追踪 |

### 1.2 目标架构

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                              统一 Sandbox 架构                                   │
├──────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  Frontend Layer                                                                 │
│    ├── Agent Chat (ReActAgent)                                                  │
│    └── Sandbox Panel (Desktop/Terminal Viewers)                               │
│                                                                                      │
│  API Gateway Layer                                                               │
│    ├── /api/v1/agent/chat (SSE)                                                 │
│    └── /api/v1/sandbox/* (REST + SSE)                                            │
│                                                                                      │
│  Service Orchestration Layer                                                      │
│    └── SandboxOrchestrator (统一入口)                                           │
│         ├── start_desktop()                                                     │
│         ├── stop_desktop()                                                      │
│         ├── start_terminal()                                                   │
│         ├── stop_terminal()                                                    │
│         └── execute_command()                                                   │
│                                                                                      │
│  MCP Protocol Layer                                                              │
│    ├── MCPSandboxAdapter                                                        │
│    └── MCPWebSocketClient                                                       │
│                                                                                      │
│  sandbox-mcp-server (Docker)                                                      │
│    ├── MCP Tools (控制平面)                                                    │
│    └── Background Services (数据平面: noVNC, ttyd)                            │
│                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

## 二、核心组件设计

### 2.1 SandboxOrchestrator

统一服务编排层，为 REST API 和 Agent Tools 提供一致接口。

```python
# src/application/services/sandbox_orchestrator.py

class SandboxOrchestrator:
    """统一 Sandbox 服务编排层"""

    def __init__(
        self,
        sandbox_adapter: SandboxPort,
        event_publisher: Optional[SandboxEventPublisher] = None,
        default_timeout: int = 30,
    ):
        self._adapter = sandbox_adapter
        self._events = event_publisher
        self._default_timeout = default_timeout

    # Desktop 管理
    async def start_desktop(sandbox_id: str, config: DesktopConfig) -> DesktopStatus
    async def stop_desktop(sandbox_id: str) -> bool
    async def get_desktop_status(sandbox_id: str) -> DesktopStatus

    # Terminal 管理
    async def start_terminal(sandbox_id: str, config: TerminalConfig) -> TerminalStatus
    async def stop_terminal(sandbox_id: str) -> bool
    async def get_terminal_status(sandbox_id: str) -> TerminalStatus

    # 命令执行
    async def execute_command(sandbox_id: str, command: str, ...) -> CommandResult
```

### 2.2 统一事件系统

```python
# src/domain/events/sandbox_events.py

class SandboxEventType(str, Enum):
    DESKTOP_STARTED = "desktop_started"
    DESKTOP_STOPPED = "desktop_stopped"
    TERMINAL_STARTED = "terminal_started"
    TERMINAL_STOPPED = "terminal_stopped"
    COMMAND_EXECUTED = "command_executed"
    SANDBOX_CREATED = "sandbox_created"
    SANDBOX_TERMINATED = "sandbox_terminated"

@dataclass
class DesktopStartedEvent(AgentDomainEvent):
    sandbox_id: str
    url: Optional[str]
    display: str
    resolution: str
    port: int
```

## 三、MCP 协议边界

### 3.1 控制平面 vs 数据平面

| 平面 | 使用 MCP 协议 | 直接连接 |
|------|----------------|----------|
| **控制平面** | ✅ 启停服务、状态查询、文件操作 | ❌ |
| **数据平面** | ❌ | ✅ noVNC WebSocket、ttyd WebSocket |

**控制平面通过 MCP**:
- 文件操作: read, write, edit, glob, grep, bash
- 桌面控制: start_desktop, stop_desktop, get_desktop_status
- 终端控制: start_terminal, stop_terminal, get_terminal_status

**数据平面直连**:
- noVNC: ws://host:6080/websock (VNC 协议)
- ttyd: ws://host:7681 (Shell I/O)

## 四、工具暴露路径

```
sandbox-mcp-server (MCP WebSocket Server)
    ↓
Temporal MCP Worker (MCPTemporalAdapter)
    ↓
Agent Worker (MCPTemporalToolLoader)
    ↓
Agent Session Pool (缓存 MCP 工具, TTL: 5min)
    ↓
ReActAgent (tool_definitions)
    ↓
SessionProcessor (工具执行)
```

## 五、迁移步骤

### Phase 1: 创建 SandboxOrchestrator
- 创建 `src/application/services/sandbox_orchestrator.py`
- 创建 `src/domain/events/sandbox_events.py`
- 添加单元测试

### Phase 2: 重构 Agent Tools
- 修改 DesktopTool 使用 SandboxOrchestrator
- 修改 TerminalTool 使用 SandboxOrchestrator

### Phase 3: 重构 REST API
- 修改 `src/infrastructure/adapters/primary/web/routers/sandbox.py`
- 注入 SandboxOrchestrator

### Phase 4: 统一 SSE 事件
- 合并事件发布器
- 添加 `/api/v1/sandbox/events/{project_id}` 端点
- 前端迁移到单一事件流

### Phase 5: 移除冗余代码
- 清理重复的工具调用逻辑
- 保留数据平面 WebSocket

## 六、预期收益

| 指标 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| 代码重复 | DesktopTool + REST 两套 | SandboxOrchestrator 单一 | -50% |
| 首次延迟 | 300-800ms | <20ms (缓存命中) | 95%+ |
| 维护成本 | 修改需更新两处 | 修改一处生效 | 显著降低 |
