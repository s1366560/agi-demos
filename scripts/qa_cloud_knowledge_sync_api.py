"""Loopback-only QA API with real authentication and an isolated PostgreSQL schema."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

import sqlalchemy as sa
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scripts.qa_cloud_knowledge_sync_database import (
    PROFILE_PATH,
    QaCloudDatabase,
    cleanup_qa_database,
    initialize_qa_database,
    qa_engine,
)
from scripts.qa_cloud_knowledge_sync_graph import QA_NEO4J_URI
from scripts.qa_cloud_knowledge_sync_runtime import qa_runtime_definitions
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.boundary import (
    PluginGenerationMiddlewareV2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_cloud_knowledge_sync_http_routes import (
    CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2,
)
from src.infrastructure.plugins.v2.http_routes import (
    RouteDefinitionV2,
    RouteTableBuilderV2,
    RouteTableRegistryV2,
    RouteTableV2,
    install_route_definitions_v2,
)
from src.infrastructure.plugins.v2.protocol import control_envelope_v2, parse_profile_snapshot_v2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.web_public_view import project_web_public_view_v2

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

# Exact production method/path pairs; no worker, scheduler, plugin-publication or debug routes.
QA_HTTP_ROUTES = frozenset(
    {
        ("POST", "/api/v1/auth/token"),
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/signout"),
        ("POST", "/api/v1/auth/force-change-password"),
        ("GET", "/api/v1/tenants/"),
        ("POST", "/api/v1/tenants/"),
        ("GET", "/api/v1/tenants/{tenant_id}"),
        ("GET", "/api/v1/platform-plugins/v2/web-view"),
        ("GET", "/api/v1/projects/"),
        ("POST", "/api/v1/projects/"),
        ("GET", "/api/v1/projects/{project_id}"),
        ("GET", "/api/v1/memories/"),
        ("POST", "/api/v1/memories/"),
        ("GET", "/api/v1/memories/{memory_id}"),
        ("PATCH", "/api/v1/memories/{memory_id}"),
        ("DELETE", "/api/v1/memories/{memory_id}"),
    }
)


async def require_qa_enrolled_memory_write(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Do not let this QA API dispatch the legacy unenrolled background workflow."""
    project_id: object
    memory_id = request.path_params.get("memory_id")
    if memory_id:
        memory = await db.get(Memory, memory_id)
        project_id = memory.project_id if memory else None
    else:
        payload = await request.json()
        project_id = (
            cast("dict[str, object]", payload).get("project_id")
            if isinstance(payload, dict)
            else None
        )
    enrolled = None
    if isinstance(project_id, str):
        enrolled = await db.scalar(
            sa.select(KnowledgeSyncEnrollmentModel.enabled).where(
                KnowledgeSyncEnrollmentModel.project_id == project_id,
            )
        )
    if enrolled is not True:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "qa_cloud_sync_enrollment_required",
                "message": _(
                    "Enable project synchronization before writing memories in this QA API"
                ),
            },
        )


def qa_web_public_view_endpoint(
    host: PlatformPluginRuntimeHostV2,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def get_qa_web_public_view(
        response: Response,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "private, no-store"
        try:
            distribution = host.distribution_for_generation(current_generation_v2())
            return project_web_public_view_v2(
                distribution.to_payload()["snapshot"], authority_id=current_user.id
            )
        except RuntimeV2Error:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "web_public_view_unavailable",
                    "message": _("Public Web plugin view is unavailable"),
                },
            ) from None

    return get_qa_web_public_view


def select_qa_routes(
    definitions: tuple[object, ...], *, host: PlatformPluginRuntimeHostV2
) -> tuple[RouteDefinitionV2, ...]:
    selected: list[RouteDefinitionV2] = []
    found: set[tuple[str, str]] = set()
    cloud_count = 0
    for definition in definitions:
        if not isinstance(definition, RouteDefinitionV2):
            continue
        keys = {(method, definition.path) for method in definition.methods}
        if definition.owner_entry_id == CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2:
            cloud_count += 1
        elif not keys or not keys <= QA_HTTP_ROUTES:
            continue
        found.update(keys & QA_HTTP_ROUTES)
        if keys == {("GET", "/api/v1/platform-plugins/v2/web-view")}:
            # The QA host has no durable ROOT publication ledger. Project its actual
            # request-pinned snapshot with the production browser-public validator.
            definition = replace(definition, endpoint=qa_web_public_view_endpoint(host))
        if definition.path.startswith("/api/v1/memories/") and keys & {
            ("POST", "/api/v1/memories/"),
            ("PATCH", "/api/v1/memories/{memory_id}"),
            ("DELETE", "/api/v1/memories/{memory_id}"),
        }:
            definition = replace(
                definition,
                dependencies=(
                    Depends(require_qa_enrolled_memory_write),
                    *definition.dependencies,
                ),
            )
        selected.append(definition)
    if cloud_count != 6 or frozenset(found) != QA_HTTP_ROUTES:
        raise RuntimeError(
            f"QA routes missing: {sorted(QA_HTTP_ROUTES - found)}; cloud_count={cloud_count}"
        )
    return tuple(selected)


