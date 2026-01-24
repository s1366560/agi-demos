import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.configuration.config import get_settings
from src.configuration.di_container import DIContainer
from src.configuration.factories import create_native_graph_adapter
from src.infrastructure.adapters.primary.web.dependencies import initialize_default_credentials
from src.infrastructure.adapters.primary.web.routers import (
    agent,
    agent_websocket,
    ai_tools,
    auth,
    background_tasks,
    billing,
    data_export,
    enhanced_search,
    episodes,
    graph,
    llm_providers,
    maintenance,
    mcp,
    memories,
    notifications,
    projects,
    recall,
    sandbox,
    schema,
    shares,
    skills,
    subagents,
    support,
    tasks,
    tenant_skill_configs,
    tenants,
    terminal,
)
from src.infrastructure.adapters.secondary.persistence.database import (
    async_session_factory,
    initialize_database,
)
from src.infrastructure.adapters.secondary.temporal import TemporalWorkflowEngine
from src.infrastructure.adapters.secondary.temporal.client import TemporalClientFactory
from src.infrastructure.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)
settings = get_settings()

# Trigger reload 10


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting MemStack (Hexagonal) application...")

    # Initialize Database Schema
    logger.info("Initializing database schema...")
    await initialize_database()
    logger.info("Database schema initialized")

    # Initialize Default Credentials (Admin/User/Tenant)
    logger.info("Initializing default credentials...")
    await initialize_default_credentials()
    logger.info("Default credentials initialized")

    # Initialize Default LLM Provider from environment
    logger.info("Initializing default LLM provider...")
    from src.infrastructure.llm.initializer import initialize_default_llm_providers

    provider_created = await initialize_default_llm_providers()
    if provider_created:
        logger.info("Default LLM provider created from environment configuration")
    else:
        logger.info("LLM provider initialization skipped (providers already exist or no config)")

    # Initialize Langfuse LLM Observability (if enabled)
    if settings.langfuse_enabled:
        try:
            import litellm

            # Set environment variables for LiteLLM Langfuse callback
            if settings.langfuse_public_key:
                os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
            if settings.langfuse_secret_key:
                os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
            os.environ["LANGFUSE_HOST"] = settings.langfuse_host

            # Enable Langfuse callback for all LiteLLM calls
            litellm.success_callback = ["langfuse"]
            litellm.failure_callback = ["langfuse"]

            logger.info(
                f"Langfuse LLM observability enabled (host: {settings.langfuse_host}, "
                f"sample_rate: {settings.langfuse_sample_rate})"
            )
        except Exception as e:
            logger.warning(
                f"Failed to initialize Langfuse callback: {e}. Tracing will be disabled."
            )
    else:
        logger.info("Langfuse LLM observability disabled")

    # Initialize NativeGraphAdapter (self-developed knowledge graph engine)
    logger.info("Creating NativeGraphAdapter...")
    try:
        graph_service = await create_native_graph_adapter()
        logger.info("NativeGraphAdapter created successfully")
    except Exception as e:
        logger.error(f"Failed to create NativeGraphAdapter: {e}")
        logger.error("Neo4j is required for MemStack to function. Please ensure Neo4j is running.")
        raise

    # Initialize Temporal Workflow Engine
    logger.info("Initializing Temporal Workflow Engine...")
    temporal_client = None
    workflow_engine = None
    try:
        temporal_client = await TemporalClientFactory.get_client()
        workflow_engine = TemporalWorkflowEngine(client=temporal_client)
        logger.info("Temporal Workflow Engine initialized")
    except Exception as e:
        logger.warning(
            f"Failed to connect to Temporal server: {e}. Workflow engine will be unavailable."
        )

    # Initialize Background Task Manager
    from src.infrastructure.adapters.secondary.background_tasks import task_manager

    task_manager.start_cleanup()
    logger.info("Background task manager started")

    # Initialize MCP Temporal Adapter (if Temporal is available)
    mcp_temporal_adapter = None
    logger.info(f"Checking Temporal client availability: {temporal_client is not None}")
    if temporal_client:
        try:
            from src.infrastructure.adapters.secondary.temporal.mcp.adapter import (
                MCPTemporalAdapter,
            )

            mcp_temporal_adapter = MCPTemporalAdapter(temporal_client)
            logger.info("MCP Temporal Adapter initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize MCP Temporal Adapter: {e}")

    # Initialize Redis client for event bus
    redis_client = None
    try:
        import redis.asyncio as redis

        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        logger.info("Redis client initialized for event bus")
    except Exception as e:
        logger.warning(f"Failed to initialize Redis client: {e}")

    # Initialize Container with NativeGraphAdapter as graph_service
    logger.info("Initializing DI container...")
    container = DIContainer(
        session_factory=async_session_factory,
        graph_service=graph_service,
        redis_client=redis_client,
        workflow_engine=workflow_engine,
        temporal_client=temporal_client if workflow_engine else None,
        mcp_temporal_adapter=mcp_temporal_adapter,
    )
    logger.info("DI container initialized")

    app.state.container = container
    app.state.workflow_engine = workflow_engine
    app.state.graph_service = graph_service

    yield

    # Shutdown
    logger.info("Shutting down...")
    # Close Neo4j connection
    if hasattr(graph_service, "client") and hasattr(graph_service.client, "close"):
        await graph_service.client.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="MemStack API",
        description="""
## MemStack API Documentation

MemStack is a memory-enhanced application platform with AI-powered knowledge management.

### Features

- **Multi-Level Thinking**: Agent breaks down complex queries into work plans
- **Workflow Patterns**: Learn and reuse successful query patterns
- **Tool Composition**: Chain multiple tools together for complex tasks
- **Structured Output**: Generate reports, tables, and code in various formats
- **Tenant Configuration**: Configure agent behavior per tenant

### Authentication

All endpoints require authentication using API keys in the format: `ms_sk_<64_hex_chars>`.

Include the API key in the `Authorization` header:
```
Authorization: Bearer ms_sk_abc123...
```

### Error Handling

The API uses standard HTTP status codes and returns error responses in the following format:

```json
{
  "detail": "Error message description",
  "code": "ERROR_CODE",
  "error_id": "unique-error-id"
}
```

### SSE Streaming

Chat endpoints use Server-Sent Events (SSE) for real-time agent responses:
- Event types: `thought`, `act`, `observe`, `step_start`, `step_end`, `complete`, `error`
- Clients should handle reconnects gracefully
- Use `EventSource` or similar SSE client libraries

### Rate Limiting

API keys are subject to rate limits based on tenant configuration.
Check the `/api/v1/tenant/config` endpoint for your current limits.

---

*T132: Updated OpenAPI documentation with React Agent features*
        """,
        version="0.3.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=[
            {
                "name": "agents",
                "description": "AI agent operations with multi-level thinking and tool composition",
            },
            {
                "name": "conversations",
                "description": "Chat conversations and message management",
            },
            {
                "name": "work-plans",
                "description": "Work-level planning for complex queries",
            },
            {
                "name": "patterns",
                "description": "Workflow pattern learning and matching",
            },
            {
                "name": "tenant-config",
                "description": "Tenant-level agent configuration",
            },
            {
                "name": "structured-output",
                "description": "Report generation in various formats",
            },
        ],
        contact={
            "name": "MemStack Team",
            "email": "support@memstack.ai",
        },
        license_info={
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT",
        },
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Configure rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "version": "0.2.0"}

    # Register Routers
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(tenants.router)
    app.include_router(projects.router)
    app.include_router(agent.router)
    app.include_router(agent_websocket.router)  # WebSocket for agent chat
    app.include_router(shares.router)
    app.include_router(memories.router)
    app.include_router(graph.router)
    app.include_router(schema.router)
    app.include_router(llm_providers.router)  # LiteLLM provider management

    # New routers - feature parity with server/
    app.include_router(episodes.router)
    app.include_router(recall.router)
    app.include_router(enhanced_search.router)
    app.include_router(enhanced_search.memory_router)
    app.include_router(data_export.router)
    app.include_router(maintenance.router)
    app.include_router(tasks.router)
    app.include_router(ai_tools.router)
    app.include_router(background_tasks.router)
    app.include_router(billing.router)
    app.include_router(notifications.router)
    app.include_router(support.router)

    # Agent Capability System (L2 Skill + L3 SubAgent)
    app.include_router(skills.router)
    app.include_router(tenant_skill_configs.router)
    app.include_router(subagents.router)

    # MCP Ecosystem Integration (Phase 4)
    app.include_router(mcp.router)

    # Sandbox (MCP-enabled Docker containers)
    app.include_router(sandbox.router)

    # Terminal (Interactive shell via WebSocket)
    app.include_router(terminal.router)

    return app


app = create_app()
