# Agent Pool Architecture

## Overview

The Agent Pool Architecture provides enterprise-grade management for ReAct agents with:
- **Pooled Instance Management**: Pre-warmed agents for fast response
- **Resource Isolation**: Per-project quotas and limits
- **Lifecycle Management**: Full state machine for instance control
- **High Availability**: Automatic recovery, checkpointing, and scaling

## Architecture Diagram

```
                            ┌─────────────────────────────────────────┐
                            │           PoolOrchestrator              │
                            │  (Unified Service Management Layer)     │
                            └────────────────────┬────────────────────┘
                                                 │
        ┌────────────────────┬───────────────────┼───────────────────┬────────────────────┐
        │                    │                   │                   │                    │
        ▼                    ▼                   ▼                   ▼                    ▼
┌───────────────┐  ┌─────────────────┐  ┌───────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ AgentPool     │  │ HealthMonitor   │  │ StateRecovery │  │ FailureRecovery │  │ AutoScaling     │
│ Manager       │  │                 │  │ Service       │  │ Service         │  │ Service         │
└───────┬───────┘  └─────────────────┘  └───────────────┘  └─────────────────┘  └─────────────────┘
        │
        │  Instance Management
        │
┌───────┴───────────────────────────────────────────────────────────────────┐
│                        Three-Tier Architecture                             │
│                                                                            │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐         │
│  │    HOT Tier      │  │    WARM Tier     │  │    COLD Tier     │         │
│  │  (Container)     │  │  (Shared Pool)   │  │  (On-Demand)     │         │
│  │                  │  │                  │  │                  │         │
│  │ • Docker/K8s     │  │ • LRU Cache      │  │ • Created on     │         │
│  │ • Dedicated CPU  │  │ • Shared memory  │  │   request        │         │
│  │ • Full isolation │  │ • Fast warmup    │  │ • Destroyed      │         │
│  │ • High-traffic   │  │ • Cost-effective │  │   after use      │         │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘         │
└───────────────────────────────────────────────────────────────────────────┘
```

## Three-Tier Architecture

### HOT Tier (Container Backend)

**Use Case**: High-traffic, mission-critical projects

**Characteristics**:
- Dedicated Docker container per project
- Full resource isolation (CPU, memory, network)
- Fastest response time (< 10ms)
- Always-on, pre-initialized
- gRPC communication with main service

**Resource Allocation**:
```python
ResourceQuota(
    max_memory_mb=2048,      # 2GB dedicated memory
    max_cpu_percent=100.0,   # Full CPU core
    max_concurrent_requests=50,
    max_requests_per_minute=1000,
)
```

### WARM Tier (Shared Pool)

**Use Case**: Regular projects with moderate traffic

**Characteristics**:
- LRU-cached instances in shared memory pool
- Quick activation from warm state (< 50ms)
- Shared infrastructure, isolated execution
- Cost-effective resource usage
- Default tier for most projects

**Resource Allocation**:
```python
ResourceQuota(
    max_memory_mb=512,       # 512MB shared
    max_cpu_percent=50.0,    # Half CPU core
    max_concurrent_requests=10,
    max_requests_per_minute=100,
)
```

### COLD Tier (On-Demand)

**Use Case**: Inactive or low-traffic projects

**Characteristics**:
- Created on-demand when requested
- Destroyed after idle timeout
- Minimal resource consumption when inactive
- Higher latency for first request (< 500ms)
- Suitable for infrequent access patterns

**Resource Allocation**:
```python
ResourceQuota(
    max_memory_mb=256,       # 256MB on-demand
    max_cpu_percent=25.0,    # Quarter CPU core
    max_concurrent_requests=5,
    max_requests_per_minute=30,
)
```

## Instance Lifecycle

### State Machine

