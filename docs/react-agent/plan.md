# ReActAgent 重构方案

## 📋 问题陈述

当前 ReActAgent 系统存在以下核心问题：

### 代码规模问题

| 文件                     | 行数   | 问题                   |
| ------------------------ | ------ | ---------------------- |
| `processor.py`           | 2175行 | 过于庞大，职责混杂     |
| `react_agent.py`         | 1661行 | 过于庞大，多层抽象混合 |
| `llm_stream.py`          | 1020行 | JSON 解析逻辑过于复杂  |
| `project_react_agent.py` | 1217行 | 与 react_agent.py 重复 |

### 架构问题

1. **工具系统重复** - `AgentTool` 和 `ToolDefinition` 两套抽象并存
2. **单一职责违反** - SessionProcessor 同时处理 LLM 调用、工具执行、权限检查、成本追踪
3. **硬编码配置** - 超时时间 (300s)、阈值等硬编码
4. **事件系统耦合** - 30+ 种事件类型，创建和发送逻辑混杂
5. **Skill 系统分散** - Skill 相关代码分布在多个目录，缺乏统一管理
6. **MCP 系统分散** - MCP 相关代码分布在 3 个不同目录
7. **缺乏热插拔能力** - 工具和 MCP 服务器无法运行时动态加载/卸载
8. **测试困难** - 组件耦合度高，难以单元测试

### 热插拔能力现状

| 组件           | 当前状态                                | 问题                                             |
| -------------- | --------------------------------------- | ------------------------------------------------ |
| **Tool**       | `ToolRegistry` 支持 register/unregister | 但 ReActAgent 初始化时固定 tools，运行时无法更新 |
| **MCP Server** | `MCPServerRegistry` 支持动态注册        | 但与 Agent 工具列表不联动，需手动同步            |
| **Skill**      | 仅支持启动时加载                        | 无运行时加载/卸载机制                            |
| **SubAgent**   | 数据库加载                              | 无运行时更新通知机制                             |

**核心问题**: 

- ReActAgent 构造时接收 `tools: Dict[str, Any]`，生命周期内不可变
- MCP 工具变更后需重建 Agent 实例
- 缺乏统一的变更通知机制 (Observer/Event)

### Skill 系统问题

| 文件                  | 行数  | 位置                | 问题                           |
| --------------------- | ----- | ------------------- | ------------------------------ |
| `skill.py`            | 533行 | domain/model/agent/ | 领域模型过于复杂，包含业务逻辑 |
| `skill_executor.py`   | 344行 | core/               | 与 react_agent.py 耦合         |
| `skill_loader.py`     | 418行 | tools/              | 工具与 Skill 逻辑混合          |
| `skill_installer.py`  | 564行 | tools/              | 安装逻辑过于复杂               |
| `skill_resource_*.py` | 329行 | skill/              | 资源加载分散                   |

**Skill 系统总计**: ~2188 行，分布在 4 个目录

### MCP 系统问题

| 目录                               | 行数   | 职责                  | 问题                  |
| ---------------------------------- | ------ | --------------------- | --------------------- |
| `infrastructure/agent/mcp/`        | 2354行 | Agent MCP 客户端      | client.py 831行过大   |
| `infrastructure/mcp/`              | 744行  | Temporal MCP 工具适配 | 与 agent/mcp 职责重叠 |
| `adapters/secondary/temporal/mcp/` | 2608行 | Temporal MCP 工作流   | 多种客户端实现分散    |

**MCP 系统总计**: ~5706 行，分布在 **3 个不同目录**

**MCP 具体问题**:

- `client.py` (831行) - 连接管理、工具调用、错误处理混合
- `oauth.py` (595行) - OAuth 逻辑复杂
- `http_client.py` (663行) - HTTP 客户端过大
- 3 种客户端 (HTTP/WebSocket/Subprocess) 无统一接口
- Temporal MCP 与 Agent MCP 职责边界不清

### 上下文管理系统问题

| 文件                | 行数  | 位置     | 职责                                     |
| ------------------- | ----- | -------- | ---------------------------------------- |
| `window_manager.py` | 660行 | context/ | 上下文窗口管理、Token 预算分配、压缩策略 |
| `compaction.py`     | 373行 | session/ | 溢出检测、工具输出裁剪                   |
| `truncation.py`     | 307行 | tools/   | 工具输出截断                             |
| `message.py`        | 264行 | core/    | 消息数据结构、Token 追踪                 |

**上下文管理系统总计**: ~1604 行，分布在 **4 个不同目录**

**上下文管理具体问题**:

- **目录分散**: `context/`、`session/`、`tools/`、`core/` 四个位置
- **职责重叠**: `window_manager` 和 `compaction` 都有 Token 估算逻辑
- **Token 估算不一致**: `window_manager` 用 4.0 chars/token，`compaction` 也用 4.0，但中文检测仅在 window_manager
- **Message 类重复**: `compaction.py` 定义了独立的 Message/ToolPart，与 `core/message.py` 重复
- **缺乏统一 Token 计数器**: 各组件自行实现 Token 估算，结果可能不一致
- **配置硬编码**: `PRUNE_MINIMUM_TOKENS=20000`、`PRUNE_PROTECT_TOKENS=40000` 等常量散落各处
- **缺乏可插拔压缩策略**: 压缩策略枚举定义在 window_manager，但执行逻辑分散
- **无缓存机制**: 每次 Token 估算都重新计算，缺乏 memoization

**上下文管理数据流**:

```
User Message → SessionProcessor
      ↓
ContextWindowManager (check 80% threshold)
      ├→ If overflow: split history/recent + summarize (LLM call)
      ├→ OutputTruncator (tool output limit 50KB)
      └→ CompactionModule (prune old tool outputs)
      ↓
Tool Execution with state tracking
      ↓
Message parts (text, tool, reasoning)
      ↓
Token accounting → CostTracker
```

### 技术债务

- JSON 解析有 70+ 行 fallback 逻辑
- Work Plan 基于关键词匹配，易碎
- Doom Loop 检测仅比较 tool_name + arguments，不够智能
- Permission 超时统一 300s，无法按类型调整

---

## 🎯 重构目标

1. **可维护性**: 单文件 < 500 行，职责单一
2. **可扩展性**: 易于添加新工具、新事件
3. **可测试性**: 核心逻辑可独立测试
4. **热插拔能力**: 工具、MCP、Skill 支持运行时动态加载/卸载
5. **保持 ReAct 范式**: 保留 Think → Act → Observe 循环的简洁性

