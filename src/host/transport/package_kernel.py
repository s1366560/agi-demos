"""Production ASGI factory for cloud identity and project-scoped signed packages."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from src.configuration.config import Settings, get_settings
from src.host.identity.desktop_catalog import router as desktop_catalog_router
from src.host.identity.device_plugin_grants import (
    router as device_grants_router,
)
from src.host.identity.project_package_scope import (
    router as project_package_scope_router,
)
from src.host.identity.workspace_context import router as workspace_context_router
from src.host.operations.device_conversations import DEVICE_HISTORY_OPERATIONS
from src.host.operations.project_package_audit import configure_project_package_audit
from src.host.operations.project_package_readiness import (
    project_packages_ready,
)
from src.host.operations.remote_application_commands import application_runtime_origin
from src.host.packages.bootstrap import bootstrap_empty_project
from src.host.runtime.oci_mcp_lease import worker_recovery
from src.host.transport.conversation_journal import router as journal_router
from src.host.transport.local_run_upload import router as local_runs_router
from src.host.transport.project_package_routes import project_package_router
from src.host.transport.remote_local_run_upload import router as remote_local_runs_router
from src.host.transport.tenant_packages import router as tenant_package_router
from src.infrastructure.adapters.primary.web.routers.auth import router as auth_router
from src.infrastructure.adapters.primary.web.routers.project_marketplace import (
    kernel_marketplace_router,
)
from src.infrastructure.adapters.primary.web.startup.database import initialize_database_schema
from src.infrastructure.adapters.primary.web.startup.plugin_trust_v2 import (
    configure_plugin_trust_v2,
)
from src.infrastructure.adapters.secondary.cache.redis_pool import (
    close_redis_pool,
    get_redis_client,
)
from src.infrastructure.adapters.secondary.persistence.database import (
    engine,
    get_db,
    initialize_database,
)
from src.infrastructure.adapters.secondary.persistence.package_kernel_database import (
    initialize_package_kernel_database,
)
from src.infrastructure.i18n.middleware import LocaleMiddleware
from src.infrastructure.plugins.v2.protocol import IF_PLUGIN_GENERATION_HEADER_V2


@dataclass(frozen=True)
class _IdentityResources:
    """The cloud OAuth state store shared with the full API."""

    client: Redis

    def redis(self) -> Redis:
        return self.client


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_project_package_audit()
    settings = get_settings()
    if settings.environment == "production" and (
        not settings.secret_key
        or settings.secret_key == Settings.model_fields["secret_key"].default
    ):
        raise RuntimeError("Configure the deployment SECRET_KEY before starting the package kernel")
    configure_plugin_trust_v2(
        app,
        key_files=settings.plugin_marketplace_trusted_key_files,
        allowed_registries=settings.plugin_marketplace_allowed_registries,
    )
    if (
        settings.package_kernel_bootstrap_directory
        and settings.package_kernel_database_mode != "standalone"
    ):
        raise RuntimeError("Initial package installation requires a standalone database")
    if settings.package_kernel_database_mode == "standalone":
        await initialize_package_kernel_database(engine)
    elif settings.environment == "development":
        await initialize_database_schema()
    else:
        await initialize_database()
    redis = await get_redis_client()
    app.state.container = _IdentityResources(redis)
    try:
        async with worker_recovery(bool(settings.plugin_worker_allowed_registries)):
            if directory := settings.package_kernel_bootstrap_directory:
                await bootstrap_empty_project(
                    engine, directory, app.state.plugin_marketplace_trusted_public_keys_v2
                )
            yield
    finally:
        await redis.aclose()
        await close_redis_pool()


async def _health() -> dict[str, str]:
    return {"status": "ok"}


async def _ready(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> JSONResponse:
    if await project_packages_ready(request, db):
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "unready"}, status_code=503)


def _check_generation(request: Request) -> None:
    if IF_PLUGIN_GENERATION_HEADER_V2 in request.headers:
        raise HTTPException(status_code=409, detail={"code": "route_generation_mismatch"})


def create_app() -> FastAPI:
    """Start with only the package management and identity APIs."""
    app = FastAPI(
        title="MemStack Package Kernel",
        version="1",
        lifespan=_lifespan,
        dependencies=[Depends(_check_generation)],
    )
    if origin := get_settings().package_application_runtime_url:
        app.state.package_application_runtime_origin = application_runtime_origin(origin)
        app.include_router(remote_local_runs_router, prefix="/api/v1/agent")
    else:
        app.state.package_operations_v1 = dict(DEVICE_HISTORY_OPERATIONS)
        app.include_router(journal_router, prefix="/api/v1/agent")
        app.include_router(local_runs_router, prefix="/api/v1/agent")
    app.state.standalone_run_authority = True
    app.add_middleware(LocaleMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().api_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Language"],
    )
    app.add_api_route("/health", _health, include_in_schema=False)
    app.add_api_route("/health/ready", _ready, include_in_schema=False)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(device_grants_router)
    app.include_router(project_package_router)
    app.include_router(tenant_package_router)
    app.include_router(project_package_scope_router)
    app.include_router(desktop_catalog_router)
    app.include_router(workspace_context_router)
    app.include_router(kernel_marketplace_router)
    return app
