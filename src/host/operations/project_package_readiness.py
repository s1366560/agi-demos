"""Replica readiness for immutable project releases on both Python hosts."""

import asyncio
import logging
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import PlatformPluginPackageModel
from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
    ProjectPluginInstallation as Installation,
    ProjectPluginRelease as Release,
)
from src.infrastructure.plugins.v2.project_package_execution import (
    allowed_worker_registries,
    prepare_project_guest,
)
from src.infrastructure.plugins.v2.project_plugin_package import admit_package
from src.infrastructure.plugins.v2.signed_optional_business_v2 import ScopeBindingV2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Target:
    scope: ScopeBindingV2
    plugin: str
    version: str
    digest: str
    permissions: frozenset[str]


async def _targets(db: AsyncSession) -> frozenset[_Target]:
    withdrawn = (
        exists()
        .where(
            PlatformPluginPackageModel.plugin_id == Installation.plugin_id,
            PlatformPluginPackageModel.version == Installation.active,
            or_(
                PlatformPluginPackageModel.revoked.is_(True),
                PlatformPluginPackageModel.security_scan_status == "failed",
                PlatformPluginPackageModel.manifest["digest"].as_string() != Release.digest,
            ),
        )
        .correlate(Installation, Release)
    )
    rows = await db.execute(
        select(
            Installation.project_id,
            Installation.plugin_id,
            Installation.active,
            Release.tenant_id,
            Release.digest,
            Release.permissions,
        )
        .outerjoin(
            Release,
            and_(
                Release.project_id == Installation.project_id,
                Release.plugin_id == Installation.plugin_id,
                Release.version == Installation.active,
            ),
        )
        .where(Installation.enabled.is_(True), Installation.active.is_not(None), ~withdrawn)
        .execution_options(populate_existing=True)
    )
    result: set[_Target] = set()
    for project, plugin, version, tenant, digest, permissions in rows:
        if tenant is None or digest is None or permissions is None or version is None:
            raise ValueError("active release is missing")
        result.add(
            _Target(
                ScopeBindingV2(tenant_id=tenant, project_id=project),
                plugin,
                version,
                digest,
                frozenset(permissions),
            )
        )
    return frozenset(result)


@dataclass(frozen=True)
class _Prepared:
    image: str | None
    exports: frozenset[tuple[str, str]]
    imports: frozenset[tuple[str, str]]


async def _prepare(db: AsyncSession, target: _Target, keys: tuple[str, ...]) -> _Prepared:
    archive = await db.scalar(
        select(Release.archive).where(
            Release.project_id == target.scope.project_id,
            Release.tenant_id == target.scope.tenant_id,
            Release.plugin_id == target.plugin,
            Release.version == target.version,
            Release.digest == target.digest,
        )
    )
    if archive is None:
        raise ValueError("active release has no archive")
    package = await asyncio.to_thread(
        admit_package, archive, keys, target.permissions, target.scope
    )
    if (package.plugin_id, package.version, package.digest) != (
        target.plugin,
        target.version,
        target.digest,
    ):
        raise ValueError("selected release does not match its archive")
    await prepare_project_guest(package, target.scope)
    return _Prepared(
        package.worker.image if package.worker else None,
        frozenset((s.service, s.version) for s in package.services.provides),
        frozenset((s.service, s.version) for s in package.services.requires),
    )


class ProjectPackageReplicaReadiness:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._prepared: dict[_Target, _Prepared] = {}
        self._authority: tuple[tuple[str, ...], frozenset[str]] | None = None

    async def ready(self, db: AsyncSession, keys: tuple[str, ...]) -> bool:
        async with self._lock:
            targets = await _targets(db)
            authority = (keys, allowed_worker_registries())
            if self._authority != authority:
                self._prepared.clear()
                self._authority = authority
            for old in self._prepared.keys() - targets:
                del self._prepared[old]
            images = {item.image for item in self._prepared.values() if item.image is not None}
            if images:
                from src.infrastructure.plugins.v2.oci_mcp_worker import missing_worker_images

                missing = await asyncio.to_thread(missing_worker_images, images)
                self._prepared = {
                    t: item for t, item in self._prepared.items() if item.image not in missing
                }
            pending = targets - self._prepared.keys()
            for target in pending:
                self._prepared[target] = await _prepare(db, target, keys)
            offered = {
                (target.scope, service)
                for target, prepared in self._prepared.items()
                for service in prepared.exports
            }
            if any(
                (target.scope, service) not in offered
                for target, prepared in self._prepared.items()
                for service in prepared.imports
            ):
                return False
            return not pending or targets == await _targets(db)


async def project_packages_ready(request: Request, db: AsyncSession) -> bool:
    state = request.app.state
    if not hasattr(state, "package_readiness"):
        state.package_readiness = ProjectPackageReplicaReadiness()
    verifier: ProjectPackageReplicaReadiness = state.package_readiness
    keys = tuple(getattr(state, "plugin_marketplace_trusted_public_keys_v2", ()))
    try:
        return await verifier.ready(db, keys)
    except Exception as error:
        logger.debug("Project package readiness failed (%s)", type(error).__name__)
        return False
