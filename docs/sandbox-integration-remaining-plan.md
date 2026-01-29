# Sandbox 集成剩余工作 - 架构设计与实施计划

## 执行摘要

本文档详细说明了完成 Sandbox 在 Agent UI 集成的剩余工作（Phase 3 和 Phase 7）。

**当前进度**: 5/7 阶段完成 (71%)

**剩余工作**:
- **Phase 3**: 后端 Sandbox SSE 事件发送机制
- **Phase 7**: 后端 Desktop API 端点实现

---

## 架构分析

### 现有组件概览

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Frontend (React)                          │
├──────────────────────────────────────────────────────────────────────┤
│  AgentChat.tsx          │  RightPanel.tsx       │  sandbox.ts      │
│  - ensureSandbox()      │  - Auto tab switch   │  (Zustand Store)  │
│  - handleSend()         │  - Render SandboxPanel│  - handleSSEEvent()│
└──────────────┬───────────────────┬───────────────────┬───────────────┘
               │                   │                   │
               ▼                   ▼                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    sandboxService.ts (✅ Phase 1 完成)              │
│  - createSandbox(), listSandboxes(), getSandbox()                   │
│  - startTerminal(), stopTerminal(), getTerminalStatus()            │
│  - startDesktop(), stopDesktop(), getDesktopStatus() (TODO)         │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP/WebSocket
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI)                              │
├──────────────────────────────────────────────────────────────────────┤
│  routers/sandbox.py       │  routers/terminal.py   │  processor.py   │
│  - POST /create           │  - POST /{id}/create   │  - SSE Events   │
│  - GET /{id}              │  - GET /{id}/sessions   │  - ReAct Loop   │
│  - DELETE /{id}           │  - DELETE /.../{sid}    │                │
└──────────────┬─────────────────┴──────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│              sandbox-mcp-server (Docker Container)                  │
├──────────────────────────────────────────────────────────────────────┤
│  desktop_manager.py       │  desktop_tools.py       │  main.py     │
│  - DesktopManager ✅     │  - start_desktop()     │  - MCP Server│
│  - Xvfb + TigerVNC        │  - stop_desktop()      │              │
│  - noVNC                  │  - get_desktop_status() │              │
└──────────────────────────────────────────────────────────────────────┘
```

### 关键发现

1. **DesktopManager 已存在**: `sandbox-mcp-server/src/server/desktop_manager.py` 已完整实现
2. **MCP 工具已注册**: `desktop_tools.py` 已定义 `start_desktop`, `stop_desktop` 等函数
3. **缺失的部分**:
   - 后端 API 路由未暴露 Desktop 端点
   - 后端未通过 SSE 发送 Sandbox 事件

---

## Phase 3: 后端 Sandbox SSE 事件发送机制

### 需求描述

在 Agent 执行期间，后端需要发送以下 SSE 事件通知前端：

| 事件名称 | 触发时机 | 数据内容 |
|----------|----------|----------|
| `sandbox_created` | Sandbox 创建成功 | `{ id, status, websocket_url }` |
| `desktop_started` | Desktop 服务启动 | `{ running, url, display, resolution, port }` |
| `desktop_stopped` | Desktop 服务停止 | `{ running: false }` |
| `terminal_started` | Terminal 会话创建 | `{ running, url, sessionId, port }` |
| `terminal_stopped` | Terminal 会话关闭 | `{ running: false }` |

### 前端已实现的处理逻辑

`web/src/stores/sandbox.ts` 中的 `handleSSEEvent()` 已实现：

```typescript
handleSSEEvent: (event) => {
  const { type, data } = event;

  switch (type) {
    case "desktop_started": {
      const status: DesktopStatus = {
        running: true,
        url: data.url || null,
        display: data.display || ":0",
        resolution: data.resolution || "1280x720",
        port: data.port || 6080,
      };
      set({ desktopStatus: status });
      break;
    }
    // ... 其他事件处理
  }
}
```

### 实施方案

#### 方案 A: 在 Router 端点中发送 SSE（推荐）

**优点**:
- 简单直接，与现有 API 路由一致
- 不修改 Agent Processor 核心逻辑
- 易于测试和维护

**缺点**:
- SSE 连接仅存在于 API 调用期间
- 需要额外的 WebSocket 用于实时状态更新

**实施步骤**:

1. **创建 SSE 事件响应模型**

   文件: `src/domain/events/agent_events.py`

   ```python
   # 添加新的 AgentEventType
   SANDBOX_CREATED = "sandbox_created"
   DESKTOP_STARTED = "desktop_started"
   DESKTOP_STOPPED = "desktop_stopped"
   TERMINAL_STARTED = "terminal_started"
   TERMINAL_STOPPED = "terminal_stopped"

   # 添加对应的事件类
   class AgentSandboxCreatedEvent(AgentDomainEvent):
       event_type: AgentEventType = AgentEventType.SANDBOX_CREATED
       sandbox_id: str
       status: str
       websocket_url: Optional[str] = None

   class AgentDesktopStartedEvent(AgentDomainEvent):
       event_type: AgentEventType = AgentEventType.DESKTOP_STARTED
       sandbox_id: str
       running: bool
       url: Optional[str] = None
       display: str = ":0"
       resolution: str = "1280x720"
       port: int = 6080

   # ... 其他事件类
   ```

2. **在 Sandbox Router 中集成事件发送**

   文件: `src/infrastructure/adapters/primary/web/routers/sandbox.py`

   ```python
   from src.domain.events.agent_events import AgentSandboxCreatedEvent

   # 可选: 注入事件队列/发送器
   # 或者使用 SSE StreamingResponse

   @router.post("/create")
   async def create_sandbox(...):
       # 创建 sandbox
       instance = await adapter.create_sandbox(...)

       # 发送 SSE 事件（如果是在 Agent 上下文中）
       # 或者通过 WebSocket 广播

       return SandboxResponse(...)
   ```

#### 方案 B: 在 Agent Processor 中发送（完整方案）

**优点**:
- 与 Agent 执行流程紧密集成
- 可在工具调用时自动发送事件
- 统一的事件流

**缺点**:
- 需要修改 Processor 核心逻辑
- 需要将 Sandbox 适配器注入到 Processor

**实施步骤**:

1. **创建 Sandbox 事件发送器**

   文件: `src/infrastructure/agent/sandbox/sandbox_event_emitter.py`

   ```python
   """Sandbox event emitter for SSE notifications."""

   import logging
   from typing import TYPE_CHECKING

   if TYPE_CHECKING:
       from ..core.processor import SessionProcessor

   logger = logging.getLogger(__name__)

   class SandboxEventEmitter:
       """Emits sandbox-related events during agent execution."""

       def __init__(self, processor: "SessionProcessor"):
           self._processor = processor

       async def emit_sandbox_created(
           self,
           sandbox_id: str,
           status: str,
           websocket_url: str | None = None,
       ):
           """Emit sandbox_created event."""
           from src.domain.events.agent_events import AgentSandboxCreatedEvent

           event = AgentSandboxCreatedEvent(
               sandbox_id=sandbox_id,
               status=status,
               websocket_url=websocket_url,
           )
           # 通过 Processor 的 yield 机制发送
           # 或者直接添加到事件队列
           await self._emit_event(event)

       async def emit_desktop_started(
           self,
           sandbox_id: str,
           url: str,
           display: str = ":0",
           resolution: str = "1280x720",
           port: int = 6080,
       ):
           """Emit desktop_started event."""
           from src.domain.events.agent_events import AgentDesktopStartedEvent

           event = AgentDesktopStartedEvent(
               sandbox_id=sandbox_id,
               running=True,
               url=url,
               display=display,
               resolution=resolution,
               port=port,
           )
           await self._emit_event(event)

       async def _emit_event(self, event):
           """Emit event through processor."""
           # Processor 通过 yield 返回事件
           # 这里需要将事件添加到某个队列
           pass
   ```

2. **集成到 SessionProcessor**

   文件: `src/infrastructure/agent/core/processor.py`

   ```python
   class SessionProcessor:
       def __init__(
           self,
           ...,
           sandbox_adapter: Optional["MCPSandboxAdapter"] = None,
       ):
           ...
           self._sandbox_emitter: Optional[SandboxEventEmitter] = None
           if sandbox_adapter:
               self._sandbox_emitter = SandboxEventEmitter(self, sandbox_adapter)

       async def _execute_tool(self, tool_call: ToolCall) -> ToolResult:
           """Execute a tool and emit sandbox events if applicable."""

           # 检测 sandbox 相关工具
           if tool_call.name == "start_desktop":
               result = await self._execute_start_desktop(tool_call)
               # 发送 desktop_started 事件
               await self._sandbox_emitter.emit_desktop_started(...)
               return result

           # ... 其他工具
   ```

### 推荐方案

**采用方案 A（Router 层发送）+ WebSocket 广播**

原因：
1. 不修改 Agent 核心逻辑
2. 利用现有 WebSocket 基础设施
3. Desktop/Terminal 是独立于 Agent 执行的操作

**具体实现**:

```
┌─────────────────────────────────────────────────────────────────┐
│                    SSE Event Flow (方案 A)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Agent Execution                        │  Direct API Calls     │
│  ┌─────────────────────────────┐      │  ┌─────────────────┐│
│  │ 1. Agent calls tool         │      │  │ 1. POST /create ││
│  │    - start_desktop         │      │  │ 2. POST /desktop││
│  │    - start_terminal        │      │  │ 3. DELETE /...  ││
│  └───────────┬─────────────────┘      │  └────────┬────────┘│
│              │                           │          │        │
│              ▼                           │          ▼        │
│  ┌─────────────────────────────┐      │  ┌─────────────────┐│
│  │ 2. Tool executes in         │      │  │ 2. Router calls ││
│  │    sandbox container        │      │  │    container    ││
│  │    (via MCP WebSocket)       │      │  │                 ││
│  └───────────┬─────────────────┘      │  └────────┬────────┘│
│              │                           │          │        │
│              ▼                           │          ▼        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ 3. Result returned + Event emitted via WebSocket/SSE       ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                  │
│                              ▼                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Frontend receives SSE event → sandboxStore.handleSSEEvent()││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 7: 后端 Desktop API 端点实现