```
                                    ┌──────────────────┐
                                    │     CREATED      │
                                    └────────┬─────────┘
                                             │ initialize()
                                             ▼
                                    ┌──────────────────┐
                                    │   INITIALIZING   │
                                    └────────┬─────────┘
                                             │ ready()
                                             ▼
                          ┌─────────►┌──────────────────┐◄─────────┐
                          │          │      READY       │          │
                          │          └────────┬─────────┘          │
                          │                   │                    │
                 release()│        acquire()  │         pause()    │ resume()
                          │                   ▼                    │
                          │          ┌──────────────────┐          │
                          └──────────│      BUSY        │──────────┘
                                     └────────┬─────────┘
                                              │
                              ┌───────────────┼───────────────┐
                              │               │               │
                              ▼               ▼               ▼
                     ┌──────────────┐  ┌──────────┐  ┌──────────────┐
                     │   PAUSED     │  │  ERROR   │  │  TERMINATED  │
                     └──────────────┘  └──────────┘  └──────────────┘
```

### State Descriptions

| State | Description | Transitions |
|-------|-------------|-------------|
| `CREATED` | Instance created, not yet initialized | → INITIALIZING |
| `INITIALIZING` | Loading tools, LLM connections | → READY, ERROR |
| `READY` | Available for requests | → BUSY, PAUSED, TERMINATED |
| `BUSY` | Processing a request | → READY, ERROR |
| `PAUSED` | Temporarily suspended | → READY, TERMINATED |
| `ERROR` | Recoverable error state | → INITIALIZING, TERMINATED |
| `TERMINATED` | Instance destroyed | (final state) |

## High Availability Features

### State Recovery Service

Provides crash recovery through Redis-backed checkpointing:

```python
# Automatic checkpointing
checkpoint = StateCheckpoint(
    instance_id="inst-123",
    project_id="proj-456",
    state=InstanceState.READY,
    metadata={"last_request_id": "req-789"},
    created_at=datetime.utcnow(),
)
await state_recovery.checkpoint(checkpoint)

# Recovery after restart
instances = await state_recovery.recover_all()
```

**Configuration**:
```bash
AGENT_POOL_CHECKPOINT_INTERVAL=60        # Checkpoint every 60 seconds
AGENT_POOL_CHECKPOINT_STORAGE=redis      # redis or memory
```

### Failure Recovery Service

Automatic recovery with escalating strategies:

| Strategy | Description | Use Case |
|----------|-------------|----------|
| `RESTART` | Restart the instance | Transient failures |
| `RECOVER` | Restore from checkpoint | State corruption |
| `MIGRATE` | Move to different tier | Resource exhaustion |
| `ESCALATE` | Alert administrators | Persistent failures |

**Configuration**:
```bash
AGENT_POOL_MAX_FAILURES_PER_HOUR=5       # Failure threshold
AGENT_POOL_PATTERN_DETECTION_WINDOW=60   # Pattern detection window (minutes)
```

### Auto Scaling Service

Automatic scaling based on metrics:

```python
ScalingPolicy(
    min_instances=2,
    max_instances=20,
    scale_up_threshold=0.8,    # 80% utilization
    scale_down_threshold=0.3,  # 30% utilization
    cooldown_seconds=300,      # 5 minutes between scaling
)
```

**Scaling Triggers**:
- CPU utilization threshold
- Memory utilization threshold
- Request queue depth
- Response latency percentiles

### Circuit Breaker

Prevents cascade failures with exponential backoff:

```python
CircuitBreakerConfig(
    failure_threshold=5,       # Open after 5 failures
    reset_timeout_seconds=30,  # Try half-open after 30s
    half_open_max_requests=3,  # Allow 3 test requests
)
```

**States**:
- `CLOSED`: Normal operation
- `OPEN`: Blocking requests
- `HALF_OPEN`: Testing recovery

## API Reference

### REST Endpoints

```
GET  /api/v1/pool/stats              # Pool statistics
GET  /api/v1/pool/instances          # List all instances
GET  /api/v1/pool/instances/:id      # Get instance details
POST /api/v1/pool/instances          # Create instance
DELETE /api/v1/pool/instances/:id    # Destroy instance

POST /api/v1/pool/instances/:id/pause    # Pause instance
POST /api/v1/pool/instances/:id/resume   # Resume instance

GET  /api/v1/pool/health             # Pool health check
GET  /api/v1/pool/metrics            # Prometheus metrics
```

### Metrics

Prometheus-compatible metrics at `/api/v1/pool/metrics`:

