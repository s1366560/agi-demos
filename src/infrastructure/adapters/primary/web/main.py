import logging
import os
import sys
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol, cast

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
from src.configuration.factories import create_native_graph_adapter
from src.configuration.workspace_core import WorkspaceCoreSettings, get_workspace_core_settings
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.domain.ports.services.retrieval_store_port import RetrievalStorePort
from src.domain.ports.services.sandbox_port import SandboxConnectionError
from src.infrastructure.adapters.primary.web.middleware import (
    configure_exception_handlers,
    install_api_access_log_middleware,
)
from src.infrastructure.adapters.primary.web.startup import (
    initialize_container,
    initialize_database_schema,
    initialize_llm_providers,
    initialize_redis_client,
    initialize_telemetry,
    mount_generation_http_dispatcher_v2,
    shutdown_telemetry_services,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    plugin_runtime_host_v2_from_scope,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
    get_connection_manager,
)
from src.infrastructure.adapters.primary.web.workspace_core_runtime import (
    create_workspace_core_runtime_service_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import (
    async_session_factory,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_deadline_reconciler_v2 import (
    PlatformPluginDeadlineReconcilerV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.middleware.rate_limit import limiter
from src.infrastructure.plugins.v2.agent_pool_runtime import (
    default_agent_pool_runtime_config_v2,
)
from src.infrastructure.plugins.v2.boundary import PluginGenerationMiddlewareV2
from src.infrastructure.plugins.v2.channel_runtime import ChannelRuntimeManagerV2
from src.infrastructure.plugins.v2.graph_runtime import GraphRuntimeServiceV2
from src.infrastructure.plugins.v2.reflection_runtime import ReflectionRuntimeManagerV2
from src.infrastructure.plugins.v2.telemetry_runtime import TelemetryRuntimeManagerV2
from src.infrastructure.plugins.v2.workspace_core_runtime import WorkspaceCoreRuntimeServiceV2
from src.infrastructure.retrieval.stores import MemstackPgvectorRetrievalStore

logger = logging.getLogger(__name__)
settings = get_settings()


class _RedisConfigurableGraph(Protocol):
    def set_redis_client(self, redis_client: Redis) -> None: ...


async def _create_generation_graph_runtime(redis_client: Redis | None) -> GraphStorePort:
    """Build and configure the graph resource for every candidate generation."""
    graph_service = await create_native_graph_adapter()
    if redis_client is not None and hasattr(graph_service, "set_redis_client"):
        configurable_graph = cast("_RedisConfigurableGraph", graph_service)
        configurable_graph.set_redis_client(redis_client)
    return graph_service


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
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, None]:
    """Application lifespan manager - handles startup and shutdown."""
    # Startup
    logger.info("Starting MemStack (Hexagonal) application...")

    from .startup.plugin_trust_v2 import configure_plugin_trust_v2
    from .startup.scoped_profile_runtime_v2 import (
        initialize_scoped_profile_runtime_v2,
    )

    configure_plugin_trust_v2(
        app,
        key_files=settings.plugin_marketplace_trusted_key_files,
        allowed_registries=settings.plugin_marketplace_allowed_registries,
    )

    # Initialize Database Schema and Default Credentials
    await initialize_database_schema()
    # Initialize Default LLM Provider from environment
    await initialize_llm_providers()

    # Initialize Redis client for event bus
    redis_client = await initialize_redis_client()
    telemetry_runtime_manager = TelemetryRuntimeManagerV2(
        start=initialize_telemetry,
        stop=shutdown_telemetry_services,
    )
    channel_runtime_manager = ChannelRuntimeManagerV2()
    reflection_runtime_manager = (
        ReflectionRuntimeManagerV2(redis_client=redis_client) if redis_client is not None else None
    )

    async def graph_runtime_factory() -> GraphStorePort:
        return await _create_generation_graph_runtime(cast("Redis | None", redis_client))

    def retrieval_runtime_factory(graph_runtime: GraphRuntimeServiceV2) -> RetrievalStorePort:
        return MemstackPgvectorRetrievalStore(
            session_factory=async_session_factory,
            embedding_service=getattr(graph_runtime.graph_service, "embedder", None),
        )

    def sandbox_runtime_factory() -> MCPSandboxAdapter | None:
        try:
            return MCPSandboxAdapter(
                mcp_image=settings.sandbox_default_image,
                default_timeout=settings.sandbox_timeout_seconds,
                default_memory_limit=settings.sandbox_memory_limit,
                default_cpu_limit=settings.sandbox_cpu_limit,
                workspace_base=settings.sandbox_workspace_base,
                redis_client=redis_client,
            )
        except SandboxConnectionError:
            logger.warning("Sandbox runtime unavailable because Docker is not reachable")
            return None

    workspace_core_settings = getattr(app.state, "workspace_core_settings", None)
    if not isinstance(workspace_core_settings, WorkspaceCoreSettings):
        raise RuntimeError("Workspace Core settings are not installed")

    async def workspace_core_runtime_factory() -> WorkspaceCoreRuntimeServiceV2:
        return await create_workspace_core_runtime_service_v2(workspace_core_settings)

    # Publish V2 before constructing legacy DI consumers. Graph, retrieval, and
    # sandbox/workflow resources are created by candidate effects and are not
    # retained by the legacy application container.
    publication_policy = PlatformPluginPublicationPolicyV2.from_deployment(
        environment=settings.environment,
        required_data_plane_ids=settings.plugin_v2_required_data_plane_ids,
        ack_deadline_seconds=settings.plugin_v2_ack_deadline_seconds,
    )
    _ = await initialize_plugin_runtime_v2(
        app,
        session_factory=async_session_factory,
        agent_lifecycle_connection_manager=get_connection_manager(),
        agent_pool_runtime_enabled=settings.agent_pool_enabled,
        agent_pool_runtime_config=default_agent_pool_runtime_config_v2(
            health_check_interval_seconds=settings.agent_pool_health_check_interval_seconds,
        ),
        graph_runtime_factory=graph_runtime_factory,
        retrieval_runtime_factory=retrieval_runtime_factory,
        sandbox_runtime_factory=sandbox_runtime_factory,
        sandbox_redis_client=redis_client,
        telemetry_runtime_manager=telemetry_runtime_manager,
        channel_runtime_manager=channel_runtime_manager,
        reflection_runtime_manager=reflection_runtime_manager,
        workspace_core_runtime_factory=workspace_core_runtime_factory,
        publication_policy=publication_policy,
    )
    try:
        _ = initialize_scoped_profile_runtime_v2(
            app, session_factory=async_session_factory, redis_client=redis_client
        )
        # Initialize DI Container
        container = initialize_container(redis_client=redis_client)

        app.state.container = container
        deadline_reconciler = PlatformPluginDeadlineReconcilerV2(
            session_factory=async_session_factory,
        )
        app.state.platform_plugin_deadline_reconciler_v2 = deadline_reconciler
        deadline_reconciler.start()
    except BaseException:
        await _shutdown_application_plugins_v2(app)
        raise

    # Workspace autonomy and WTP fan-in are owned by Avernet Workspace Core.
    app.state.workspace_supervisor = None

    try:
        yield
    finally:
        await _shutdown_application_plugins_v2(app)


async def _shutdown_application_plugins_v2(app: FastAPI) -> None:
    from .startup.scoped_profile_runtime_v2 import shutdown_scoped_profile_runtime_v2

    try:
        await shutdown_scoped_profile_runtime_v2(app)
    finally:
        http_routes = getattr(app.state, "platform_plugin_http_routes", None)
        try:
            if http_routes is not None:
                http_routes.dispose()
                app.state.platform_plugin_http_routes = None
        finally:
            logger.info("Shutting down...")
            await shutdown_plugin_runtime_v2(app)


def create_app(
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
    app.add_middleware(
        PluginGenerationMiddlewareV2,
        host_provider=plugin_runtime_host_v2_from_scope,
    )

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

    # Authentication remains a non-pluginized kernel route during v2 cutover.
    from src.infrastructure.adapters.primary.web.routers import auth

    app.include_router(auth.router, prefix="/api/v1")

    # One stable catch-all route resolves the generation pinned by middleware.
    # Legacy registrations remain after it as an unreachable rollback surface
    # until REST/WS parity and native acceptance are complete.
    mount_generation_http_dispatcher_v2(app)

    # Workspace Core configuration remains kernel-owned while its routes and
    # runtime capabilities are contributed by the pinned V2 generation.
    workspace_core_settings = workspace_core_settings or get_workspace_core_settings()
    app.state.workspace_core_settings = workspace_core_settings

    return app


app = create_app()
