"""
Agent Pool - ReActAgent 池化管理模块.

提供企业级 Agent 实例池化管理能力:
- 项目资源隔离 (HOT/WARM/COLD 分层)
- 完整生命周期管理
- 健康监控与自动恢复
- 动态扩缩容

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
from .backends.ondemand_backend import OnDemandBackend, OnDemandConfig
from .backends.shared_pool_backend import SharedPoolBackend, SharedPoolConfig

# Circuit Breaker
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError

# Classification
from .classification import ClassificationResult, ProjectClassifier
from .config import AgentInstanceConfig, PoolConfig, ResourceQuota

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
    # Core
    "AgentPoolManager",
    "AgentInstance",
    "ChatRequest",
    "ChatResult",
    # Config
    "AgentInstanceConfig",
    "PoolConfig",
    "ResourceQuota",
    # Types
    "ProjectTier",
    "AgentInstanceStatus",
    "HealthStatus",
    "HealthCheckResult",
    "CircuitState",
    "RecoveryAction",
    "InstanceMetrics",
    "ResourceUsage",
    "PoolStats",
    "ProjectMetrics",
    "TierMigration",
    "LifecycleEvent",
    # Lifecycle
    "LifecycleStateMachine",
    "InvalidStateTransitionError",
    # Resource
    "ResourceManager",
    "QuotaExceededError",
    # Health
    "HealthMonitor",
    "HealthMonitorConfig",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitOpenError",
    # Backends
    "Backend",
    "BackendType",
    "SharedPoolBackend",
    "SharedPoolConfig",
    "OnDemandBackend",
    "OnDemandConfig",
    # Prewarm
    "PrewarmPool",
    "PrewarmConfig",
    # Classification
    "ProjectClassifier",
    "ClassificationResult",
    # Integration
    "PooledAgentSessionAdapter",
    "AdapterConfig",
    "SessionRequest",
    "create_pooled_adapter",
    "get_global_adapter",
    "shutdown_global_adapter",
]

# Integration (lazy import to avoid circular dependencies)
from .integration import PooledAgentSessionAdapter
from .integration.session_adapter import (
    AdapterConfig,
    SessionRequest,
    create_pooled_adapter,
    get_global_adapter,
    shutdown_global_adapter,
)
