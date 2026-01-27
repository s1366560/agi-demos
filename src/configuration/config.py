"""Configuration management for MemStack."""

from functools import lru_cache
from typing import List, Optional, Union

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # API Settings
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_workers: int = Field(default=4, alias="API_WORKERS")
    api_allowed_origins: Union[str, List[str]] = Field(default=["*"], alias="API_ALLOWED_ORIGINS")

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
    postgres_read_replica_host: Optional[str] = Field(
        default=None, alias="POSTGRES_READ_REPLICA_HOST"
    )
    postgres_read_replica_port: int = Field(default=5432, alias="POSTGRES_READ_REPLICA_PORT")

    # Redis Settings
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")

    # LLM Provider Selection
    llm_provider: str = Field(
        default="qwen", alias="LLM_PROVIDER"
    )  # 'gemini', 'qwen', 'openai', 'deepseek', 'zai'

    # Native SDK Integration
    # Note: use_litellm now enables database provider resolution with native SDKs (not LiteLLM)
    # LiteLLM has been removed in favor of native SDK implementations
    use_litellm: bool = Field(
        default=True, alias="USE_LITELM"
    )  # Enable database provider resolution

    # LLM Provider API Key Encryption
    # 32-byte (256-bit) encryption key as hex string (64 hex characters)
    # Generate with: python -c "import os; print(os.urandom(32).hex())"
    llm_encryption_key: Optional[str] = Field(default=None, alias="LLM_ENCRYPTION_KEY")

    # LLM Provider - Gemini
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_embedding_model: str = Field(
        default="text-embedding-004", alias="GEMINI_EMBEDDING_MODEL"
    )
    # Gemini doesn't have a dedicated rerank API, uses LLM-based reranking
    gemini_rerank_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_RERANK_MODEL")

    # LLM Provider - Qwen (通义千问)
    qwen_api_key: Optional[str] = Field(default=None, alias="DASHSCOPE_API_KEY")
    qwen_model: str = Field(default="qwen-plus", alias="QWEN_MODEL")
    qwen_small_model: str = Field(default="qwen-turbo", alias="QWEN_SMALL_MODEL")
    qwen_embedding_model: str = Field(default="text-embedding-v3", alias="QWEN_EMBEDDING_MODEL")
    # Qwen has gte-rerank models but may need special API access; uses LLM fallback
    qwen_rerank_model: str = Field(default="qwen-plus", alias="QWEN_RERANK_MODEL")
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="QWEN_BASE_URL",
    )

    # OpenAI
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(default=None, alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")
    openai_small_model: str = Field(default="gpt-4o-mini", alias="OPENAI_SMALL_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )
    # OpenAI doesn't have a dedicated rerank API, uses LLM-based reranking
    openai_rerank_model: str = Field(default="gpt-4o-mini", alias="OPENAI_RERANK_MODEL")

    # LLM Provider - Deepseek
    deepseek_api_key: Optional[str] = Field(default=None, alias="DEEPSEEK_API_KEY")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    deepseek_small_model: str = Field(default="deepseek-coder", alias="DEEPSEEK_SMALL_MODEL")
    # Deepseek doesn't have a dedicated rerank API, uses LLM-based reranking
    deepseek_rerank_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_RERANK_MODEL")
    deepseek_base_url: str = Field(default="https://api.deepseek.com/v1", alias="DEEPSEEK_BASE_URL")

    # LLM Provider - Z.AI (智谱AI) - LiteLLM provider name: zai
    # ZhipuAI has reranking models; see: https://open.bigmodel.cn/dev/api#rerank
    zai_api_key: Optional[str] = Field(default=None, alias="ZAI_API_KEY")
    zai_model: str = Field(default="glm-4.7", alias="ZAI_MODEL")
    zai_small_model: str = Field(default="glm-4.5-flash", alias="ZAI_SMALL_MODEL")
    zai_embedding_model: str = Field(default="embedding-3", alias="ZAI_EMBEDDING_MODEL")
    # Using LLM-based reranking as default; dedicated rerank models available via API
    zai_rerank_model: str = Field(default="glm-4.5-flash", alias="ZAI_RERANK_MODEL")
    zai_base_url: Optional[str] = Field(default=None, alias="ZAI_BASE_URL")

    # LLM Provider - ZhipuAI (legacy, for backward compatibility)
    zhipu_api_key: Optional[str] = Field(default=None, alias="ZHIPU_API_KEY")
    zhipu_model: str = Field(default="glm-4-plus", alias="ZHIPU_MODEL")
    zhipu_small_model: str = Field(default="glm-4-flash", alias="ZHIPU_SMALL_MODEL")
    zhipu_embedding_model: str = Field(default="embedding-3", alias="ZHIPU_EMBEDDING_MODEL")
    # Using LLM-based reranking as default; dedicated rerank models available via API
    zhipu_rerank_model: str = Field(default="glm-4-flash", alias="ZHIPU_RERANK_MODEL")
    zhipu_base_url: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4", alias="ZHIPU_BASE_URL"
    )

    # Web Search Settings (Tavily API)
    tavily_api_key: Optional[str] = Field(default=None, alias="TAVILY_API_KEY")
    tavily_max_results: int = Field(default=10, alias="TAVILY_MAX_RESULTS")
    tavily_search_depth: str = Field(default="basic", alias="TAVILY_SEARCH_DEPTH")
    tavily_include_domains: Optional[List[str]] = Field(
        default=None, alias="TAVILY_INCLUDE_DOMAINS"
    )
    tavily_exclude_domains: Optional[List[str]] = Field(
        default=None, alias="TAVILY_EXCLUDE_DOMAINS"
    )

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

    # Temporal Workflow Engine Settings (migrated from Redis queue)
    # Note: All task processing now uses Temporal workflows

    # Embedding Management
    auto_clear_mismatched_embeddings: bool = Field(
        default=True, alias="AUTO_CLEAR_MISMATCHED_EMBEDDINGS"
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

    # Agent Execution Limits
    agent_max_steps: int = Field(
        default=5000, alias="AGENT_MAX_STEPS"
    )  # Maximum steps for ReActAgent execution

    # Monitoring
    enable_metrics: bool = Field(default=True, alias="ENABLE_METRICS")
    metrics_port: int = Field(default=9090, alias="METRICS_PORT")

    # S3 Storage Settings (MinIO for local dev)
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    aws_access_key_id: Optional[str] = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    s3_bucket_name: str = Field(default="memstack-files", alias="S3_BUCKET_NAME")
    s3_endpoint_url: Optional[str] = Field(default=None, alias="S3_ENDPOINT_URL")
    presigned_url_expiration: int = Field(default=3600, alias="PRESIGNED_URL_EXPIRATION")

    # Sandbox Settings
    sandbox_default_provider: str = Field(default="docker", alias="SANDBOX_DEFAULT_PROVIDER")
    sandbox_default_image: str = Field(default="python:3.12-slim", alias="SANDBOX_DEFAULT_IMAGE")
    sandbox_timeout_seconds: int = Field(
        default=300, alias="SANDBOX_TIMEOUT_SECONDS"
    )  # Increased from 60 to 300 (5 minutes)
    sandbox_memory_limit: str = Field(default="2G", alias="SANDBOX_MEMORY_LIMIT")
    sandbox_cpu_limit: str = Field(default="2", alias="SANDBOX_CPU_LIMIT")
    sandbox_network_isolated: bool = Field(default=True, alias="SANDBOX_NETWORK_ISOLATED")

    # CUA (Computer Use Agent) Integration Settings
    cua_enabled: bool = Field(default=False, alias="CUA_ENABLED")
    cua_model: str = Field(default="anthropic/claude-sonnet-4-20250514", alias="CUA_MODEL")
    cua_temperature: float = Field(default=0.0, alias="CUA_TEMPERATURE")
    cua_max_steps: int = Field(default=20, alias="CUA_MAX_STEPS")
    cua_screenshot_delay: float = Field(default=0.5, alias="CUA_SCREENSHOT_DELAY")
    cua_max_retries: int = Field(default=3, alias="CUA_MAX_RETRIES")
    cua_telemetry_enabled: bool = Field(default=False, alias="CUA_TELEMETRY_ENABLED")

    # CUA Provider Settings (Docker for isolation)
    cua_provider: str = Field(default="docker", alias="CUA_PROVIDER")  # docker, local, cloud
    cua_docker_image: str = Field(
        default="ghcr.io/trycua/cua-desktop:latest", alias="CUA_DOCKER_IMAGE"
    )
    cua_docker_display: str = Field(default="1920x1080", alias="CUA_DOCKER_DISPLAY")
    cua_docker_memory: str = Field(default="4GB", alias="CUA_DOCKER_MEMORY")
    cua_docker_cpu: str = Field(default="2", alias="CUA_DOCKER_CPU")

    # CUA Permission Settings (Docker environment allows more permissive defaults)
    cua_allow_screenshot: bool = Field(default=True, alias="CUA_ALLOW_SCREENSHOT")
    cua_allow_mouse_click: bool = Field(default=True, alias="CUA_ALLOW_MOUSE_CLICK")
    cua_allow_keyboard_input: bool = Field(default=True, alias="CUA_ALLOW_KEYBOARD_INPUT")
    cua_allow_browser_navigation: bool = Field(default=True, alias="CUA_ALLOW_BROWSER_NAVIGATION")

    # CUA SubAgent/Skill Settings
    cua_subagent_enabled: bool = Field(default=True, alias="CUA_SUBAGENT_ENABLED")
    cua_skill_enabled: bool = Field(default=True, alias="CUA_SKILL_ENABLED")
    cua_subagent_match_threshold: float = Field(default=0.7, alias="CUA_SUBAGENT_MATCH_THRESHOLD")
    cua_skill_match_threshold: float = Field(default=0.8, alias="CUA_SKILL_MATCH_THRESHOLD")

    # CUA MCP Server Settings (WebSocket)
    cua_mcp_url: str = Field(default="ws://localhost:18766", alias="CUA_MCP_URL")

    # Codebox MCP Server Settings (WebSocket)
    codebox_mcp_url: str = Field(default="ws://localhost:8765", alias="CODEBOX_MCP_URL")

    # Agent Skill System (L2 Layer) Settings
    # Threshold for skill prompt injection (0.5 = medium match score)
    agent_skill_match_threshold: float = Field(default=0.5, alias="AGENT_SKILL_MATCH_THRESHOLD")
    # Threshold for direct skill execution (0.8 = high confidence match)
    agent_skill_direct_execute_threshold: float = Field(
        default=0.8, alias="AGENT_SKILL_DIRECT_EXECUTE_THRESHOLD"
    )
    # Whether to fallback to LLM when skill execution fails
    agent_skill_fallback_on_error: bool = Field(default=True, alias="AGENT_SKILL_FALLBACK_ON_ERROR")
    # Timeout for skill direct execution in seconds
    agent_skill_execution_timeout: int = Field(
        default=300, alias="AGENT_SKILL_EXECUTION_TIMEOUT"
    )  # Increased from 60 to 300 (5 minutes)

    # MCP (Model Context Protocol) Settings
    mcp_enabled: bool = Field(default=True, alias="MCP_ENABLED")
    mcp_config_path: Optional[str] = Field(default=None, alias="MCP_CONFIG_PATH")
    mcp_default_timeout: int = Field(
        default=120000, alias="MCP_DEFAULT_TIMEOUT"
    )  # ms (increased from 30000 to 120000 = 2 minutes)
    mcp_auto_connect: bool = Field(default=True, alias="MCP_AUTO_CONNECT")

    # OpenTelemetry Settings
    service_name: str = Field(default="memstack", alias="SERVICE_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    otel_exporter_otlp_endpoint: Optional[str] = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    enable_telemetry: bool = Field(default=True, alias="ENABLE_TELEMETRY")

    # Langfuse LLM Observability Settings
    langfuse_enabled: bool = Field(default=False, alias="LANGFUSE_ENABLED")
    langfuse_public_key: Optional[str] = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = Field(default=None, alias="LANGFUSE_SECRET_KEY")
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

    @model_validator(mode="after")
    def auto_select_provider(self) -> "Settings":
        """Auto-select provider based on available API keys if not explicitly set to a valid one."""
        # If provider is default (gemini) but no Gemini key, try other providers
        if self.llm_provider.lower() == "gemini" and not self.gemini_api_key:
            if self.qwen_api_key:
                self.llm_provider = "qwen"
            elif self.openai_api_key:
                self.llm_provider = "openai"
            elif self.deepseek_api_key:
                self.llm_provider = "deepseek"
            elif self.zai_api_key:
                self.llm_provider = "zai"

        return self

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