### 需求描述

在后端 `sandbox.py` 路由中添加 Desktop 管理端点，这些端点将调用 sandbox-mcp-server 容器内的 Desktop 功能。

### 现有基础设施

**sandbox-mcp-server 已实现**:
- `DesktopManager` 类 - 管理 Xvfb + TigerVNC + noVNC
- `start_desktop()` / `stop_desktop()` / `get_desktop_status()` 函数
- MCP 工具定义

**后端适配器已实现**:
- `MCPSandboxAdapter` - Docker 容器管理
- 容器内 MCP WebSocket 通信

### API 端点设计

#### 1. POST /api/v1/sandbox/{sandbox_id}/desktop

启动 sandbox 的远程桌面服务。

**请求**:
```json
{
  "resolution": "1920x1080",
  "display": ":1"
}
```

**响应** (200 OK):
```json
{
  "running": true,
  "url": "http://localhost:6080/vnc.html",
  "display": ":1",
  "resolution": "1920x1080",
  "port": 6080
}
```

#### 2. DELETE /api/v1/sandbox/{sandbox_id}/desktop

停止 sandbox 的远程桌面服务。

**响应** (200 OK):
```json
{
  "success": true
}
```

#### 3. GET /api/v1/sandbox/{sandbox_id}/desktop

获取 sandbox 的桌面状态。

