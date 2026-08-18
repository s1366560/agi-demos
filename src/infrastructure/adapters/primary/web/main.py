import logging
import os
import sys
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

from src.infrastructure.logging_redaction import install_sensitive_log_redaction

# Configure application-wide logging before importing the rest of the app.
# Uvicorn only configures its own loggers; without this, all src.* loggers
# have no handlers and their output is silently discarded.
install_sensitive_log_redaction()
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
    force=True,
)

from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.configuration.config import get_settings
from src.configuration.workspace_core import WorkspaceCoreSettings, get_workspace_core_settings
from src.infrastructure.adapters.primary.web.middleware import (
    configure_exception_handlers,
    install_api_access_log_middleware,
)
from src.infrastructure.adapters.primary.web.routers import (
    acp,
    admin_dlq,
    ai_tools,
    artifacts,
    attachments_upload,
    audit,
    auth,
    background_tasks,
    billing,
    channels,
    clusters,
    cron,
    data_export,
    deploy,
    engines,
    enhanced_search,
    episodes,
    events,
    genes,
    graph,
    graph_stores,
    instance_channels,
    instance_files,
    instance_templates,
    instances,
    invitations,
    llm_providers,
    maintenance,
    mcp,
    memories,
    notifications,
    observability,
    platform_plugins,
    plugin_marketplace,
    project_my_work,
    project_sandbox,
    projects,
    recall,
    reflection,
    retrieval_stores,
    sandbox,
    schema,
    security_ws,
    shares,
    skills,
    smtp_config,
    subagents,
    support,
    system,
    tasks,
    tenant_skill_configs,
    tenant_webhooks,
    tenants,
    terminal,
    trust,
    tunnel,
    webhooks,
)
from src.infrastructure.adapters.primary.web.routers.agent import (
    router as agent_router,
)
from src.infrastructure.adapters.primary.web.startup import (
    initialize_artifact_content_orphan_gc_worker,
    initialize_channel_manager,
    initialize_container,
    initialize_database_schema,
    initialize_docker_services,
    initialize_graph_service,
    initialize_llm_providers,
    initialize_redis_client,
    initialize_sandbox_idle_reaper,
    initialize_shadow_rollout_worker,
    initialize_telemetry,
    initialize_websocket_manager,
    initialize_workflow_engine,
    shutdown_artifact_content_orphan_gc_worker,
    shutdown_channel_manager,
    shutdown_docker_services,
    shutdown_sandbox_idle_reaper,
    shutdown_shadow_rollout_worker,
    shutdown_telemetry_services,
    sync_health_checker_providers,
)
from src.infrastructure.adapters.primary.web.startup.graph import (
    shutdown_graph_service,
)
from src.infrastructure.adapters.primary.web.websocket import (
    router as websocket_router,
)
from src.infrastructure.adapters.primary.web.workspace_core_routes import (
    register_workspace_core_routes,
    register_workspace_core_static_routes,
)
from src.infrastructure.adapters.primary.web.workspace_core_runtime import (
    install_workspace_core_runtime,
    shutdown_workspace_core_runtime,
    start_workspace_core_runtime,
)
from src.infrastructure.adapters.primary.web.workspace_core_task_sessions import (
    register_task_session_routes,
)
from src.infrastructure.adapters.secondary.persistence.database import (
    async_session_factory,
)
from src.infrastructure.llm.resilience.health_checker import (
    start_health_checker,
    stop_health_checker,
)
from src.infrastructure.middleware.rate_limit import limiter
from src.infrastructure.plugins.cutover_gate import ensure_agent_v2_cutover_ready

logger = logging.getLogger(__name__)
settings = get_settings()

# Fix LiteLLM duplicate logging - prevent log propagation to root logger
# LiteLLM adds its own handler AND allows propagation by default, causing duplicate logs
_litellm_loggers = ["LiteLLM", "LiteLLM Router", "LiteLLM Proxy"]
for _logger_name in _litellm_loggers:
    _litellm_logger = logging.getLogger(_logger_name)
    _litellm_logger.propagate = False

