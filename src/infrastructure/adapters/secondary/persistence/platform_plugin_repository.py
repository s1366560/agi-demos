"""Repository for the platform plugin control plane."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins import PluginManifest, PluginScope
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginApplyStateModel,
    PlatformPluginCapabilityAuditModel,
    PlatformPluginCatalogModel,
    PlatformPluginDesiredStateModel,
    PlatformPluginPackageModel,
    PlatformPluginShadowRolloutEventModel,
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

    async def list_desired_states(self) -> list[PlatformPluginDesiredStateModel]:
        """Return every declarative desired-state row deterministically."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginDesiredStateModel).order_by(
                    PlatformPluginDesiredStateModel.scope_type,
                    PlatformPluginDesiredStateModel.scope_id,
                    PlatformPluginDesiredStateModel.plugin_id,
                )
            )
        )
        return list(result.scalars().all())

    async def list_installed_packages(self) -> list[PlatformPluginPackageModel]:
        """Return installed marketplace package sources."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginPackageModel)
                .where(
                    PlatformPluginPackageModel.revoked.is_(False),
                    PlatformPluginPackageModel.install_status == "installed",
                )
                .order_by(PlatformPluginPackageModel.plugin_id)
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

    async def remove_desired_state(
        self,
        plugin_id: str,
        *,
        scope: PluginScope = PluginScope.GLOBAL,
        scope_id: str | None = None,
    ) -> bool:
        """Remove one desired row and report whether it existed."""
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
            return False
        await self._session.delete(existing)
        await self._session.flush()
        return True

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

    async def record_shadow_rollout_events(
        self,
        records: list[dict[str, Any]],
    ) -> list[PlatformPluginShadowRolloutEventModel]:
        """Append a bounded batch of shadow rollout comparisons."""
        models = [
            PlatformPluginShadowRolloutEventModel(
                id=PlatformPluginShadowRolloutEventModel.generate_id(),
                capability=str(record["capability"]),
                event_name=str(record["event_name"]),
                hook_name=str(record["hook_name"]),
                scope_type=str(record["scope_type"]),
                scope_id=str(record["scope_id"]),
                equal=bool(record["equal"]),
                legacy_payload=dict(record["legacy_payload"]),
                typed_payload=dict(record["typed_payload"]),
                occurred_at=record["occurred_at"],
            )
            for record in records
        ]
        self._session.add_all(models)
        await self._session.flush()
        return models

    async def list_shadow_rollout_events(
        self,
        *,
        limit: int,
        only_diffs: bool = False,
    ) -> list[PlatformPluginShadowRolloutEventModel]:
        """Return newest rollout evidence for operator review."""
        statement = select(PlatformPluginShadowRolloutEventModel).order_by(
            PlatformPluginShadowRolloutEventModel.occurred_at.desc(),
            PlatformPluginShadowRolloutEventModel.id.desc(),
        )
        if only_diffs:
            statement = statement.where(PlatformPluginShadowRolloutEventModel.equal.is_(False))
        result = await self._session.execute(
            refresh_select_statement(statement.limit(max(1, min(limit, 500))))
        )
        return list(result.scalars().all())

    async def shadow_rollout_summary(self) -> list[dict[str, object]]:
        """Aggregate durable rollout evidence by capability and event."""
        equal_count = func.sum(
            case((PlatformPluginShadowRolloutEventModel.equal.is_(True), 1), else_=0)
        )
        result = await self._session.execute(
            refresh_select_statement(
                select(
                    PlatformPluginShadowRolloutEventModel.capability,
                    PlatformPluginShadowRolloutEventModel.event_name,
                    func.count().label("total_count"),
                    equal_count.label("equal_count"),
                    func.max(PlatformPluginShadowRolloutEventModel.occurred_at).label(
                        "last_occurred_at"
                    ),
                ).group_by(
                    PlatformPluginShadowRolloutEventModel.capability,
                    PlatformPluginShadowRolloutEventModel.event_name,
                )
            )
        )
        rows: list[dict[str, object]] = []
        for row in result.mappings():
            total = int(row["total_count"])
            equal = int(row["equal_count"])
            rows.append(
                {
                    "capability": row["capability"],
                    "event_name": row["event_name"],
                    "total_count": total,
                    "equal_count": equal,
                    "diff_count": total - equal,
                    "equal": total > 0 and total == equal,
                    "last_occurred_at": row["last_occurred_at"],
                }
            )
        return sorted(rows, key=lambda row: (str(row["capability"]), str(row["event_name"])))