---

## 🏗️ 重构方案

### Phase 1: 组件解耦

#### 1.1 拆分 SessionProcessor

将 2175 行的 processor.py 拆分为职责单一的模块：

```
src/infrastructure/agent/
├── processor/
│   ├── __init__.py
│   ├── orchestrator.py      # 主协调器 (~200行)
│   ├── llm_handler.py       # LLM 调用处理 (~200行)
│   ├── tool_executor.py     # 工具执行器 (~250行)
│   ├── result_observer.py   # 结果观察器 (~150行)
│   ├── work_plan.py         # Work Plan 生成 (~200行)
│   └── message_builder.py   # 消息构建 (~150行)
```

**职责划分**:

- `orchestrator.py`: 状态机驱动，协调各组件
- `llm_handler.py`: LLM 调用、流式响应处理
- `tool_executor.py`: 工具执行、并发控制
- `result_observer.py`: 结果处理、Artifact 提取
- `work_plan.py`: 工作计划生成和追踪
- `message_builder.py`: OpenAI 格式消息构建

#### 1.2 拆分 ReActAgent

将 1661 行的 react_agent.py 拆分：

```
src/infrastructure/agent/
├── core/
│   ├── __init__.py
│   ├── react_agent.py       # 精简的主类 (~300行)
│   ├── react_loop.py        # ReAct 循环核心 (~250行)
│   ├── subagent_delegator.py # SubAgent 委托 (~150行)
│   ├── prompt_builder.py    # Prompt 构建 (~200行)
│   └── config.py            # Agent 配置 (~100行)
```

### Phase 2: Skill 系统重构

#### 2.1 统一 Skill 目录结构

将分散的 Skill 代码整合到 `skill/` 目录：

```
src/infrastructure/agent/
├── skill/
│   ├── __init__.py
│   ├── models.py            # Skill 数据模型 (从 domain 移入) (~200行)
│   ├── matcher.py           # Skill 匹配逻辑 (~150行)
│   ├── executor.py          # Skill 执行器 (~200行)
│   ├── loader.py            # Skill 加载 (合并 resource_loader) (~200行)
│   ├── installer.py         # Skill 安装 (~250行)
│   ├── registry.py          # Skill 注册中心 (~150行)
│   └── parser/
│       ├── __init__.py
│       ├── skill_md_parser.py  # SKILL.md 解析 (~150行)
│       └── agentskills_spec.py # AgentSkills.io 规范 (~100行)
```

#### 2.2 Skill 领域模型简化

将 533 行的 `domain/model/agent/skill.py` 拆分：

```python
# domain/model/agent/skill.py - 精简为纯数据模型 (~150行)
@dataclass
class Skill:
    """Skill 核心数据模型 - 仅包含数据，不含业务逻辑"""
    id: str
    name: str
    description: str
    tools: List[str]
    trigger_type: TriggerType
    trigger_patterns: List[TriggerPattern]
    status: SkillStatus
    scope: SkillScope
    # ... 其他字段

# infrastructure/agent/skill/matcher.py - 匹配逻辑 (~150行)
class SkillMatcher:
    """Skill 匹配服务"""
    def match(self, query: str, skills: List[Skill]) -> SkillMatch: ...
    def _match_keywords(self, query: str, skill: Skill) -> float: ...
    def _match_semantic(self, query: str, skill: Skill) -> float: ...

# infrastructure/agent/skill/executor.py - 执行逻辑 (~200行)
class SkillExecutor:
    """Skill 执行服务"""
    async def execute(self, skill: Skill, context: ExecutionContext) -> SkillResult: ...
```

#### 2.3 Skill 注册中心

```python
# skill/registry.py
class SkillRegistry:
    """中心化 Skill 注册和管理"""
    
    def register(self, skill: Skill) -> None: ...
    def unregister(self, name: str) -> None: ...
    def get(self, name: str) -> Optional[Skill]: ...
    def list_by_scope(self, scope: SkillScope) -> List[Skill]: ...
    def list_for_agent(self, agent_mode: str) -> List[Skill]: ...
    def match(self, query: str, threshold: float = 0.5) -> List[SkillMatch]: ...

# 合并 SkillLoaderTool 和 SkillInstallerTool 的核心逻辑
class SkillManager:
    """Skill 生命周期管理"""
    
    def __init__(self, registry: SkillRegistry): ...
    async def load_from_filesystem(self, path: Path) -> Skill: ...
    async def install_from_url(self, url: str) -> Skill: ...
    async def validate(self, skill: Skill) -> ValidationResult: ...
```

### Phase 3: 工具系统统一

#### 3.1 统一工具接口

消除 `AgentTool` 和 `ToolDefinition` 的重复：

```python
# tools/protocol.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class Tool(Protocol):
    """统一的工具协议"""
    name: str
    description: str
    
    def get_schema(self) -> ToolSchema: ...
    async def execute(self, **kwargs) -> ToolResult: ...
    def get_permission(self) -> Optional[str]: ...

@dataclass
class ToolSchema:
    parameters: Dict[str, Any]
    required: List[str]
    
    def to_openai_format(self) -> Dict[str, Any]: ...
    def to_anthropic_format(self) -> Dict[str, Any]: ...

@dataclass
class ToolResult:
    success: bool
    output: Any
    error: Optional[str] = None
    artifacts: List[Artifact] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

#### 3.2 工具注册中心

```python
# tools/registry.py
class ToolRegistry:
    """中心化工具注册"""
    
    def register(self, tool: Tool, category: str = "default") -> None: ...
    def unregister(self, name: str) -> None: ...
    def get(self, name: str) -> Optional[Tool]: ...
    def list_by_category(self, category: str) -> List[Tool]: ...
    def get_all_schemas(self) -> List[ToolSchema]: ...
    
    # 权限集成
    def check_permission(self, name: str, action: str) -> PermissionResult: ...
```

### Phase 4: 热插拔系统

#### 4.1 统一变更通知机制

```python
# hotplug/events.py
from enum import Enum
from dataclasses import dataclass
from typing import Any

class ChangeType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    UPDATED = "updated"
    ENABLED = "enabled"
    DISABLED = "disabled"

@dataclass
class ComponentChange:
    """组件变更事件"""
    component_type: str  # "tool", "mcp_server", "skill", "subagent"
    component_id: str
    change_type: ChangeType
    data: Optional[Any] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