```
# Instance counts
agent_pool_instances_total{tier="WARM",state="READY"} 10

# Request metrics
agent_pool_requests_total{status="success"} 1000
agent_pool_request_latency_seconds{quantile="0.99"} 0.05

# Resource usage
agent_pool_memory_bytes{instance_id="inst-123"} 268435456
agent_pool_cpu_percent{instance_id="inst-123"} 25.5

# Circuit breaker
agent_pool_circuit_breaker_state{instance_id="inst-123"} 0
```

## Feature Flags

Gradual rollout support with multiple strategies:

### Strategies

| Strategy | Description | Example |
|----------|-------------|---------|
| `ALL` | Enabled for everyone | Production ready features |
| `NONE` | Disabled for everyone | Experimental features |
| `PERCENTAGE` | Enabled for X% of requests | Gradual rollout |
| `ALLOWLIST` | Enabled for specific tenants/projects | Beta testing |
| `DENYLIST` | Disabled for specific tenants/projects | Excluding problematic users |
| `GRADUAL` | Automatic percentage increase | Phased deployment |

### Configuration

```python
# Enable pool for 50% of requests
feature_flags.set_flag(
    "agent_pool_enabled",
    FeatureFlagConfig(
        enabled=True,
        strategy=RolloutStrategy.PERCENTAGE,
        percentage=50.0,
    )
)

# Enable HOT tier for specific tenants
feature_flags.enable_for_tenant("agent_pool_hot_tier", "tenant-123")
```

## Configuration Reference

### Environment Variables

```bash
# Core Pool Settings
AGENT_POOL_ENABLED=true                    # Enable pool architecture
AGENT_POOL_MAX_INSTANCES=100               # Maximum total instances
AGENT_POOL_DEFAULT_TIER=WARM               # Default tier (HOT/WARM/COLD)
AGENT_POOL_WARMUP_COUNT=5                  # Pre-warmed instances
AGENT_POOL_MAX_IDLE_SECONDS=300            # Idle timeout before cleanup

# Health Monitoring
AGENT_POOL_HEALTH_CHECK_INTERVAL=30        # Health check interval (seconds)
AGENT_POOL_HEALTH_CHECK_TIMEOUT=10         # Health check timeout (seconds)

# High Availability
AGENT_POOL_ENABLE_HA=true                  # Enable HA features
AGENT_POOL_CHECKPOINT_INTERVAL=60          # State checkpoint interval
AGENT_POOL_CHECKPOINT_STORAGE=redis        # Checkpoint storage (redis/memory)
AGENT_POOL_MAX_FAILURES_PER_HOUR=5         # Failure threshold for recovery

# Auto Scaling
AGENT_POOL_ENABLE_AUTO_SCALING=false       # Enable auto scaling
AGENT_POOL_SCALE_UP_THRESHOLD=0.8          # Scale up at 80% utilization
AGENT_POOL_SCALE_DOWN_THRESHOLD=0.3        # Scale down at 30% utilization
AGENT_POOL_SCALING_COOLDOWN=300            # Cooldown between scaling (seconds)

# Circuit Breaker
AGENT_POOL_CIRCUIT_FAILURE_THRESHOLD=5     # Failures before circuit opens
AGENT_POOL_CIRCUIT_RESET_TIMEOUT=30        # Seconds before half-open

# Related SubAgent Runtime Controls (orchestration behavior)
AGENT_SUBAGENT_MAX_DELEGATION_DEPTH=2
AGENT_SUBAGENT_MAX_ACTIVE_RUNS=16
AGENT_SUBAGENT_MAX_CHILDREN_PER_REQUESTER=8
AGENT_SUBAGENT_LANE_CONCURRENCY=8
AGENT_SUBAGENT_TERMINAL_RETENTION_SECONDS=86400
AGENT_SUBAGENT_ANNOUNCE_MAX_EVENTS=20
AGENT_SUBAGENT_ANNOUNCE_MAX_RETRIES=2
AGENT_SUBAGENT_ANNOUNCE_RETRY_DELAY_MS=200
AGENT_SUBAGENT_FOCUS_TTL_SECONDS=300
```

### Python Configuration

