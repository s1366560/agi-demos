"""Kubernetes readiness for the request-serving Python replica."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.host.operations.project_package_readiness import (
    project_packages_ready,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    PlatformPluginRecoveryRepositoryV2,
)
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

replica_probe_router = APIRouter()


def _unavailable(reason: str) -> JSONResponse:
    return JSONResponse({"status": "unready", "reason": reason}, status_code=503)


@replica_probe_router.get("/health/ready", include_in_schema=False)
async def replica_readiness(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)]
) -> JSONResponse:
    host = getattr(request.app.state, "platform_plugin_runtime_v2", None)
    routes = getattr(request.app.state, "platform_plugin_route_registry_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2) or not isinstance(
        routes, RouteTableRegistryV2
    ):
        return _unavailable("replica_starting")
    if not await project_packages_ready(request, db):
        return _unavailable("project_package_unavailable")
    try:
        async with await host.acquire() as generation:
            distribution = host.distribution_for_generation(generation)
            target = await PlatformPluginRecoveryRepositoryV2(db).requested_generation(
                ScopeV2(kind=ScopeKindV2.ROOT)
            )
            if target != (generation.descriptor, distribution.envelope.nonce):
                return _unavailable(
                    "target_unavailable" if target is None else "generation_mismatch"
                )
            if (
                routes.resolve_generation(generation) is not routes.current
                or host.manager.current is not generation
            ):
                return _unavailable("routes_unavailable")
    except (RuntimeV2Error, SQLAlchemyError, OSError) as error:
        return _unavailable(
            error.code if isinstance(error, RuntimeV2Error) else "target_unavailable"
        )
    return JSONResponse({"status": "ready", "generation": generation.generation})
