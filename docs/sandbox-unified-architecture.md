# Sandbox 统一架构方案

> 状态：架构已落地（部分阶段仍为 Partial）。
> Last checked against code: 2026-06-22
>
> 说明：本文原为「方案 / Phase 提案」，现改为反映现状的架构说明。代码事实以 `src/application/services/sandbox_orchestrator.py`、`src/infrastructure/adapters/primary/web/routers/project_sandbox.py` 等为准。

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
│    ├── /api/v1/agent/ws (WebSocket)                                             │
│    └── /api/v1/sandbox/* (REST + SSE/WebSocket helpers)                         │
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

### 2.1 SandboxOrchestrator（已实现）

统一服务编排层，为 REST API 和 Agent Tools 提供一致接口。**当前状态：已实现**，代码位于 `src/application/services/sandbox_orchestrator.py`，并通过 `src/infrastructure/adapters/primary/web/routers/project_sandbox.py` 注入到 REST API。

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
        ...

    # 按类型派发到对应 adapter（MCPSandboxAdapter / LocalSandboxAdapter 等）
    def register_sandbox_type(self, sandbox_id: str, sandbox_type: str) -> None
    def is_local_sandbox(self, sandbox_id: str) -> bool

    # Desktop 管理
    async def start_desktop(sandbox_id, config: DesktopConfig) -> DesktopStatus
    async def stop_desktop(sandbox_id) -> bool
    async def get_desktop_status(sandbox_id) -> DesktopStatus

    # Terminal 管理
    async def start_terminal(sandbox_id, config: TerminalConfig) -> TerminalStatus
    async def stop_terminal(sandbox_id) -> bool
    async def get_terminal_status(sandbox_id) -> TerminalStatus

    # 命令执行
    async def execute_command(sandbox_id, command, ...) -> CommandResult
```

辅助类型 `DesktopConfig` / `TerminalConfig` / `DesktopStatus` / `TerminalStatus` / `CommandResult` 同文件定义。

### 2.2 统一事件系统

> 旧版文档把这部分标为「新建 `src/domain/events/sandbox_events.py`」。该文件**不存在**——sandbox / desktop / terminal 事件复用通用 Agent 事件体系，分布在两个文件：

- 枚举：`src/domain/events/types.py` 中的 `AgentEventType`，包含 `SANDBOX_CREATED`、`SANDBOX_TERMINATED`、`SANDBOX_STATUS`、`DESKTOP_STARTED`、`DESKTOP_STOPPED`、`DESKTOP_STATUS`、`TERMINAL_STARTED`、`TERMINAL_STOPPED`、`TERMINAL_STATUS` 等（`EventCategory.SANDBOX` 归类于同文件 `EVENT_CATEGORY_MAP`）。
- 事件 dataclass：`src/domain/events/agent_events.py`，如 `AgentSandboxCreatedEvent`、`AgentSandboxTerminatedEvent`、`AgentSandboxStatusEvent`、`AgentDesktopStartedEvent`、`AgentDesktopStoppedEvent`、`AgentDesktopStatusEvent`、`AgentTerminalStartedEvent`、`AgentTerminalStoppedEvent`、`AgentTerminalStatusEvent`（均继承 `AgentDomainEvent`）。

> 注意：旧文档列出的 `COMMAND_EXECUTED` 事件类型在当前枚举中不存在；命令执行结果通过 `CommandResult` 同步返回，不走事件流。

```python
# 例：src/domain/events/agent_events.py（节选）

class AgentDesktopStartedEvent(AgentDomainEvent):
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
Workflow MCP Worker (MCPWorkflowAdapter)
    ↓
Agent Worker (MCPWorkflowToolLoader)
    ↓
Agent Session Pool (缓存 MCP 工具, TTL: 5min)
    ↓
ReActAgent (tool_definitions)
    ↓
SessionProcessor (工具执行)
```

## 五、迁移步骤与完成度

### Phase 1: 创建 SandboxOrchestrator — **Done**
- `src/application/services/sandbox_orchestrator.py` 已实现 `SandboxOrchestrator`（含 desktop/terminal/command 全套方法）。
- 事件**未**独立成 `sandbox_events.py`，而是归入 `src/domain/events/types.py` + `agent_events.py`（见 2.2）。

### Phase 2: 重构 Agent Tools — **Partial**
- DesktopTool / TerminalTool 经 MCP 工具链暴露给 Agent，控制平面通过 `SandboxOrchestrator` 派发。具体哪些工具直接持有 orchestrator 引用，维护时请用 grep / `gitnexus` 核实当前接线状态。

### Phase 3: 重构 REST API — **Done**
- `src/infrastructure/adapters/primary/web/routers/project_sandbox.py` 通过 `get_orchestrator()` 注入 `SandboxOrchestrator`，desktop / terminal 启停端点均经 orchestrator。
- 旧文档把目标文件写作 `src/infrastructure/adapters/primary/web/routers/sandbox.py`，实际路由已拆为 `routers/sandbox/` 目录与 `project_sandbox.py`，不再有单一 `sandbox.py`。

### Phase 4: 统一 SSE 事件 — **Done**
- `src/infrastructure/adapters/primary/web/routers/sandbox/events.py` 提供 `GET /api/v1/sandbox/events/{project_id}` SSE 端点（`response_class=StreamingResponse`）。
- 事件类型沿用 `AgentEventType` 的 `SANDBOX_*` / `DESKTOP_*` / `TERMINAL_*`。

### Phase 5: 移除冗余代码 — **Partial**
- 控制平面已收敛到 orchestrator；数据平面 WebSocket（noVNC / ttyd）仍保留直连。重复的工具调用逻辑清理状态请以代码检索为准。

## 六、预期收益

| 指标 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| 代码重复 | DesktopTool + REST 两套 | SandboxOrchestrator 单一 | -50% |
| 首次延迟 | 300-800ms | <20ms (缓存命中) | 95%+ |
| 维护成本 | 修改需更新两处 | 修改一处生效 | 显著降低 |