# Suppress Neo4j driver notifications about non-existent property keys.
# These are benign warnings emitted when querying properties (e.g. embedding_dim,
# entity_type) that don't exist on any nodes yet. The queries use coalesce() and
# IS NOT NULL checks that handle missing properties correctly.
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, None]:  # noqa: PLR0915, C901, PLR0912
    """Application lifespan manager - handles startup and shutdown."""
    # Startup
    logger.info("Starting MemStack (Hexagonal) application...")

    # Initialize OpenTelemetry and Langfuse
    await initialize_telemetry()

    # Initialize Database Schema and Default Credentials
    await initialize_database_schema()
    _ = await ensure_agent_v2_cutover_ready(async_session_factory)
    shadow_rollout_worker = initialize_shadow_rollout_worker(async_session_factory)

    # Initialize Default LLM Provider from environment
    await initialize_llm_providers()
    health_provider_count = await sync_health_checker_providers()
    await start_health_checker()
    logger.info("LLM health checker started with %d active providers", health_provider_count)

    # Initialize NativeGraphAdapter (self-developed knowledge graph engine)
    graph_service = await initialize_graph_service()

    # Initialize Workflow Engine
    workflow_engine = await initialize_workflow_engine(graph_service)

    # Initialize Background Task Manager
    from src.infrastructure.adapters.secondary.background_tasks import task_manager

    task_manager.start_cleanup()
    logger.info("Background task manager started")

    # Initialize Redis client for event bus
    redis_client = await initialize_redis_client()
    # Wire Redis into graph service for cached embedding support
    if redis_client and graph_service and hasattr(graph_service, "set_redis_client"):
        graph_service.set_redis_client(redis_client)  # type: ignore[arg-type]  # runtime type is Redis
    try:
        from src.infrastructure.retrieval.registry import register_env_default_retrieval_store
        from src.infrastructure.retrieval.stores import MemstackPgvectorRetrievalStore

        retrieval_store = MemstackPgvectorRetrievalStore(
            session_factory=async_session_factory,
            embedding_service=getattr(graph_service, "embedder", None),
        )
        register_env_default_retrieval_store(retrieval_store)
        app.state.retrieval_store = retrieval_store
        logger.info("Registered env-default retrieval backend in registry")
    except Exception:
        logger.exception("Failed to register env-default retrieval backend")

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

    # Initialize sandbox idle reaper (opt-in; disabled by default)
    await initialize_sandbox_idle_reaper(container)

    # Workspace autonomy and WTP fan-in are owned by Avernet Workspace Core.
    app.state.workspace_supervisor = None

    # Start Skill Evolution Plugin scheduler (periodic pipeline for SKILL.md improvement)
    try:
        async with async_session_factory() as db:
            plugin = container.with_db(db).skill_evolution_plugin()
        if plugin is not None:
            app.state.skill_evolution_plugin = plugin
            await plugin.on_enable()
            logger.info("Skill evolution plugin scheduler started")
        else:
            logger.info("Skill evolution plugin not started (disabled or missing dependencies)")
    except Exception:
        logger.exception("Failed to start skill evolution plugin")

    # Resume bounded cleanup of provisional Artifact objects after process restarts.
    await initialize_artifact_content_orphan_gc_worker(
        storage_service=container.storage_service(),
    )

    # Start Avernet recovery only after DB-backed DI services are ready.
    await start_workspace_core_runtime(app)

    # Initialize Channel Connection Manager for IM integrations
    channel_manager = await initialize_channel_manager()
    if channel_manager:
        app.state.channel_manager = channel_manager
        logger.info("Channel connection manager initialized")

    # Initialize APScheduler for cron jobs
    try:
        from src.infrastructure.scheduler.scheduler_service import (
            start_scheduler,
            sync_all_jobs,
        )

        _ = await start_scheduler()
        await sync_all_jobs()
        logger.info("Cron job scheduler initialized")
    except Exception:
        logger.exception("Failed to start cron scheduler -- cron jobs disabled")

    # Wire the friction → playbook reflection loop. All three calls are
    # best-effort: a failure here disables reflection but never blocks
    # application startup.
    try:
        from src.application.services.friction_runtime import (
            configure_friction_ingest,
        )
        from src.application.services.reflection_events import (
            ReflectionCompleteStatus,
            publish_reflection_complete,
        )
        from src.application.services.reflection_factory import (
            default_in_memory_ledger,
        )
        from src.application.services.reflection_service import (
            ReflectionService,
        )
        from src.domain.model.flow.reflection_verdict import ReflectionVerdict
        from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
        from src.infrastructure.adapters.secondary.cache.redis_friction_ledger import (
            RedisFrictionLedger,
        )
        from src.infrastructure.agent.tools.reflection_tool import (
            configure_reflection_complete_emitter,
            configure_reflection_tool,
        )

        ledger: Any = (
            RedisFrictionLedger(redis_client)  # type: ignore[arg-type]
            if redis_client is not None
            else default_in_memory_ledger()
        )
        # Canonical happy-path order; backward moves emit BOUNCE signals.
        lane_order = (
            WorkspaceTaskStatus.TODO.value,
            WorkspaceTaskStatus.DISPATCHED.value,
            WorkspaceTaskStatus.EXECUTING.value,
            WorkspaceTaskStatus.REPORTED.value,
            WorkspaceTaskStatus.ADJUDICATING.value,
            WorkspaceTaskStatus.DONE.value,
        )
        configure_friction_ingest(ledger, lane_order=lane_order)

        async def _reflection_provider(
            project_id: str,
        ) -> "ReflectionService | None":
            """Per-call session-scoped ReflectionService for the agent tool.

            Mirrors the contract used by ``ReflectionRunner``: opens a fresh
            DB session, builds the SQL-backed service, and returns an object
            whose ``reflect_window`` commits before returning.
            """
            session_factory = container._session_factory
            if session_factory is None:
                return None
            active_session_factory = session_factory

            class _SessionScopedReflection:
                async def reflect_window(self, pid: str) -> list[ReflectionVerdict]:
                    async with active_session_factory() as session:
                        service = await container.reflection_service(pid, session=session)
                        verdicts = await service.reflect_window(pid)
                        await session.commit()
                        return cast("list[ReflectionVerdict]", verdicts)

            del project_id  # service is keyed by reflect_window's argument
            return cast("ReflectionService", _SessionScopedReflection())

        configure_reflection_tool(_reflection_provider)

        async def _emit_completion(
            project_id: str,
            verdicts: list[ReflectionVerdict],
            status: ReflectionCompleteStatus,
            error: str | None,
            run_id: str | None,
        ) -> None:
            if redis_client is None:
                return
            await publish_reflection_complete(
                redis_client=cast("Redis", redis_client),
                project_id=project_id,
                verdicts=verdicts,
                status=status,
                source="tool",
                run_id=run_id,
                error=error,
            )

        configure_reflection_complete_emitter(_emit_completion)

        runner = container.reflection_runner()
        runner.start()
        app.state.reflection_runner = runner
        logger.info("Reflection runtime wired (friction ledger + runner started)")
    except Exception:
        logger.exception("Failed to wire reflection runtime -- loop disabled")

    yield

    # Stop new recovery claims and drain all persisted Provider callbacks
    # before their DB, Redis, and Agent Runtime dependencies are torn down.
    await shutdown_workspace_core_runtime(app)

    # Stop cron job scheduler
    try:
        from src.infrastructure.scheduler.scheduler_service import stop_scheduler

        await stop_scheduler()
    except Exception:
        logger.exception("Error stopping cron scheduler")

    # Stop Skill Evolution Plugin scheduler
    try:
        plugin = getattr(app.state, "skill_evolution_plugin", None)
        if plugin is not None:
            await plugin.on_disable()
            logger.info("Skill evolution plugin scheduler stopped")
            app.state.skill_evolution_plugin = None
    except Exception:
        logger.exception("Error stopping skill evolution plugin")

    # Stop reflection runner
    try:
        runner = getattr(app.state, "reflection_runner", None)
        if runner is not None:
            await runner.stop()
            logger.info("Reflection runner stopped")
    except Exception:
        logger.exception("Error stopping reflection runner")
    try:
        from src.application.services.friction_runtime import (
            reset_friction_ingest,
        )
        from src.infrastructure.agent.tools.reflection_tool import (
            configure_reflection_complete_emitter,
            configure_reflection_tool,
        )

        reset_friction_ingest()
        configure_reflection_complete_emitter(None)
        configure_reflection_tool(None)  # type: ignore[arg-type]
    except Exception:
        logger.exception("Error tearing down friction/reflection wiring")

    await stop_health_checker()

    # Flush in-process shadow evidence before DB dependencies become unavailable.
    if shadow_rollout_worker is not None:
        await shutdown_shadow_rollout_worker()

    # Stop sandbox idle reaper
    await shutdown_sandbox_idle_reaper()

    # Stop Artifact content orphan GC after current bounded work.
    await shutdown_artifact_content_orphan_gc_worker()

    # Close MCP websocket clients owned by sandbox adapters without
    # terminating containers; they are recovered from Docker on startup.
    try:
        from src.infrastructure.adapters.primary.web.routers.sandbox.utils import (
            shutdown_sandbox_adapter_singleton,
        )

        await shutdown_sandbox_adapter_singleton()
    except Exception:
        logger.exception("Error closing API sandbox adapter")

    try:
        from src.infrastructure.agent.state.agent_worker_state import (
            shutdown_mcp_sandbox_adapter,
        )

        await shutdown_mcp_sandbox_adapter()
    except Exception:
        logger.exception("Error closing agent MCP sandbox adapter")

    try:
        infra_container = getattr(app.state.container, "_infra", None)
        sandbox_adapter = getattr(infra_container, "_sandbox_adapter_instance", None)
        if infra_container is not None and sandbox_adapter is not None:
            await sandbox_adapter.close()
            infra_container._sandbox_adapter_instance = None
            logger.info("Container sandbox adapter closed")
    except Exception:
        logger.exception("Error closing container sandbox adapter")

    # Shutdown
    logger.info("Shutting down...")

    # Shutdown channel manager (close all IM connections)
    await shutdown_channel_manager()

    # Stop Docker event monitor
    await shutdown_docker_services()

    # Shutdown OpenTelemetry
    shutdown_telemetry_services()

    # Close Neo4j connection
    if graph_service is not None:
        await shutdown_graph_service(graph_service)