# hotplug/notifier.py
class ChangeNotifier:
    """变更通知器 - 发布/订阅模式"""
    
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
    
    def subscribe(self, component_type: str, callback: Callable[[ComponentChange], Awaitable]) -> None:
        """订阅组件变更"""
        self._subscribers[component_type].append(callback)
    
    def unsubscribe(self, component_type: str, callback: Callable) -> None:
        """取消订阅"""
        self._subscribers[component_type].remove(callback)
    
    async def notify(self, change: ComponentChange) -> None:
        """通知所有订阅者"""
        for callback in self._subscribers[change.component_type]:
            await callback(change)
        # 同时通知 "*" 订阅者 (监听所有变更)
        for callback in self._subscribers["*"]:
            await callback(change)
```

#### 4.2 动态工具注册中心

```python
# tools/dynamic_registry.py
class DynamicToolRegistry:
    """
    支持热插拔的工具注册中心
    
    Features:
    - 运行时注册/注销工具
    - 变更通知
    - 版本管理
    - 优雅降级
    """
    
    def __init__(self, notifier: ChangeNotifier):
        self._tools: Dict[str, Tool] = {}
        self._versions: Dict[str, int] = {}  # 版本号，用于缓存失效
        self._notifier = notifier
        self._lock = asyncio.Lock()
    
    async def register(self, tool: Tool, notify: bool = True) -> None:
        """注册工具 (线程安全)"""
        async with self._lock:
            self._tools[tool.name] = tool
            self._versions[tool.name] = self._versions.get(tool.name, 0) + 1
        
        if notify:
            await self._notifier.notify(ComponentChange(
                component_type="tool",
                component_id=tool.name,
                change_type=ChangeType.ADDED,
                data=tool.get_schema(),
            ))
    
    async def unregister(self, name: str, notify: bool = True) -> None:
        """注销工具"""
        async with self._lock:
            if name in self._tools:
                del self._tools[name]
                self._versions[name] += 1
        
        if notify:
            await self._notifier.notify(ComponentChange(
                component_type="tool",
                component_id=name,
                change_type=ChangeType.REMOVED,
            ))
    
    def get_version(self) -> int:
        """获取全局版本号 (用于缓存失效检测)"""
        return sum(self._versions.values())
    
    def get_snapshot(self) -> Tuple[Dict[str, Tool], int]:
        """获取工具快照和版本号"""
        return dict(self._tools), self.get_version()
```

#### 4.3 MCP 热插拔管理器

```python
# mcp/hotplug_manager.py
class MCPHotPlugManager:
    """
    MCP 服务器热插拔管理器
    
    职责:
    - 动态添加/移除 MCP 服务器
    - 自动同步工具到 ToolRegistry
    - 健康监控和自动重连
    - 优雅关闭
    """
    
    def __init__(
        self,
        tool_registry: DynamicToolRegistry,
        notifier: ChangeNotifier,
    ):
        self._servers: Dict[str, MCPClient] = {}
        self._server_tools: Dict[str, List[str]] = {}  # server_id -> tool_names
        self._tool_registry = tool_registry
        self._notifier = notifier
    
    async def add_server(self, server_id: str, config: MCPServerConfig) -> None:
        """添加 MCP 服务器并同步工具"""
        # 1. 创建客户端
        client = MCPClientFactory.create(config)
        await client.connect()
        
        # 2. 获取工具列表
        mcp_tools = await client.list_tools()
        
        # 3. 适配为 AgentTool 并注册
        tool_names = []
        for mcp_tool in mcp_tools:
            agent_tool = MCPToolAdapter(client, mcp_tool)
            await self._tool_registry.register(agent_tool)
            tool_names.append(agent_tool.name)
        
        # 4. 记录服务器和工具映射
        self._servers[server_id] = client
        self._server_tools[server_id] = tool_names
        
        # 5. 发送通知
        await self._notifier.notify(ComponentChange(
            component_type="mcp_server",
            component_id=server_id,
            change_type=ChangeType.ADDED,
            data={"tools": tool_names},
        ))
    
    async def remove_server(self, server_id: str) -> None:
        """移除 MCP 服务器并清理工具"""
        if server_id not in self._servers:
            return
        
        # 1. 注销该服务器的所有工具
        for tool_name in self._server_tools.get(server_id, []):
            await self._tool_registry.unregister(tool_name)
        
        # 2. 断开连接
        client = self._servers.pop(server_id)
        await client.disconnect()
        del self._server_tools[server_id]
        
        # 3. 发送通知
        await self._notifier.notify(ComponentChange(
            component_type="mcp_server",
            component_id=server_id,
            change_type=ChangeType.REMOVED,
        ))
    
    async def refresh_server(self, server_id: str) -> None:
        """刷新服务器工具列表 (工具变更时调用)"""
        # ... 重新同步工具
```

#### 4.4 ReActAgent 热插拔支持

```python
# core/react_agent.py (重构后)
class ReActAgent:
    """
    支持热插拔的 ReActAgent
    
    通过订阅 ChangeNotifier 实现工具动态更新
    """
    
    def __init__(
        self,
        tool_registry: DynamicToolRegistry,
        notifier: ChangeNotifier,
        # ... 其他参数
    ):
        self._tool_registry = tool_registry
        self._cached_tools: Optional[List[ToolDefinition]] = None
        self._cached_version: int = -1
        
        # 订阅工具变更
        notifier.subscribe("tool", self._on_tool_change)
    
    async def _on_tool_change(self, change: ComponentChange) -> None:
        """工具变更回调 - 使缓存失效"""
        self._cached_tools = None
        logger.info(f"Tool change detected: {change.change_type} {change.component_id}")
    
    def _get_tools(self) -> List[ToolDefinition]:
        """获取工具列表 (带缓存)"""
        current_version = self._tool_registry.get_version()
        
        if self._cached_tools is None or self._cached_version != current_version:
            tools, version = self._tool_registry.get_snapshot()
            self._cached_tools = self._convert_tools(tools)
            self._cached_version = version
        
        return self._cached_tools
