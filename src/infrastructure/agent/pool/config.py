"""
Agent Pool 配置定义.

包含池管理、实例配置、资源配额等配置类。
"""

from dataclasses import dataclass, field

from .types import ProjectTier


@dataclass
class ResourceQuota:
    """资源配额.

    定义项目或实例的资源限制。
    """

    # 内存限制
    memory_limit_mb: int = 512
    memory_request_mb: int = 256  # 最小保证

    # CPU限制
    cpu_limit_cores: float = 1.0
    cpu_request_cores: float = 0.25  # 最小保证

    # 并发限制
    max_instances: int = 1  # 最大实例数
    max_concurrent_requests: int = 10  # 每实例最大并发

    # 执行限制
    max_execution_time_seconds: int = 300  # 单次执行最大时间
    max_steps_per_request: int = 50  # 单次请求最大步数

    def validate(self) -> list[str]:
        """验证配额设置.

        Returns:
            验证错误列表，空列表表示验证通过
        """
        errors = []
        if self.memory_limit_mb < self.memory_request_mb:
            errors.append("memory_limit_mb must >= memory_request_mb")
        if self.cpu_limit_cores < self.cpu_request_cores:
            errors.append("cpu_limit_cores must >= cpu_request_cores")
        if self.max_concurrent_requests < 1:
            errors.append("max_concurrent_requests must >= 1")
        return errors


@dataclass
class AgentInstanceConfig:
    """Agent实例配置.

    定义单个 Agent 实例的完整配置。
    """

    # 标识
    project_id: str
    tenant_id: str
    agent_mode: str = "default"

    # 分级 (可自动或手动指定)
    tier: ProjectTier = ProjectTier.WARM
    tier_override: bool = False  # 是否手动覆盖分级

    # 资源配额
    quota: ResourceQuota = field(default_factory=ResourceQuota)

    # LLM配置
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    max_steps: int = 20

    # 生命周期配置
    idle_timeout_seconds: int = 3600  # 空闲超时 (1小时)
    max_lifetime_seconds: int = 86400  # 最大生存时间 (24小时)
    health_check_interval_seconds: int = 30  # 健康检查间隔

    # 预热配置
    enable_prewarming: bool = True
    prewarm_tools: bool = True
    prewarm_llm_client: bool = True
    prewarm_mcp_tools: bool = False  # MCP工具预热较慢，默认关闭

    # 特性开关
    enable_skills: bool = True
    enable_subagents: bool = True
    enable_plan_mode: bool = True
    enable_circuit_breaker: bool = True

    # MCP配置
    mcp_tools_ttl_seconds: int = 300  # MCP工具缓存TTL

    # 重试配置
    max_retry_attempts: int = 3
    retry_delay_seconds: float = 1.0

    @property
    def instance_key(self) -> str:
        """生成实例唯一键."""
        return f"{self.tenant_id}:{self.project_id}:{self.agent_mode}"

    def with_tier(self, tier: ProjectTier) -> "AgentInstanceConfig":
        """创建指定分级的配置副本."""
        import copy

        new_config = copy.deepcopy(self)
        new_config.tier = tier
        return new_config

    def with_quota(self, quota: ResourceQuota) -> "AgentInstanceConfig":
        """创建指定配额的配置副本."""
        import copy

        new_config = copy.deepcopy(self)
        new_config.quota = quota
        return new_config


@dataclass
class TierConfig:
    """分级配置.

    定义每个分级的默认资源配额和行为。
    """

    tier: ProjectTier

    # 默认资源配额
    default_quota: ResourceQuota = field(default_factory=ResourceQuota)

    # 实例池配置
    min_instances: int = 0  # 最小实例数 (预热)
    max_instances: int = 10  # 最大实例数
    scale_up_threshold: float = 0.8  # 扩容阈值 (负载)
    scale_down_threshold: float = 0.2  # 缩容阈值 (负载)

    # 驱逐策略
    eviction_policy: str = "lru"  # lru, lfu, fifo
    eviction_idle_seconds: int = 1800  # 空闲多久后可被驱逐