**响应** (200 OK):
```json
{
  "running": true,
  "url": "http://localhost:6080/vnc.html",
  "display": ":1",
  "resolution": "1920x1080",
  "port": 6080,
  "xvfb_pid": 12345,
  "xvnc_pid": 12346
}
```

### 实施方案

由于 sandbox-mcp-server 是独立的容器，我们需要通过以下方式调用 Desktop 功能：

#### 方案 A: 通过 MCP 调用（推荐）

利用现有的 MCP WebSocket 连接调用 `start_desktop` 工具。

```python
@router.post("/{sandbox_id}/desktop")
async def start_desktop(
    sandbox_id: str,
    request: DesktopRequest,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Start remote desktop for sandbox."""
    # 通过 MCP 调用 start_desktop 工具
    result = await adapter.call_tool(
        sandbox_id=sandbox_id,
        tool_name="start_desktop",
        arguments={
            "display": request.display,
            "resolution": request.resolution,
            "port": request.port,
        },
    )
    return result
```

#### 方案 B: Docker Exec 直接调用

直接在容器内执行命令。

```python
@router.post("/{sandbox_id}/desktop")
async def start_desktop(
    sandbox_id: str,
    request: DesktopRequest,
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Start remote desktop for sandbox."""
    # 获取容器
    container = adapter._docker.containers.get(sandbox_id)

    # 在容器内调用 MCP 工具
    # 或者通过 exec 进入容器调用 Python 函数
    exec_result = container.exec_run(
        f"python -c 'from src.tools.desktop_tools import start_desktop; "
        f"import asyncio; asyncio.run(start_desktop())'"
    )

    # 解析结果并返回
    return parse_result(exec_result)
```

### 推荐方案: MCP 调用（方案 A）

**原因**:
1. 复用现有 MCP 工具逻辑
2. 与 Agent 执行 sandbox 工具的路径一致
3. 不需要额外的 Docker exec 开销

---

## 详细实施步骤

### Phase 3.1: 添加 Sandbox 事件类型（30 分钟）

**文件**: `src/domain/events/agent_events.py`

**任务**:
1. 添加 `AgentEventType` 枚举值
2. 创建事件数据类
3. 添加 `to_event_dict()` 方法支持

**验收**:
- 事件类型定义完整
- 类型检查通过 (`mypy`)

### Phase 3.2: 创建 Desktop 路由端点（1 小时）

**文件**: `src/infrastructure/adapters/primary/web/routers/sandbox.py`

**任务**:
1. 添加 `DesktopRequest` Pydantic 模型
2. 添加 `DesktopStatusResponse` Pydantic 模型
3. 实现 `POST /{sandbox_id}/desktop` 端点
4. 实现 `DELETE /{sandbox_id}/desktop` 端点
5. 实现 `GET /{sandbox_id}/desktop` 端点

