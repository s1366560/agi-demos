"""Repository for plugin permissions, backend selection, routes, and quotas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginBackendSelectionModel,
    PlatformPluginCredentialGrantModel,
    PlatformPluginHttpRouteModel,
    PlatformPluginPackageModel,
    PlatformPluginPermissionModel,
    PlatformPluginQuotaUsageModel,
)


class PlatformPluginGovernanceRepository:
    """Persist Phase 4/6 desired state without executing runtime effects."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def grant_permission(
        self,
        *,
        plugin_id: str,
        permission: str,
        scope_type: str = "tenant",
        scope_id: str = "global",
        granted_by: str | None = None,
    ) -> PlatformPluginPermissionModel:
        """Grant one scoped permission idempotently."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginPermissionModel).where(
                    PlatformPluginPermissionModel.scope_type == scope_type,
                    PlatformPluginPermissionModel.scope_id == scope_id,
                    PlatformPluginPermissionModel.plugin_id == plugin_id,
                    PlatformPluginPermissionModel.permission == permission,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.revoked_at = None
            existing.granted_by = granted_by
            await self._session.flush()
            return cast(PlatformPluginPermissionModel, existing)
        model = PlatformPluginPermissionModel(
            id=PlatformPluginPermissionModel.generate_id(),
            scope_type=scope_type,
            scope_id=scope_id,
            plugin_id=plugin_id,
            permission=permission,
            granted_by=granted_by,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def list_permissions(
        self,
        plugin_id: str,
        *,
        scope_type: str = "tenant",
        scope_id: str = "global",
    ) -> list[PlatformPluginPermissionModel]:
        """Return active permission grants."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginPermissionModel)
                .where(
                    PlatformPluginPermissionModel.scope_type == scope_type,
                    PlatformPluginPermissionModel.scope_id == scope_id,
                    PlatformPluginPermissionModel.plugin_id == plugin_id,
                    PlatformPluginPermissionModel.revoked_at.is_(None),
                )
                .order_by(PlatformPluginPermissionModel.permission)
            )
        )
        return list(result.scalars().all())

    async def permission_is_granted(
        self,
        *,
        plugin_id: str,
        permission: str,
        scope_type: str,
        scope_id: str,
    ) -> bool:
        """Return whether one exact permission grant is active."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginPermissionModel.id).where(
                    PlatformPluginPermissionModel.plugin_id == plugin_id,
                    PlatformPluginPermissionModel.permission == permission,
                    PlatformPluginPermissionModel.scope_type == scope_type,
                    PlatformPluginPermissionModel.scope_id == scope_id,
                    PlatformPluginPermissionModel.revoked_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def revoke_permissions(self, plugin_id: str) -> int:
        """Revoke every active grant for a plugin and return the count."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginPermissionModel).where(
                    PlatformPluginPermissionModel.plugin_id == plugin_id,
                    PlatformPluginPermissionModel.revoked_at.is_(None),
                )
            )
        )
        revoked_at = utc_now()
        rows = list(result.scalars().all())
        for row in rows:
            row.revoked_at = revoked_at
        await self._session.flush()
        return len(rows)

    async def grant_credential(
        self,
        *,
        plugin_id: str,
        credential_ref: str,
        permission: str,
        expires_at: datetime,
        granted_by: str | None = None,
    ) -> PlatformPluginCredentialGrantModel:
        """Persist a credential reference lease; never store its value."""
        model = PlatformPluginCredentialGrantModel(
            id=PlatformPluginCredentialGrantModel.generate_id(),
            plugin_id=plugin_id,
            credential_ref=credential_ref,
            permission=permission,
            expires_at=expires_at,
            granted_by=granted_by,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def set_backend_selection(
        self,
        *,
        capability_kind: str,
        plugin_id: str,
        capability_id: str,
        scope_type: str = "tenant",
        scope_id: str = "global",
    ) -> PlatformPluginBackendSelectionModel:
        """Select one replaceable backend and increment its revision."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginBackendSelectionModel).where(
                    PlatformPluginBackendSelectionModel.scope_type == scope_type,
                    PlatformPluginBackendSelectionModel.scope_id == scope_id,
                    PlatformPluginBackendSelectionModel.capability_kind == capability_kind,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            existing = PlatformPluginBackendSelectionModel(
                id=PlatformPluginBackendSelectionModel.generate_id(),
                scope_type=scope_type,
                scope_id=scope_id,
                capability_kind=capability_kind,
                plugin_id=plugin_id,
                capability_id=capability_id,
                revision=1,
            )
            self._session.add(existing)
        else:
            existing.plugin_id = plugin_id
            existing.capability_id = capability_id
            existing.revision += 1
        await self._session.flush()
        return existing

    async def upsert_http_route(
        self,
        *,
        plugin_id: str,
        method: str,
        path: str,
        permission: str,
        authorization_mode: str,
        enabled: bool = True,
    ) -> PlatformPluginHttpRouteModel:
        """Upsert declarative plugin route desired state."""
        normalized_method = method.upper()
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginHttpRouteModel).where(
                    PlatformPluginHttpRouteModel.method == normalized_method,
                    PlatformPluginHttpRouteModel.path == path,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            existing = PlatformPluginHttpRouteModel(
                id=PlatformPluginHttpRouteModel.generate_id(),
                plugin_id=plugin_id,
                method=normalized_method,
                path=path,
                permission=permission,
                authorization_mode=authorization_mode,
                enabled=enabled,
                revision=1,
            )
            self._session.add(existing)
        else:
            existing.plugin_id = plugin_id
            existing.permission = permission
            existing.authorization_mode = authorization_mode
            existing.enabled = enabled
            existing.revision += 1
        await self._session.flush()
        return existing

    async def list_http_routes(self) -> list[PlatformPluginHttpRouteModel]:
        """Return declarative route desired state deterministically."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginHttpRouteModel).order_by(
                    PlatformPluginHttpRouteModel.method,
                    PlatformPluginHttpRouteModel.path,
                )
            )
        )
        return list(result.scalars().all())

    async def acquire_quota(self, plugin_id: str, *, output_bytes: int = 0) -> None:
        """Record one active quota reservation."""
        usage = await self._session.get(PlatformPluginQuotaUsageModel, plugin_id)
        if usage is None:
            usage = PlatformPluginQuotaUsageModel(
                plugin_id=plugin_id,
                concurrent_calls=1,
                window_started_at=utc_now(),
                requests_in_window=1,
                output_bytes=max(0, output_bytes),
                storage_bytes=0,
                usd_micros=0,
            )
            self._session.add(usage)
            await self._session.flush()
            return
        usage.concurrent_calls += 1
        usage.requests_in_window += 1
        usage.output_bytes += max(0, output_bytes)
        await self._session.flush()

    async def release_quota(self, plugin_id: str) -> None:
        """Release one active quota reservation without driving counters negative."""
        usage = await self._session.get(PlatformPluginQuotaUsageModel, plugin_id)
        if usage is None:
            return
        usage.concurrent_calls = max(0, usage.concurrent_calls - 1)
        await self._session.flush()

    async def upsert_package(
        self,
        *,
        plugin_id: str,
        version: str,
        publisher: str,
        artifact_digest: str,
        artifact_registry: str = "inline://marketplace",
        artifact_repository: str | None = None,
        oci_manifest_digest: str | None = None,
        manifest: dict[str, object],
        signature: dict[str, object],
        provenance: dict[str, object],
        security_scan_status: str,
    ) -> PlatformPluginPackageModel:
        """Upsert a marketplace package trust record."""
        model = await self._session.get(
            PlatformPluginPackageModel,
            {"plugin_id": plugin_id, "version": version},
        )
        if model is None:
            model = PlatformPluginPackageModel(
                plugin_id=plugin_id,
                version=version,
                publisher=publisher,
                artifact_digest=artifact_digest,
                artifact_registry=artifact_registry,
                artifact_repository=artifact_repository or plugin_id,
                oci_manifest_digest=oci_manifest_digest or artifact_digest,
                install_status="installed",
                manifest=dict(manifest),
                security_scan_status=security_scan_status,
            )
            self._session.add(model)
        else:
            model.publisher = publisher
            model.artifact_digest = artifact_digest
            model.artifact_registry = artifact_registry
            model.artifact_repository = artifact_repository or plugin_id
            model.oci_manifest_digest = oci_manifest_digest or artifact_digest
            model.install_status = "installed"
            model.manifest = dict(manifest)
            model.security_scan_status = security_scan_status
        model.signature = dict(signature)
        model.provenance = dict(provenance)
        await self._session.flush()
        return model

    async def get_package_version(
        self,
        plugin_id: str,
        version: str,
    ) -> PlatformPluginPackageModel | None:
        """Return one immutable catalog package version."""
        return await self._session.get(
            PlatformPluginPackageModel,
            {"plugin_id": plugin_id, "version": version},
        )

    async def uninstall_package(
        self, plugin_id: str, version: str
    ) -> PlatformPluginPackageModel | None:
        """Mark one installed package version uninstalled without revoking trust."""
        model = await self.get_package_version(plugin_id, version)
        if model is None:
            return None
        model.install_status = "uninstalled"
        await self._session.flush()
        return model

    async def revoke_package(
        self,
        plugin_id: str,
        version: str,
        reason: str,
    ) -> PlatformPluginPackageModel | None:
        """Revoke a package version."""
        model = await self._session.get(
            PlatformPluginPackageModel,
            {"plugin_id": plugin_id, "version": version},
        )
        if model is None:
            return None
        model.revoked = True
        model.revocation_reason = reason
        await self._session.flush()
        return model

    async def list_packages(
        self,
        *,
        include_revoked: bool = False,
    ) -> list[PlatformPluginPackageModel]:
        """Return deterministic marketplace package rows."""
        statement = select(PlatformPluginPackageModel).order_by(
            PlatformPluginPackageModel.plugin_id,
            PlatformPluginPackageModel.version.desc(),
        )
        if not include_revoked:
            statement = statement.where(PlatformPluginPackageModel.revoked.is_(False))
        result = await self._session.execute(refresh_select_statement(statement))
        return list(result.scalars().all())

    async def get_package(
        self,
        plugin_id: str,
    ) -> list[PlatformPluginPackageModel]:
        """Return all versions for one package."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginPackageModel)
                .where(PlatformPluginPackageModel.plugin_id == plugin_id)
                .order_by(PlatformPluginPackageModel.version.desc())
            )
        )
        return list(result.scalars().all())

    async def revoke_packages(
        self,
        plugin_id: str,
        reason: str,
        *,
        version: str | None = None,
    ) -> list[PlatformPluginPackageModel]:
        """Revoke one or all package versions and return the affected rows."""
        statement = select(PlatformPluginPackageModel).where(
            PlatformPluginPackageModel.plugin_id == plugin_id
        )
        if version is not None:
            statement = statement.where(PlatformPluginPackageModel.version == version)
        result = await self._session.execute(refresh_select_statement(statement))
        rows = list(result.scalars().all())
        for row in rows:
            row.revoked = True
            row.revocation_reason = reason
        await self._session.flush()
        return rows


def utc_now() -> datetime:
    """Return current UTC time for callers composing grants."""
    return datetime.now(UTC)
