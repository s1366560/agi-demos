# New Features Reference

This document covers the 11 new infrastructure modules added to MemStack's agent system.
Each section describes the module's purpose, architecture, key types, configuration,
and usage patterns. All modules live under `src/infrastructure/agent/`.

---

## Table of Contents

1. [Agent Pool System](#1-agent-pool-system)
2. [Agent Lifecycle Management](#2-agent-lifecycle-management)
3. [Circuit Breaker](#3-circuit-breaker)
4. [Failure Recovery](#4-failure-recovery)
5. [State Recovery](#5-state-recovery)
6. [Auto-Scaling](#6-auto-scaling)
7. [Feature Flags](#7-feature-flags)
8. [Multi-Channel Communication](#8-multi-channel-communication)
9. [Agent Canvas System](#9-agent-canvas-system)
10. [Intelligent Model Routing](#10-intelligent-model-routing)
11. [Pool Orchestrator](#11-pool-orchestrator)

---

## 1. Agent Pool System

**Source**: `pool/manager.py` (743 lines), `pool/config.py`, `pool/types.py`, `pool/instance.py`

### Overview

The Agent Pool System manages agent instances across a three-tier hierarchy (HOT / WARM / COLD).
Projects are classified by access frequency and SLA requirements, and each tier provides
different resource isolation guarantees.

| Tier | Strategy | Use Case |
|------|----------|----------|
| HOT | Dedicated container per project | High-traffic, mission-critical |
| WARM | Shared LRU-cached pool | Regular projects, cost-effective |
| COLD | Created on demand, destroyed after use | Low-traffic, inactive projects |

### Architecture

**`AgentPoolManager`** is the central class. It owns:

- An instance registry (`dict[str, AgentInstance]`) keyed by `{tenant_id}:{project_id}`.
- A `ResourceManager` that tracks memory, CPU, and concurrency quotas.
- A `HealthMonitor` that periodically checks instance health.
- Project-tier classification logic based on `ProjectMetrics` (request count, latency, last access).

Key methods:

| Method | Purpose |
|--------|---------|
| `create_instance(config)` | Create and register a new agent instance |
| `get_instance(tenant_id, project_id)` | Retrieve an existing instance (or None) |
| `get_or_create(tenant_id, project_id, config)` | Lazy initialization pattern |
| `destroy_instance(instance_key)` | Graceful shutdown and cleanup |
| `classify_project(metrics)` | Determine HOT/WARM/COLD tier from metrics |
| `rebalance()` | Re-classify all projects and migrate instances |

### Key Types

```python
# pool/types.py
class ProjectTier(str, Enum):     # HOT, WARM, COLD
class AgentInstanceStatus(str, Enum):  # CREATED, INITIALIZING, READY, EXECUTING, ...
class HealthStatus(str, Enum):    # HEALTHY, DEGRADED, UNHEALTHY, UNKNOWN
class CircuitState(str, Enum):    # CLOSED, HALF_OPEN, OPEN
class RecoveryAction(str, Enum):  # RESTART, MIGRATE, DEGRADE, ALERT, TERMINATE

@dataclass
class PoolStats:
    total_instances: int
    active_instances: int
    instances_by_tier: dict[str, int]
    instances_by_status: dict[str, int]
    total_memory_mb: int
    total_cpu_cores: float

@dataclass
class ProjectMetrics:
    project_id: str
    tenant_id: str
    request_count_1h: int
    avg_latency_ms: float
    error_rate: float
    last_access: datetime
```

### Configuration

```python
# pool/config.py
@dataclass
class PoolConfig:
    max_instances: int = 100            # Maximum total instances
    default_tier: ProjectTier = ProjectTier.WARM
    warmup_count: int = 5               # Pre-warmed instances
    max_idle_seconds: int = 300         # Idle timeout before cleanup
    health_check_interval: int = 30     # Seconds between health checks
    enable_ha: bool = False             # Enable high availability features
    enable_auto_scaling: bool = False   # Enable auto-scaling
    checkpoint_interval: int = 60       # State checkpoint interval (seconds)

@dataclass
class ResourceQuota:
    memory_limit_mb: int = 512
    memory_request_mb: int = 256
    cpu_limit_cores: float = 1.0
    cpu_request_cores: float = 0.25
    max_instances: int = 1
    max_concurrent_requests: int = 10
    max_execution_time_seconds: int = 300
    max_steps_per_request: int = 50

@dataclass
class AgentInstanceConfig:
    project_id: str
    tenant_id: str
    tier: ProjectTier = ProjectTier.WARM
    quota: ResourceQuota = field(default_factory=ResourceQuota)
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    idle_timeout_seconds: int = 3600
    max_lifetime_seconds: int = 86400
```

### Environment Variables

```bash
AGENT_POOL_ENABLED=true
AGENT_POOL_MAX_INSTANCES=100
AGENT_POOL_DEFAULT_TIER=WARM
AGENT_POOL_WARMUP_COUNT=5
AGENT_POOL_MAX_IDLE_SECONDS=300
AGENT_POOL_HEALTH_CHECK_INTERVAL=30
```

---

## 2. Agent Lifecycle Management

**Source**: `pool/lifecycle/state_machine.py` (302 lines)

### Overview

A deterministic finite state machine that governs agent instance state transitions.
Every state change must pass through a defined transition with optional guard conditions
and transition actions. Invalid transitions raise `ValueError`.

### State Diagram

```
CREATED --> INITIALIZING --> READY <--> EXECUTING
                |              |           |
                v              v           v
       INITIALIZATION_FAILED  PAUSED  UNHEALTHY
                |              |           |
                v              |           v
            (retry) --------+  |       DEGRADED
                               |           |
                               v           v
                          TERMINATING --> TERMINATED
```

### Architecture

**`LifecycleStateMachine`** holds a `current_status` and a list of `StateTransition` records.
Each transition defines:

```python
@dataclass
class StateTransition:
    from_status: AgentInstanceStatus
    to_status: AgentInstanceStatus
    trigger: str                              # Event name (e.g. "initialize", "pause")
    guard: Callable[[], bool] | None = None   # Optional precondition
    action: Callable[[], None] | None = None  # Optional side effect
```

**`VALID_TRANSITIONS`** is a module-level list of ~20 transitions covering:

| Phase | Transitions |
|-------|-------------|
| Initialization | CREATED -> INITIALIZING -> READY / INITIALIZATION_FAILED |
| Execution | READY <-> EXECUTING, READY <-> PAUSED, EXECUTING -> PAUSED |
| Degradation | READY/EXECUTING -> UNHEALTHY -> DEGRADED -> READY |
| Termination | Any operational state -> TERMINATING -> TERMINATED |

### Usage

```python
from pool.lifecycle import LifecycleStateMachine
from pool.types import AgentInstanceStatus

sm = LifecycleStateMachine(initial_status=AgentInstanceStatus.CREATED)
sm.trigger("initialize")    # CREATED -> INITIALIZING
sm.trigger("initialization_complete")  # INITIALIZING -> READY
sm.trigger("execute")       # READY -> EXECUTING
sm.trigger("complete")      # EXECUTING -> READY

# Invalid transition raises ValueError
sm.trigger("pause")         # READY -> PAUSED (valid)
sm.trigger("execute")       # PAUSED -> ? (no such transition, raises ValueError)
```

### Key Methods

| Method | Purpose |
|--------|---------|
| `trigger(event)` | Execute a named transition |
| `can_trigger(event)` | Check if a transition is valid from current state |
| `get_available_triggers()` | List valid triggers from current state |
| `get_history()` | Return list of past transitions with timestamps |

---

## 3. Circuit Breaker

**Source**: `pool/circuit_breaker/breaker.py` (426 lines)

### Overview

Implements the Circuit Breaker pattern to prevent cascading failures when agent instances
or their backing services become unhealthy. The breaker tracks failure counts within a
sliding time window and transitions through three states: CLOSED (normal), OPEN (blocking),
and HALF_OPEN (testing recovery).

### State Machine

```
         success         failure >= threshold
CLOSED ----------> CLOSED     CLOSED -----------> OPEN
                                                    |
                              recovery_timeout      |
                              expires               v
                           HALF_OPEN <----------  OPEN
                              |          |
                   success >= |          | failure
                   threshold  v          v
                           CLOSED      OPEN
```

### Architecture

**`CircuitBreaker`** is a standalone class (no external dependencies). It can be used
as both a direct call wrapper and an async context manager.

```python
@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5           # Failures before opening
    recovery_timeout_seconds: int = 60   # Wait before half-open
    half_open_requests: int = 3          # Test requests in half-open
    success_threshold: int = 2           # Successes to close from half-open
    window_seconds: int = 60             # Sliding window for failure counting
    excluded_exceptions: list[type] = field(default_factory=list)

@dataclass
class CircuitBreakerStats:
    state: CircuitState
    failure_count: int
    success_count: int
    total_requests: int
    last_failure_time: datetime | None
    last_success_time: datetime | None
    consecutive_failures: int
    consecutive_successes: int
```

### Usage

```python
from pool.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError

breaker = CircuitBreaker(
    name="llm-provider",
    config=CircuitBreakerConfig(failure_threshold=3, recovery_timeout_seconds=30),
)

# Wrap calls
try:
    result = await breaker.call(some_async_function, arg1, arg2)
except CircuitOpenError:
    # Circuit is open -- use fallback
    result = fallback_value
```

### Key Methods

| Method | Purpose |
|--------|---------|
| `call(func, *args, **kwargs)` | Execute function through the breaker |
| `record_success()` | Manually record a success |
| `record_failure(error)` | Manually record a failure |
| `get_stats()` | Return `CircuitBreakerStats` snapshot |
| `reset()` | Force-reset to CLOSED state |
| `force_open()` | Force-open the circuit |

---

## 4. Failure Recovery

**Source**: `pool/ha/failure_recovery.py` (522 lines)

### Overview

Automatic failure detection and recovery for agent instances. The service monitors
failure events, detects failure patterns, selects appropriate recovery strategies,
and executes recovery actions. Integrates with the circuit breaker and state recovery
services.

### Failure Types

```python
class FailureType(str, Enum):
    HEALTH_CHECK_FAILED = "health_check_failed"
    INITIALIZATION_FAILED = "initialization_failed"
    EXECUTION_ERROR = "execution_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    TIMEOUT = "timeout"
    CONNECTION_LOST = "connection_lost"
    CONTAINER_CRASHED = "container_crashed"
    UNKNOWN = "unknown"
```

### Recovery Strategies

| Strategy | Description | When Used |
|----------|-------------|-----------|
| RESTART | Simple restart without state | Transient errors, first occurrence |
| RECOVER | Restart with state recovery from checkpoint | Repeated failures, stateful instances |
| MIGRATE | Move instance to a different backend/tier | Resource exhaustion, backend issues |
| ESCALATE | Alert human operators | Unrecoverable failures, repeated escalation |

### Architecture

**`FailureRecoveryService`** tracks:

- Recent failure events per instance (sliding window).
- Failure patterns (frequency, correlation with failure type).
- Recovery attempt history (to avoid repeating failed strategies).

Key classes:

```python
@dataclass
class FailureEvent:
    instance_key: str
    failure_type: FailureType
    timestamp: datetime
    error_message: str
    context: dict[str, Any]

@dataclass
class FailurePattern:
    instance_key: str
    failure_type: FailureType
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    is_recurring: bool
```

### Strategy Selection Logic

1. First failure -> RESTART
2. Same failure type recurs within window -> RECOVER (with state checkpoint)
3. Multiple recovery attempts failed -> MIGRATE to different tier/backend
4. Migration failed or critical failure -> ESCALATE to human operators

### Key Methods

| Method | Purpose |
|--------|---------|
| `handle_failure(event)` | Process a failure event and execute recovery |
| `select_strategy(instance_key, failure_type)` | Determine best recovery strategy |
| `execute_recovery(instance_key, strategy)` | Execute the selected strategy |
| `get_failure_history(instance_key)` | Return recent failures for an instance |
| `register_recovery_handler(strategy, handler)` | Register custom recovery logic |

---

## 5. State Recovery

**Source**: `pool/ha/state_recovery.py` (469 lines)

### Overview

Provides state persistence and recovery for agent instances via checkpointing. When an
instance crashes or restarts, the service restores its last known state from a checkpoint.
Supports Redis-based storage (fast) with an in-memory fallback when Redis is unavailable.

### Checkpoint Types

```python
class CheckpointType(str, Enum):
    LIFECYCLE = "lifecycle"         # Instance state machine position
    CONVERSATION = "conversation"   # Active conversation context
    EXECUTION = "execution"         # Tool execution state
    RESOURCE = "resource"           # Resource allocation snapshot
    FULL = "full"                   # Complete state snapshot
```

### Architecture

**`StateRecoveryService`** manages:

- Checkpoint creation on state changes (triggered by lifecycle transitions).
- Checkpoint storage (Redis with TTL, or in-memory dict as fallback).
- State recovery after crashes (deserialize checkpoint, restore instance state).

Key classes:

```python
@dataclass
class StateCheckpoint:
    checkpoint_id: str
    instance_key: str
    checkpoint_type: CheckpointType
    timestamp: datetime
    state_data: dict[str, Any]          # Serialized instance state
    metadata: dict[str, Any]            # Recovery hints

@dataclass
class RecoveryResult:
    success: bool
    instance_key: str
    checkpoint_type: CheckpointType
    recovered_state: dict[str, Any] | None
    error: str | None = None
```

### Serialization

Checkpoints use `to_dict()` / `from_dict()` for JSON-compatible serialization.
All datetime values are stored as ISO 8601 strings. The service handles both
Redis `SET`/`GET` operations and in-memory dict storage transparently.

### Key Methods

| Method | Purpose |
|--------|---------|
| `create_checkpoint(instance_key, type, state_data)` | Persist a state checkpoint |
| `recover_instance(instance_key, type)` | Restore state from latest checkpoint |
| `get_latest_checkpoint(instance_key)` | Retrieve most recent checkpoint |
| `cleanup_old_checkpoints(max_age)` | Remove expired checkpoints |
| `list_checkpoints(instance_key)` | List all checkpoints for an instance |

### Configuration

```bash
AGENT_POOL_ENABLE_HA=true
AGENT_POOL_CHECKPOINT_INTERVAL=60    # Seconds between automatic checkpoints
```

---

## 6. Auto-Scaling

**Source**: `pool/ha/auto_scaling.py` (527 lines)

### Overview

Dynamic scaling service that adjusts the number of agent instances based on load metrics.
Monitors CPU, memory, queue depth, and latency, then makes scaling decisions with
configurable policies and cooldown periods to prevent thrashing.

### Scaling Triggers

```python
class ScalingDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    NONE = "none"

class ScalingReason(str, Enum):
    HIGH_CPU = "high_cpu"
    HIGH_MEMORY = "high_memory"
    HIGH_QUEUE_DEPTH = "high_queue_depth"
    HIGH_LATENCY = "high_latency"
    LOW_UTILIZATION = "low_utilization"
    HEALTH_ISSUES = "health_issues"
    SCHEDULED = "scheduled"
    MANUAL = "manual"
```

### Architecture

**`AutoScalingService`** evaluates metrics against policies and produces scaling decisions.

```python
@dataclass
class ScalingPolicy:
    min_instances: int = 1
    max_instances: int = 10
    target_cpu_percent: float = 70.0
    target_memory_percent: float = 80.0
    target_queue_depth: int = 10
    target_latency_ms: float = 1000.0
    scale_up_cooldown_seconds: int = 60
    scale_down_cooldown_seconds: int = 300
    scale_up_step: int = 1              # Instances to add per scale-up
    scale_down_step: int = 1            # Instances to remove per scale-down

@dataclass
class ScalingMetrics:
    cpu_percent: float
    memory_percent: float
    queue_depth: int
    avg_latency_ms: float
    active_instances: int
    total_requests_1m: int

@dataclass
class ScalingDecision:
    direction: ScalingDirection
    reason: ScalingReason
    current_instances: int
    desired_instances: int
    metrics_snapshot: ScalingMetrics
    timestamp: datetime
```

### Decision Logic

1. Collect current `ScalingMetrics` from the pool manager.
2. Compare each metric against `ScalingPolicy` thresholds.
3. If any metric exceeds its threshold, propose scale-up (capped at `max_instances`).
4. If all metrics are well below thresholds, propose scale-down (floored at `min_instances`).
5. Check cooldown period since last scaling action.
6. Return `ScalingDecision` with direction, reason, and desired count.

### Key Methods

| Method | Purpose |
|--------|---------|
| `evaluate(metrics)` | Produce a scaling decision from current metrics |
| `apply_decision(decision)` | Execute scaling (create/destroy instances) |
| `get_scaling_history()` | Return recent scaling decisions |
| `update_policy(policy)` | Change the active scaling policy |

### Configuration

```bash
AGENT_POOL_ENABLE_AUTO_SCALING=false   # Disabled by default
```

---

## 7. Feature Flags

**Source**: `pool/feature_flags.py` (422 lines)

### Overview

Gradual rollout system for pool features. Supports per-tenant and per-project flags
with multiple rollout strategies including percentage-based, allowlist/denylist, and
time-based gradual rollout.

### Rollout Strategies

```python
class RolloutStrategy(str, Enum):
    ALL = "all"                # Enable for everyone
    NONE = "none"              # Disable for everyone
    PERCENTAGE = "percentage"  # Enable for N% (deterministic hash-based)
    ALLOWLIST = "allowlist"    # Enable only for listed tenants/projects
    DENYLIST = "denylist"      # Enable for all except listed
    GRADUAL = "gradual"        # Auto-increase percentage over time
```

### Architecture

**`FeatureFlags`** manages flag configurations and evaluates them at runtime.

```python
@dataclass
class FeatureFlagConfig:
    name: str
    description: str
    strategy: RolloutStrategy = RolloutStrategy.NONE
    percentage: float = 0.0                    # For PERCENTAGE/GRADUAL
    allowlist: list[str] = field(default_factory=list)
    denylist: list[str] = field(default_factory=list)
    start_time: datetime | None = None         # For time-based activation
    end_time: datetime | None = None
    gradual_start_percentage: float = 0.0      # For GRADUAL
    gradual_end_percentage: float = 100.0
    gradual_duration_hours: float = 168.0      # 1 week default
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Percentage Rollout

Percentage-based rollout uses a deterministic hash of `flag_name + tenant_id` (SHA256)
to produce a stable float in [0, 100). This ensures the same tenant always gets the
same result for a given flag, and rollout is uniformly distributed.

### Usage

```python
flags = FeatureFlags()
flags.register(FeatureFlagConfig(
    name="pool_v2",
    description="New pool architecture",
    strategy=RolloutStrategy.PERCENTAGE,
    percentage=25.0,
))

# Check at runtime
if await flags.is_enabled("pool_v2", tenant_id="tenant-abc"):
    use_new_pool()
else:
    use_legacy_pool()

# Gradual rollout
flags.register(FeatureFlagConfig(
    name="canvas_blocks",
    description="Enable canvas UI blocks",
    strategy=RolloutStrategy.GRADUAL,
    gradual_start_percentage=0.0,
    gradual_end_percentage=100.0,
    gradual_duration_hours=168,   # Ramp over 1 week
    start_time=datetime.now(UTC),
))
```

### Key Methods

| Method | Purpose |
|--------|---------|
| `register(config)` | Register or update a feature flag |
| `is_enabled(flag, tenant_id, project_id)` | Evaluate flag for a specific context |
| `get_all_flags()` | List all registered flags |
| `get_flag(name)` | Get a single flag configuration |
| `remove(name)` | Remove a flag |
| `get_rollout_percentage(name)` | Get effective percentage (including gradual) |

---

## 8. Multi-Channel Communication

**Source**: `channels/` (8 files)

### Overview

A transport-agnostic channel system that routes messages from various sources (WebSocket,
REST API, Feishu, Slack, webhooks) into agent conversations. The system decouples
transport-specific logic from conversation management via a unified message format and
an adapter pattern.

### Supported Channels

```python
class ChannelType(str, Enum):
    WEBSOCKET = "websocket"
    REST_API = "rest_api"
    FEISHU = "feishu"
    SLACK = "slack"
    WEBHOOK = "webhook"
```

### Architecture

The system has three layers:

1. **`ChannelAdapter`** (abstract base) -- Translates between a specific transport and
   the unified `ChannelMessage` format. Each adapter implements `connect()`,
   `disconnect()`, `receive()` (async iterator), and `send()`.

2. **`ChannelMessage`** (frozen dataclass) -- The canonical message representation
   carrying `channel_type`, `channel_id`, `sender_id`, `content`, `metadata`,
   `conversation_id`, `project_id`, and `tenant_id`.

3. **`ChannelRouter`** -- Maintains a registry of adapters keyed by
   `(channel_type, channel_id)` and an in-memory mapping from `channel_id` to
   `conversation_id`. When a message arrives on a previously-unseen channel, the
   router allocates a new conversation ID.

### Concrete Adapters

| Adapter | Source | Description |
|---------|--------|-------------|
| `RestApiAdapter` | `rest_api_adapter.py` | Receives messages via HTTP POST |
| `WebSocketAdapter` | `websocket_adapter.py` | Bidirectional WebSocket streams |

### Route Result

```python
@dataclass
class RouteResult:
    message: ChannelMessage      # Enriched message with conversation_id set
    is_new_conversation: bool    # True when a new conversation was allocated
```

### Usage

```python
from channels import ChannelRouter, WebSocketAdapter

router = ChannelRouter()
ws_adapter = WebSocketAdapter(session_id="ws-123", websocket=ws)
router.register_adapter(ws_adapter)

# Route an incoming message
result = await router.route(incoming_message)
if result.is_new_conversation:
    # Initialize conversation context
    pass
```

### Design Notes

- The router is deliberately stateless with respect to persistence (in-memory mapping
  only). A production deployment would back the channel-to-conversation mapping with
  Redis or a database table.
- Adapters are registered/unregistered dynamically as connections open and close.
- The `ChannelMessage.metadata` dict carries transport-specific fields (HTTP headers,
  Feishu event fields, etc.) without polluting the core message model.

---

## 9. Agent Canvas System

**Source**: `canvas/` (6 files)

### Overview

The Canvas system provides agents with the ability to create, update, and delete rich UI
blocks during a conversation. This enables "Agent-to-UI" (A2UI) interactions where the
agent can render code snippets, data tables, charts, forms, images, markdown, and custom
widgets directly in the chat interface.

### Block Types

```python
class CanvasBlockType(str, Enum):
    CODE = "code"           # Syntax-highlighted source code
    TABLE = "table"         # Structured tabular data (JSON rows)
    CHART = "chart"         # Data visualization (chart spec)
    FORM = "form"           # Interactive input form
    IMAGE = "image"         # Image/media display
    MARKDOWN = "markdown"   # Rich formatted text
    WIDGET = "widget"       # Custom interactive component
```

### Architecture

**`CanvasManager`** (singleton) -- Manages per-conversation canvas state in memory.
Each conversation has an independent `CanvasState` containing an ordered list of
`CanvasBlock` instances.

**`CanvasBlock`** (frozen dataclass) -- Immutable value object with `id`, `block_type`,
`title`, `content`, `metadata`, and a monotonically increasing `version` for
optimistic concurrency control.

**`CanvasState`** -- Mutable container holding the block list for one conversation.
Provides `add_block()`, `update_block()`, `remove_block()`, and `get_block()`.

**Canvas Tools** (`tools.py`) -- Three `@tool_define`-decorated functions that the
ReAct agent can invoke:

| Tool | Parameters | Description |
|------|------------|-------------|
| `canvas_create` | `block_type, title, content, metadata` | Create a new block |
| `canvas_update` | `block_id, title, content, metadata` | Update an existing block |
| `canvas_delete` | `block_id` | Remove a block |

### SSE Events

Canvas mutations emit `canvas_updated` SSE events via the standard pending-events pattern:

```python
{
    "type": "canvas_updated",
    "conversation_id": "...",
    "block_id": "...",
    "action": "created" | "updated" | "deleted",
    "block": { ... }  # CanvasBlock.to_dict(), None for deletes
}
```

The `build_canvas_event_dict()` helper in `events.py` constructs these payloads.

### Usage

```python
# Agent tool invocation (via ReAct loop)
canvas_create(
    block_type="table",
    title="Q3 Sales Report",
    content='[{"region": "US", "revenue": 1200000}, ...]',
    metadata={"sortable": "true"},
)

# Programmatic usage
from canvas import CanvasManager
manager = CanvasManager()
block = manager.create_block(
    conversation_id="conv-123",
    block_type="code",
    title="Solution",
    content="def solve(): ...",
    metadata={"language": "python"},
)
```

### Configuration

The canvas system is configured via module-level DI:

```python
from canvas.tools import configure_canvas
from canvas.manager import CanvasManager

configure_canvas(CanvasManager())
```

This is called during agent initialization. The `CanvasManager` instance is shared
across all conversations within the same agent process.

---

## 10. Intelligent Model Routing

**Source**: `routing/execution_router.py` (35 lines)

### Overview

Defines the execution path types for the ReAct agent. Originally implemented as a
confidence-scoring router, the actual routing logic has migrated to prompt-driven
lane detection within `ReActAgent._decide_execution_path()`. This module now provides
only the type definitions used by the rest of the system.

### Execution Paths

```python
class ExecutionPath(Enum):
    DIRECT_SKILL = "direct_skill"   # Execute skill directly without LLM
    PLAN_MODE = "plan_mode"         # Use multi-step planning mode
    REACT_LOOP = "react_loop"       # Standard ReAct reasoning loop
```

### Routing Decision

```python
@dataclass
class RoutingDecision:
    path: ExecutionPath
    confidence: float       # 0.0 to 1.0
    reason: str
    target: str | None      # Skill/subagent name if applicable
    metadata: dict[str, Any]
```

### Current Routing Flow

The ReAct agent determines the execution path through prompt-based analysis rather than
confidence scoring:

1. **DIRECT_SKILL** -- Matched when user input triggers a skill with high keyword overlap.
2. **PLAN_MODE** -- Selected for complex queries requiring multi-step decomposition.
3. **REACT_LOOP** -- Default path for general-purpose reasoning.

The confidence-scoring `ExecutionRouter` class and its Protocol dependencies were removed
in the Wave 1a cleanup. The remaining types are retained for backward compatibility and
metadata annotation.

---

## 11. Pool Orchestrator

**Source**: `pool/orchestrator.py` (617 lines)

### Overview

The Pool Orchestrator is the top-level coordinator that unifies all pool subsystems into
a single management interface. It starts, stops, and coordinates the pool manager, health
monitor, failure recovery, auto-scaling, state recovery, metrics collector, and alert
service.

### Architecture

**`PoolOrchestrator`** composes:

| Component | Class | Purpose |
|-----------|-------|---------|
| Pool Manager | `AgentPoolManager` | Instance lifecycle |
| Health Monitor | `HealthMonitor` | Periodic health checks |
| Failure Recovery | `FailureRecoveryService` | Auto-healing |
| Auto-Scaling | `AutoScalingService` | Dynamic scaling |
| State Recovery | `StateRecoveryService` | Checkpoint persistence |
| Metrics Collector | `PoolMetricsCollector` | Prometheus-style metrics |
| Alert Service | `AlertServicePort` | Critical event notifications |

```python
@dataclass
class OrchestratorConfig:
    pool_config: PoolConfig
    health_config: HealthMonitorConfig
    scaling_policy: ScalingPolicy | None = None
    enable_failure_recovery: bool = True
    enable_auto_scaling: bool = False
    enable_state_recovery: bool = True
    enable_metrics: bool = True
    alert_service: AlertServicePort = field(default_factory=NullAlertService)
```

### Lifecycle

```python
orchestrator = PoolOrchestrator(config)

# Start all subsystems (health monitor loop, scaling loop, etc.)
await orchestrator.start()

# Get or create an instance for a project
instance = await orchestrator.get_instance(
    tenant_id="t-1",
    project_id="p-1",
    config=AgentInstanceConfig(project_id="p-1", tenant_id="t-1"),
)

# Process a chat request
result = await instance.chat(request)

# Graceful shutdown
await orchestrator.stop()
```

### Key Methods

| Method | Purpose |
|--------|---------|
| `start()` | Initialize and start all subsystems |
| `stop()` | Graceful shutdown of all subsystems |
| `get_instance(tenant_id, project_id, config)` | Get or create a managed instance |
| `destroy_instance(instance_key)` | Remove an instance with cleanup |
| `get_pool_stats()` | Aggregate statistics across all instances |
| `handle_health_event(event)` | Process a health check result |
| `trigger_scaling_evaluation()` | Force an immediate scaling check |
| `create_checkpoint(instance_key)` | Force a state checkpoint |

### Alert Integration

The orchestrator emits alerts for critical events:

```python
class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

@dataclass
class Alert:
    severity: AlertSeverity
    title: str
    message: str
    metadata: dict[str, Any]
```

Alert events include: instance failures, circuit breaker state changes, scaling actions,
and recovery escalations. The default `NullAlertService` discards alerts; production
deployments provide an implementation that sends to PagerDuty, Slack, etc.

---

## Feature Matrix

| Feature | Module | Status | HA | Persistence | Frontend |
|---------|--------|--------|----|-------------|----------|
| Agent Pool | `pool/manager.py` | Active | Yes | In-memory + Redis | Pool Dashboard |
| Lifecycle FSM | `pool/lifecycle/` | Active | -- | Via state recovery | Status Bar |
| Circuit Breaker | `pool/circuit_breaker/` | Active | -- | In-memory | -- |
| Failure Recovery | `pool/ha/failure_recovery.py` | Active | Yes | In-memory | -- |
| State Recovery | `pool/ha/state_recovery.py` | Active | Yes | Redis / in-memory | -- |
| Auto-Scaling | `pool/ha/auto_scaling.py` | Opt-in | Yes | In-memory | -- |
| Feature Flags | `pool/feature_flags.py` | Active | -- | Redis (optional) | -- |
| Multi-Channel | `channels/` | Active | -- | In-memory mapping | -- |
| Canvas (A2UI) | `canvas/` | Active | -- | In-memory | Chat UI blocks |
| Model Routing | `routing/execution_router.py` | Types only | -- | -- | -- |
| Pool Orchestrator | `pool/orchestrator.py` | Active | Yes | Delegates to subsystems | -- |

### Performance Characteristics

| Operation | Expected Latency | Notes |
|-----------|-----------------|-------|
| Instance creation | < 50ms | HOT tier pre-warmed |
| Instance lookup | < 1ms | In-memory dict |
| Health check | < 10ms | Per-instance async |
| Circuit breaker evaluation | < 0.1ms | In-memory counters |
| Checkpoint serialization | < 5ms | JSON dict conversion |
| Feature flag evaluation | < 0.1ms | SHA256 hash + comparison |
| Channel routing | < 1ms | In-memory mapping |
| Canvas block CRUD | < 1ms | In-memory state |
| Scaling decision | < 5ms | Metric comparison |

---

## Testing

All modules have corresponding test coverage:

- **Unit tests**: `src/tests/unit/` -- Domain logic, state machines, configuration validation
- **Integration tests**: `src/tests/integration/` -- Service interactions, Redis-backed recovery
- **Performance tests**: `src/tests/performance/test_pool_performance.py` -- 20 tests covering
  pool throughput, circuit breaker transitions, failure recovery selection, checkpoint
  serialization, and auto-scaler decision latency
- **E2E tests**: `web/e2e/` -- Pool Dashboard, MCP Servers, Plugin Hub, Agent Lifecycle

Run all tests:

```bash
make test                    # All tests
make test-unit               # Unit only
uv run pytest src/tests/performance/ -v  # Performance only
```
