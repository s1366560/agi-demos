import logging
import os
import sys
from contextlib import asynccontextmanager

# Configure application-wide logging before any other imports.
# Uvicorn only configures its own loggers; without this, all src.* loggers
# have no handlers and their output is silently discarded.
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
    force=True,
)

from pathlib import Path  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

from src.configuration.config import get_settings  # noqa: E402
from src.infrastructure.adapters.primary.web.middleware import (  # noqa: E402
    configure_exception_handlers,
)
from src.infrastructure.adapters.primary.web.routers import (  # noqa: E402
    ai_tools,
    artifacts,
    attachments_upload,
    auth,
    background_tasks,
    billing,
    channels,
    data_export,
    enhanced_search,
    episodes,
    graph,
    llm_providers,
    maintenance,
    mcp,
    memories,
    notifications,
    project_sandbox,
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
from src.infrastructure.adapters.primary.web.routers.agent import (  # noqa: E402
    router as agent_router,
)
from src.infrastructure.adapters.primary.web.startup import (  # noqa: E402
    get_channel_manager,
    initialize_channel_manager,
    initialize_container,
    initialize_database_schema,
    initialize_docker_services,
    initialize_graph_service,
    initialize_llm_providers,
    initialize_redis_client,
    initialize_telemetry,
    initialize_websocket_manager,
    initialize_workflow_engine,
    shutdown_channel_manager,
    shutdown_docker_services,
    shutdown_telemetry_services,
)
from src.infrastructure.adapters.primary.web.startup.graph import (  # noqa: E402
    shutdown_graph_service,
)
from src.infrastructure.adapters.primary.web.websocket import (  # noqa: E402
    router as websocket_router,
)
from src.infrastructure.middleware.rate_limit import limiter  # noqa: E402

logger = logging.getLogger(__name__)
settings = get_settings()

# Fix LiteLLM duplicate logging - prevent log propagation to root logger
# LiteLLM adds its own handler AND allows propagation by default, causing duplicate logs
_litellm_loggers = ["LiteLLM", "LiteLLM Router", "LiteLLM Proxy"]
for _logger_name in _litellm_loggers:
    _litellm_logger = logging.getLogger(_logger_name)
    _litellm_logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - handles startup and shutdown."""
    # Startup
    logger.info("Starting MemStack (Hexagonal) application...")

    # Initialize OpenTelemetry and Langfuse
    await initialize_telemetry()

    # Initialize Database Schema and Default Credentials
    await initialize_database_schema()

    # Initialize Default LLM Provider from environment
    await initialize_llm_providers()

    # Initialize NativeGraphAdapter (self-developed knowledge graph engine)
    graph_service = await initialize_graph_service()

    # Initialize Workflow Engine
    workflow_engine = await initialize_workflow_engine()

    # Initialize Background Task Manager
    from src.infrastructure.adapters.secondary.background_tasks import task_manager

    task_manager.start_cleanup()
    logger.info("Background task manager started")

    # Initialize Redis client for event bus
    redis_client = await initialize_redis_client()

    # Initialize DI Container
    container = initialize_container(
        graph_service=graph_service,
        redis_client=redis_client,
        workflow_engine=workflow_engine,
    )

    app.state.container = container
    app.state.workflow_engine = workflow_engine
    app.state.graph_service = graph_service

    # Register WebSocket manager for lifecycle state notifications
    initialize_websocket_manager()

    # Initialize Docker services (sandbox sync and event monitor)
    await initialize_docker_services(container)

    # Initialize Channel Connection Manager for IM integrations
    channel_manager = await initialize_channel_manager()
    if channel_manager:
        app.state.channel_manager = channel_manager
        logger.info("Channel connection manager initialized")

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Shutdown channel manager (close all IM connections)
    await shutdown_channel_manager()

    # Stop Docker event monitor
    await shutdown_docker_services()

    # Shutdown OpenTelemetry
    shutdown_telemetry_services()

    # Close Neo4j connection
    await shutdown_graph_service(graph_service)


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
- Event types: `thought`, `act`, `observe`, `task_start`, `task_complete`, `complete`, `error`
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

    # Instrument FastAPI for OpenTelemetry (must be done before router registration)
    if settings.enable_telemetry:
        from src.infrastructure.telemetry.config import configure_tracer_provider
        from src.infrastructure.telemetry.instrumentation import instrument_fastapi

        configure_tracer_provider()
        if instrument_fastapi(app):
            logger.info("FastAPI instrumented for OpenTelemetry")

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

    # Configure domain exception handlers
    configure_exception_handlers(app)

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "version": "0.2.0"}

    # Serve static files (MCP Apps sandbox proxy, etc.)
    _static_dir = Path(__file__).parent / "static"
    if _static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    # Register Routers
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(tenants.router)
    app.include_router(projects.router)
    app.include_router(agent_router)  # Modular agent router
    app.include_router(websocket_router)  # WebSocket for agent chat
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

    # Project Sandbox (Project-dedicated persistent sandboxes)
    app.include_router(project_sandbox.router)

    # Terminal (Interactive shell via WebSocket)
    app.include_router(terminal.router)

    # Artifacts (Rich output from sandbox/MCP tools)
    app.include_router(artifacts.router)

    # Attachments (File upload for agent chat)
    app.include_router(attachments_upload.router)

    # Channel Configuration (IM integrations: Feishu, DingTalk, WeCom)
    app.include_router(channels.router, prefix="/api/v1")

    # Agent Pool Admin API (always registered, returns disabled status when pool not enabled)
    from src.infrastructure.agent.pool import create_pool_router

    app.include_router(create_pool_router())
    logger.info("Agent Pool Admin API registered at /api/v1/admin/pool")

    return app


app = create_app()
