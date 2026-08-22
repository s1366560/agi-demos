"""Read-only V1 desired-state export and append-only conversion audit persistence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    PlatformPluginDesiredStateModel,
    PlatformPluginPackageModel,
    PlatformPluginV1MigrationRunModel,
    Project,
    Tenant,
)
from src.infrastructure.plugins.v2.protocol import canonical_json_v2


class PlatformPluginV1MigrationRepositoryError(ValueError):
    """Stable source-integrity or audit-conflict failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class LegacyPluginDesiredStateRowV1:
    """Secret-free, content-addressed projection of one V1 desired-state row."""

    source_row_id: str
    source_row_digest: str
    source_scope_type: str
    source_scope_id: str
    scope: ScopeV2
    plugin_id: str
    enabled: bool
    revision: int
    config_digest: str
    config_keys: tuple[str, ...]
    packages: tuple[dict[str, object], ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "source_row_id": self.source_row_id,
            "source_row_digest": self.source_row_digest,
            "source_scope_type": self.source_scope_type,
            "source_scope_id": self.source_scope_id,
            "scope": scope_v2_to_payload(self.scope),
            "plugin_id": self.plugin_id,
            "enabled": self.enabled,
            "revision": self.revision,
            "config_digest": self.config_digest,
            "config_keys": list(self.config_keys),
            "packages": [dict(package) for package in self.packages],
        }


@dataclass(frozen=True, kw_only=True)
class LegacyPluginDesiredStateExportV1:
    """Exact secret-free source snapshot bound by one canonical digest."""

    digest: str
    rows: tuple[LegacyPluginDesiredStateRowV1, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "digest": self.digest,
            "rows": [row.to_payload() for row in self.rows],
        }


@dataclass(frozen=True, kw_only=True)
class PlatformPluginV1MigrationRunRecord:
    """Completed conversion audit returned without exposing mutable ORM state."""

    record_id: str
    migration_id: str
    source_digest: str
    mapping_digest: str
    output_digest: str
    actor_id: str
    report: dict[str, object]
    created_at: datetime