def create_qa_cloud_knowledge_sync_app(metadata_path: Path) -> FastAPI:
    state = QaCloudDatabase.load(metadata_path)
    snapshot = parse_profile_snapshot_v2(json.loads(PROFILE_PATH.read_text()))
    if (snapshot.profile_id, snapshot.digest, snapshot.generation) != (
        state.profile_id,
        state.profile_digest,
        1,
    ):
        raise ValueError("QA metadata no longer matches the compiled Cloud profile template")
    host = PlatformPluginRuntimeHostV2(qa_runtime_definitions(state.neo4j_uri))
    registry = RouteTableRegistryV2()
    engine = qa_engine(state)
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def qa_database() -> AsyncIterator[AsyncSession]:
        async with sessions() as db:
            yield db

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            async with engine.connect() as connection:
                current = await connection.scalar(sa.text("SELECT current_schema()"))
                if current != state.schema:
                    raise RuntimeError("The exact QA schema is absent; refusing startup")
            publication = await host.apply(snapshot, control_envelope_v2(snapshot, version=1))
            if not publication.accepted:
                raise RuntimeError("The exact compiled Cloud QA profile was rejected")
            async with await host.acquire() as generation:
                builder = generation.resolve(
                    ROUTE_TABLE_BUILDER_SERVICE_V2, ScopeV2(kind=ScopeKindV2.ROOT)
                )
                if not isinstance(builder, RouteTableBuilderV2):
                    raise RuntimeError("The QA profile did not supply a route table builder")
                definitions = select_qa_routes(tuple(builder.definitions), host=host)
            private = FastAPI()
            private.dependency_overrides[get_db] = qa_database
            install_route_definitions_v2(private, definitions)
            distribution = host.current_distribution
            if distribution is None:
                raise RuntimeError("QA generation was not published")
            _ = await registry.publish(
                distribution.descriptor,
                RouteTableV2.from_fastapi_graph(
                    private,
                    definitions=definitions,
                ),
            )
            app.state.qa_database = state
            app.state.qa_sessions = sessions
            app.state.qa_host = host
            yield
        finally:
            await host.close()
            await engine.dispose()
            # Intentionally preserve this schema for a later process/restart.

    app = FastAPI(title="Cloud Knowledge Sync QA Only", lifespan=lifespan, redirect_slashes=False)
    app.state.platform_plugin_route_registry_v2 = registry
    mount_generation_http_dispatcher_v2(app)
    app.add_middleware(PluginGenerationMiddlewareV2, host_provider=lambda _scope: host)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init")
    _ = initialize.add_argument("--metadata", type=Path, required=True)
    _ = initialize.add_argument("--email", required=True)
    _ = initialize.add_argument("--neo4j-uri", choices=[QA_NEO4J_URI], required=True)
    serve = commands.add_parser("serve")
    _ = serve.add_argument("--metadata", type=Path, required=True)
    _ = serve.add_argument("--port", type=int, default=18080)
    cleanup = commands.add_parser("cleanup")
    _ = cleanup.add_argument("--metadata", type=Path, required=True)
    _ = cleanup.add_argument("--confirm-schema", required=True)
    args = parser.parse_args()
    if args.command == "init":
        password = os.environ.pop("QA_CLOUD_SYNC_PASSWORD", "")
        state = asyncio.run(
            initialize_qa_database(
                args.metadata,
                email=args.email,
                password=password,
                neo4j_uri=args.neo4j_uri,
            )
        )
        print(json.dumps(asdict(state)))
    elif args.command == "serve":
        if not 1024 <= args.port <= 65535:
            raise ValueError("QA port must be between 1024 and 65535")
        app = create_qa_cloud_knowledge_sync_app(args.metadata)
        uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, access_log=False)
    else:
        asyncio.run(cleanup_qa_database(args.metadata, confirm_schema=args.confirm_schema))
        print("The explicitly confirmed QA schema was removed.")


if __name__ == "__main__":
    main()