# 预定义分级配置
HOT_TIER_CONFIG = TierConfig(
    tier=ProjectTier.HOT,
    default_quota=ResourceQuota(
        memory_limit_mb=2048,
        memory_request_mb=1024,
        cpu_limit_cores=2.0,
        cpu_request_cores=1.0,
        max_instances=4,
        max_concurrent_requests=50,
    ),
    min_instances=1,  # HOT tier 始终保持至少1个实例
    max_instances=4,
    eviction_idle_seconds=7200,  # 2小时
)

WARM_TIER_CONFIG = TierConfig(
    tier=ProjectTier.WARM,
    default_quota=ResourceQuota(
        memory_limit_mb=512,
        memory_request_mb=256,
        cpu_limit_cores=0.5,
        cpu_request_cores=0.25,
        max_instances=2,
        max_concurrent_requests=10,
    ),
    min_instances=0,
    max_instances=2,
    eviction_idle_seconds=1800,  # 30分钟
)

COLD_TIER_CONFIG = TierConfig(
    tier=ProjectTier.COLD,
    default_quota=ResourceQuota(
        memory_limit_mb=256,
        memory_request_mb=128,
        cpu_limit_cores=0.25,
        cpu_request_cores=0.1,
        max_instances=1,
        max_concurrent_requests=3,
    ),
    min_instances=0,
    max_instances=1,
    eviction_idle_seconds=300,  # 5分钟
)

DEFAULT_TIER_CONFIGS = {
    ProjectTier.HOT: HOT_TIER_CONFIG,
    ProjectTier.WARM: WARM_TIER_CONFIG,
    ProjectTier.COLD: COLD_TIER_CONFIG,
}


@dataclass
class PoolConfig:
    """池管理器配置."""

    # 分级配置
    tier_configs: dict[ProjectTier, TierConfig] = field(
        default_factory=lambda: DEFAULT_TIER_CONFIGS.copy()
    )

    # 全局限制
    max_total_instances: int = 100
    max_total_memory_mb: int = 32768  # 32GB
    max_total_cpu_cores: float = 16.0

    # 预热池配置
    prewarm_pool_size: int = 5  # 预热池大小
    prewarm_interval_seconds: int = 60  # 预热检查间隔

    # 健康检查配置
    health_check_interval_seconds: int = 30
    health_check_timeout_seconds: int = 10
    unhealthy_threshold: int = 3  # 连续N次失败判定为不健康
    healthy_threshold: int = 2  # 连续N次成功判定为健康

    # 熔断器配置
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout_seconds: int = 60
    circuit_breaker_half_open_requests: int = 3

    # 分级迁移配置
    tier_upgrade_threshold_days: int = 3  # 连续N天满足条件触发升级
    tier_downgrade_threshold_days: int = 7  # 连续N天满足条件触发降级
    tier_migration_cooldown_days: int = 7  # 迁移后冷却期

    # 清理配置
    cleanup_interval_seconds: int = 300  # 清理检查间隔
    terminated_instance_retention_seconds: int = 3600  # 已终止实例保留时间

    # Redis配置 (状态存储)
    redis_key_prefix: str = "agent_pool:"
    state_ttl_seconds: int = 86400  # 状态TTL (24小时)

    def get_tier_config(self, tier: ProjectTier) -> TierConfig:
        """获取分级配置."""
        return self.tier_configs.get(tier, WARM_TIER_CONFIG)


@dataclass
class ClassificationConfig:
    """分级分类配置."""

    # 请求频率权重 (40%)
    request_weight: float = 0.4
    hot_request_threshold: int = 1000  # 日均请求数 > 1000 为 HOT
    warm_request_threshold: int = 100  # 日均请求数 > 100 为 WARM

    # 付费等级权重 (30%)
    subscription_weight: float = 0.3
    enterprise_score: int = 100
    professional_score: int = 70
    basic_score: int = 40
    free_score: int = 10

    # SLA要求权重 (20%)
    sla_weight: float = 0.2
    high_sla_threshold: float = 0.999  # 99.9%
    medium_sla_threshold: float = 0.995  # 99.5%

    # 并发要求权重 (10%)
    concurrent_weight: float = 0.1
    high_concurrent_threshold: int = 10
    medium_concurrent_threshold: int = 3

    # 分级阈值
    hot_score_threshold: int = 80
    warm_score_threshold: int = 50