class PlatformPluginV1MigrationRepository:
    """Snapshot frozen V1 inputs and append one completed conversion record."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def export_source(self) -> LegacyPluginDesiredStateExportV1:
        """Read all V1 desired rows without exporting config values or credentials."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginDesiredStateModel).order_by(
                    PlatformPluginDesiredStateModel.scope_type,
                    PlatformPluginDesiredStateModel.scope_id,
                    PlatformPluginDesiredStateModel.plugin_id,
                    PlatformPluginDesiredStateModel.id,
                )
            )
        )
        models = list(result.scalars().all())
        package_map = await self._package_snapshots({model.plugin_id for model in models})
        rows: list[LegacyPluginDesiredStateRowV1] = []
        for model in models:
            scope = await self._resolve_scope(model)
            config_keys = tuple(sorted(str(key) for key in model.config))
            packages = tuple(dict(item) for item in package_map.get(model.plugin_id, ()))
            base_payload: dict[str, object] = {
                "source_row_id": model.id,
                "source_scope_type": model.scope_type,
                "source_scope_id": model.scope_id,
                "scope": scope_v2_to_payload(scope),
                "plugin_id": model.plugin_id,
                "enabled": model.enabled,
                "revision": model.revision,
                "config_digest": digest_payload_v1_to_v2(dict(model.config)),
                "config_keys": list(config_keys),
                "packages": [dict(item) for item in packages],
            }
            row_digest = digest_payload_v1_to_v2(base_payload)
            rows.append(
                LegacyPluginDesiredStateRowV1(
                    source_row_id=model.id,
                    source_row_digest=row_digest,
                    source_scope_type=model.scope_type,
                    source_scope_id=model.scope_id,
                    scope=scope,
                    plugin_id=model.plugin_id,
                    enabled=model.enabled,
                    revision=model.revision,
                    config_digest=str(base_payload["config_digest"]),
                    config_keys=config_keys,
                    packages=packages,
                )
            )
        rows_payload = [row.to_payload() for row in rows]
        digest = digest_payload_v1_to_v2(
            {
                "schema_version": 1,
                "rows": rows_payload,
            }
        )
        return LegacyPluginDesiredStateExportV1(digest=digest, rows=tuple(rows))

    async def get_completed_run(
        self,
        migration_id: str,
    ) -> PlatformPluginV1MigrationRunRecord | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV1MigrationRunModel).where(
                    PlatformPluginV1MigrationRunModel.migration_id == migration_id
                )
            )
        )
        model = result.scalar_one_or_none()
        return None if model is None else self._run_record(model)

    async def record_completed_run(
        self,
        *,
        migration_id: str,
        source_digest: str,
        mapping_digest: str,
        output_digest: str,
        actor_id: str,
        report: dict[str, object],
    ) -> PlatformPluginV1MigrationRunRecord:
        existing = await self.get_completed_run(migration_id)
        if existing is not None:
            exact = (existing.source_digest, existing.mapping_digest, existing.output_digest)
            requested = (source_digest, mapping_digest, output_digest)
            if exact != requested:
                _fail(
                    "migration_id_conflict",
                    "migration_id already belongs to different conversion evidence",
                )
            return existing
        model = PlatformPluginV1MigrationRunModel(
            id=PlatformPluginV1MigrationRunModel.generate_id(),
            migration_id=migration_id,
            source_digest=source_digest,
            mapping_digest=mapping_digest,
            output_digest=output_digest,
            actor_id=actor_id,
            report=dict(report),
        )
        self._session.add(model)
        await self._session.flush()
        return self._run_record(model)

    async def _resolve_scope(self, row: PlatformPluginDesiredStateModel) -> ScopeV2:
        if row.scope_type == "global":
            if row.scope_id != "global":
                _fail("migration_source_scope_invalid", "global V1 scope_id must be global")
            return ScopeV2(kind=ScopeKindV2.ROOT)
        if row.scope_type == "tenant":
            if await self._session.get(Tenant, row.scope_id) is None:
                _fail("migration_source_scope_missing", "V1 tenant scope no longer exists")
            return ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=row.scope_id)
        if row.scope_type == "project":
            project = await self._session.get(Project, row.scope_id)
            if project is None:
                _fail("migration_source_scope_missing", "V1 project scope no longer exists")
            return ScopeV2(
                kind=ScopeKindV2.PROJECT,
                tenant_id=project.tenant_id,
                project_id=project.id,
            )
        if row.scope_type == "session":
            conversation = await self._session.get(Conversation, row.scope_id)
            if conversation is None:
                _fail("migration_source_scope_missing", "V1 session scope no longer exists")
            return ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id=conversation.tenant_id,
                project_id=conversation.project_id,
                session_id=conversation.id,
            )
        _fail("migration_source_scope_invalid", "V1 desired row declares an unknown scope")

    async def _package_snapshots(
        self,
        plugin_ids: set[str],
    ) -> dict[str, tuple[dict[str, object], ...]]:
        if not plugin_ids:
            return {}
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginPackageModel)
                .where(PlatformPluginPackageModel.plugin_id.in_(plugin_ids))
                .order_by(
                    PlatformPluginPackageModel.plugin_id,
                    PlatformPluginPackageModel.version,
                )
            )
        )
        grouped: dict[str, list[dict[str, object]]] = {}
        for package in result.scalars().all():
            grouped.setdefault(package.plugin_id, []).append(
                {
                    "version": package.version,
                    "artifact_digest": package.artifact_digest,
                    "oci_manifest_digest": package.oci_manifest_digest,
                    "install_status": package.install_status,
                    "security_scan_status": package.security_scan_status,
                    "revoked": package.revoked,
                    "manifest_digest": digest_payload_v1_to_v2(package.manifest),
                    "signature_digest": digest_payload_v1_to_v2(package.signature),
                    "provenance_digest": digest_payload_v1_to_v2(package.provenance),
                }
            )
        return {plugin_id: tuple(items) for plugin_id, items in grouped.items()}

    @staticmethod
    def _run_record(
        model: PlatformPluginV1MigrationRunModel,
    ) -> PlatformPluginV1MigrationRunRecord:
        created_at = model.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return PlatformPluginV1MigrationRunRecord(
            record_id=model.id,
            migration_id=model.migration_id,
            source_digest=model.source_digest,
            mapping_digest=model.mapping_digest,
            output_digest=model.output_digest,
            actor_id=model.actor_id,
            report=dict(model.report),
            created_at=created_at,
        )


def digest_payload_v1_to_v2(payload: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_v2(payload)).hexdigest()}"


def scope_v2_to_payload(scope: ScopeV2) -> dict[str, str]:
    payload = {"kind": scope.kind.value}
    for name in ("tenant_id", "project_id", "session_id"):
        value = getattr(scope, name)
        if value is not None:
            payload[name] = value
    return payload


def _fail(code: str, message: str) -> NoReturn:
    raise PlatformPluginV1MigrationRepositoryError(code, message)


__all__ = [
    "LegacyPluginDesiredStateExportV1",
    "LegacyPluginDesiredStateRowV1",
    "PlatformPluginV1MigrationRepository",
    "PlatformPluginV1MigrationRepositoryError",
    "PlatformPluginV1MigrationRunRecord",
    "digest_payload_v1_to_v2",
    "scope_v2_to_payload",
]