```

#### 4.5 热插拔目录结构

```
src/infrastructure/agent/
├── hotplug/
│   ├── __init__.py
│   ├── events.py            # 变更事件定义 (~50行)
│   ├── notifier.py          # 变更通知器 (~100行)
│   ├── manager.py           # 热插拔管理器 (~200行)
│   └── health_monitor.py    # 健康监控 (~150行)
```

### Phase 5: MCP 系统重构

#### 5.1 统一 MCP 目录结构

将分散的 MCP 代码整合到 `infrastructure/agent/mcp/`：

```
src/infrastructure/agent/
├── mcp/
│   ├── __init__.py
│   ├── protocol.py          # MCP 协议抽象 (~100行)
│   ├── client/
│   │   ├── __init__.py
│   │   ├── base.py          # 客户端基类 (~150行)
│   │   ├── http.py          # HTTP 客户端 (~300行)
│   │   ├── websocket.py     # WebSocket 客户端 (~250行)
│   │   ├── subprocess.py    # Subprocess 客户端 (~200行)
│   │   └── factory.py       # 客户端工厂 (~100行)
│   ├── connection/
│   │   ├── __init__.py
│   │   ├── manager.py       # 连接池管理 (~200行)
│   │   ├── health.py        # 健康检查 (~100行)
│   │   └── retry.py         # 重试策略 (~100行)
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── oauth.py         # OAuth 核心 (~300行)
│   │   └── callback.py      # OAuth 回调 (~150行)
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── adapter.py       # MCP → AgentTool 适配 (~150行)
│   │   ├── loader.py        # 工具加载 (~200行)
│   │   └── wrapper.py       # Sandbox 工具包装 (~150行)
│   ├── registry.py          # MCP Server 注册 (~200行)
│   └── config.py            # MCP 配置 (~100行)
```

#### 5.2 MCP 客户端统一接口

```python
# mcp/protocol.py
from typing import Protocol

class MCPClient(Protocol):
    """MCP 客户端统一协议"""
    
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def list_tools(self) -> List[MCPTool]: ...
    async def call_tool(self, name: str, arguments: Dict) -> MCPResult: ...
    async def health_check(self) -> bool: ...
    
    @property
    def is_connected(self) -> bool: ...

# mcp/client/factory.py
class MCPClientFactory:
    """根据配置创建合适的客户端"""
    
    def create(self, config: MCPServerConfig) -> MCPClient:
        match config.transport:
            case "http": return HTTPMCPClient(config)
            case "websocket": return WebSocketMCPClient(config)
            case "subprocess": return SubprocessMCPClient(config)
```

#### 5.3 MCP 连接池管理

```python
# mcp/connection/manager.py
class MCPConnectionManager:
    """MCP 连接池管理"""
    
    def __init__(self, max_connections: int = 10): ...
    
    async def get_client(self, server_id: str) -> MCPClient: ...
    async def release_client(self, server_id: str, client: MCPClient) -> None: ...
    async def health_check_all(self) -> Dict[str, bool]: ...
    async def reconnect(self, server_id: str) -> None: ...
    
    # 优雅关闭
    async def shutdown(self) -> None: ...
```

#### 5.4 迁移 Temporal MCP

将 `adapters/secondary/temporal/mcp/` 重构为 Temporal 专用适配：

```
src/infrastructure/adapters/secondary/temporal/
├── mcp_adapter.py           # Temporal → MCP 桥接 (~200行)
├── mcp_activities.py        # Temporal Activities (~200行)
└── mcp_workflows.py         # Temporal Workflows (~150行)
```

### Phase 6: 事件系统重构

#### 6.1 事件分层

```
src/domain/events/
├── agent/
│   ├── __init__.py
│   ├── base.py              # 基础事件类 (~50行)
│   ├── lifecycle.py         # 生命周期事件 (Start, Complete, Error)
│   ├── thinking.py          # 思考事件 (Thought, WorkPlan)
│   ├── action.py            # 动作事件 (Act, Observe)
│   ├── interaction.py       # 交互事件 (Permission, Clarification)
│   ├── streaming.py         # 流式事件 (TextDelta, ThoughtDelta)
│   └── metrics.py           # 指标事件 (Cost, Latency)
```

#### 6.2 事件总线

```python
# events/bus.py
class EventBus:
    """类型安全的事件发布"""
    
    async def emit(self, event: AgentEvent) -> None:
        """发布事件"""
        for handler in self._handlers[type(event)]:
            await handler(event)
    
    def subscribe(self, event_type: Type[T], handler: Callable[[T], Awaitable]) -> None:
        """订阅事件"""
        self._handlers[event_type].append(handler)
    
    def stream(self) -> AsyncIterator[AgentEvent]:
        """流式获取事件"""
        while True:
            event = await self._queue.get()
            yield event
```

### Phase 7: 配置外部化

#### 7.1 配置结构

```python
# config/agent_config.py
@dataclass
class AgentConfig:
    """Agent 完整配置"""
    
    # 模型配置
    model: ModelConfig
    
    # 执行配置
    execution: ExecutionConfig
    
    # 权限配置
    permission: PermissionConfig
    
    # 重试配置
    retry: RetryConfig
    
    # 成本配置
    cost: CostConfig
    
    # 上下文管理配置
    context: ContextConfig

@dataclass
class ExecutionConfig:
    max_steps: int = 20
    step_timeout: float = 60.0
    max_tool_calls_per_step: int = 10
    doom_loop_threshold: int = 3

@dataclass
class PermissionConfig:
    default_timeout: float = 300.0
    tool_timeouts: Dict[str, float] = field(default_factory=dict)
    continue_on_deny: bool = False

@dataclass
class ContextConfig:
    """上下文管理配置"""
    max_context_tokens: int = 128000
    max_output_tokens: int = 4096
    compression_trigger_pct: float = 0.80
    prune_minimum_tokens: int = 20000
    prune_protect_tokens: int = 40000
    chars_per_token: float = 4.0
    cjk_chars_per_token: float = 2.0
```

### Phase 8: 上下文管理系统重构

#### 8.1 统一上下文管理目录结构

将分散在 4 个目录的上下文管理代码整合到 `context/`：

```
src/infrastructure/agent/
├── context/
│   ├── __init__.py
│   ├── config.py               # 上下文配置 (~100行)
│   ├── token/
│   │   ├── __init__.py
│   │   ├── estimator.py        # 统一 Token 估算器 (~150行)
│   │   ├── counter.py          # Token 计数器 (~100行)
│   │   └── cache.py            # Token 缓存 (~80行)
│   ├── window/
│   │   ├── __init__.py
│   │   ├── manager.py          # 上下文窗口管理 (~300行)
│   │   ├── budgets.py          # Token 预算分配 (~100行)
│   │   └── splitter.py         # 消息分割 (~100行)
│   ├── compression/
│   │   ├── __init__.py
│   │   ├── strategy.py         # 压缩策略接口 (~50行)
│   │   ├── truncation.py       # 截断策略 (~100行)
│   │   ├── summarization.py    # 摘要策略 (~150行)
│   │   └── compaction.py       # 压实策略 (~150行)
│   ├── pruning/
│   │   ├── __init__.py
│   │   ├── tool_output.py      # 工具输出裁剪 (~150行)
│   │   └── protected.py        # 保护列表管理 (~50行)
│   └── message/
│       ├── __init__.py
│       ├── models.py           # 统一消息模型 (~150行)
│       └── builder.py          # 消息构建器 (~100行)
```

#### 8.2 统一 Token 估算器

```python
# context/token/estimator.py
from typing import Protocol

