"""
Agent Pool - ReActAgent 池化管理模块.

提供企业级 Agent 实例池化管理能力:
- 项目资源隔离 (HOT/WARM/COLD 分层)
- 完整生命周期管理
- 健康监控与自动恢复
- 动态扩缩容
- 容器化隔离 (Docker/K8s)
- 高可用 (状态恢复、故障自愈)

Usage:
    from src.infrastructure.agent.pool import AgentPoolManager

    pool_manager = AgentPoolManager()
    instance = await pool_manager.get_or_create_instance(
        tenant_id="tenant-123",
        project_id="project-456"
    )
"""

# Backends
from .backends import Backend, BackendType
from .backends.container_backend import ContainerBackend, ContainerConfig
from .backends.ondemand_backend import OnDemandBackend, OnDemandConfig
from .backends.shared_pool_backend import SharedPoolBackend, SharedPoolConfig

# Circuit Breaker
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError

# Classification
from .classification import ClassificationResult, ProjectClassifier
from .config import AgentInstanceConfig, PoolConfig, ResourceQuota

# High Availability
from .ha import (
    AutoScalingService,
    CheckpointType,
    FailureEvent,
    FailureRecoveryService,
    FailureType,
    RecoveryResult,
    ScalingDecision,
    ScalingDirection,
    ScalingMetrics,
    ScalingPolicy,
    StateCheckpoint,
    StateRecoveryService,
)

# Health
from .health import HealthMonitor, HealthMonitorConfig
from .instance import AgentInstance, ChatRequest, ChatResult

# Lifecycle
from .lifecycle import InvalidStateTransitionError, LifecycleStateMachine
from .manager import AgentPoolManager

# Prewarm
from .prewarm import PrewarmConfig, PrewarmPool

# Resource
from .resource import QuotaExceededError, ResourceManager
from .types import (
    AgentInstanceStatus,
    CircuitState,
    HealthCheckResult,
    HealthStatus,
    InstanceMetrics,
    LifecycleEvent,
    PoolStats,
    ProjectMetrics,
    ProjectTier,
    RecoveryAction,
    ResourceUsage,
    TierMigration,
)

__all__ = [
    "AdapterConfig",
    "AgentInstance",
    # Config
    "AgentInstanceConfig",
    "AgentInstanceStatus",
    # Core
    "AgentPoolManager",
    "AutoScalingService",
    # Backends
    "Backend",
    "BackendType",
    "ChatRequest",
    "ChatResult",
    "CheckpointType",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitOpenError",
    "CircuitState",
    "ClassificationResult",
    "ContainerBackend",
    "ContainerConfig",
    "FailureEvent",
    "FailureRecoveryService",
    "FailureType",
    "FeatureFlagConfig",
    # Feature Flags
    "FeatureFlags",
    "HealthCheckResult",
    # Health
    "HealthMonitor",
    "HealthMonitorConfig",
    "HealthStatus",
    "InstanceMetrics",
    "InvalidStateTransitionError",
    "LifecycleEvent",
    # Lifecycle
    "LifecycleStateMachine",
    "OnDemandBackend",
    "OnDemandConfig",
    "OrchestratorConfig",
    "PoolConfig",
    # Orchestrator
    "PoolOrchestrator",
    "PoolStats",
    # Integration
    "PooledAgentSessionAdapter",
    "PrewarmConfig",
    # Prewarm
    "PrewarmPool",
    # Classification
    "ProjectClassifier",
    "ProjectMetrics",
    # Types
    "ProjectTier",
    "QuotaExceededError",
    "RecoveryAction",
    "RecoveryResult",
    # Resource
    "ResourceManager",
    "ResourceQuota",
    "ResourceUsage",
    "RolloutStrategy",
    "ScalingDecision",
    "ScalingDirection",
    "ScalingMetrics",
    "ScalingPolicy",
    "SessionRequest",
    "SharedPoolBackend",
    "SharedPoolConfig",
    "StateCheckpoint",
    # High Availability
    "StateRecoveryService",
    "TierMigration",
    "create_orchestrator",
    "create_pooled_adapter",
    "get_feature_flags",
    "get_global_adapter",
    "get_global_orchestrator",
    "shutdown_global_adapter",
    "shutdown_global_orchestrator",
]

# Integration (lazy import to avoid circular dependencies)
# API
from .api import create_pool_router

# Feature Flags
from .feature_flags import (
    FeatureFlagConfig,
    FeatureFlags,
    RolloutStrategy,
    get_feature_flags,
)
from .integration import PooledAgentSessionAdapter
from .integration.session_adapter import (
    AdapterConfig,
    SessionRequest,
    create_pooled_adapter,
    get_global_adapter,
    shutdown_global_adapter,
)

# Metrics
from .metrics import PoolMetricsCollector, get_metrics_collector

# Orchestrator
from .orchestrator import (
    OrchestratorConfig,
    PoolOrchestrator,
    create_orchestrator,
    get_global_orchestrator,
    shutdown_global_orchestrator,
)

__all__ += [
    "PoolMetricsCollector",
    "create_pool_router",
    "get_metrics_collector",
]
