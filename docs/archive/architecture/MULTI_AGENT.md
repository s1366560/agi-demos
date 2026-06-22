# Multi-Agent Architecture Proposal

> **Status**: Draft  
> **Author**: Architecture Review  
> **Date**: 2026-03-17  
> **References**: [OpenClaw Multi-Agent Docs](https://docs.openclaw.ai/concepts/multi-agent), `~/github/openclaw` source code

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Analysis](#2-current-state-analysis)
3. [OpenClaw Reference Architecture](#3-openclaw-reference-architecture)
4. [Gap Analysis](#4-gap-analysis)
5. [Proposed Multi-Agent Architecture](#5-proposed-multi-agent-architecture)
6. [Domain Model Changes](#6-domain-model-changes)
7. [Infrastructure Changes](#7-infrastructure-changes)
8. [Event Pipeline for Multi-Agent](#8-event-pipeline-for-multi-agent)
9. [Agent Communication Protocol](#9-agent-communication-protocol)
10. [Routing & Binding System](#10-routing--binding-system)
11. [Configuration Model](#11-configuration-model)
12. [Migration Plan](#12-migration-plan)
13. [Risk Assessment](#13-risk-assessment)

---

## 1. Executive Summary

MemStack already has a robust **SubAgent system** (L3 layer) with parallel execution, background tasks, context bridging, and run lifecycle management. However, it lacks **true multi-agent orchestration** where multiple fully-autonomous agents collaborate with isolated workspaces, explicit inter-agent communication, and deterministic routing.

This proposal introduces a **Multi-Agent Orchestration Layer** (L5) on top of the existing four-layer capability model, inspired by OpenClaw's proven patterns but adapted to MemStack's DDD + Hexagonal architecture.

**Key design principles:**
- **Isolation by default**: Each agent has its own workspace, persona, model, session store, and tool set
- **Explicit communication**: Agents communicate through well-defined protocols (spawn, message, announce), not shared state
- **Deterministic routing**: Channel messages are routed to agents via a binding system with "most-specific wins" priority
- **Backward compatible**: The existing L1-L4 architecture continues to work unchanged; multi-agent is an opt-in layer

**Capability model after this proposal:**

```
Tool (L1) -> Skill (L2) -> SubAgent (L3) -> Agent (L4) -> Multi-Agent Orchestration (L5)
```

---

## 2. Current State Analysis

### 2.1 What MemStack Already Has

#### Four-Layer Capability Model (L1-L4)

| Layer | Implementation | Key Files |
|-------|---------------|-----------|
| **L1: Tool** | 40+ tools: terminal, desktop, MCP, web, env, todo, skills | `src/infrastructure/agent/tools/` |
| **L2: Skill** | Declarative markdown skills, keyword/semantic/hybrid triggers | `src/infrastructure/agent/skill/orchestrator.py` |
| **L3: SubAgent** | Specialized agents with isolated SessionProcessor, filtered tools, run lifecycle | `src/infrastructure/agent/subagent/` (20 files) |
| **L4: Agent** | ReAct reasoning loop, session processor, event emission | `src/infrastructure/agent/core/react_agent.py` |

#### SubAgent System (L3) -- Detailed

The existing SubAgent system is substantial and provides many building blocks for multi-agent:

| Component | File | Responsibility |
|-----------|------|---------------|
| `SubAgentProcess` | `subagent/process.py` | Isolated ReAct loop per SubAgent, retries, doom-loop detection |
| `SubAgentSessionRunner` | `core/subagent_runner.py` | Lifecycle management, parallel/chain/background execution |
| `SubAgentRouter` | `core/subagent_router.py` | Semantic + keyword matching to route queries to SubAgents |
| `SubAgentToolBuilder` | `core/subagent_tools.py` | Inject nested delegate/spawn/cancel tools |
| `ContextBridge` | `subagent/context_bridge.py` | Condense parent context, token budget, memory injection |
| `ParallelScheduler` | `subagent/parallel_scheduler.py` | Concurrent SubAgent execution |
| `BackgroundExecutor` | `subagent/background_executor.py` | Async background SubAgent tasks |
| `RunRegistry` | `subagent/run_registry.py` | Track active SubAgent runs with limits |
| `ResultAggregator` | `subagent/result_aggregator.py` | Combine results from multiple SubAgents |
| `TaskDecomposer` | `subagent/task_decomposer.py` | Break complex tasks into SubAgent-sized chunks |
| `StateTracker` | `subagent/state_tracker.py` | Track SubAgent execution state |
| `TemplateRegistry` | `subagent/template_registry.py` | Predefined SubAgent templates |
| `ChainExecutor` | `subagent/chain.py` | Sequential SubAgent chain execution |

#### Channel System

| Component | File | Responsibility |
|-----------|------|---------------|
| `ChannelRouter` | `channels/channel_router.py` | Routes channel messages to conversations via channel_id -> conversation_id mapping |
| `TransportChannelAdapter` | `channels/channel_adapter.py` | Abstract adapter interface for channels |
| `RESTApiAdapter` | `channels/rest_api_adapter.py` | REST API channel |
| `WebSocketAdapter` | `channels/websocket_adapter.py` | WebSocket channel |

#### Agent Pool Architecture

Three-tier (HOT/WARM/COLD) agent pooling with lifecycle management, health monitoring, circuit breaker, auto-scaling, and state recovery.

#### Domain Model (SubAgent Entity)

```python
@dataclass
class SubAgent:
    id: str
    tenant_id: str
    name: str                      # Unique name for routing
    display_name: str
    system_prompt: str             # Custom persona
    trigger: AgentTrigger          # When to activate (description + examples + keywords)
    model: AgentModel              # LLM model (or INHERIT from parent)
    allowed_tools: list[str]       # Tool whitelist (["*"] = all)
    allowed_skills: list[str]      # Skill whitelist
    allowed_mcp_servers: list[str] # MCP server whitelist
    max_tokens: int
    temperature: float
    max_iterations: int
    enabled: bool
    project_id: str | None         # Optional project scoping
    source: SubAgentSource         # DATABASE | FILESYSTEM | BUILTIN
    max_retries: int
    fallback_models: list[str]
```

#### Existing Environment Variables for SubAgent Tuning

```
AGENT_SUBAGENT_MAX_DELEGATION_DEPTH
AGENT_SUBAGENT_MAX_ACTIVE_RUNS
AGENT_SUBAGENT_MAX_CHILDREN_PER_REQUESTER
AGENT_SUBAGENT_LANE_CONCURRENCY
AGENT_SUBAGENT_TERMINAL_RETENTION_SECONDS
AGENT_SUBAGENT_ANNOUNCE_MAX_RETRIES
AGENT_SUBAGENT_ANNOUNCE_RETRY_DELAY_MS
AGENT_SUBAGENT_FOCUS_TTL_SECONDS
```

### 2.2 Event Pipeline (Current)

```
Tool.execute()
  -> _pending_events / ToolContext.emit()
    -> SessionProcessor._emit_tool_side_effects()
      -> AgentDomainEvent subclasses
        -> EventConverter.convert() -> SSE dict
          -> Actor: publish to Redis Stream (agent:events:{conversation_id})
            -> agent_service.connect_chat_stream() reads Redis
              -> WebSocket/SSE to frontend
```

All events are scoped to a single `conversation_id`. No support for multi-agent event multiplexing.

---

## 3. OpenClaw Reference Architecture

### 3.1 Core Abstractions

| Concept | Description |
|---------|-------------|
| **Agent** | Fully scoped entity with own `agentId`, `agentDir` (workspace), persona, model, session store |
| **Account** | User identity (`accountId`) that can interact with agents |
| **Binding** | Routing rule: `(channel, accountId, peer)` -> `agentId` with most-specific-wins priority |
| **Sub-Agent** | Agent spawned by another agent for delegation; parent-child hierarchy |
| **Workspace** | Per-agent isolated file directory (`agentDir`) serving as long-term memory |

### 3.2 Agent Isolation Model

- **Memory isolation**: Agents do NOT share chat history by default
- **Tool isolation**: Each agent defines its own tool set
- **Auth isolation**: Per-agent auth profiles; sharing requires manual copy
- **Workspace isolation**: Each agent has its own `agentDir` for files
- **Context injection**: `AGENTS.md`, `SOUL.md`, `USER.md` injected per-agent

### 3.3 Routing System

OpenClaw uses **deterministic "most-specific wins"** routing:

```
Priority (high to low):
1. Peer-specific binding     (channel + accountId + peer -> agentId)
2. Parent peer binding       (channel + accountId + parentPeer -> agentId)
3. Account-specific binding  (channel + accountId -> agentId)
4. Channel-wide binding      (channel -> agentId)
5. Default agent             (system default)
```

### 3.4 Communication Patterns

| Pattern | Mechanism | Use Case |
|---------|-----------|----------|
| **Channel Routing** | Binding system | External message -> specific agent |
| **Sub-Agent Spawning** | `sessions_spawn` tool | Parent delegates task to child |
| **Agent-to-Agent Messaging** | `sessions_send` tool (opt-in) | Peer agents exchange messages |

### 3.5 Sub-Agent Spawning (`sessions_spawn`)

```
Parameters:
  - agentId: target agent to spawn
  - mode: "run" (one-shot) | "session" (persistent)
  - message: task description
  - maxSpawnDepth: nesting limit (e.g., 2)

Lifecycle:
  1. Parent calls sessions_spawn(agentId, message, mode)
  2. Child agent executes in isolation
  3. Child "announces" result back to parent (configurable announce step)
  4. Parent receives result and continues

Control:
  - Cascade stop: stopping parent aborts all children
  - Nesting depth: maxSpawnDepth prevents infinite recursion
  - Discovery: agents_list tool lets agents discover available peers
```

### 3.6 Session Tools

| Tool | Purpose |
|------|---------|
| `sessions_spawn` | Spawn a sub-agent to handle a delegated task |
| `sessions_list` | List active sessions (own or children) |
| `sessions_history` | Read a session's message history |
| `sessions_send` | Send a message to another agent's session |
| `agents_list` | Discover available agents |

---

## 4. Gap Analysis

### What MemStack Has vs. What Multi-Agent Needs

| Capability | MemStack Current | OpenClaw Reference | Gap |
|-----------|-----------------|-------------------|-----|
| **Agent as entity** | SubAgent (L3) -- specialized worker | Agent -- fully autonomous entity with workspace | SubAgent lacks workspace isolation, is treated as "worker" not "peer" |
| **Agent isolation** | Filtered tools, separate SessionProcessor | Full workspace, persona, model, session store, auth | Missing: workspace dir, auth profile, session store per agent |
| **Routing** | SubAgentRouter (semantic matching) | Binding system (deterministic, most-specific-wins) | Missing: Binding entity, priority-based routing, channel-to-agent mapping |
| **Spawning** | SubAgentSessionRunner.launch_subagent_session() | `sessions_spawn` tool with run/session modes | Partial: exists but lacks persistent session mode, announce step |
| **Agent-to-Agent** | Not supported | `sessions_send` (opt-in) | Missing entirely |
| **Agent discovery** | SubAgent templates loaded at init | `agents_list` tool for runtime discovery | Missing: runtime agent discovery tool |
| **Session management** | Per-conversation (conversation_id) | Per-agent session store with history | Missing: agent-scoped session isolation |
| **Nesting control** | `MAX_DELEGATION_DEPTH` env var | `maxSpawnDepth` per spawn call | Exists but less granular |
| **Event pipeline** | Single conversation_id scope | Multi-agent event correlation | Missing: agent_id in events, event multiplexing |
| **Channel routing** | channel_id -> conversation_id | channel -> (account, peer) -> agentId -> conversation | Missing: binding layer between channel and agent |

### Reusable Components (No Changes Needed)

- `SubAgentProcess` -- Isolated ReAct loop (core execution engine)
- `ContextBridge` -- Context condensation and token budget
- `ParallelScheduler` -- Concurrent agent execution
- `BackgroundExecutor` -- Async background execution
- `RunRegistry` -- Active run tracking and limits
- `ResultAggregator` -- Multi-agent result combination
- `EventConverter` -- SSE event conversion (needs extension, not replacement)
- `ChannelRouter` -- Base routing (needs wrapping, not replacement)
- Agent Pool (HOT/WARM/COLD) -- Instance management

---

## 5. Proposed Multi-Agent Architecture

### 5.1 Architecture Overview

```
                   External Channels
                   (REST, WebSocket, Feishu, etc.)
                          |
                          v
              ┌──────────────────────┐
              |    Binding Router     |   <- NEW: deterministic agent routing
              |  (most-specific wins) |
              └──────────┬───────────┘
                         |
            ┌────────────┼────────────┐
            v            v            v
     ┌──────────┐ ┌──────────┐ ┌──────────┐
     | Agent A  | | Agent B  | | Agent C  |    <- ENHANCED: full agent entities
     | (coder)  | | (analyst)| | (writer) |
     |          | |          | |          |
     | workspace| | workspace| | workspace|    <- NEW: per-agent isolated workspace
     | tools    | | tools    | | tools    |
     | skills   | | skills   | | skills   |
     | persona  | | persona  | | persona  |
     | model    | | model    | | model    |
     | sessions | | sessions | | sessions |    <- NEW: per-agent session store
     └────┬─────┘ └────┬─────┘ └────┬─────┘
          |             |             |
          |    spawn/send/announce    |         <- NEW: inter-agent protocol
          └─────────────┼─────────────┘
                        |
              ┌─────────v──────────┐
              | Agent Orchestrator |            <- NEW: coordination layer
              | - Spawn Manager    |
              | - Message Bus      |
              | - Session Registry |
              | - Lifecycle Ctrl   |
              └─────────┬──────────┘
                        |
              ┌─────────v──────────┐
              | Existing L1-L4     |            <- UNCHANGED
              | (Tool/Skill/       |
              |  SubAgent/Agent)   |
              └────────────────────┘
```

### 5.2 New Components

#### 5.2.1 Agent Entity (Enhanced Domain Model)

Evolve `SubAgent` into a full `Agent` entity that can operate both as a standalone agent and as a sub-agent:

```python
@dataclass
class Agent:
    """A fully autonomous agent with isolated execution environment.
    
    Extends the SubAgent concept with workspace isolation,
    per-agent session management, and inter-agent communication.
    """
    # Identity
    id: str
    tenant_id: str
    project_id: str | None
    name: str                          # Unique within tenant
    display_name: str
    
    # Persona & Behavior
    system_prompt: str
    persona_files: list[str]           # NEW: SOUL.md, AGENTS.md paths
    model: AgentModel
    temperature: float
    max_tokens: int
    max_iterations: int
    
    # Capability Scoping
    allowed_tools: list[str]
    allowed_skills: list[str]
    allowed_mcp_servers: list[str]
    
    # Routing
    trigger: AgentTrigger
    bindings: list[AgentBinding]       # NEW: routing bindings
    
    # Workspace
    workspace_dir: str | None          # NEW: isolated workspace path
    workspace_config: WorkspaceConfig  # NEW: workspace settings
    
    # Inter-Agent
    can_spawn: bool                    # NEW: can this agent spawn sub-agents?
    max_spawn_depth: int               # NEW: max nesting depth for spawning
    agent_to_agent_enabled: bool       # NEW: opt-in for peer messaging
    discoverable: bool                 # NEW: visible in agents_list?
    
    # Runtime
    source: AgentSource
    enabled: bool
    max_retries: int
    fallback_models: list[str]
    
    # Stats
    total_invocations: int
    avg_execution_time_ms: float
    success_rate: float
```

#### 5.2.2 Agent Binding (Routing Rule)

```python
@dataclass(frozen=True)
class AgentBinding:
    """Routing rule that maps a channel context to an agent.
    
    Priority resolution (most-specific wins):
    1. channel_type + channel_id + account_id + peer_id -> agent_id
    2. channel_type + channel_id + account_id           -> agent_id
    3. channel_type + channel_id                        -> agent_id
    4. channel_type                                     -> agent_id
    5. (default agent)
    """
    id: str
    tenant_id: str
    agent_id: str
    
    # Specificity fields (None = wildcard)
    channel_type: str | None    # "rest_api", "websocket", "feishu", etc.
    channel_id: str | None      # Specific channel instance
    account_id: str | None      # Specific user
    peer_id: str | None         # Specific peer (e.g., DM partner, group ID)
    
    # Metadata
    priority: int               # Explicit override (higher = more specific)
    enabled: bool
    created_at: datetime
    
    @property
    def specificity_score(self) -> int:
        """Calculate specificity for most-specific-wins resolution."""
        score = 0
        if self.peer_id is not None:
            score += 8
        if self.account_id is not None:
            score += 4
        if self.channel_id is not None:
            score += 2
        if self.channel_type is not None:
            score += 1
        return score + self.priority
```

#### 5.2.3 Agent Workspace

```python
@dataclass
class WorkspaceConfig:
    """Configuration for an agent's isolated workspace.
    
    Workspace serves as:
    - Long-term memory (files persist across sessions)
    - Shared context (AGENTS.md, SOUL.md, USER.md)
    - Artifact storage
    """
    base_path: str              # e.g., ".memstack/agents/{agent_name}/"
    max_size_mb: int = 100
    persona_files: list[str] = field(default_factory=list)
    shared_files: list[str] = field(default_factory=list)
    auto_cleanup: bool = False
    retention_days: int = 30
```

#### 5.2.4 Binding Router (Enhanced Channel Router)

```python
class BindingRouter:
    """Routes incoming messages to agents using the binding system.
    
    Wraps the existing ChannelRouter with agent-level routing.
    
    Resolution order:
    1. Find all matching bindings for (channel_type, channel_id, account_id, peer_id)
    2. Sort by specificity_score (descending)
    3. Return the most specific match
    4. Fall back to default agent if no match
    """
    
    def __init__(
        self,
        binding_repository: AgentBindingRepository,
        channel_router: ChannelRouter,
        agent_registry: AgentRegistry,
    ):
        self._binding_repo = binding_repository
        self._channel_router = channel_router
        self._agent_registry = agent_registry
    
    async def resolve_agent(
        self,
        channel_type: str,
        channel_id: str,
        account_id: str | None = None,
        peer_id: str | None = None,
        tenant_id: str = "",
    ) -> Agent:
        """Resolve which agent should handle this message."""
        ...
    
    async def route(self, message: ChannelMessage) -> AgentRouteResult:
        """Route a channel message to a specific agent + conversation."""
        # 1. Resolve agent via binding system
        agent = await self.resolve_agent(
            channel_type=message.channel_type,
            channel_id=message.channel_id,
            account_id=message.sender_id,
            tenant_id=message.tenant_id,
        )
        # 2. Delegate to existing ChannelRouter for conversation mapping
        route_result = self._channel_router.route(message)
        # 3. Combine
        return AgentRouteResult(
            agent=agent,
            conversation_id=route_result.message.conversation_id,
            is_new_conversation=route_result.is_new_conversation,
        )
```

#### 5.2.5 Agent Orchestrator

```python
class AgentOrchestrator:
    """Coordinates multi-agent interactions.
    
    Responsibilities:
    - Agent lifecycle management (create, start, stop, pause)
    - Spawn management (parent-child tracking, cascade stop)
    - Inter-agent message routing
    - Session registry (agent -> active sessions)
    - Nesting depth enforcement
    """
    
    def __init__(
        self,
        agent_registry: AgentRegistry,
        session_registry: AgentSessionRegistry,
        spawn_manager: SpawnManager,
        message_bus: AgentMessageBus,
        run_registry: RunRegistry,  # Reuse existing
    ):
        ...
    
    async def spawn_agent(
        self,
        parent_agent_id: str,
        target_agent_id: str,
        message: str,
        mode: SpawnMode,  # RUN | SESSION
        parent_session_id: str,
    ) -> SpawnResult:
        """Spawn a sub-agent from a parent agent."""
        ...
    
    async def send_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        message: str,
        session_id: str | None = None,
    ) -> SendResult:
        """Send a message from one agent to another (opt-in)."""
        ...
    
    async def stop_agent(
        self,
        agent_id: str,
        session_id: str,
        cascade: bool = True,
    ) -> None:
        """Stop an agent session, optionally cascading to children."""
        ...
```

#### 5.2.6 Inter-Agent Tools (New L1 Tools)

Following OpenClaw's `sessions_*` pattern, adapted for MemStack:

| Tool | Description | Parameters |
|------|-------------|------------|
| `agent_spawn` | Spawn a sub-agent for task delegation | `agent_id`, `message`, `mode` (run/session) |
| `agent_list` | Discover available agents | `filter` (optional) |
| `agent_send` | Send message to another agent's session | `agent_id`, `session_id`, `message` |
| `agent_sessions` | List active sessions (own + children) | `include_children` |
| `agent_history` | Read a session's message history | `session_id`, `limit` |
| `agent_stop` | Stop a spawned sub-agent session | `session_id`, `cascade` |

These tools integrate with the existing tool pipeline:
- Wrapped as `ToolDefinition` via `tool_converter.py`
- Use `_pending_events` pattern for SSE emission
- Respect `ToolExecutor` permission/doom-loop checks
- Emit `AgentDomainEvent` subclasses through `EventConverter`

### 5.3 Execution Flow

#### 5.3.1 Channel Message -> Agent (Enhanced)

```
1. External message arrives via channel adapter
2. BindingRouter.route(message):
   a. resolve_agent() via binding specificity
   b. ChannelRouter.route() for conversation_id
3. AgentOrchestrator creates/resumes agent session
4. Agent executes via existing L4 ReActAgent.stream()
5. Events published to Redis Stream (agent:events:{conversation_id})
6. Frontend receives via SSE/WebSocket
```

#### 5.3.2 Agent Spawning Another Agent

```
1. Parent Agent calls agent_spawn(agent_id="analyst", message="Analyze Q3 data")
2. AgentOrchestrator.spawn_agent():
   a. Validate nesting depth (max_spawn_depth check)
   b. Register child run in RunRegistry
   c. Create child AgentSession
   d. Build child context via ContextBridge (reuse existing)
   e. Launch child via SubAgentProcess (reuse existing)
3. Child executes in isolation with own workspace, tools, persona
4. Child completes -> announce result to parent
5. Parent receives result and continues reasoning
```

#### 5.3.3 Agent-to-Agent Messaging (Opt-in)

```
1. Agent A calls agent_send(agent_id="writer", message="Draft the report")
2. AgentOrchestrator.send_message():
   a. Verify both agents have agent_to_agent_enabled=True
   b. Resolve target agent's active session
   c. Inject message into target's session context
   d. Emit notification event to target
3. Target agent processes message in its next reasoning step
4. Target may respond via agent_send back
```

---

## 6. Domain Model Changes

### 6.1 New Entities

| Entity | Location | Description |
|--------|----------|-------------|
| `Agent` | `src/domain/model/agent/agent_definition.py` | Full agent entity (evolves from SubAgent) |
| `AgentBinding` | `src/domain/model/agent/agent_binding.py` | Routing rule entity |
| `WorkspaceConfig` | `src/domain/model/agent/workspace_config.py` | Workspace configuration VO |
| `AgentSession` | `src/domain/model/agent/agent_session.py` | Per-agent session with history |
| `SpawnRecord` | `src/domain/model/agent/spawn_record.py` | Parent-child spawn tracking |

### 6.2 New Ports (Interfaces)

| Port | Location | Description |
|------|----------|-------------|
| `AgentRegistry` | `src/domain/ports/agent/agent_registry.py` | CRUD for Agent entities |
| `AgentBindingRepository` | `src/domain/ports/agent/binding_repository.py` | Binding persistence |
| `AgentSessionRepository` | `src/domain/ports/agent/session_repository.py` | Agent session persistence |
| `SpawnRecordRepository` | `src/domain/ports/agent/spawn_repository.py` | Spawn tracking |

### 6.3 Backward Compatibility

The existing `SubAgent` entity remains as-is. The new `Agent` entity supersedes it for multi-agent scenarios. A compatibility layer converts between them:

```python
class AgentSubAgentBridge:
    """Converts between Agent (L5) and SubAgent (L3) for backward compatibility.
    
    SubAgent definitions continue to work as before.
    When multi-agent is enabled, SubAgents are treated as single-purpose Agents
    with workspace isolation disabled.
    """
    
    @staticmethod
    def subagent_to_agent(subagent: SubAgent) -> Agent:
        """Promote a SubAgent to an Agent with defaults."""
        ...
    
    @staticmethod
    def agent_to_subagent(agent: Agent) -> SubAgent:
        """Demote an Agent to a SubAgent (loses workspace/binding)."""
        ...
```

---

## 7. Infrastructure Changes

### 7.1 New Infrastructure Components

| Component | Location | Description |
|-----------|----------|-------------|
| `BindingRouter` | `src/infrastructure/agent/routing/binding_router.py` | Enhanced routing with binding system |
| `AgentOrchestrator` | `src/infrastructure/agent/orchestration/orchestrator.py` | Multi-agent coordination |
| `SpawnManager` | `src/infrastructure/agent/orchestration/spawn_manager.py` | Parent-child spawn lifecycle |
| `AgentMessageBus` | `src/infrastructure/agent/orchestration/message_bus.py` | Inter-agent message passing via Redis |
| `AgentSessionRegistry` | `src/infrastructure/agent/orchestration/session_registry.py` | Active agent session tracking |
| `WorkspaceManager` | `src/infrastructure/agent/workspace/agent_workspace.py` | Per-agent workspace directory management |
| `AgentSpawnTool` | `src/infrastructure/agent/tools/agent_spawn.py` | `agent_spawn` L1 tool |
| `AgentListTool` | `src/infrastructure/agent/tools/agent_list.py` | `agent_list` L1 tool |
| `AgentSendTool` | `src/infrastructure/agent/tools/agent_send.py` | `agent_send` L1 tool |
| `AgentSessionsTool` | `src/infrastructure/agent/tools/agent_sessions.py` | `agent_sessions` L1 tool |
| `AgentHistoryTool` | `src/infrastructure/agent/tools/agent_history.py` | `agent_history` L1 tool |

### 7.2 Modified Infrastructure Components

| Component | Change |
|-----------|--------|
| `ReActAgent` | Add `agent_id` to context; inject inter-agent tools when agent has `can_spawn=True` |
| `SessionProcessor` | Add `agent_id` to `RunContext`; emit agent-scoped events |
| `EventConverter` | Add `agent_id` field to SSE events for multi-agent correlation |
| `ChannelRouter` | Wrapped by `BindingRouter` (not modified directly) |
| `SubAgentToolBuilder` | Extend to inject `agent_spawn`/`agent_send` tools alongside existing delegate tools |
| `actor/execution.py` | Add `agent_id` to Redis Stream publish metadata |

### 7.3 Reused Components (No Changes)

| Component | Why It Works As-Is |
|-----------|-------------------|
| `SubAgentProcess` | Already provides isolated ReAct loop per agent |
| `ContextBridge` | Already handles context condensation and token budgeting |
| `ParallelScheduler` | Already supports concurrent agent execution |
| `BackgroundExecutor` | Already supports async background agents |
| `RunRegistry` | Already tracks active runs with configurable limits |
| `ResultAggregator` | Already combines multi-agent results |
| `StateTracker` | Already tracks execution state |
| `ToolExecutor` | Already handles permission, doom-loop, argument parsing |
| Agent Pool | Already manages agent instances with three tiers |

---

## 8. Event Pipeline for Multi-Agent

### 8.1 Enhanced Event Schema

Current events are scoped to `conversation_id`. Multi-agent adds `agent_id` for correlation:

```python
# Enhanced SSE event dict
{
    "type": "thought",
    "data": {
        "thought": "I should delegate data analysis to the analyst agent...",
        "agent_id": "agent-coder-001",        # NEW: which agent emitted this
        "agent_name": "coder",                 # NEW: human-readable agent name
        "parent_agent_id": null,               # NEW: null if root agent
        "spawn_depth": 0,                      # NEW: nesting level
    },
    "conversation_id": "conv-123",
    "timestamp": "2026-03-17T10:00:00Z"
}
```

### 8.2 New Event Types

| Event Type | Emitter | Purpose |
|------------|---------|---------|
| `agent_spawned` | Parent agent (via `agent_spawn` tool) | Notify frontend that a child agent was spawned |
| `agent_completed` | Child agent (announce step) | Notify parent + frontend that child finished |
| `agent_message_sent` | Agent (via `agent_send` tool) | Notify frontend of inter-agent message |
| `agent_message_received` | Target agent | Notify frontend that agent received a message |
| `agent_stopped` | Agent or orchestrator | Agent session terminated |

### 8.3 Redis Stream Enhancement

Current: Single stream per conversation `agent:events:{conversation_id}`

Enhanced: Add agent-scoped metadata to stream entries:

```python
# Redis Stream entry (enhanced)
{
    "event_type": "thought",
    "agent_id": "agent-coder-001",
    "parent_agent_id": None,
    "conversation_id": "conv-123",
    "data": "...",
    "timestamp": "..."
}
```

Frontend can filter/group events by `agent_id` to render multi-agent activity in separate panels or a unified timeline.

### 8.4 Frontend Event Routing

```
agentService.routeToHandler(event):
  if event.type in ["agent_spawned", "agent_completed", "agent_stopped"]:
    -> onAgentLifecycle(event)          # NEW handler
  if event.agent_id != root_agent_id:
    -> onSubAgentEvent(event)           # Route to sub-agent panel
  else:
    -> existing handlers (onThought, onToolCall, etc.)
```

---

## 9. Agent Communication Protocol

### 9.1 Spawn Protocol

```
                Parent Agent                          Child Agent
                    |                                      |
                    |-- agent_spawn(analyst, msg, "run") ->|
                    |                                      |
                    |   [AgentOrchestrator validates]      |
                    |   [Creates child session]            |
                    |   [Injects context via ContextBridge]|
                    |                                      |
                    |<--- agent_spawned event -------------|
                    |                                      |
                    |   [Parent continues or waits]        |
                    |                                      |
                    |                     [Child executes] |
                    |                     [Child reasons]  |
                    |                     [Child uses tools]|
                    |                                      |
                    |<--- agent_completed (announce) ------|
                    |   {result, artifacts, metadata}      |
                    |                                      |
                    |   [Parent processes result]          |
                    v                                      v
```

### 9.2 Spawn Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| `RUN` | One-shot: child executes, announces result, session ends | Quick delegated tasks |
| `SESSION` | Persistent: child session stays alive, parent can send follow-ups | Ongoing collaboration |

### 9.3 Announce Step

When a child agent completes (in RUN mode) or reaches a milestone:

```python
@dataclass
class AnnouncePayload:
    """Result announced by a child agent back to its parent."""
    agent_id: str
    session_id: str
    result: str                 # Summary of work done
    artifacts: list[str]        # File paths or artifact IDs produced
    success: bool
    metadata: dict[str, Any]    # Additional context
```

The announce is injected into the parent's message history as a system message, triggering the parent's next reasoning step.

### 9.4 Cascade Stop

```python
async def cascade_stop(agent_id: str, session_id: str) -> None:
    """Stop an agent and all its children recursively."""
    children = await spawn_repo.find_children(session_id)
    for child in children:
        await cascade_stop(child.agent_id, child.session_id)
    await stop_agent(agent_id, session_id)
```

---

## 10. Routing & Binding System

### 10.1 Binding Resolution Algorithm

```python
async def resolve_agent(
    bindings: list[AgentBinding],
    channel_type: str,
    channel_id: str,
    account_id: str | None,
    peer_id: str | None,
) -> Agent | None:
    """Resolve the most specific binding match.
    
    Priority (most specific wins):
    1. Exact match on all 4 fields (channel_type + channel_id + account_id + peer_id)
    2. Match on 3 fields (channel_type + channel_id + account_id)
    3. Match on 2 fields (channel_type + channel_id)
    4. Match on 1 field (channel_type only)
    5. Default agent (no fields specified)
    """
    candidates = []
    for binding in bindings:
        if not binding.enabled:
            continue
        if binding.channel_type and binding.channel_type != channel_type:
            continue
        if binding.channel_id and binding.channel_id != channel_id:
            continue
        if binding.account_id and binding.account_id != account_id:
            continue
        if binding.peer_id and binding.peer_id != peer_id:
            continue
        candidates.append(binding)
    
    if not candidates:
        return None
    
    # Sort by specificity (descending)
    candidates.sort(key=lambda b: b.specificity_score, reverse=True)
    return await agent_registry.get(candidates[0].agent_id)
```

### 10.2 Binding Management API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/agents/{tenant_id}/bindings` | GET | List all bindings for tenant |
| `/api/v1/agents/{tenant_id}/bindings` | POST | Create a new binding |
| `/api/v1/agents/{tenant_id}/bindings/{id}` | PUT | Update a binding |
| `/api/v1/agents/{tenant_id}/bindings/{id}` | DELETE | Delete a binding |
| `/api/v1/agents/{tenant_id}/bindings/resolve` | POST | Test binding resolution |

---

## 11. Configuration Model

### 11.1 Agent Definition (YAML / Database)

Agents can be defined via YAML files (filesystem source) or database records:

```yaml
# .memstack/agents/analyst.yaml
name: analyst
display_name: Data Analyst
system_prompt: |
  You are a data analyst specialized in business intelligence.
  You have access to the project's knowledge graph and memory system.
  Always provide data-driven insights with citations.

model: qwen-max
temperature: 0.3
max_iterations: 15

trigger:
  description: "Data analysis, business intelligence, metrics review"
  keywords: ["analyze", "data", "metrics", "chart", "statistics"]
  examples:
    - "Analyze Q3 sales performance"
    - "Show me customer retention metrics"

allowed_tools:
  - memory_search
  - entity_lookup
  - graph_query
  - web_search

allowed_skills:
  - data-analysis
  - chart-generation

workspace:
  max_size_mb: 200
  persona_files:
    - AGENTS.md
    - DATA_GUIDELINES.md

can_spawn: true
max_spawn_depth: 2
agent_to_agent_enabled: false
discoverable: true

bindings:
  - channel_type: rest_api
    priority: 0
  - channel_type: feishu
    channel_id: "data-team-group"
    priority: 10
```

### 11.2 Environment Variables (New)

```bash
# Multi-Agent feature flag
MULTI_AGENT_ENABLED=true

# Agent workspace
AGENT_WORKSPACE_BASE_PATH=".memstack/agents/"
AGENT_WORKSPACE_MAX_SIZE_MB=100

# Inter-agent communication
AGENT_TO_AGENT_DEFAULT_ENABLED=false
AGENT_MAX_SPAWN_DEPTH=3
AGENT_SPAWN_TIMEOUT_SECONDS=300

# Binding system
AGENT_BINDING_CACHE_TTL_SECONDS=60
AGENT_DEFAULT_AGENT_NAME="default"
```

---

## 12. Migration Plan

### Phase 1: Foundation (2-3 weeks)

**Goal**: Introduce Agent entity and binding system without breaking existing functionality.

| Task | Effort | Risk |
|------|--------|------|
| Create `Agent` domain entity | Medium | Low -- new entity, no existing code affected |
| Create `AgentBinding` domain entity | Low | Low |
| Create `WorkspaceConfig` value object | Low | Low |
| Add database migrations for `agents`, `agent_bindings` tables | Medium | Low |
| Implement `AgentRegistry` port + SQL adapter | Medium | Low |
| Implement `AgentBindingRepository` port + SQL adapter | Medium | Low |
| Create `AgentSubAgentBridge` for backward compat | Low | Low |
| Add `MULTI_AGENT_ENABLED` feature flag | Low | Low |

**Verification**: Existing SubAgent tests continue to pass. New Agent CRUD works.

### Phase 2: Routing (1-2 weeks)

**Goal**: Implement binding-based routing that wraps existing ChannelRouter.

| Task | Effort | Risk |
|------|--------|------|
| Implement `BindingRouter` wrapping `ChannelRouter` | Medium | Medium -- routing is critical path |
| Add binding resolution algorithm | Low | Low |
| Add binding management API endpoints | Medium | Low |
| Wire `BindingRouter` into existing channel flow (behind feature flag) | Medium | Medium |
| Add binding resolution tests | Medium | Low |

**Verification**: When `MULTI_AGENT_ENABLED=false`, routing works exactly as before. When enabled, default binding routes to the same agent as current behavior.

### Phase 3: Agent Isolation (2-3 weeks)

**Goal**: Implement per-agent workspaces and session isolation.

| Task | Effort | Risk |
|------|--------|------|
| Implement `WorkspaceManager` for per-agent directories | Medium | Low |
| Implement `AgentSessionRegistry` | Medium | Low |
| Enhance `ReActAgent` to accept `agent_id` in context | Low | Medium -- touches core loop |
| Enhance `SessionProcessor` with `agent_id` in `RunContext` | Low | Medium |
| Inject persona files from workspace into system prompt | Medium | Low |
| Add `agent_id` to SSE events via `EventConverter` | Low | Low |

**Verification**: Single-agent mode produces identical output. Multi-agent mode creates isolated workspaces.

### Phase 4: Inter-Agent Communication (2-3 weeks)

**Goal**: Implement spawn, messaging, and the new L1 tools.

| Task | Effort | Risk |
|------|--------|------|
| Implement `AgentOrchestrator` | High | Medium |
| Implement `SpawnManager` with cascade stop | Medium | Medium |
| Implement `AgentMessageBus` via Redis | Medium | Low |
| Create `agent_spawn` tool | Medium | Low |
| Create `agent_list` tool | Low | Low |
| Create `agent_send` tool | Medium | Medium -- requires session injection |
| Create `agent_sessions` / `agent_history` / `agent_stop` tools | Medium | Low |
| Add new `AgentEventType` values | Low | Low |
| Wire tools into `SubAgentToolBuilder` | Low | Low |
| Integration tests for spawn lifecycle | High | Medium |

**Verification**: Agent can spawn sub-agent, receive announced result, and continue reasoning. Cascade stop works.

### Phase 5: Frontend Integration (2-3 weeks)

**Goal**: Multi-agent UI in the Agent Workspace page.

| Task | Effort | Risk |
|------|--------|------|
| Add `agent_id` handling in `agentService.ts` event routing | Medium | Low |
| Add multi-agent panel in Agent Workspace (show active agents, their events) | High | Low |
| Add binding management UI in tenant settings | Medium | Low |
| Add agent definition management UI | High | Low |
| Add spawn visualization (parent-child tree) | Medium | Low |

---

## 13. Risk Assessment

### High Risk

| Risk | Mitigation |
|------|------------|
| **Breaking existing SubAgent flow** | `AgentSubAgentBridge` provides backward compat; `MULTI_AGENT_ENABLED` feature flag gates all new code |
| **Event pipeline corruption** | `agent_id` is additive (new field, not replacing existing). Old events remain valid. |
| **Infinite spawn recursion** | `max_spawn_depth` enforcement in `SpawnManager` + `RunRegistry` limits |

### Medium Risk

| Risk | Mitigation |
|------|------------|
| **Workspace disk usage** | `WorkspaceConfig.max_size_mb` + `retention_days` + cleanup job |
| **Inter-agent message ordering** | Redis Streams guarantee ordering per stream. Each agent-pair gets a stream key. |
| **Binding resolution performance** | Cache bindings in memory with TTL. Bindings change rarely. |

### Low Risk

| Risk | Mitigation |
|------|------------|
| **Domain model complexity** | New entities are independent. Existing entities unchanged. |
| **Database migration** | New tables only. No ALTER on existing tables. |
| **Frontend regression** | New event types are additive. Old handlers unchanged. |

---

## Appendix A: OpenClaw vs MemStack Mapping

| OpenClaw Concept | MemStack Equivalent | Notes |
|-----------------|---------------------|-------|
| `Agent` | `Agent` (new) / `SubAgent` (existing) | New entity supersedes SubAgent for multi-agent |
| `Account` | `User` (existing) | Map OpenClaw accountId to MemStack user_id |
| `Binding` | `AgentBinding` (new) | New routing rule entity |
| `agentDir` | `WorkspaceConfig.base_path` | Per-agent workspace directory |
| `sessions_spawn` | `agent_spawn` tool | Adapted naming for MemStack conventions |
| `sessions_send` | `agent_send` tool | Adapted naming |
| `sessions_list` | `agent_sessions` tool | Adapted naming |
| `sessions_history` | `agent_history` tool | Adapted naming |
| `agents_list` | `agent_list` tool | Adapted naming |
| `maxSpawnDepth` | `Agent.max_spawn_depth` | Per-agent configuration |
| `agentToAgent` | `Agent.agent_to_agent_enabled` | Opt-in flag |
| `SOUL.md` / `AGENTS.md` / `USER.md` | `WorkspaceConfig.persona_files` | Persona injection |
| `announce` step | `AnnouncePayload` | Child-to-parent result delivery |
| `cascade stop` | `SpawnManager.cascade_stop()` | Recursive child termination |

## Appendix B: File Layout (New Files)

```
src/
├── domain/
│   └── model/
│       └── agent/
│           ├── agent_definition.py      # NEW: Agent entity
│           ├── agent_binding.py         # NEW: AgentBinding entity
│           ├── workspace_config.py      # NEW: WorkspaceConfig VO
│           ├── agent_session.py         # NEW: AgentSession entity
│           ├── spawn_record.py          # NEW: SpawnRecord entity
│           └── spawn_mode.py            # NEW: SpawnMode enum
│   └── ports/
│       └── agent/
│           ├── agent_registry.py        # NEW: Agent CRUD port
│           ├── binding_repository.py    # NEW: Binding persistence port
│           ├── session_repository.py    # NEW: Agent session port
│           └── spawn_repository.py      # NEW: Spawn tracking port
│
├── infrastructure/
│   └── agent/
│       ├── orchestration/               # NEW: Multi-agent coordination
│       │   ├── __init__.py
│       │   ├── orchestrator.py          # AgentOrchestrator
│       │   ├── spawn_manager.py         # SpawnManager
│       │   ├── message_bus.py           # AgentMessageBus (Redis)
│       │   └── session_registry.py      # AgentSessionRegistry
│       ├── routing/
│       │   ├── binding_router.py        # NEW: BindingRouter
│       │   └── (existing files unchanged)
│       ├── workspace/
│       │   └── agent_workspace.py       # NEW: Per-agent workspace mgmt
│       ├── tools/
│       │   ├── agent_spawn.py           # NEW: agent_spawn tool
│       │   ├── agent_list.py            # NEW: agent_list tool
│       │   ├── agent_send.py            # NEW: agent_send tool
│       │   ├── agent_sessions.py        # NEW: agent_sessions tool
│       │   ├── agent_history.py         # NEW: agent_history tool
│       │   └── (existing files unchanged)
│       └── compatibility/
│           └── subagent_bridge.py       # NEW: Agent <-> SubAgent bridge
│
│   └── adapters/
│       └── secondary/
│           └── persistence/
│               ├── sql_agent_registry.py     # NEW
│               ├── sql_binding_repository.py # NEW
│               └── (existing files unchanged)
│
│       └── primary/
│           └── web/
│               └── routers/
│                   └── agent/
│                       ├── binding_router.py  # NEW: Binding mgmt API
│                       └── agent_mgmt_router.py # NEW: Agent CRUD API
│
└── application/
    └── services/
        └── agent_orchestration_service.py    # NEW: Application service
```