**验收**:
- 端点响应正确
- 错误处理完善
- Swagger 文档生成

### Phase 3.3: 集成 SSE 事件发送（1 小时）

**文件**: `src/infrastructure/adapters/primary/web/routers/sandbox.py`

**任务**:
1. 在 `create_sandbox` 中添加 `sandbox_created` 事件
2. 在 `start_desktop` 中添加 `desktop_started` 事件
3. 在 `stop_desktop` 中添加 `desktop_stopped` 事件
4. 在 `terminal.py` 中添加 `terminal_started/ stopped` 事件

**验收**:
- 事件正确发送
- 前端接收到事件并更新状态

### Phase 3.4: 更新前端测试（30 分钟）

**文件**: `web/src/test/services/sandboxService.test.ts`

**任务**:
1. 更新 `startDesktop` 测试（移除"未实现"警告）
2. 更新 `stopDesktop` 测试
3. 更新 `getDesktopStatus` 测试
4. 验证所有测试通过

**验收**:
- 18/18 测试通过
- 测试覆盖所有 Desktop 功能

### Phase 3.5: E2E 集成测试（1 小时）

**文件**: `web/e2e/sandbox.spec.ts`

**任务**:
1. 创建 Sandbox 集成 E2E 测试
2. 测试 Desktop 启动/停止流程
3. 测试 Terminal 创建/关闭流程
4. 测试 SSE 事件接收

**验收**:
- E2E 测试通过
- 覆盖关键用户流程

---

## 风险评估

| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| MCP 调用延迟 | **MEDIUM** | 添加超时和重试机制 |
| Desktop 启动失败 | **MEDIUM** | 友好错误提示，返回失败原因 |
| SSE 事件丢失 | **LOW** | 前端可手动刷新状态 |
| Docker 资源限制 | **MEDIUM** | 设置内存/CPU 限制，超时自动清理 |
| WebSocket 连接中断 | **LOW** | 前端自动重连机制 |

---

## 预估工作量

| 阶段 | 任务 | 预估时间 |
|------|------|----------|
| Phase 3.1 | 添加 Sandbox 事件类型 | 30 分钟 |
| Phase 3.2 | 创建 Desktop 路由端点 | 1 小时 |
| Phase 3.3 | 集成 SSE 事件发送 | 1 小时 |
| Phase 3.4 | 更新前端测试 | 30 分钟 |
| Phase 3.5 | E2E 集成测试 | 1 小时 |
| **总计** | | **4 小时** |

---

## 验收标准

### 功能验收

- [ ] POST /sandbox/{id}/desktop 启动桌面成功
- [ ] DELETE /sandbox/{id}/desktop 停止桌面成功
- [ ] GET /sandbox/{id}/desktop 返回正确状态
- [ ] 前端接收到 `desktop_started` 事件
- [ ] 前端接收到 `desktop_stopped` 事件
- [ ] 前端接收到 `terminal_started` 事件
- [ ] 前端接收到 `terminal_stopped` 事件
- [ ] E2E 测试覆盖完整流程

### 技术验收

- [ ] 所有新代码有类型注解
- [ ] `mypy` 检查通过
- [ ] Swagger 文档生成正确
- [ ] 错误处理完善（400, 404, 500）
- [ ] 测试覆盖率 > 80%

---

## 相关文件清单

### 后端文件（需修改）

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/domain/events/agent_events.py` | 修改 | 添加 Sandbox 事件类型 |
| `src/infrastructure/adapters/primary/web/routers/sandbox.py` | 修改 | 添加 Desktop 端点 |
| `src/infrastructure/adapters/primary/web/routers/terminal.py` | 修改 | 添加 SSE 事件发送 |

### 前端文件（需修改）

| 文件 | 操作 | 说明 |
|------|------|------|
| `web/src/services/sandboxService.ts` | 修改 | 移除 Desktop "未实现" 警告 |
| `web/src/test/services/sandboxService.test.ts` | 修改 | 更新 Desktop 测试用例 |

### 测试文件（需创建）

| 文件 | 说明 |
|------|------|
| `web/e2e/sandbox.spec.ts` | Sandbox 集成 E2E 测试 |
| `src/tests/integration/test_sandbox_desktop.py` | Desktop API 集成测试 |

---

## 参考资料

**现有实现**:
- `sandbox-mcp-server/src/server/desktop_manager.py` - Desktop Manager
- `sandbox-mcp-server/src/tools/desktop_tools.py` - Desktop MCP 工具
- `web/src/stores/sandbox.ts` - 前端 Store (已实现 `handleSSEEvent`)

**相关文档**:
- `docs/sandbox-integration-plan.md` - 原集成计划
- `CLAUDE.md` - 项目架构文档