```python
from src.infrastructure.agent.pool import PoolConfig, ResourceQuota, ProjectTier

config = PoolConfig(
    max_instances=100,
    default_tier=ProjectTier.WARM,
    warmup_count=5,
    max_idle_seconds=300,
    health_check_interval_seconds=30,
    enable_ha=True,
    enable_auto_scaling=False,
)

quota = ResourceQuota(
    max_memory_mb=512,
    max_cpu_percent=50.0,
    max_concurrent_requests=10,
    max_requests_per_minute=100,
)
```

## Performance Benchmarks

### Latency Comparison

| Operation | Old Architecture | Pool Architecture | Improvement |
|-----------|------------------|-------------------|-------------|
| First request | ~2000ms | ~50ms | 40x faster |
| Subsequent requests | ~2000ms | ~5ms | 400x faster |
| Instance creation | ~2000ms | ~1ms | 2000x faster |
| Pool acquire/release | N/A | ~2ms | N/A |

### Resource Efficiency

| Metric | Old | New | Improvement |
|--------|-----|-----|-------------|
| Memory per project | ~200MB | ~50MB | 4x less |
| Max concurrent projects | ~10 | ~100 | 10x more |
| CPU per idle project | ~5% | ~0.1% | 50x less |

### Running Benchmarks

```bash
# Run performance benchmarks
pytest src/tests/performance/test_agent_pool_benchmarks.py -v -m performance

# Run with output
pytest src/tests/performance/test_agent_pool_benchmarks.py -v -m performance -s
```

## File Structure

```
src/infrastructure/agent/pool/
├── __init__.py                 # Module exports
├── manager.py                  # AgentPoolManager
├── instance.py                 # AgentInstance
├── config.py                   # PoolConfig, ResourceQuota
├── types.py                    # Enums, types
├── orchestrator.py             # PoolOrchestrator (unified management)
├── feature_flags.py            # Feature flag system
├── adapter.py                  # Legacy adapter
├── worker_state.py             # Worker state management
│
├── backends/
│   ├── base.py                 # Backend interface
│   ├── container_backend.py    # HOT tier (Docker)
│   ├── shared_pool_backend.py  # WARM tier (LRU)
│   └── ondemand_backend.py     # COLD tier
│
├── container/
│   ├── Dockerfile.agent        # Agent container image
│   ├── agent_pool.proto        # gRPC protocol
│   └── server.py               # gRPC server
│
├── ha/
│   ├── state_recovery.py       # Checkpointing
│   ├── failure_recovery.py     # Auto recovery
│   └── auto_scaling.py         # Scaling service
│
├── health/
│   └── monitor.py              # Health monitoring
│
├── metrics/
│   └── collector.py            # Prometheus metrics
│
├── lifecycle/
│   └── state_machine.py        # State transitions
│
├── resource/
│   └── manager.py              # Resource quotas
│
├── prewarm/
│   └── pool.py                 # Pre-warm pool
│
├── classification/
│   └── classifier.py           # Project tier classifier
│
└── circuit_breaker/
    └── breaker.py              # Circuit breaker
```

## Migration Guide

### Enabling Pool Architecture

1. **Set environment variable**:
   ```bash
   AGENT_POOL_ENABLED=true
   ```

2. **Restart services**:
   ```bash
   make restart
   ```

3. **Verify pool status**:
   ```bash
   curl http://localhost:8000/api/v1/pool/stats
   ```

### Gradual Rollout

1. **Start with allowlist**:
   ```python
   feature_flags.enable_for_tenant("agent_pool_enabled", "test-tenant")
   ```

2. **Increase percentage**:
   ```python
   feature_flags.set_percentage("agent_pool_enabled", 25.0)  # 25%
   feature_flags.set_percentage("agent_pool_enabled", 50.0)  # 50%
   feature_flags.set_percentage("agent_pool_enabled", 100.0) # 100%
   ```

3. **Monitor metrics**:
   - Request latency
   - Error rates
   - Resource utilization

### Rollback

```python
# Disable pool
feature_flags.set_flag(
    "agent_pool_enabled",
    FeatureFlagConfig(enabled=False, strategy=RolloutStrategy.NONE)
)
```

## Development Notes

### API Method Conventions (Async vs Sync)

When extending the pool API router, be aware of the sync/async nature of pool manager methods:

