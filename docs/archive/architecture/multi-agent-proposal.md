# MemStack Multi-Agent 架构方案

> 参考来源: [OpenClaw Multi-Agent 文档](https://docs.openclaw.ai/concepts/multi-agent) + OpenClaw 源码 (`~/github/openclaw`)
> 
> 日期: 2026-03-19

---

## 1. 现状分析

MemStack 已经具备相当完善的多智能体基础设施, 远超"从零开始"的程度。

### 1.1 已有的四层能力模型

```
┌─────────────────────────────────────────────┐
│  L4: Agent (ReAct 推理循环)                  │
│  - Agent entity + AgentRegistryPort          │
│  - SessionProcessor + ReActAgent             │
│  - AgentOrchestrator (lifecycle管理)          │
├─────────────────────────────────────────────┤
│  L3: SubAgent (专业化代理)                    │
│  - SubAgent entity + SubAgentRouter          │
│  - SubAgentSessionRunner                     │
│  - SubAgentToolBuilder (delegate/spawn/cancel)│
├─────────────────────────────────────────────┤
│  L2: Skill (声明式工具组合)                    │
│  - SkillOrchestrator + SkillExecutor         │
│  - Trigger: keyword / semantic / hybrid      │
├─────────────────────────────────────────────┤
│  L1: Tool (原子能力)                          │
│  - TerminalTool, WebSearchTool, PlanTool...  │
│  - SandboxMCPToolWrapper                     │
└─────────────────────────────────────────────┘
```

### 1.2 已有的多智能体组件

| 组件 | 文件 | 功能 |
|------|------|------|
| **Agent** 领域实体 | `domain/model/agent/agent_definition.py` | L4 顶层智能体: persona, bindings, workspace, 工具/技能/MCP 作用域, 生成能力 (`can_spawn`, `max_spawn_depth`, `agent_to_agent_enabled`) |
| **SubAgent** 领域实体 | `domain/model/agent/subagent.py` | L3 专业化智能体: 触发配置, allowed_tools/skills, 模型覆盖, 预定义模板 (researcher/coder/writer) |
| **AgentBinding** | `domain/model/agent/agent_binding.py` | 路由规则, 基于 specificity score 的确定性解析 (peer_id=8, account_id=4, channel_id=2, channel_type=1) + priority |
| **WorkspaceConfig** | `domain/model/agent/workspace_config.py` | 每 Agent 的工作区: 长期记忆, persona 文件, 共享文件, 构件存储 |
| **SpawnRecord** | `domain/model/agent/spawn_record.py` | 冻结的父-子关系记录 (parent_agent_id, child_agent_id, child_session_id, mode, status) |
| **SpawnMode** | `domain/model/agent/spawn_mode.py` | RUN (一次性) 或 SESSION (持久化) |
| **AgentMessageBusPort** | `domain/ports/services/agent_message_bus_port.py` | 抽象消息总线接口: REQUEST/RESPONSE/NOTIFICATION, 按 session 的 stream, 阻塞订阅, message threading |
| **AgentOrchestrator** | `infrastructure/agent/orchestration/orchestrator.py` | 协调中心: spawn_agent(), send_message(), stop_agent(), list_agents() |
| **SpawnManager** | `infrastructure/agent/orchestration/spawn_manager.py` | 父-子生命周期管理: register_spawn(), cascade_stop(), find_descendants(), depth 强制 (默认 max 5) |
| **AgentSessionRegistry** | `infrastructure/agent/orchestration/session_registry.py` | 内存中的 (project_id, conversation_id) -> AgentSession 映射 |
| **SubAgentSessionRunner** | `infrastructure/agent/core/subagent_runner.py` | 独立上下文运行 subagent session |
| **SubAgentToolBuilder** | `infrastructure/agent/core/subagent_tools.py` | 构建 delegate/spawn/cancel ToolDefinition |

### 1.3 与 OpenClaw 的映射关系

| 维度 | OpenClaw | MemStack 现状 | 差距 |
|------|----------|--------------|------|
| Agent 定义 | agentDir config | `Agent` entity + `AgentRegistryPort` | **已对齐** |
| Binding 路由 | 8级 specificity 解析 | `AgentBinding.specificity_score` | 需要 `AgentRouter` 服务 |
| Sub-agent 生成 | `subagent-spawn.ts` | `AgentOrchestrator.spawn_agent()` + `SpawnManager` | **已对齐** |
| 结果回传 (Announce) | `subagent-announce.ts` + queue | **缺失** | 需要 AnnounceService + 消息总线 |
| 角色化能力 | `subagent-capabilities.ts` (main/orchestrator/leaf) | 未实现 | 需要 AgentRoleResolver |
| 工具策略 | 8级优先级 | 扁平 `allowed_tools` 列表 | 需要 ToolPolicyResolver |
| 智能体间通信 | `callGateway()` RPC | `AgentMessageBusPort` (仅接口) | 需要 Redis 实现 |
| Session 管理 | 文件存储 | 内存 `AgentSessionRegistry` | 可能需要 Redis 持久化 |
| 工作区隔离 | per-agent agentDir | `WorkspaceConfig` | **已对齐** |
| Run Registry | `subagent-registry.ts` | `SubAgentRunRegistry` + `SpawnManager` | **已对齐** |

---

## 2. 需要新增的核心组件

### 2.1 概览

```
┌──────────────────────────────────────────────────────────────────┐
│                        新增组件 (6个)                             │
│                                                                  │
│  Domain Layer:                                                   │
│  ├─ AgentBindingResolver (纯函数, 路由评分)                       │
│  ├─ AgentRole + AgentRoleResolver (角色化能力)                    │
│  └─ AnnounceEvent (领域事件: child_completed/failed/cancelled)   │
│                                                                  │
│  Application Layer:                                              │
│  ├─ AgentRouterService (加载 bindings + 调用 Resolver)           │
│  └─ ToolPolicyResolver (分层策略组合)                             │
│                                                                  │
│  Infrastructure Layer:                                           │
│  └─ RedisAgentMessageBus (AgentMessageBusPort 的 Redis 实现)     │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 RedisAgentMessageBus (P0 - 最高优先级)

**为什么是 P0**: Oracle 审查确认, announce 是最可见的缺失功能, 但更深层的基础缺失是**持久化的智能体间消息传递 + 关联 (request/reply) + 投递语义**。如果不建立这个基础, announce 只会变成临时方案, 很快就要重写。

**设计原则**: 使用 Redis Streams (匹配现有事件管道模式), 支持 replay/consumer groups/backpressure, at-least-once 投递。

```
┌─────────────┐    Redis Stream     ┌─────────────┐
│ Child Actor  │──publish announce──>│ agent:bus:   │
│ (execution.py)│                    │ {session_addr}│
└─────────────┘                     └──────┬──────┘
                                           │ consume
                                    ┌──────▼──────┐
                                    │ Parent Actor │
                                    │ (inject as   │
                                    │  observation) │
                                    └─────────────┘
```

**领域层 (Port)**:

```python
# domain/ports/services/agent_message_bus_port.py (已有, 需扩展)
# 新增字段:
@dataclass
class AgentMessage:
    id: str
    message_type: AgentMessageType  # REQUEST / RESPONSE / NOTIFICATION
    sender_session_address: SessionAddress
    recipient_session_address: SessionAddress
    correlation_id: str | None = None      # 新增: request/reply 关联
    reply_to: SessionAddress | None = None  # 新增: 回复地址
    expires_at: datetime | None = None      # 新增: 消息过期
    idempotency_key: str | None = None      # 新增: 幂等键
    payload: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class SessionAddress:
    """智能体 session 的规范地址"""
    tenant_id: str
    project_id: str
    conversation_id: str
    agent_id: str | None = None  # 可选, 用于精确路由
```

**基础设施层 (Adapter)**:

```python
# infrastructure/agent/messaging/redis_message_bus.py (新增)
class RedisAgentMessageBus(AgentMessageBusPort):
    """
    基于 Redis Streams + Consumer Groups 的消息总线实现。
    
    Stream 命名: agent:bus:{tenant_id}:{project_id}:{conversation_id}
    Consumer Group: agent-bus-cg
    
    特性:
    - At-least-once 投递 (consumer group + ack)
    - 幂等处理 (idempotency_key 去重)
    - 消息过期 (expires_at 检查)
    - 背压 (XREADGROUP BLOCK + COUNT 限制)
    """
    
    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client
        self._processed_keys: set[str] = set()  # 幂等去重缓存
    
    async def send(self, message: AgentMessage) -> None:
        stream_key = self._stream_key(message.recipient_session_address)
        await self._redis.xadd(stream_key, message.to_dict())
    
    async def receive(
        self, 
        address: SessionAddress, 
        timeout_ms: int = 5000
    ) -> AgentMessage | None:
        stream_key = self._stream_key(address)
        # XREADGROUP with consumer group for at-least-once
        ...
    
    async def subscribe(
        self, 
        address: SessionAddress, 
        callback: Callable[[AgentMessage], Awaitable[None]]
    ) -> None:
        # 持续消费循环, 在 safe checkpoint 处理消息
        ...
```

**Announce 事件 (作为 NOTIFICATION 类型的 AgentMessage)**:

```python
# domain/events/agent_events.py (扩展)
@dataclass
class AgentAnnounceEvent:
    """子智能体完成时发送给父智能体的通知"""
    spawn_record_id: str
    child_session_id: str
    child_agent_id: str
    status: Literal["completed", "failed", "cancelled"]
    summary: str                      # 结果摘要
    artifact_refs: list[str] = field(default_factory=list)  # 可选的构件引用
    error: str | None = None          # 失败时的错误信息
```

**集成点 (execution.py 中的 child actor)**:

```python
# infrastructure/agent/actor/execution.py (修改)
# 在 child agent session 完成时:
async def _on_session_complete(
    self, 
    spawn_record: SpawnRecord, 
    result: SessionResult
) -> None:
    announce = AgentMessage(
        message_type=AgentMessageType.NOTIFICATION,
        sender_session_address=SessionAddress(
            tenant_id=spawn_record.tenant_id,
            project_id=spawn_record.project_id,
            conversation_id=spawn_record.child_session_id,
            agent_id=spawn_record.child_agent_id,
        ),
        recipient_session_address=SessionAddress(
            tenant_id=spawn_record.tenant_id,
            project_id=spawn_record.project_id,
            conversation_id=spawn_record.parent_conversation_id,
            agent_id=spawn_record.parent_agent_id,
        ),
        correlation_id=spawn_record.id,
        payload=AgentAnnounceEvent(
            spawn_record_id=spawn_record.id,
            child_session_id=spawn_record.child_session_id,
            child_agent_id=spawn_record.child_agent_id,
            status="completed",
            summary=result.summary,
        ).to_dict(),
    )
    await self._message_bus.send(announce)
```

**父 actor 消费端 (SessionProcessor 集成)**:

```python
# infrastructure/agent/processor/processor.py (修改)
# 在 ReAct 循环的 safe checkpoint (tool 执行完毕后) 检查 announce 队列:
async def _check_announcements(self) -> list[AgentAnnounceEvent]:
    """在安全检查点消费子智能体的 announce 消息"""
    messages = await self._message_bus.drain(
        address=self._session_address,
        message_type=AgentMessageType.NOTIFICATION,
        max_count=10,
    )
    for msg in messages:
        if msg.idempotency_key in self._processed_announces:
            continue
        self._processed_announces.add(msg.idempotency_key)
        # 注入为 observation (系统消息), 不打断当前 tool 执行
        self._inject_observation(
            f"[SubAgent Result] {msg.payload['summary']}"
        )
    return messages
```

**关键设计决策** (来自 Oracle 审查):
- **不要打断父 agent 的当前 tool 执行** — 将 announce 放入输入缓冲区, 在 safe checkpoint 处理
- **需要幂等处理** — Streams 是 at-least-once, 必须用 `correlation_id` + 幂等 apply
- **规范地址格式** — 定义 `SessionAddress(tenant_id, project_id, conversation_id)` 作为唯一规范地址, 子→父路由永远不猜测

### 2.3 AgentBindingResolver + AgentRouterService (P0)

**设计原则**: 将 binding 评分/匹配作为**领域纯函数** (无外部依赖), 将加载 bindings + 选择目标的逻辑放在**应用服务**中。

**为什么分两层**: Oracle 确认, binding resolution 是纯业务逻辑, 应该在 domain 层; 而加载 bindings 需要访问 repository, 必须在 application 层。

**领域层 (纯函数)**:

```python
# domain/services/agent_binding_resolver.py (新增)
class AgentBindingResolver:
    """
    纯函数: 评估一组 AgentBinding 候选项, 返回最佳匹配。
    
    基于 OpenClaw 的 specificity resolution:
    - peer_id 匹配 → 权重 8
    - account_id 匹配 → 权重 4
    - channel_id 匹配 → 权重 2
    - channel_type 匹配 → 权重 1
    - 同 specificity 时按 priority 排序
    
    无外部依赖, 可直接单元测试。
    """
    
    @staticmethod
    def resolve(
        bindings: list[AgentBinding],
        context: RoutingContext,
    ) -> AgentBinding | None:
        scored = []
        for binding in bindings:
            score = binding.compute_specificity_score(context)
            if score >= 0:
                scored.append((score, binding.priority, binding))
        if not scored:
            return None
        # 最高 specificity 优先, 同 specificity 按 priority 降序
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return scored[0][2]

@dataclass(frozen=True)
class RoutingContext:
    """路由请求的上下文"""
    tenant_id: str
    project_id: str
    channel_type: str | None = None
    channel_id: str | None = None
    account_id: str | None = None
    peer_id: str | None = None
```

**应用层 (Service)**:

```python
# application/services/agent_router_service.py (新增)
class AgentRouterService:
    """
    应用服务: 加载候选 bindings, 调用 Resolver, 返回目标 Agent。
    """
    
    def __init__(
        self,
        agent_registry: AgentRegistryPort,
        binding_resolver: AgentBindingResolver,
    ) -> None:
        self._agent_registry = agent_registry
        self._resolver = binding_resolver
    
    async def route(
        self, 
        context: RoutingContext,
    ) -> Agent | None:
        bindings = await self._agent_registry.list_bindings(
            tenant_id=context.tenant_id,
            project_id=context.project_id,
        )
        matched = self._resolver.resolve(bindings, context)
        if not matched:
            return None
        return await self._agent_registry.find_by_id(matched.agent_id)
```

### 2.4 ToolPolicyResolver (P1)

**设计原则**: 起步 3 层 (agent → subagent → sandbox), 但实现为**通用优先级链** (策略源列表), 后续添加层级不需要重写调用方。

Oracle 确认: 3 层对于第一迭代足够, 关键是数据结构要可扩展。

```python
# application/services/tool_policy_resolver.py (新增)
@dataclass(frozen=True)
class ToolPolicy:
    """一个策略源的工具访问规则"""
    source: str                  # "agent" / "subagent" / "sandbox" / future layers
    precedence: int              # 越高越优先
    allowed: set[str] | None     # None = 不限制, {"*"} = 全部允许
    denied: set[str]             # 显式拒绝列表
    
class ToolPolicyResolver:
    """
    分层工具策略解析器。
    
    策略按 precedence 降序评估。
    对每个 tool_name:
    1. 从最高优先级开始
    2. 如果在 denied → 拒绝 (无论其他层)
    3. 如果 allowed 非 None 且 tool 不在其中 → 拒绝
    4. 所有层通过 → 允许
    
    V1 层级 (可通过 register_policy_source 扩展):
    - sandbox (precedence=10): 沙箱级限制
    - agent (precedence=20): Agent 实体的 allowed_tools
    - subagent (precedence=30): SubAgent 的 allowed_tools (最高优先级)
    """
    
    def __init__(self) -> None:
        self._policies: list[ToolPolicy] = []
    
    def register_policy(self, policy: ToolPolicy) -> None:
        self._policies.append(policy)
        self._policies.sort(key=lambda p: p.precedence, reverse=True)
    
    def is_allowed(self, tool_name: str) -> bool:
        for policy in self._policies:
            if tool_name in policy.denied:
                return False
            if policy.allowed is not None and tool_name not in policy.allowed:
                if "*" not in policy.allowed:
                    return False
        return True
    
    def filter_tools(self, tool_names: list[str]) -> list[str]:
        return [t for t in tool_names if self.is_allowed(t)]
```

### 2.5 AgentRole + AgentRoleResolver (P1)

**参考 OpenClaw**: `subagent-capabilities.ts` 定义了基于 depth 的角色:
- `main` (depth=0): 完整能力, 可以 spawn + 控制所有子代
- `orchestrator` (depth=1..n-1): 可以 spawn, 只控制自己的直接子代
- `leaf` (depth=max): 不能 spawn, 只执行

```python
# domain/model/agent/agent_role.py (新增)
from enum import Enum

class AgentRole(str, Enum):
    MAIN = "main"              # depth=0, 完整能力
    ORCHESTRATOR = "orchestrator"  # 中间层, 可 spawn
    LEAF = "leaf"              # 最深层, 只执行

@dataclass(frozen=True)
class RoleCapabilities:
    """角色对应的能力集"""
    can_spawn: bool
    can_control_children: bool     # list/steer/kill
    can_control_siblings: bool     # 仅 main 可以
    max_concurrent_children: int
    denied_tools: frozenset[str]   # 该角色不能使用的工具

# 默认配置
ROLE_DEFAULTS: dict[AgentRole, RoleCapabilities] = {
    AgentRole.MAIN: RoleCapabilities(
        can_spawn=True,
        can_control_children=True,
        can_control_siblings=False,
        max_concurrent_children=8,
        denied_tools=frozenset(),
    ),
    AgentRole.ORCHESTRATOR: RoleCapabilities(
        can_spawn=True,
        can_control_children=True,
        can_control_siblings=False,
        max_concurrent_children=5,
        denied_tools=frozenset(),
    ),
    AgentRole.LEAF: RoleCapabilities(
        can_spawn=False,
        can_control_children=False,
        can_control_siblings=False,
        max_concurrent_children=0,
        denied_tools=frozenset({"spawn_agent", "delegate_to_subagent"}),
    ),
}

class AgentRoleResolver:
    """根据 spawn depth 确定角色"""
    
    @staticmethod
    def resolve(depth: int, max_depth: int) -> AgentRole:
        if depth == 0:
            return AgentRole.MAIN
        if depth >= max_depth:
            return AgentRole.LEAF
        return AgentRole.ORCHESTRATOR
```

### 2.6 Sandbox Scoping (P2)

OpenClaw 支持三种沙箱隔离模式:
- `session`: 每个会话独立沙箱
- `agent`: 同一 agent 的所有会话共享沙箱
- `shared`: 所有 agent 共享沙箱

```python
# domain/model/agent/sandbox_scope.py (新增)
from enum import Enum

class SandboxScope(str, Enum):
    SESSION = "session"    # 每 session 独立 (最严格)
    AGENT = "agent"        # 同 agent 共享 (默认)
    SHARED = "shared"      # 全部共享 (最宽松)
```

修改 `WorkspaceConfig` 增加 `sandbox_scope: SandboxScope = SandboxScope.AGENT`。

---

## 3. 整体架构图

```
                    ┌─────────────────────────────┐
                    │      Inbound Request         │
                    │  (WebSocket / HTTP / MCP)    │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │    AgentRouterService         │
                    │  (RoutingContext → Agent)     │
                    │  ├─ Load AgentBindings       │
                    │  └─ AgentBindingResolver     │
                    │     (specificity scoring)    │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │    AgentOrchestrator          │
                    │  (lifecycle + coordination)   │
                    │  ├─ spawn_agent()            │
                    │  ├─ send_message()           │
                    │  └─ stop_agent()             │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
   ┌──────────▼─────┐  ┌──────▼──────┐  ┌──────▼──────┐
   │  Parent Agent   │  │  Child A    │  │  Child B    │
   │  (Ray Actor)    │  │  (Ray Actor)│  │  (Ray Actor)│
   │                 │  │             │  │             │
   │ SessionProcessor│  │ Session-    │  │ Session-    │
   │  ├─ ReAct Loop  │  │ Processor   │  │ Processor   │
   │  ├─ Tool Exec   │  │             │  │             │
   │  ├─ Announce    │  │             │  │             │
   │  │  Consumer    │  │             │  │             │
   │  └─ ToolPolicy  │  │             │  │             │
   │     Resolver    │  │             │  │             │
   └────────▲────────┘  └──────┬──────┘  └──────┬──────┘
            │                  │                 │
            │           ┌──────▼─────────────────▼──────┐
            │           │     RedisAgentMessageBus       │
            └───────────│  (Redis Streams + Consumer     │
                        │   Groups, at-least-once)       │
                        │                                │
                        │  Streams:                      │
                        │  agent:bus:{tenant}:{project}: │
                        │  {conversation_id}             │
                        │                                │
                        │  Features:                     │
                        │  - correlation_id              │
                        │  - idempotency_key             │
                        │  - expires_at                  │
                        │  - REQUEST/RESPONSE/NOTIFICATION│
                        └────────────────────────────────┘
```

### 3.1 Announce 完整流程

```
1. Parent Agent 通过 spawn_agent() 创建 Child
   → SpawnManager.register_spawn() 记录 SpawnRecord
   → Child Ray Actor 启动

2. Child Agent 执行任务 (独立 SessionProcessor)
   → 独立的 ReAct 循环
   → 独立的工具集 (经 ToolPolicyResolver 过滤)

3. Child 完成/失败/取消
   → execution.py 中 publish AgentAnnounceEvent
   → 通过 RedisAgentMessageBus.send() 发送到 parent stream
   → SpawnRecord.status 更新

4. Parent 在 safe checkpoint 消费
   → SessionProcessor._check_announcements()
   → 幂等去重 (correlation_id)
   → 注入为 observation (不打断当前 tool 执行)
   → Parent LLM 在下一轮 Think 中看到结果

5. Parent 可选择:
   → 汇总结果, 继续推理
   → spawn 新的 child
   → 直接回复用户
```

### 3.2 工具策略解析流程

```
请求: "Agent X 的 SubAgent Y 在 Sandbox Z 中能用 tool T 吗?"

┌─────────────────┐
│ ToolPolicyResolver│
│                   │
│ 1. Sandbox Policy │  precedence=10
│    denied: [rm]   │  → tool T 不在 denied → pass
│                   │
│ 2. Agent Policy   │  precedence=20
│    allowed: [*]   │  → wildcard → pass
│                   │
│ 3. SubAgent Policy│  precedence=30
│    allowed: [a,b] │  → tool T 不在列表 → DENIED
│                   │
│ Result: DENIED    │
└─────────────────┘
```

---

## 4. 领域模型变更总结

### 4.1 新增实体/值对象

| 类型 | 名称 | 位置 | 说明 |
|------|------|------|------|
| Value Object | `SessionAddress` | `domain/model/agent/` | 规范的 session 地址 (tenant_id, project_id, conversation_id) |
| Value Object | `RoutingContext` | `domain/model/agent/` | 路由请求上下文 |
| Enum | `AgentRole` | `domain/model/agent/agent_role.py` | MAIN / ORCHESTRATOR / LEAF |
| Value Object | `RoleCapabilities` | `domain/model/agent/agent_role.py` | 角色对应的能力集 |
| Enum | `SandboxScope` | `domain/model/agent/sandbox_scope.py` | SESSION / AGENT / SHARED |
| Domain Event | `AgentAnnounceEvent` | `domain/events/agent_events.py` | 子智能体完成通知 |

### 4.2 修改现有实体

| 实体 | 修改 | 说明 |
|------|------|------|
| `AgentMessage` | 新增 `correlation_id`, `reply_to`, `expires_at`, `idempotency_key` | 支持 request/reply 关联和幂等 |
| `WorkspaceConfig` | 新增 `sandbox_scope: SandboxScope` | 沙箱隔离模式 |
| `AgentEventType` | 新增 `ANNOUNCE_RECEIVED`, `ANNOUNCE_SENT` | 事件类型枚举扩展 |

### 4.3 新增领域服务

| 服务 | 位置 | 说明 |
|------|------|------|
| `AgentBindingResolver` | `domain/services/` | 纯函数, binding 评分逻辑 |
| `AgentRoleResolver` | `domain/services/` | 纯函数, depth → role 映射 |

### 4.4 新增应用服务

| 服务 | 位置 | 说明 |
|------|------|------|
| `AgentRouterService` | `application/services/` | 加载 bindings + 调用 Resolver |
| `ToolPolicyResolver` | `application/services/` | 分层工具策略组合 |

### 4.5 新增基础设施组件

| 组件 | 位置 | 说明 |
|------|------|------|
| `RedisAgentMessageBus` | `infrastructure/agent/messaging/` | `AgentMessageBusPort` 的 Redis Streams 实现 |

---

## 5. 与现有代码的集成点

### 5.1 需修改的现有文件

| 文件 | 修改内容 | 影响范围 |
|------|----------|----------|
| `domain/ports/services/agent_message_bus_port.py` | 扩展 `AgentMessage` 字段 (correlation_id, reply_to, expires_at, idempotency_key); 新增 `SessionAddress` | Port 接口变更, 所有实现需同步 |
| `domain/events/agent_events.py` | 新增 `AgentAnnounceEvent` | 事件系统扩展 |
| `domain/events/types.py` | 新增 `ANNOUNCE_RECEIVED`, `ANNOUNCE_SENT` 到 `AgentEventType` | 枚举扩展 |
| `domain/model/agent/workspace_config.py` | 新增 `sandbox_scope` 字段 | 可选字段, 向后兼容 |
| `infrastructure/agent/actor/execution.py` | child 完成时 publish announce | 关键集成点 |
| `infrastructure/agent/processor/processor.py` | ReAct 循环中增加 announce 消费检查点 | 关键集成点 |
| `infrastructure/agent/orchestration/orchestrator.py` | 集成 AgentRouterService, 在 spawn 时设置 role | 协调层扩展 |
| `infrastructure/agent/core/subagent_tools.py` | 基于 AgentRole 过滤可用工具 | 工具构建扩展 |
| `configuration/di_container.py` | 注册新服务 (RedisAgentMessageBus, AgentRouterService, ToolPolicyResolver) | DI 容器扩展 |

### 5.2 关键约束

> 来自项目 AGENTS.md, **必须遵守**:

1. **Domain 层禁止 infrastructure 导入** — `AgentBindingResolver` 和 `AgentRoleResolver` 必须是纯函数, 不依赖 SQLAlchemy/Redis/FastAPI
2. **不要在非 actor 代码中导入 actor/** — announce publish 必须在 actor 内部完成
3. **不要绕过 EventConverter** — announce 事件必须通过标准的 SSE 事件管道
4. **ToolDefinition wrapping** — 访问 tool 实例方法时必须用 `tool_def._tool_instance`

---

## 6. 分阶段实施计划

### Phase 0 (P0): 消息总线 + Announce + 路由 — 预计 2-3 天

**目标**: 建立多智能体通信基础, 让子智能体的结果能可靠回传给父智能体。

| 步骤 | 任务 | 预计耗时 |
|------|------|----------|
| 0.1 | 扩展 `AgentMessage` (correlation_id, reply_to, expires_at, idempotency_key) + 新增 `SessionAddress` | 2h |
| 0.2 | 实现 `RedisAgentMessageBus` (send/receive/subscribe/drain) + 单元测试 | 8h |
| 0.3 | 新增 `AgentAnnounceEvent` 领域事件 | 1h |
| 0.4 | 修改 `execution.py`: child 完成时 publish announce | 4h |
| 0.5 | 修改 `SessionProcessor`: safe checkpoint 消费 announce | 4h |
| 0.6 | 实现 `AgentBindingResolver` (纯函数) + 单元测试 | 2h |
| 0.7 | 实现 `AgentRouterService` (应用服务) + 集成测试 | 2h |
| 0.8 | DI 容器注册 + 端到端测试 | 2h |

**验收标准**:
- [ ] Parent spawn child → child 执行完 → parent 收到 announce → parent 在下一轮 Think 中看到结果
- [ ] 幂等: 重复 announce 不会导致重复处理
- [ ] 超时: child 超时 → announce status=failed
- [ ] 路由: 给定 RoutingContext, AgentRouterService 返回正确的 Agent

### Phase 1 (P1): 角色化能力 + 工具策略 — 预计 1-2 天

**目标**: 按 depth 限制能力, 分层管控工具访问。

| 步骤 | 任务 | 预计耗时 |
|------|------|----------|
| 1.1 | 新增 `AgentRole` + `RoleCapabilities` + `AgentRoleResolver` | 2h |
| 1.2 | 实现 `ToolPolicyResolver` (通用优先级链) | 4h |
| 1.3 | 修改 `SubAgentToolBuilder`: 基于 role 过滤工具 | 2h |
| 1.4 | 修改 `AgentOrchestrator.spawn_agent()`: 设置 child role | 2h |
| 1.5 | 超时 + 取消传播: parent cancel → child 定期检查 → announce "cancelled" | 4h |
| 1.6 | 单元测试 + 集成测试 | 2h |

**验收标准**:
- [ ] depth=0 → MAIN, depth=max → LEAF, 中间 → ORCHESTRATOR
- [ ] LEAF agent 无法使用 spawn_agent 工具
- [ ] ToolPolicyResolver 正确合成 3 层策略
- [ ] Parent cancel → child 终止 → announce status=cancelled

### Phase 2 (P2): 沙箱隔离 + 高级特性 — 预计 2-3 天

**目标**: 精细化沙箱隔离, 完善生产级可靠性。

| 步骤 | 任务 | 预计耗时 |
|------|------|----------|
| 2.1 | 新增 `SandboxScope` + 修改 `WorkspaceConfig` | 1h |
| 2.2 | 实现 sandbox scoping (session/agent/shared) | 4h |
| 2.3 | AgentSessionRegistry Redis 持久化 (可选) | 4h |
| 2.4 | 分布式 tracing: spawn chain 可视化 | 4h |
| 2.5 | Policy 调试 UI: "为什么这个 tool 被拒绝了?" | 4h |

---

## 7. 风险与注意事项

### 7.1 架构风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| **重复投递** | Streams 是 at-least-once, parent 可能收到重复 announce | idempotency_key + 已处理集合去重 |
| **父 agent 繁忙/重入** | announce 到达时 parent 正在执行 tool, 直接注入会破坏状态 | 放入输入缓冲区, 只在 safe checkpoint (tool 完成后) 处理 |
| **Ray Actor 隔离** | actor 代码在 Docker 容器中, 本地代码修改不生效 | 开发时用 `make ray-up-dev` 实现实时代码加载 |
| **内存 SessionRegistry** | agent 崩溃后丢失 session 映射 | P2 阶段迁移到 Redis 持久化 |

### 7.2 OpenClaw 模式的适配注意

| OpenClaw 模式 | 适配方案 |
|---------------|----------|
| Gateway RPC (`callGateway()`) | 映射为 `RedisAgentMessageBus` 的 REQUEST/RESPONSE (异步, 非同步 RPC) |
| 文件存储 Session Store | MemStack 用内存 Registry + DB 持久化, 不需要文件存储 |
| ACP Agents (外部编码运行时) | 暂不实现, 可通过 MCP 协议桥接外部 agent (已有 MCPServer/MCPTool 基础设施) |
| WebSocket 直连 | MemStack 已有 WebSocket → Redis Stream → SSE 管道, announce 事件复用此管道推送到前端 |

### 7.3 不建议实现的 OpenClaw 模式

| 模式 | 原因 |
|------|------|
| 8 级工具策略 | 过度设计, 3 层 + 可扩展链已满足需求 |
| parentPeer / guildId+roles 路由 | MemStack 的 tenant 模型更简洁, 不需要 guild/team 层级 |
| 文件系统 session 存储 | MemStack 用 DB + 内存, 性能更好 |

---

## 8. 总结

MemStack 的多智能体基础设施已经建设了约 **70%**, 领域模型和生命周期管理特别完善。剩余工作集中在三个核心缺口:

1. **P0 — 消息总线 + Announce** (最关键): `RedisAgentMessageBus` + 子→父结果回传机制。这是让 spawn 出的子智能体能够真正"汇报"的基础。
2. **P0 — 路由服务**: `AgentBindingResolver` + `AgentRouterService`。让 binding 规则真正生效。
3. **P1 — 角色与策略**: `AgentRoleResolver` + `ToolPolicyResolver`。精细化能力管控。

按此方案实施后, MemStack 将拥有与 OpenClaw 对等的多智能体能力, 同时保持 DDD + 六边形架构的整洁性和 Python 异步生态的优势。
