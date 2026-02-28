"""Configuration management for MemStack."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # API Settings
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_workers: int = Field(default=4, alias="API_WORKERS")
    api_allowed_origins: str | list[str] = Field(default=["*"], alias="API_ALLOWED_ORIGINS")

    # Database Settings
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="password", alias="NEO4J_PASSWORD")

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="memstack", alias="POSTGRES_DB")
    postgres_user: str = Field(default="postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(default="password", alias="POSTGRES_PASSWORD")

    # PostgreSQL Connection Pool Settings (for high concurrency)
    postgres_pool_size: int = Field(default=20, alias="POSTGRES_POOL_SIZE")
    postgres_max_overflow: int = Field(default=40, alias="POSTGRES_MAX_OVERFLOW")
    postgres_pool_recycle: int = Field(default=3600, alias="POSTGRES_POOL_RECYCLE")
    postgres_pool_pre_ping: bool = Field(default=True, alias="POSTGRES_POOL_PRE_PING")

    # PostgreSQL Read Replica Settings (for read scaling)
    postgres_read_replica_host: str | None = Field(default=None, alias="POSTGRES_READ_REPLICA_HOST")
    postgres_read_replica_port: int = Field(default=5432, alias="POSTGRES_READ_REPLICA_PORT")

    # Redis Settings
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: str | None = Field(default=None, alias="REDIS_PASSWORD")

    # Audit Log Settings
    audit_log_backend: str = Field(
        default="database", alias="AUDIT_LOG_BACKEND"
    )  # database, file, console
    audit_log_file: str | None = Field(default=None, alias="AUDIT_LOG_FILE")

    # Alerting Settings
    alert_slack_webhook_url: str | None = Field(default=None, alias="ALERT_SLACK_WEBHOOK_URL")
    alert_slack_channel: str | None = Field(default=None, alias="ALERT_SLACK_CHANNEL")
    alert_email_smtp_host: str | None = Field(default=None, alias="ALERT_EMAIL_SMTP_HOST")
    alert_email_smtp_port: int = Field(default=587, alias="ALERT_EMAIL_SMTP_PORT")
    alert_email_username: str | None = Field(default=None, alias="ALERT_EMAIL_USERNAME")
    alert_email_password: str | None = Field(default=None, alias="ALERT_EMAIL_PASSWORD")
    alert_email_from: str | None = Field(default=None, alias="ALERT_EMAIL_FROM")
    alert_email_to: str | None = Field(default=None, alias="ALERT_EMAIL_TO")

    # LLM Provider API Key Encryption
    # 32-byte (256-bit) encryption key as hex string (64 hex characters)
    # Generate with: python -c "import os; print(os.urandom(32).hex())"
    llm_encryption_key: str | None = Field(default=None, alias="LLM_ENCRYPTION_KEY")

    # Web Search Settings (Tavily API)
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    tavily_max_results: int = Field(default=10, alias="TAVILY_MAX_RESULTS")
    tavily_search_depth: str = Field(default="basic", alias="TAVILY_SEARCH_DEPTH")
    tavily_include_domains: list[str] | None = Field(default=None, alias="TAVILY_INCLUDE_DOMAINS")
    tavily_exclude_domains: list[str] | None = Field(default=None, alias="TAVILY_EXCLUDE_DOMAINS")

    # Web Scraping Settings (Playwright)
    playwright_timeout: int = Field(default=30000, alias="PLAYWRIGHT_TIMEOUT")
    playwright_headless: bool = Field(default=True, alias="PLAYWRIGHT_HEADLESS")
    playwright_max_content_length: int = Field(default=10000, alias="PLAYWRIGHT_MAX_CONTENT_LENGTH")
    web_search_cache_ttl: int = Field(default=3600, alias="WEB_SEARCH_CACHE_TTL")

    # Security
    secret_key: str = Field(default="dev-secret-key-change-in-production", alias="SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # API Key Settings
    require_api_key: bool = Field(default=True, alias="REQUIRE_API_KEY")
    api_key_header_name: str = Field(default="Authorization", alias="API_KEY_HEADER_NAME")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")

    # Graphiti Settings
    graphiti_semaphore_limit: int = Field(default=10, alias="GRAPHITI_SEMAPHORE_LIMIT")
    max_async_workers: int = Field(default=20, alias="MAX_ASYNC_WORKERS")
    run_background_workers: bool = Field(default=True, alias="RUN_BACKGROUND_WORKERS")
    queue_batch_size: int = Field(default=1, alias="QUEUE_BATCH_SIZE")

    # Temporal Workflow Engine Settings (background workflows)
    # Note: Agent execution uses Ray Actors; Temporal remains for background workflows.

    # Embedding Management
    auto_clear_mismatched_embeddings: bool = Field(
        default=True, alias="AUTO_CLEAR_MISMATCHED_EMBEDDINGS"
    )
    embedding_dimension: int | None = Field(
        default=None,
        alias="EMBEDDING_DIMENSION",
        description="Embedding vector dimension. Auto-detected from provider if None. "
        "Common values: 1024 (Qwen/Dashscope), 1536 (OpenAI ada-002), 768 (Gemini).",
    )
    embedding_index_auto_create: bool = Field(
        default=True,
        alias="EMBEDDING_INDEX_AUTO_CREATE",
        description="Auto-create vector indices on startup if missing.",
    )

    # LLM Timeout & Concurrency Settings
    llm_timeout: int = Field(
        default=300, alias="LLM_TIMEOUT"
    )  # Increased from 60 to 300 (5 minutes)
    llm_stream_timeout: int = Field(
        default=600, alias="LLM_STREAM_TIMEOUT"
    )  # 10 minutes for streaming
    llm_concurrency_limit: int = Field(
        default=8, alias="LLM_CONCURRENCY_LIMIT"
    )  # Limit concurrent requests to provider
    llm_max_retries: int = Field(
        default=3, alias="LLM_MAX_RETRIES"
    )  # Max retries for failed requests
    llm_cache_enabled: bool = Field(default=True, alias="LLM_CACHE_ENABLED")
    llm_cache_ttl: int = Field(default=3600, alias="LLM_CACHE_TTL")

    # Agent Event & Artifact Settings
    agent_emit_thoughts: bool = Field(default=True, alias="AGENT_EMIT_THOUGHTS")
    agent_persist_thoughts: bool = Field(default=True, alias="AGENT_PERSIST_THOUGHTS")
    agent_persist_detail_events: bool = Field(default=True, alias="AGENT_PERSIST_DETAIL_EVENTS")
    agent_artifact_inline_max_bytes: int = Field(
        default=4096, alias="AGENT_ARTIFACT_INLINE_MAX_BYTES"
    )
    agent_artifact_url_ttl_seconds: int = Field(
        default=3600000, alias="AGENT_ARTIFACT_URL_TTL_SECONDS"
    )

    # Agent Session Prewarm (reduce first-request latency)
    agent_session_prewarm_enabled: bool = Field(default=True, alias="AGENT_SESSION_PREWARM_ENABLED")
    agent_session_prewarm_max_projects: int = Field(
        default=20, alias="AGENT_SESSION_PREWARM_MAX_PROJECTS"
    )
    agent_session_prewarm_concurrency: int = Field(
        default=4, alias="AGENT_SESSION_PREWARM_CONCURRENCY"
    )

    # Agent Session Pool TTL (cleanup after inactivity)
    agent_session_ttl_seconds: int = Field(
        default=86400,
        alias="AGENT_SESSION_TTL_SECONDS",  # 24 hours default
    )
    agent_subagent_max_delegation_depth: int = Field(
        default=2,
        alias="AGENT_SUBAGENT_MAX_DELEGATION_DEPTH",
        ge=1,
    )
    agent_subagent_max_active_runs: int = Field(
        default=16,
        alias="AGENT_SUBAGENT_MAX_ACTIVE_RUNS",
        ge=1,
    )
    agent_subagent_max_children_per_requester: int = Field(
        default=8,
        alias="AGENT_SUBAGENT_MAX_CHILDREN_PER_REQUESTER",
        ge=1,
    )
    agent_subagent_lane_concurrency: int = Field(
        default=8,
        alias="AGENT_SUBAGENT_LANE_CONCURRENCY",
        ge=1,
    )
    agent_subagent_terminal_retention_seconds: int = Field(
        default=86400,
        alias="AGENT_SUBAGENT_TERMINAL_RETENTION_SECONDS",
        ge=0,
    )
    agent_subagent_announce_max_events: int = Field(
        default=20,
        alias="AGENT_SUBAGENT_ANNOUNCE_MAX_EVENTS",
        ge=1,
    )
    agent_subagent_announce_max_retries: int = Field(
        default=2,
        alias="AGENT_SUBAGENT_ANNOUNCE_MAX_RETRIES",
        ge=0,
    )
    agent_subagent_announce_retry_delay_ms: int = Field(
        default=200,
        alias="AGENT_SUBAGENT_ANNOUNCE_RETRY_DELAY_MS",
        ge=0,
    )
    agent_subagent_focus_ttl_seconds: float = Field(
        default=300.0,
        alias="AGENT_SUBAGENT_FOCUS_TTL_SECONDS",  # 5 minutes default
        ge=0.0,
    )

    # HITL (Human-in-the-Loop) Real-time Optimization
    # Uses Redis Streams for low-latency (~30ms) HITL response delivery
    hitl_realtime_enabled: bool = Field(default=True, alias="HITL_REALTIME_ENABLED")

    # Agent Execution Limits
    agent_runtime_mode: Literal["auto", "ray", "local"] = Field(
        default="auto",
        alias="AGENT_RUNTIME_MODE",
    )  # Runtime mode: auto (prefer ray), ray (ray only), local (local only)
    agent_max_steps: int = Field(
        default=5000, alias="AGENT_MAX_STEPS"
    )  # Maximum steps for ReActAgent execution
    agent_max_tokens: int = Field(
        default=16384, alias="AGENT_MAX_TOKENS"
    )  # Maximum output tokens for LLM responses (increased for large file writes)

    # Agent Pool Management (NEW: 3-tier pooled architecture)
    agent_pool_enabled: bool = Field(
        default=False, alias="AGENT_POOL_ENABLED"
    )  # Enable new pooled architecture
    agent_pool_default_tier: str = Field(
        default="warm", alias="AGENT_POOL_DEFAULT_TIER"
    )  # Default tier for new projects: hot, warm, cold
    agent_pool_warm_max_instances: int = Field(
        default=100, alias="AGENT_POOL_WARM_MAX_INSTANCES"
    )  # Max WARM tier instances
    agent_pool_cold_max_instances: int = Field(
        default=200, alias="AGENT_POOL_COLD_MAX_INSTANCES"
    )  # Max COLD tier instances
    agent_pool_cold_idle_timeout_seconds: int = Field(
        default=300, alias="AGENT_POOL_COLD_IDLE_TIMEOUT"
    )  # COLD tier idle timeout (5 min)
    agent_pool_health_check_interval_seconds: int = Field(
        default=30, alias="AGENT_POOL_HEALTH_CHECK_INTERVAL"
    )  # Health check interval

    # Monitoring
    enable_metrics: bool = Field(default=True, alias="ENABLE_METRICS")
    metrics_port: int = Field(default=9090, alias="METRICS_PORT")

    # S3 Storage Settings (MinIO for local dev)
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    aws_access_key_id: str | None = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str | None = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    s3_bucket_name: str = Field(default="memstack-files", alias="S3_BUCKET_NAME")
    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    s3_no_proxy: bool = Field(default=True, alias="S3_NO_PROXY")
    presigned_url_expiration: int = Field(default=3600, alias="PRESIGNED_URL_EXPIRATION")

    # Upload Size Limits (in MB)
    upload_max_size_llm_mb: int = Field(
        default=100, alias="UPLOAD_MAX_SIZE_LLM_MB"
    )  # Max file size for LLM context uploads
    upload_max_size_sandbox_mb: int = Field(
        default=100, alias="UPLOAD_MAX_SIZE_SANDBOX_MB"
    )  # Max file size for sandbox input uploads

    # Sandbox Settings
    sandbox_default_provider: str = Field(default="docker", alias="SANDBOX_DEFAULT_PROVIDER")
    sandbox_default_image: str = Field(
        default="sandbox-mcp-server:latest", alias="SANDBOX_DEFAULT_IMAGE"
    )
    sandbox_workspace_base: str = Field(
        default="/tmp/memstack-sandbox", alias="SANDBOX_WORKSPACE_BASE"
    )  # Base directory for sandbox workspaces (use /tmp for macOS compatibility)
    sandbox_timeout_seconds: int = Field(
        default=300, alias="SANDBOX_TIMEOUT_SECONDS"
    )  # Increased from 60 to 300 (5 minutes)
    sandbox_memory_limit: str = Field(default="2G", alias="SANDBOX_MEMORY_LIMIT")
    sandbox_cpu_limit: str = Field(default="2", alias="SANDBOX_CPU_LIMIT")
    sandbox_network_isolated: bool = Field(default=True, alias="SANDBOX_NETWORK_ISOLATED")
    sandbox_profile_type: str = Field(default="standard", alias="SANDBOX_PROFILE_TYPE")
    sandbox_auto_recover: bool = Field(default=True, alias="SANDBOX_AUTO_RECOVER")
    sandbox_health_check_interval: int = Field(default=60, alias="SANDBOX_HEALTH_CHECK_INTERVAL")
    sandbox_host_source_path: str = Field(
        default="", alias="SANDBOX_HOST_SOURCE_PATH"
    )  # Host path to mount read-only into sandbox (e.g., /path/to/project/src)
    sandbox_host_source_mount_point: str = Field(
        default="/host_src", alias="SANDBOX_HOST_SOURCE_MOUNT_POINT"
    )  # Container path where host source is mounted (read-only)
    sandbox_host_memstack_path: str = Field(
        default="", alias="SANDBOX_HOST_MEMSTACK_PATH"
    )  # Host path to .memstack dir for rw mount (e.g., /path/to/project/.memstack)
    sandbox_host_memstack_mount_point: str = Field(
        default="/workspace/.memstack",
        alias="SANDBOX_HOST_MEMSTACK_MOUNT_POINT",
    )  # Container path where .memstack is mounted (read-write overlay)

    # Agent Skill System (L2 Layer) Settings
    # Threshold for skill prompt injection (0.5 = medium match score)
    agent_skill_match_threshold: float = Field(default=0.5, alias="AGENT_SKILL_MATCH_THRESHOLD")
    # Whether to fallback to LLM when skill execution fails
    agent_skill_fallback_on_error: bool = Field(default=True, alias="AGENT_SKILL_FALLBACK_ON_ERROR")
    # Timeout for skill direct execution in seconds
    agent_skill_execution_timeout: int = Field(
        default=300, alias="AGENT_SKILL_EXECUTION_TIMEOUT"
    )  # Increased from 60 to 300 (5 minutes)

    # Workspace Persona System Settings (.memstack/workspace/)
    workspace_enabled: bool = Field(default=True, alias="WORKSPACE_ENABLED")
    workspace_dir: str = Field(
        default="/workspace/.memstack/workspace", alias="WORKSPACE_DIR"
    )
    workspace_max_chars_per_file: int = Field(
        default=20000, alias="WORKSPACE_MAX_CHARS_PER_FILE"
    )
    workspace_max_chars_total: int = Field(
        default=150000, alias="WORKSPACE_MAX_CHARS_TOTAL"
    )

    # Heartbeat System Settings
    heartbeat_enabled: bool = Field(default=False, alias="HEARTBEAT_ENABLED")
    heartbeat_interval_minutes: int = Field(
        default=30, alias="HEARTBEAT_INTERVAL_MINUTES"
    )
    heartbeat_ack_max_chars: int = Field(
        default=300, alias="HEARTBEAT_ACK_MAX_CHARS"
    )

    # Context Compression Settings
    # Adaptive compression trigger thresholds (0.0 - 1.0)
    compression_l1_trigger_pct: float = Field(
        default=0.60, alias="COMPRESSION_L1_TRIGGER_PCT"
    )  # L1 prune at 60% occupancy
    compression_l2_trigger_pct: float = Field(
        default=0.80, alias="COMPRESSION_L2_TRIGGER_PCT"
    )  # L2 summarize at 80% occupancy
    compression_l3_trigger_pct: float = Field(
        default=0.90, alias="COMPRESSION_L3_TRIGGER_PCT"
    )  # L3 deep compress at 90% occupancy
    # Summarization chunk size (messages per summary chunk)
    compression_chunk_size: int = Field(default=10, alias="COMPRESSION_CHUNK_SIZE")
    # Max tokens for generated summaries
    compression_summary_max_tokens: int = Field(default=500, alias="COMPRESSION_SUMMARY_MAX_TOKENS")
    # L1: Minimum prunable tokens before pruning is worthwhile
    compression_prune_min_tokens: int = Field(default=20000, alias="COMPRESSION_PRUNE_MIN_TOKENS")
    # L1: Protect recent N tokens of tool call outputs from pruning
    compression_prune_protect_tokens: int = Field(
        default=40000, alias="COMPRESSION_PRUNE_PROTECT_TOKENS"
    )
    # L1: Tool names whose output is never pruned (comma-separated)
    compression_prune_protected_tools: str = Field(
        default="skill", alias="COMPRESSION_PRUNE_PROTECTED_TOOLS"
    )
    # L1: Truncate assistant messages longer than this (chars)
    compression_assistant_truncate_chars: int = Field(
        default=2000, alias="COMPRESSION_ASSISTANT_TRUNCATE_CHARS"
    )
    # Role-aware summary truncation limits (chars)
    compression_truncate_user: int = Field(default=800, alias="COMPRESSION_TRUNCATE_USER")
    compression_truncate_assistant: int = Field(default=300, alias="COMPRESSION_TRUNCATE_ASSISTANT")
    compression_truncate_tool: int = Field(default=200, alias="COMPRESSION_TRUNCATE_TOOL")
    compression_truncate_system: int = Field(default=1000, alias="COMPRESSION_TRUNCATE_SYSTEM")

    # MCP (Model Context Protocol) Settings
    mcp_enabled: bool = Field(default=True, alias="MCP_ENABLED")
    mcp_config_path: str | None = Field(default=None, alias="MCP_CONFIG_PATH")
    mcp_default_timeout: int = Field(
        default=120000, alias="MCP_DEFAULT_TIMEOUT"
    )  # ms (increased from 30000 to 120000 = 2 minutes)
    mcp_auto_connect: bool = Field(default=True, alias="MCP_AUTO_CONNECT")
    mcp_websocket_heartbeat: int | None = Field(
        default=None, alias="MCP_WEBSOCKET_HEARTBEAT"
    )  # seconds; None disables heartbeat (prevents PONG timeout killing long tool calls)

    # Plan Mode Detection Settings (Hybrid Detection Strategy)
    plan_mode_enabled: bool = Field(default=False, alias="PLAN_MODE_ENABLED")
    plan_mode_detection_strategy: str = Field(
        default="hybrid", alias="PLAN_MODE_DETECTION_STRATEGY"
    )  # "hybrid", "heuristic", "llm", "always", "never"
    plan_mode_heuristic_threshold_high: float = Field(
        default=0.8, alias="PLAN_MODE_HEURISTIC_THRESHOLD_HIGH"
    )  # Score above which to auto-accept
    plan_mode_heuristic_threshold_low: float = Field(
        default=0.2, alias="PLAN_MODE_HEURISTIC_THRESHOLD_LOW"
    )  # Score below which to auto-reject
    plan_mode_min_length: int = Field(default=30, alias="PLAN_MODE_MIN_LENGTH")
    plan_mode_llm_confidence_threshold: float = Field(
        default=0.7, alias="PLAN_MODE_LLM_CONFIDENCE_THRESHOLD"
    )
    plan_mode_cache_enabled: bool = Field(default=True, alias="PLAN_MODE_CACHE_ENABLED")
    plan_mode_cache_ttl: int = Field(default=3600, alias="PLAN_MODE_CACHE_TTL")
    plan_mode_cache_max_size: int = Field(default=100, alias="PLAN_MODE_CACHE_MAX_SIZE")

    # OpenTelemetry Settings
    service_name: str = Field(default="memstack", alias="SERVICE_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_exporter_otlp_headers: str | None = Field(default=None, alias="OTEL_EXPORTER_OTLP_HEADERS")
    otel_traces_sampler: str = Field(default="traceidratio", alias="OTEL_TRACES_SAMPLER")
    otel_traces_sampler_arg: float = Field(default=1.0, alias="OTEL_TRACES_SAMPLER_ARG")
    otel_batch_timeout: int = Field(default=30000, alias="OTEL_BATCH_TIMEOUT")
    enable_telemetry: bool = Field(default=True, alias="ENABLE_TELEMETRY")

    # Langfuse LLM Observability Settings
    langfuse_enabled: bool = Field(default=False, alias="LANGFUSE_ENABLED")
    langfuse_public_key: str | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(
        default="http://localhost:3001", alias="LANGFUSE_HOST"
    )  # Default to self-hosted instance
    langfuse_sample_rate: float = Field(
        default=1.0, alias="LANGFUSE_SAMPLE_RATE"
    )  # 1.0 = trace all requests, 0.1 = 10% sampling

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("agent_runtime_mode", mode="before")
    @classmethod
    def normalize_agent_runtime_mode(cls, value: str | None) -> str:
        """Normalize runtime mode value from environment."""
        if value is None:
            return "auto"
        normalized = str(value).strip().lower()
        if normalized in {"auto", "ray", "local"}:
            return normalized
        raise ValueError("AGENT_RUNTIME_MODE must be one of: auto, ray, local")

    @property
    def postgres_url(self) -> str:
        """Get PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """Get Redis connection URL."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