| Method | Type | Notes |
|--------|------|-------|
| `get_stats()` | **sync** | Returns PoolStats directly, do NOT await |
| `classify_project()` | async | Awaitable, returns ProjectTier |
| `set_project_tier()` | async | Awaitable |
| `terminate_instance()` | async | Awaitable |
| `get_or_create_instance()` | async | Awaitable |
| `get_global_adapter()` | async | Session adapter factory, must await |

**Example (Correct)**:
```python
# Sync method - no await
stats = manager.get_stats()

# Async method - must await
tier = await manager.classify_project(tenant_id, project_id)

# Async adapter lookup
adapter = await get_global_adapter()
```

**Common Mistakes**:
```python
# ❌ WRONG: get_stats() is sync
stats = await manager.get_stats()  # TypeError: can't be used in 'await' expression

# ❌ WRONG: get_global_adapter() is async
adapter = get_global_adapter()  # Returns coroutine, not adapter
if adapter._pool_manager:  # AttributeError: 'coroutine' object has no attribute

# ❌ WRONG: TierConfig requires 'tier' argument
TierConfig(max_instances=100)  # TypeError: missing required argument 'tier'

# ✅ CORRECT: Always provide tier
TierConfig(tier=ProjectTier.WARM, max_instances=100)
```

### Configuration Dataclass Fields

When creating configuration objects, ensure required fields are provided:

| Class | Required Fields | Notes |
|-------|-----------------|-------|
| `TierConfig` | `tier` | Must be a `ProjectTier` enum value |
| `InstanceConfig` | `tenant_id`, `project_id` | Identifies the instance |
| `ResourceQuota` | (none) | All fields have defaults |
| `PoolConfig` | (none) | All fields have defaults |

### LLM Client Integration

The ReActAgent stack now integrates with the system `LiteLLMClient` for unified resilience:

**Architecture Flow**:
```
ProjectReActAgent
    └── get_or_create_llm_client(provider_config)
          └── LiteLLMClient (cached per provider:model)
                ├── Rate Limiter (per-provider semaphores)
                └── Circuit Breaker (failure tracking)

ReActAgent
    └── ProcessorConfig(llm_client=...)
          └── SessionProcessor
                └── LLMStream(config, llm_client=...)
                      ├── _generate_with_client() ← Uses client (preferred)
                      └── _generate_direct()      ← Fallback (basic rate limiting)
```

**Key Benefits**:
- **Unified Resilience**: Circuit breaker + rate limiter across all LLM calls
- **Connection Reuse**: Cached LiteLLMClient instances per provider:model
- **Backward Compatibility**: Falls back to direct litellm calls if no client

**Code Example**:
```python
# Client is injected via ProcessorConfig
processor_config = ProcessorConfig(
    model="qwen-turbo",
    llm_client=llm_client,  # From get_or_create_llm_client()
)

# LLMStream uses client if available
llm_stream = LLMStream(stream_config, llm_client=processor_config.llm_client)
```

## Troubleshooting

### Common Issues

**Issue**: Slow first request
- **Cause**: Cold start, no warm instances
- **Solution**: Increase `AGENT_POOL_WARMUP_COUNT`

**Issue**: Memory exhaustion
- **Cause**: Too many HOT tier instances
- **Solution**: Reduce HOT tier quota, increase WARM tier usage

**Issue**: Circuit breaker constantly open
- **Cause**: Underlying service failures
- **Solution**: Check LLM provider connectivity, increase timeout

**Issue**: Instances stuck in INITIALIZING
- **Cause**: Tool loading failures
- **Solution**: Check tool configurations, verify MCP connections

### Debug Commands

```bash
# Check pool status
curl http://localhost:8000/api/v1/pool/stats | jq

# List instances
curl http://localhost:8000/api/v1/pool/instances | jq

# Check specific instance
curl http://localhost:8000/api/v1/pool/instances/inst-123 | jq

# View metrics
curl http://localhost:8000/api/v1/pool/metrics
```

## References

- [PoolOrchestrator Implementation](../../src/infrastructure/agent/pool/orchestrator.py)
- [Feature Flags Implementation](../../src/infrastructure/agent/pool/feature_flags.py)
- [Performance Benchmarks](../../src/tests/performance/test_agent_pool_benchmarks.py)
