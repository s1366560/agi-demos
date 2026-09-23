"""Precisely backed-up cleanup of inactive third-party catalog state on local development."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginBackendSelectionModel,
    PlatformPluginCredentialGrantModel,
    PlatformPluginHttpRouteModel,
    PlatformPluginPackageModel,
    PlatformPluginPermissionModel,
    PlatformPluginQuotaUsageModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2DesiredBundleSetModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins.v2.production_bundle import (
    PRODUCTION_BASE_BUNDLE_ID_V2,
    production_bundle_sources_v2,
)

_OWNED = (
    PlatformPluginPermissionModel,
    PlatformPluginCredentialGrantModel,
    PlatformPluginHttpRouteModel,
    PlatformPluginQuotaUsageModel,
)


def require_local_development(database_url: str, environment: str) -> str:
    url = make_url(database_url)
    if environment != "development" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("cleanup is restricted to the local development database")
    return hashlib.sha256(f"{url.host}:{url.port}/{url.database}".encode()).hexdigest()


def _row_payload(row: object) -> dict[str, Any]:
    values = {column.key: getattr(row, column.key) for column in inspect(type(row)).columns}
    return {
        key: {"$datetime": value.isoformat()} if isinstance(value, datetime) else value
        for key, value in values.items()
    }


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class MarketplaceLegacyCleanupV2:
    """No runtime, filesystem-cache or business-data deletion is inferred.

    Applied/desired references, active calls and backend selections block cleanup.
    The caller must retire these through their lifecycle first. Immutable publication
    history and unknown/shared files are retained. Only explicit plugin-owned rows
    are removed, with exclusive backup creation before the transaction commits.
    """

    def __init__(self, db: AsyncSession, *, database_url: str, environment: str) -> None:
        self.db = db
        self.target = require_local_development(database_url, environment)

    async def plan(self) -> dict[str, Any]:  # noqa: C901  # Independent structural ownership guards.
        packages = list(await self.db.scalars(select(PlatformPluginPackageModel).with_for_update()))
        scoped_ids = set(
            await self.db.scalars(
                select(MarketplaceRecordV3.record_key).where(
                    MarketplaceRecordV3.kind == "signed_installation"
                )
            )
        )
        candidates = [
            row
            for row in packages
            if row.plugin_id != PRODUCTION_BASE_BUNDLE_ID_V2
            and row.plugin_id not in scoped_ids
            and row.manifest.get("schema_version") == 2
            and row.manifest.get("manifests")
            and all(item.get("trust") == "signed" for item in row.manifest["manifests"])
        ]
        bundle_ids = {row.plugin_id for row in candidates}
        plugin_ids = bundle_ids | {
            item["plugin_id"] for row in candidates for item in row.manifest["manifests"]
        }
        preserved = {row.plugin_id for row in packages if row not in candidates}
        preserved.update(item.plugin_id for item in production_bundle_sources_v2().bundle.manifests)
        # A component shared with a preserved/builtin package cannot be exclusively owned.
        preserved.update(
            item.get("plugin_id")
            for row in packages
            if row not in candidates
            for item in row.manifest.get("manifests", [])
        )
        owned = plugin_ids - preserved
        blockers = []
        heads = {}
        for row in await self.db.scalars(
            select(PlatformPluginV2DesiredBundleSetModel).order_by(
                PlatformPluginV2DesiredBundleSetModel.revision.desc()
            )
        ):
            heads.setdefault(row.scope_key, row)
        for row in heads.values():
            if any(ref.get("bundle_id") in bundle_ids for ref in row.payload.get("bundles", [])):
                blockers.append({"kind": "desired_reference", "id": row.id})
        applied_ids = {
            row.applied_publication_id
            for row in await self.db.scalars(select(PlatformPluginV2ApplyStateModel))
            if row.applied_publication_id
        }
        if applied_ids:
            for row in await self.db.scalars(
                select(PlatformPluginV2PublicationModel).where(
                    PlatformPluginV2PublicationModel.id.in_(applied_ids)
                )
            ):
                snapshot = row.distribution.get("snapshot", {})
                if any(
                    item.get("plugin_id") in plugin_ids for item in snapshot.get("manifests", [])
                ):
                    blockers.append({"kind": "applied_reference", "id": row.id})
        tables = {
            PlatformPluginPackageModel.__tablename__: [_row_payload(row) for row in candidates]
        }
        for model in _OWNED:
            rows = (
                list(
                    await self.db.scalars(
                        select(model).where(model.plugin_id.in_(owned)).with_for_update()
                    )
                )
                if owned
                else []
            )
            tables[model.__tablename__] = [_row_payload(row) for row in rows]
            for row in rows:
                if isinstance(row, PlatformPluginQuotaUsageModel) and row.concurrent_calls:
                    blockers.append({"kind": "in_flight_calls", "id": row.plugin_id})
                if isinstance(row, PlatformPluginHttpRouteModel) and row.enabled:
                    blockers.append({"kind": "enabled_route", "id": row.id})
        if owned:
            for row in await self.db.scalars(
                select(PlatformPluginBackendSelectionModel).where(
                    PlatformPluginBackendSelectionModel.plugin_id.in_(owned)
                )
            ):
                blockers.append({"kind": "backend_selection", "id": row.id})
        payload = {
            "schema_version": 1,
            "target": self.target,
            "tables": tables,
            "blockers": blockers,
            "files": [],
            "preserved": [
                "builtin bundles",
                "business data",
                "publication history",
                "unattributed and shared files",
                "download caches",
            ],
        }
        return {**payload, "digest": _digest(payload)}

    async def apply(self, expected_digest: str, backup_path: Path) -> dict[str, Any]:
        plan = await self.plan()
        if plan["digest"] != expected_digest:
            raise ValueError("cleanup plan changed; generate a new dry run")
        if plan["blockers"]:
            raise ValueError("cleanup requires lifecycle retirement and call drain first")
        if backup_path.is_symlink() or not backup_path.parent.is_dir():
            raise ValueError("backup requires an existing directory and a new regular file")
        descriptor = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as backup:
            json.dump(plan, backup, sort_keys=True, indent=2)
            backup.flush()
            os.fsync(backup.fileno())
        for model in (*_OWNED, PlatformPluginPackageModel):
            for payload in plan["tables"][model.__tablename__]:
                key = tuple(payload[column.key] for column in inspect(model).primary_key)
                row = await self.db.get(model, key)
                if row is None or _row_payload(row) != payload:
                    raise ValueError("cleanup candidate changed after backup")
                await self.db.delete(row)
        await self.db.commit()
        return {
            "digest": plan["digest"],
            "deleted": {table: len(rows) for table, rows in plan["tables"].items()},
            "files_deleted": 0,
        }

    async def restore(self, backup_path: Path) -> dict[str, int]:
        plan = json.loads(backup_path.read_text())
        digest = plan.pop("digest")
        if _digest(plan) != digest or plan["target"] != self.target:
            raise ValueError("backup integrity or deployment mismatch")
        restored = {}
        for model in (PlatformPluginPackageModel, *_OWNED):
            count = 0
            for payload in plan["tables"][model.__tablename__]:
                key = tuple(payload[column.key] for column in inspect(model).primary_key)
                if await self.db.get(model, key) is not None:
                    raise ValueError("restore would overwrite an existing record")
                values = {
                    key: datetime.fromisoformat(value["$datetime"])
                    if isinstance(value, dict) and set(value) == {"$datetime"}
                    else value
                    for key, value in payload.items()
                }
                self.db.add(model(**values))
                count += 1
            restored[model.__tablename__] = count
        await self.db.commit()
        return restored
