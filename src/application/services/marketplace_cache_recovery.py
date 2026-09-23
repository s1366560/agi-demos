"""Startup and periodic recovery for registered marketplace snapshots only."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import Project, ProjectSandbox
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins.marketplace_snapshot_cache import MarketplaceSnapshotCache
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.sandbox_operation_services import (
    SANDBOX_OPERATION_APPLICATION_SERVICE_V2,
    SandboxOperationApplicationResolverProtocolV2,
)

logger = logging.getLogger(__name__)


class MarketplaceCacheRecovery:
    """Each pass uses fresh transactions and rechecks leases and remote process ownership."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        host: PlatformPluginRuntimeHostV2,
        *,
        interval: float = 60,
    ) -> None:
        super().__init__()
        self.sessions, self.host, self.interval = session_factory, host, interval
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run(), name="marketplace-cache-recovery")

    async def stop(self) -> None:
        if self.task is not None:
            _ = self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception as exc:
                logger.warning("Marketplace cache recovery deferred: %s", type(exc).__name__)
            await asyncio.sleep(self.interval)

    async def run_once(self) -> None:
        async with self.sessions() as db:
            scopes = list(
                await db.execute(
                    refresh_select_statement(
                        select(MarketplaceRecordV3.tenant_id, MarketplaceRecordV3.project_id)
                        .where(MarketplaceRecordV3.kind == "snapshot")
                        .distinct()
                    )
                )
            )
        for tenant_id, project_id in scopes:
            try:
                await self.recover_scope(tenant_id, project_id)
            except Exception as exc:
                logger.warning("Marketplace scoped cache recovery deferred: %s", type(exc).__name__)

    async def recover_scope(self, tenant_id: str, project_id: str) -> None:
        async with self.sessions() as db:
            if project_id:
                project = await db.scalar(
                    select(Project.id)
                    .where(Project.id == project_id, Project.tenant_id == tenant_id)
                    .with_for_update()
                )
                if project is None:
                    return
            cache = MarketplaceSnapshotCache(db, tenant_id, project_id)
            snapshots = list(await db.scalars(cache.query("snapshot")))
            has_roots = any(row.payload.get("runtime_root") for row in snapshots)
            association = None
            if project_id and has_roots:
                association = await db.scalar(
                    select(ProjectSandbox)
                    .where(
                        ProjectSandbox.project_id == project_id,
                        ProjectSandbox.tenant_id == tenant_id,
                    )
                    .with_for_update()
                )
            # Metadata and absent sandboxes never allocate runtime resources.
            if not has_roots or association is None:
                _ = await cache.cleanup(f"startup:{uuid4()}", remember=False)
                await db.commit()
                return
            # Sandbox access bookkeeping must not commit and release our snapshot locks.
            db.info["marketplace_transaction_owned"] = True
            lease = await self.host.acquire()
            async with lease as generation:
                scope = ScopeV2(
                    kind=ScopeKindV2.PROJECT, tenant_id=tenant_id, project_id=project_id
                )
                async with OperationContextV2(
                    generation=generation,
                    operation_id=f"marketplace-cache-recovery:{uuid4()}",
                    scope=scope,
                ) as operation:
                    _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
                    _ = operation.provide(
                        OPERATION_IDENTITY_SERVICE_V2,
                        {
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "user_id": "marketplace-cache-recovery",
                        },
                    )
                    _ = operation.provide(
                        OPERATION_METADATA_SERVICE_V2, {"kind": "marketplace-cache-recovery"}
                    )
                    resolver = operation.require(SANDBOX_OPERATION_APPLICATION_SERVICE_V2)
                    if not isinstance(resolver, SandboxOperationApplicationResolverProtocolV2):
                        raise TypeError("Sandbox recovery service is unavailable")
                    sandbox = resolver.resolve(operation).sandbox_resource
                    if (
                        await sandbox.get_sandbox_id(project_id, tenant_id)
                        == association.sandbox_id
                    ):
                        cache.sandbox = sandbox
                    try:
                        _ = await cache.cleanup(f"startup:{uuid4()}", remember=False)
                    except Exception:
                        # Retain attempt/error metadata and any completed reclamations for retry.
                        # A failed DB transaction cannot be committed and is rolled back on close.
                        if db.is_active:
                            await db.commit()
                        raise
                    await db.commit()