class TokenEstimator(Protocol):
    """Token 估算协议"""
    def estimate(self, text: str) -> int: ...
    def estimate_message(self, message: Dict[str, Any]) -> int: ...
    def estimate_messages(self, messages: List[Dict[str, Any]]) -> int: ...

class CharacterBasedEstimator:
    """
    基于字符的 Token 估算
    
    统一处理不同语言的字符比例:
    - ASCII/拉丁字符: ~4.0 chars/token
    - CJK (中日韩): ~2.0 chars/token
    - 混合文本: 加权平均
    """
    
    def __init__(
        self,
        default_chars_per_token: float = 4.0,
        cjk_chars_per_token: float = 2.0,
    ):
        self._default_ratio = default_chars_per_token
        self._cjk_ratio = cjk_chars_per_token
        self._cjk_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uac00-\ud7af]')
    
    def estimate(self, text: str) -> int:
        """估算文本 Token 数"""
        if not text:
            return 0
        
        # 分别计算 CJK 和非 CJK 字符
        cjk_count = len(self._cjk_pattern.findall(text))
        non_cjk_count = len(text) - cjk_count
        
        cjk_tokens = cjk_count / self._cjk_ratio
        non_cjk_tokens = non_cjk_count / self._default_ratio
        
        return int(cjk_tokens + non_cjk_tokens)
    
    def estimate_message(self, message: Dict[str, Any]) -> int:
        """估算单条消息 Token 数"""
        tokens = 4  # 消息结构开销
        
        # 内容
        content = message.get("content", "")
        if isinstance(content, str):
            tokens += self.estimate(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        tokens += self.estimate(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        tokens += 85  # 图像引用基础开销
        
        # 工具调用
        for tool_call in message.get("tool_calls", []):
            func = tool_call.get("function", {})
            tokens += self.estimate(func.get("name", ""))
            tokens += self.estimate(func.get("arguments", ""))
            tokens += 10  # 工具调用结构开销
        
        return tokens
```

#### 8.3 可插拔压缩策略

```python
# context/compression/strategy.py
from abc import ABC, abstractmethod
from enum import Enum

class CompressionStrategy(str, Enum):
    NONE = "none"
    TRUNCATE = "truncate"
    SUMMARIZE = "summarize"
    PRUNE = "prune"

class Compressor(ABC):
    """压缩器抽象基类"""
    
    @abstractmethod
    async def compress(
        self,
        messages: List[Dict[str, Any]],
        target_tokens: int,
        context: CompressionContext,
    ) -> CompressionResult: ...
    
    @property
    @abstractmethod
    def strategy(self) -> CompressionStrategy: ...

# context/compression/truncation.py
class TruncationCompressor(Compressor):
    """截断压缩器 - 移除最早的消息"""
    
    @property
    def strategy(self) -> CompressionStrategy:
        return CompressionStrategy.TRUNCATE
    
    async def compress(
        self,
        messages: List[Dict[str, Any]],
        target_tokens: int,
        context: CompressionContext,
    ) -> CompressionResult:
        estimator = context.token_estimator
        kept_messages = []
        total_tokens = 0
        
        # 从最新消息向前保留
        for msg in reversed(messages):
            msg_tokens = estimator.estimate_message(msg)
            if total_tokens + msg_tokens > target_tokens:
                break
            kept_messages.insert(0, msg)
            total_tokens += msg_tokens
        
        return CompressionResult(
            messages=kept_messages,
            removed_count=len(messages) - len(kept_messages),
            original_tokens=context.original_tokens,
            final_tokens=total_tokens,
        )

# context/compression/summarization.py
class SummarizationCompressor(Compressor):
    """摘要压缩器 - 使用 LLM 生成摘要"""
    
    def __init__(self, llm_client: Any, max_summary_tokens: int = 500):
        self._llm_client = llm_client
        self._max_summary_tokens = max_summary_tokens
    
    @property
    def strategy(self) -> CompressionStrategy:
        return CompressionStrategy.SUMMARIZE
    
    async def compress(
        self,
        messages: List[Dict[str, Any]],
        target_tokens: int,
        context: CompressionContext,
    ) -> CompressionResult:
        # 分割历史消息和最近消息
        history, recent = self._split_messages(messages, target_tokens, context)
        
        # 生成历史摘要
        summary = await self._generate_summary(history)
        
        # 构建压缩后的消息列表
        compressed = [{"role": "system", "content": f"[Earlier conversation summary]\n{summary}"}]
        compressed.extend(recent)
        
        return CompressionResult(
            messages=compressed,
            summary=summary,
            summarized_count=len(history),
            # ...
        )
```

#### 8.4 工具输出裁剪

```python
# context/pruning/tool_output.py
class ToolOutputPruner:
    """
    工具输出裁剪器
    
    策略 (对齐 vendor/opencode):
    1. 从后向前遍历，保护最近 40K tokens 的工具调用
    2. 对更早的工具输出进行裁剪
    3. 保护特定工具 (如 skill) 不被裁剪
    4. 仅当可回收 >= 20K tokens 时才执行裁剪
    """
    
    def __init__(
        self,
        protect_tokens: int = 40_000,
        minimum_prune_tokens: int = 20_000,
        protected_tools: Set[str] = None,
    ):
        self._protect_tokens = protect_tokens
        self._minimum_prune = minimum_prune_tokens
        self._protected_tools = protected_tools or {"skill"}
    
    def prune(self, messages: List[Message]) -> PruneResult:
        """裁剪旧工具输出"""
        result = PruneResult()
        
        if not messages:
            return result
        
        # 计算可回收 tokens
        recoverable = self._calculate_recoverable(messages)
        if recoverable < self._minimum_prune:
            logger.debug(f"Recoverable tokens {recoverable} < minimum {self._minimum_prune}")
            return result
        
        # 执行裁剪
        accumulated_tokens = 0
        for msg in reversed(messages):
            for tool_part in msg.get_tool_parts():
                accumulated_tokens += tool_part.tokens or 0
                
                # 保护最近 40K tokens
                if accumulated_tokens <= self._protect_tokens:
                    continue
                
                # 保护特定工具
                if tool_part.tool in self._protected_tools:
                    result.protected_count += 1
                    continue
                
                # 裁剪
                original_tokens = tool_part.tokens or 0
                tool_part.output = "[Output pruned to save context]"
                tool_part.compacted = True
                tool_part.compacted_at = datetime.utcnow()
                
                result.pruned_count += 1
                result.pruned_tokens += original_tokens
        
        result.was_pruned = result.pruned_count > 0
        return result
```

#### 8.5 统一消息模型

消除 `compaction.py` 和 `core/message.py` 的重复定义：

```python
# context/message/models.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"

class ToolStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"

@dataclass
class TokenUsage:
    """Token 使用统计"""
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0
    
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write + self.reasoning

@dataclass
class ToolExecution:
    """工具执行信息"""
    call_id: str
    tool_name: str
    arguments: Dict[str, Any]
    output: Optional[str] = None
    status: ToolStatus = ToolStatus.PENDING
    tokens: Optional[int] = None
    compacted: bool = False
    compacted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

@dataclass
class MessagePart:
    """消息部分 (文本/工具/推理)"""
    type: str  # "text", "tool", "reasoning", "step_start", "step_finish"
    content: Optional[str] = None
    tool_execution: Optional[ToolExecution] = None
    synthetic: bool = False

@dataclass
class Message:
    """统一消息模型"""
    id: str
    role: MessageRole
    parts: List[MessagePart] = field(default_factory=list)
    parent_id: Optional[str] = None
    created_at: Optional[datetime] = None
    tokens: Optional[TokenUsage] = None
    cost: Optional[float] = None
    model: Optional[str] = None
    is_summary: bool = False
    
    def get_tool_executions(self) -> List[ToolExecution]:
        """获取所有工具执行"""
        return [
            part.tool_execution
            for part in self.parts
            if part.type == "tool" and part.tool_execution
        ]
    
    def get_text_content(self) -> str:
        """获取文本内容"""
        return "\n".join(
            part.content
            for part in self.parts
            if part.type == "text" and part.content
        )
    
    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI 消息格式"""
        # ... 转换逻辑
```

#### 8.6 上下文窗口管理器 (精简版)

```python
# context/window/manager.py
class ContextWindowManager:
    """
    上下文窗口管理器
    
    职责:
    1. 计算 Token 预算
    2. 检测是否需要压缩
    3. 选择并执行压缩策略
    4. 返回优化后的消息列表
    """
    
    def __init__(
        self,
        config: ContextConfig,
        token_estimator: TokenEstimator,
        compressors: Dict[CompressionStrategy, Compressor],
    ):
        self._config = config
        self._estimator = token_estimator
        self._compressors = compressors
    
    async def build_context_window(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
    ) -> ContextWindowResult:
        """构建优化的上下文窗口"""
        
        # 1. 估算当前 Token 使用
        system_tokens = self._estimator.estimate(system_prompt)
        messages_tokens = self._estimator.estimate_messages(messages)
        total_tokens = system_tokens + messages_tokens
        
        # 2. 计算预算
        budgets = self._calculate_budgets()
        trigger_threshold = int(budgets["total_available"] * self._config.compression_trigger_pct)
        
        # 3. 检查是否需要压缩
        if total_tokens <= trigger_threshold:
            return ContextWindowResult(
                messages=self._prepend_system(system_prompt, messages),
                was_compressed=False,
                strategy=CompressionStrategy.NONE,
                estimated_tokens=total_tokens,
            )
        
        # 4. 选择压缩策略
        strategy = self._select_strategy(messages, budgets)
        compressor = self._compressors[strategy]
        
        # 5. 执行压缩
        context = CompressionContext(
            token_estimator=self._estimator,
            original_tokens=total_tokens,
            target_tokens=budgets["total_available"],
        )
        result = await compressor.compress(messages, budgets["total_available"], context)
        
        return ContextWindowResult(
            messages=self._prepend_system(system_prompt, result.messages),
            was_compressed=True,
            strategy=strategy,
            estimated_tokens=result.final_tokens,
            summary=result.summary,
            removed_count=result.removed_count,
        )
```

### Phase 8: LLM Stream 简化

#### 8.1 提取 JSON 解析

```
src/infrastructure/agent/
├── llm/
│   ├── __init__.py
│   ├── stream.py            # 精简的流处理 (~300行)
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── json_parser.py   # JSON 解析 (~200行)
│   │   ├── tool_call_parser.py  # 工具调用解析 (~150行)
│   │   └── recovery.py      # 错误恢复 (~100行)
│   └── providers/
│       ├── __init__.py
│       ├── openai.py        # OpenAI 适配
│       └── anthropic.py     # Anthropic 适配
```

---

## 📁 最终目录结构

```
src/infrastructure/agent/
├── __init__.py
├── config/
│   ├── __init__.py
│   ├── agent_config.py      # Agent 配置
│   └── defaults.py          # 默认值
│
├── core/
│   ├── __init__.py
│   ├── react_agent.py       # 主入口 (~300行)
│   ├── react_loop.py        # ReAct 循环核心 (~250行)
│   ├── skill_matcher.py     # Skill 匹配 (~150行)
│   ├── subagent_delegator.py # SubAgent 委托 (~150行)
│   └── prompt_builder.py    # Prompt 构建 (~200行)
│
├── processor/
│   ├── __init__.py
│   ├── orchestrator.py      # 协调器 (~200行)
│   ├── llm_handler.py       # LLM 处理 (~200行)
│   ├── tool_executor.py     # 工具执行 (~250行)
│   ├── result_observer.py   # 结果观察 (~150行)
│   ├── work_plan.py         # 工作计划 (~200行)
│   └── message_builder.py   # 消息构建 (~150行)
│
├── llm/
│   ├── __init__.py
│   ├── stream.py            # 流处理 (~300行)
│   ├── parsers/
│   │   ├── json_parser.py   # JSON 解析 (~200行)
│   │   ├── tool_call_parser.py  # 工具调用解析 (~150行)
│   │   └── recovery.py      # 错误恢复 (~100行)
│   └── providers/
│       ├── openai.py        # OpenAI 适配
│       └── anthropic.py     # Anthropic 适配
│
├── skill/                       # Skill 系统 (重构后)
│   ├── __init__.py
│   ├── models.py            # Skill 数据模型 (~200行)
│   ├── matcher.py           # Skill 匹配 (~150行)
│   ├── executor.py          # Skill 执行 (~200行)
│   ├── loader.py            # Skill 加载 (~200行)
│   ├── installer.py         # Skill 安装 (~250行)
│   ├── registry.py          # Skill 注册中心 (~150行)
│   └── parser/
│       ├── skill_md_parser.py  # SKILL.md 解析
│       └── agentskills_spec.py # AgentSkills.io 规范
│
├── tools/
│   ├── __init__.py
│   ├── protocol.py          # 统一接口
│   ├── registry.py          # 注册中心
│   ├── base.py              # 基类实现
│   └── builtin/             # 内置工具
│       ├── terminal.py
│       ├── web_search.py
│       ├── clarification.py
│       └── ...
│
├── events/
│   ├── __init__.py
│   ├── bus.py               # 事件总线
│   └── types/
│       ├── lifecycle.py     # 生命周期事件
│       ├── thinking.py      # 思考事件
│       ├── action.py        # 动作事件
│       └── streaming.py     # 流式事件
│
├── mcp/                         # MCP 系统 (重构后)
│   ├── __init__.py
│   ├── protocol.py          # MCP 协议抽象 (~100行)
│   ├── client/
│   │   ├── base.py          # 客户端基类 (~150行)
│   │   ├── http.py          # HTTP 客户端 (~300行)
│   │   ├── websocket.py     # WebSocket 客户端 (~250行)
│   │   ├── subprocess.py    # Subprocess 客户端 (~200行)
│   │   └── factory.py       # 客户端工厂 (~100行)
│   ├── connection/
│   │   ├── manager.py       # 连接池管理 (~200行)
│   │   ├── health.py        # 健康检查 (~100行)
│   │   └── retry.py         # 重试策略 (~100行)
│   ├── auth/
│   │   ├── oauth.py         # OAuth 核心 (~300行)
│   │   └── callback.py      # OAuth 回调 (~150行)
│   ├── tools/
│   │   ├── adapter.py       # MCP → AgentTool 适配 (~150行)
│   │   ├── loader.py        # 工具加载 (~200行)
│   │   └── wrapper.py       # Sandbox 工具包装 (~150行)
│   ├── registry.py          # MCP Server 注册 (~200行)
│   └── config.py            # MCP 配置 (~100行)
│
├── hotplug/                     # 热插拔系统 (新增)
│   ├── __init__.py
│   ├── events.py            # 变更事件定义 (~50行)
│   ├── notifier.py          # 变更通知器 (~100行)
│   ├── manager.py           # 热插拔管理器 (~200行)
│   └── health_monitor.py    # 健康监控 (~150行)
│
├── context/                     # 上下文管理系统 (重构后)
│   ├── __init__.py
│   ├── config.py            # 上下文配置 (~100行)
│   ├── token/
│   │   ├── estimator.py     # 统一 Token 估算器 (~150行)
│   │   ├── counter.py       # Token 计数器 (~100行)
│   │   └── cache.py         # Token 缓存 (~80行)
│   ├── window/
│   │   ├── manager.py       # 上下文窗口管理 (~300行)
│   │   ├── budgets.py       # Token 预算分配 (~100行)
│   │   └── splitter.py      # 消息分割 (~100行)
│   ├── compression/
│   │   ├── strategy.py      # 压缩策略接口 (~50行)
│   │   ├── truncation.py    # 截断策略 (~100行)
│   │   ├── summarization.py # 摘要策略 (~150行)
│   │   └── compaction.py    # 压实策略 (~150行)
│   ├── pruning/
│   │   ├── tool_output.py   # 工具输出裁剪 (~150行)
│   │   └── protected.py     # 保护列表管理 (~50行)
│   └── message/
│       ├── models.py        # 统一消息模型 (~150行)
│       └── builder.py       # 消息构建器 (~100行)
│
├── permission/              # 保持现有结构
├── doom_loop/               # 保持现有结构
├── retry/                   # 保持现有结构
├── cost/                    # 保持现有结构
├── hitl/                    # 保持现有结构
└── prompts/                 # 保持现有结构
```

---

## 📋 实施计划

### Phase 1: 组件解耦 - Processor 拆分

- [ ] 1.1 创建 `processor/` 目录结构
- [ ] 1.2 提取 `llm_handler.py` (LLM 调用逻辑)
- [ ] 1.3 提取 `tool_executor.py` (工具执行逻辑)
- [ ] 1.4 提取 `result_observer.py` (结果处理逻辑)
- [ ] 1.5 提取 `work_plan.py` (工作计划逻辑)
- [ ] 1.6 提取 `message_builder.py` (消息构建逻辑)
- [ ] 1.7 创建 `orchestrator.py` (协调器)
- [ ] 1.8 更新测试并验证功能

### Phase 1.5: 组件解耦 - ReActAgent 拆分

- [ ] 1.9 创建 `core/react_loop.py` (ReAct 循环核心)
- [ ] 1.10 提取 `subagent_delegator.py`
- [ ] 1.11 提取 `prompt_builder.py`
- [ ] 1.12 精简 `react_agent.py` 为主入口
- [ ] 1.13 更新测试并验证功能

### Phase 2: Skill 系统重构

- [ ] 2.1 创建 `skill/` 统一目录结构
- [ ] 2.2 简化 `domain/model/agent/skill.py` 为纯数据模型
- [ ] 2.3 提取 `skill/matcher.py` (匹配逻辑)
- [ ] 2.4 重构 `skill/executor.py` (执行逻辑)
- [ ] 2.5 合并 `skill_resource_loader.py` 到 `skill/loader.py`
- [ ] 2.6 简化 `skill/installer.py`
- [ ] 2.7 创建 `skill/registry.py` (注册中心)
- [ ] 2.8 创建 `skill/parser/` (SKILL.md 解析)
- [ ] 2.9 迁移 `skill_loader.py` 和 `skill_installer.py` 工具
- [ ] 2.10 更新测试并验证功能

### Phase 3: 工具系统统一

- [ ] 3.1 定义 `Tool` Protocol
- [ ] 3.2 创建 `ToolSchema` 和 `ToolResult` 数据类
- [ ] 3.3 实现 `ToolRegistry` 中心化注册
- [ ] 3.4 迁移现有工具到新接口
- [ ] 3.5 删除 `ToolDefinition` 旧抽象
- [ ] 3.6 更新所有工具使用方

### Phase 4: 热插拔系统

- [ ] 4.1 创建 `hotplug/events.py` 定义变更事件
- [ ] 4.2 创建 `hotplug/notifier.py` 实现发布/订阅
- [ ] 4.3 创建 `DynamicToolRegistry` 支持运行时注册/注销
- [ ] 4.4 创建 `MCPHotPlugManager` 实现 MCP 服务器热插拔
- [ ] 4.5 重构 `ReActAgent` 支持工具动态更新 (订阅变更)
- [ ] 4.6 添加版本号机制实现缓存失效
- [ ] 4.7 创建 `hotplug/health_monitor.py` 监控组件健康
- [ ] 4.8 集成 Skill 热加载/卸载
- [ ] 4.9 添加 WebSocket 推送工具变更通知到前端
- [ ] 4.10 更新测试并验证功能

### Phase 5: MCP 系统重构

- [ ] 5.1 创建 `mcp/protocol.py` 统一客户端协议
- [ ] 5.2 创建 `mcp/client/` 目录，定义 `MCPClient` 基类
- [ ] 5.3 重构 `http.py` 客户端 (从 663行 精简到 ~300行)
- [ ] 5.4 重构 `websocket.py` 客户端
- [ ] 5.5 重构 `subprocess.py` 客户端
- [ ] 5.6 创建 `mcp/client/factory.py` 客户端工厂
- [ ] 5.7 创建 `mcp/connection/manager.py` 连接池管理
- [ ] 5.8 重构 `mcp/auth/oauth.py` (从 595行 精简到 ~300行)
- [ ] 5.9 创建 `mcp/tools/` 工具适配层
- [ ] 5.10 迁移 `infrastructure/mcp/` 到 `agent/mcp/tools/`
- [ ] 5.11 重构 `adapters/secondary/temporal/mcp/` 为精简适配
- [ ] 5.12 更新测试并验证功能

### Phase 6: 事件系统重构

- [ ] 6.1 创建事件分层目录结构
- [ ] 6.2 实现 `EventBus` 事件总线
- [ ] 6.3 迁移现有事件到新结构
- [ ] 6.4 更新事件发布方代码
- [ ] 6.5 更新事件订阅方代码

### Phase 7: 配置外部化

- [ ] 7.1 创建 `config/` 目录
- [ ] 7.2 定义配置数据类 (含 ContextConfig)
- [ ] 7.3 迁移硬编码配置
- [ ] 7.4 支持环境变量覆盖

### Phase 8: 上下文管理系统重构

- [ ] 8.1 创建 `context/` 统一目录结构
- [ ] 8.2 创建 `context/token/estimator.py` 统一 Token 估算器 (含 CJK 支持)
- [ ] 8.3 创建 `context/token/cache.py` Token 缓存机制
- [ ] 8.4 提取 `context/compression/strategy.py` 压缩策略接口
- [ ] 8.5 实现 `TruncationCompressor` 截断压缩器
- [ ] 8.6 实现 `SummarizationCompressor` 摘要压缩器
- [ ] 8.7 提取 `context/pruning/tool_output.py` 工具输出裁剪
- [ ] 8.8 创建 `context/message/models.py` 统一消息模型 (消除重复定义)
- [ ] 8.9 重构 `context/window/manager.py` (从 660行 精简到 ~300行)
- [ ] 8.10 删除 `session/compaction.py` 中的重复定义，保留函数
- [ ] 8.11 迁移 `tools/truncation.py` 到 `context/compression/`
- [ ] 8.12 更新 `processor/` 集成新的上下文管理
- [ ] 8.13 更新测试并验证功能

### Phase 9: LLM Stream 简化

- [ ] 9.1 创建 `llm/` 目录结构
- [ ] 9.2 提取 JSON 解析到 `parsers/`
- [ ] 9.3 精简 `stream.py`
- [ ] 9.4 创建 Provider 适配层
- [ ] 9.5 更新测试

### Phase 10: 清理和文档

- [ ] 10.1 删除废弃代码 (project_react_agent.py 等)
- [ ] 10.2 更新 API 文档
- [ ] 10.3 更新架构文档
- [ ] 10.4 最终测试和验证

---

## 📊 预期收益

| 指标                   | 重构前            | 重构后             |
| ---------------------- | ----------------- | ------------------ |
| 最大单文件行数         | 2175              | < 500              |
| 核心组件数             | 3 (耦合)          | 20 (解耦)          |
| Skill 系统代码分布     | 4 个目录          | 1 个统一目录       |
| MCP 系统代码分布       | 3 个目录          | 1 个统一目录       |
| **上下文管理代码分布** | 4 个目录          | 1 个统一目录       |
| **热插拔能力**         | 无                | 完整支持           |
| ReAct 循环清晰度       | 低 (散落各处)     | 高 (react_loop.py) |
| 单元测试覆盖率         | ~60%              | > 85%              |
| 添加新工具复杂度       | 中                | 低 (运行时添加)    |
| 添加新 Skill 复杂度    | 高                | 低 (运行时添加)    |
| 添加新 MCP 客户端      | 高                | 低 (热插拔)        |
| **添加新压缩策略**     | 高 (修改 manager) | 低 (实现接口)      |

---

## ⚠️ 风险与缓解

| 风险                   | 影响 | 缓解措施                             |
| ---------------------- | ---- | ------------------------------------ |
| 大规模重构导致功能回归 | 高   | 渐进式重构，每个 Phase 独立验证      |
| 性能下降               | 中   | 保持关键路径的流式处理，增加性能测试 |
| 团队学习成本           | 中   | 详细文档，代码示例                   |
| 与现有代码集成困难     | 中   | 保持外部 API 稳定，内部渐进重构      |
| Token 估算精度变化     | 低   | 保持向后兼容，提供对比测试           |

---

## 📝 Notes

- 重构应遵循 DDD + 六边形架构原则
- 保持 ReAct 范式的简洁性: Think → Act → Observe 循环
- 每个 Phase 完成后进行代码审查
- 保持 80%+ 测试覆盖率
- 使用 Feature Flag 控制新旧实现切换
- 上下文管理重构优先级较高，直接影响 Agent 稳定性