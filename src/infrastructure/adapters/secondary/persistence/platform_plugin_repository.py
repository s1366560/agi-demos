"""Repository for the platform plugin control plane."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins import PluginManifest, PluginScope
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginApplyStateModel,
    PlatformPluginCapabilityAuditModel,
    PlatformPluginCatalogModel,
    PlatformPluginDesiredStateModel,
    PlatformPluginSnapshotModel,
)
from src.infrastructure.plugins.profile import ProfileSnapshot


class PlatformPluginRepository:
    """Persist manifests, desired state, snapshots, audit, and apply status."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_catalog_manifest(self, manifest: PluginManifest) -> PlatformPluginCatalogModel:
        """Insert or replace one catalog manifest row."""
        existing = await self._session.get(PlatformPluginCatalogModel, manifest.id)
        payload = manifest.to_payload()
        if existing is None:
            existing = PlatformPluginCatalogModel(
                plugin_id=manifest.id,
                version=manifest.version,
                runtime=manifest.runtime.value,
                trust=manifest.trust.value,
                manifest=payload,
            )
            self._session.add(existing)
        else:
            existing.version = manifest.version
            existing.runtime = manifest.runtime.value
            existing.trust = manifest.trust.value
            existing.manifest = payload
        await self._session.flush()
        return existing

    async def list_catalog(self) -> list[PlatformPluginCatalogModel]:
        """Return the deterministic catalog inventory."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginCatalogModel).order_by(PlatformPluginCatalogModel.plugin_id)
            )
        )
        return list(result.scalars().all())

    async def get_desired_state(
        self,
        plugin_id: str,
        *,
        scope: PluginScope = PluginScope.GLOBAL,
        scope_id: str | None = None,
    ) -> PlatformPluginDesiredStateModel | None:
        normalized_scope_id = scope_id if scope and scope != PluginScope.GLOBAL else "global"
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginDesiredStateModel).where(
                    PlatformPluginDesiredStateModel.scope_type == scope.value,
                    PlatformPluginDesiredStateModel.scope_id == normalized_scope_id,
                    PlatformPluginDesiredStateModel.plugin_id == plugin_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def set_desired_state(
        self,
        *,
        plugin_id: str,
        enabled: bool,
        config: dict[str, object],
        scope: PluginScope = PluginScope.GLOBAL,
        scope_id: str | None = None,
    ) -> PlatformPluginDesiredStateModel:
        """Set declarative desired state and increment its revision."""
        normalized_scope_id = scope_id if scope and scope != PluginScope.GLOBAL else "global"
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginDesiredStateModel).where(
                    PlatformPluginDesiredStateModel.scope_type == scope.value,
                    PlatformPluginDesiredStateModel.scope_id == normalized_scope_id,
                    PlatformPluginDesiredStateModel.plugin_id == plugin_id,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            existing = PlatformPluginDesiredStateModel(
                id=PlatformPluginDesiredStateModel.generate_id(),
                scope_type=scope.value,
                scope_id=normalized_scope_id,
                plugin_id=plugin_id,
                enabled=enabled,
                config=dict(config),
                revision=1,
            )
            self._session.add(existing)
        else:
            existing.enabled = enabled
            existing.config = dict(config)
            existing.revision += 1
        await self._session.flush()
        return existing

    async def record_snapshot(
        self,
        snapshot: ProfileSnapshot,
        *,
        version: int,
        nonce: str,
    ) -> PlatformPluginSnapshotModel:
        """Persist an immutable effective plugin snapshot."""
        existing = await self._session.get(PlatformPluginSnapshotModel, snapshot.digest)
        if existing is not None:
            if existing.version != version or existing.nonce != nonce:
                raise ValueError(
                    f"snapshot digest {snapshot.digest} already belongs to another envelope"
                )
            return existing
        model = PlatformPluginSnapshotModel(
            digest=snapshot.digest,
            profile_id=snapshot.profile_id,
            version=version,
            nonce=nonce,
            payload=snapshot.to_payload(),
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def get_snapshot(self, version: int) -> PlatformPluginSnapshotModel | None:
        """Return one snapshot by control-plane version."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginSnapshotModel).where(
                    PlatformPluginSnapshotModel.version == version
                )
            )
        )
        return result.scalar_one_or_none()

    async def latest_snapshot(self) -> PlatformPluginSnapshotModel | None:
        """Return the newest published snapshot."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginSnapshotModel).order_by(
                    PlatformPluginSnapshotModel.version.desc()
                )
            )
        )
        return result.scalars().first()

    async def record_capability_transition(
        self,
        *,
        snapshot_digest: str,
        plugin_id: str,
        action: str,
        capability_kind: str,
        capability_id: str,
        actor_id: str | None,
        before_state: dict[str, object],
        after_state: dict[str, object],
    ) -> PlatformPluginCapabilityAuditModel:
        """Append a capability ownership transition."""
        model = PlatformPluginCapabilityAuditModel(
            id=PlatformPluginCapabilityAuditModel.generate_id(),
            snapshot_digest=snapshot_digest,
            plugin_id=plugin_id,
            action=action,
            capability_kind=capability_kind,
            capability_id=capability_id,
            actor_id=actor_id,
            before_state=dict(before_state),
            after_state=dict(after_state),
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def record_apply_state(
        self,
        *,
        data_plane_id: str,
        snapshot_digest: str,
        requested_version: int,
        applied_version: int,
        status: str,
        error_message: str | None = None,
    ) -> PlatformPluginApplyStateModel:
        """Upsert the latest ACK/NACK state for a data plane."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginApplyStateModel).where(
                    PlatformPluginApplyStateModel.data_plane_id == data_plane_id
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            existing = PlatformPluginApplyStateModel(
                id=PlatformPluginApplyStateModel.generate_id(),
                data_plane_id=data_plane_id,
                snapshot_digest=snapshot_digest,
                requested_version=requested_version,
                applied_version=applied_version,
                status=status,
                error_message=error_message,
            )
            self._session.add(existing)
        else:
            existing.snapshot_digest = snapshot_digest
            existing.requested_version = requested_version
            existing.applied_version = applied_version
            existing.status = status
            existing.error_message = error_message
        await self._session.flush()
        return existing