def create_app(  # noqa: PLR0915
    *,
    workspace_core_settings: WorkspaceCoreSettings | None = None,
) -> FastAPI:
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
        # P0-4: disable redirect_slashes. FastAPI's default 307 redirect strips
        # the Authorization header on cross-origin clients (Vite 3000 → API 8000)
        # and produces silent 401s. Routes must be registered with their canonical
        # form; clients are expected to use the documented path.
        redirect_slashes=False,
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

    install_api_access_log_middleware(app)

    # P0-4: with ``redirect_slashes=False`` we must still tolerate clients that
    # send the alternate trailing-slash form. A 307/308 redirect would strip the
    # Authorization header on cross-origin requests, so we rewrite the path
    # in-process instead of redirecting.
    @app.middleware("http")
    async def _trailing_slash_normalizer(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        scope = request.scope
        if scope.get("type") == "http":
            path: str = scope.get("path", "")
            # Only rewrite for /api/* paths to avoid clobbering /docs, /static.
            if path.startswith("/api/") and path not in ("/api/", "/api"):
                routes = request.app.router.routes
                # Try the request as-is; if no match, try the toggled-slash form.
                # Cheap heuristic: check if any registered APIRoute path matches.
                registered = {getattr(r, "path", None) for r in routes}
                if path not in registered:
                    alt = path[:-1] if path.endswith("/") else path + "/"
                    if alt in registered:
                        scope["path"] = alt
                        scope["raw_path"] = alt.encode("latin-1")
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
            "X-Request-ID",
            "X-Language",
            "Accept-Language",
        ],
        expose_headers=["Content-Language"],
    )

    # Locale negotiation: resolves X-Language / lang / Accept-Language and pins
    # the request to a contextvar consumed by gettext wrappers.
    from src.infrastructure.i18n.middleware import LocaleMiddleware

    app.add_middleware(LocaleMiddleware)

    # Configure rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]  # Starlette handler type limitation

    # Configure domain exception handlers
    configure_exception_handlers(app)

    @app.get("/health")
    async def health_check() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok", "version": "0.2.0"}

    # Serve static files (MCP Apps sandbox proxy, etc.)
    _static_dir = Path(__file__).parent / "static"
    if _static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    # Register Routers
    workspace_core_settings = workspace_core_settings or get_workspace_core_settings()
    app.state.workspace_core_settings = workspace_core_settings

    app.include_router(auth.router, prefix="/api/v1")
    register_workspace_core_static_routes(app)
    app.include_router(tenants.router)
    # Register project sandbox routes before the generic project routes so
    # /api/v1/projects/sandboxes is not captured as a project id.
    app.include_router(project_sandbox.router)
    app.include_router(project_my_work.router)
    app.include_router(projects.router)
    app.include_router(agent_router)  # Modular agent router
    app.include_router(websocket_router)  # WebSocket for agent chat
    app.include_router(acp.router)  # Agent Client Protocol
    app.include_router(shares.router)
    app.include_router(memories.router)
    app.include_router(graph.router)
    app.include_router(graph_stores.router)
    app.include_router(retrieval_stores.router)
    app.include_router(schema.router)
    # The Workspace static group above includes routing-policy compatibility;
    # it must precede these dynamic /{provider_id} routes.
    app.include_router(llm_providers.router)  # LiteLLM provider management

    # New routers - feature parity with server/
    app.include_router(episodes.router)
    app.include_router(recall.router)
    app.include_router(reflection.router)
    app.include_router(enhanced_search.router)
    app.include_router(enhanced_search.memory_router)
    app.include_router(data_export.router)
    app.include_router(maintenance.router)
    app.include_router(tasks.router)
    register_workspace_core_routes(app)
    install_workspace_core_runtime(app, workspace_core_settings)
    register_task_session_routes(app)
    app.include_router(cron.router)
    app.include_router(ai_tools.router)
    app.include_router(background_tasks.router)
    app.include_router(billing.router)
    app.include_router(notifications.router)
    app.include_router(support.router, prefix="/api/v1")
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

    # Artifacts (Rich output from sandbox/MCP tools)
    app.include_router(artifacts.router)

    # Attachments (File upload for agent chat)
    app.include_router(attachments_upload.router)

    # Channel Configuration (IM integrations: Feishu, DingTalk, WeCom)
    app.include_router(channels.router, prefix="/api/v1")

    # Instance / Deploy / Cluster / Gene Marketplace / Template Marketplace
    app.include_router(instances.router)
    app.include_router(instance_files.router)
    app.include_router(instance_channels.router)
    app.include_router(deploy.router)
    app.include_router(clusters.router)
    app.include_router(genes.router)
    app.include_router(instance_templates.router)

    # Audit Logs (tenant-scoped read-only audit trail)
    app.include_router(audit.router)

    # Trust System (graduated autonomy policies and approval decisions)
    app.include_router(trust.router)
    app.include_router(trust.workspace_router)

    # SMTP Configuration (tenant-scoped mail server settings)
    app.include_router(smtp_config.router)

    # Webhooks (Feishu challenge verification + message ingestion)
    app.include_router(webhooks.router)
    app.include_router(tenant_webhooks.router, prefix="/api/v1")
    app.include_router(system.router, prefix="/api/v1")
    app.include_router(plugin_marketplace.router)
    app.include_router(platform_plugins.router)
    app.include_router(events.router)

    # Tunnel (WebSocket reverse tunnel for local sandbox connectivity)
    app.include_router(tunnel.router)

    # Engines (runtime engine catalog)
    app.include_router(engines.router)

    # Security WebSocket (pre/post execution security evaluation)
    app.include_router(security_ws.router)

    # Observability (workspace-scoped event logs, DLQ, circuit state, queues)
    app.include_router(observability.router)
    app.include_router(admin_dlq.router)

    app.include_router(invitations.router)
    app.include_router(invitations.public_router)

    # Agent Pool Admin API (always registered, returns disabled status when pool not enabled)
    from src.infrastructure.agent.pool import create_pool_router, create_project_pool_router

    app.include_router(create_pool_router())
    app.include_router(create_project_pool_router())

    logger.info("Agent Pool Admin API registered at /api/v1/admin/pool")

    # Voice WebSocket (ASR/TTS streaming pipeline)
    from src.infrastructure.adapters.primary.web.routers import voice_websocket

    app.include_router(voice_websocket.router)
    logger.info("Voice WebSocket registered at /api/v1/voice/chat")

    # Host-based sandbox service previews. This catch-all router is intentionally
    # last so normal API/static routes win for localhost.
    app.include_router(project_sandbox.preview_router)

    return app


app = create_app()
