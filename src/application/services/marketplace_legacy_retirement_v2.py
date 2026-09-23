"""Publish real replacement generations for inactive local legacy recovery scopes."""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
        ScopedProfileRuntimeV2,
    )
    from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.marketplace_legacy_cleanup_v2 import MarketplaceLegacyCleanupV2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import desired_bundle_set_v2_to_payload
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginPublicationV2


async def retire_legacy_applied_scopes(
    cleanup: MarketplaceLegacyCleanupV2,
    *,
    expected_digest: str,
    backup_path: Path,
    publish: Callable[[ScopeV2], Awaitable[PlatformPluginPublicationV2]],
) -> list[dict[str, Any]]:
    """Change only the builtin archive reference in exact blocked scope heads.

    No receipt is synthesized. Existing desired refs must already exclude legacy
    packages. Replacing the stale builtin content digest preserves profile sources
    and configuration; the real scoped runtime must ACK the complete candidate.
    """
    plan = await cleanup.plan()
    if plan["digest"] != expected_digest:
        raise ValueError("cleanup plan changed")
    if any(item["kind"] != "applied_reference" for item in plan["blockers"]):
        raise ValueError("retirement supports only inactive applied references")
    db: AsyncSession = cleanup.db
    repository = PlatformPluginDesiredBundleSetRepositoryV2(db)
    scopes = []
    records = []
    for item in plan["blockers"]:
        row = await db.get(PlatformPluginV2PublicationModel, item["id"])
        if row is None or row.scope_kind == "root":
            raise ValueError("root authority must be retired by its managed application")
        scope = ScopeV2(
            kind=ScopeKindV2(row.scope_kind),
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            session_id=row.session_id,
        )
        if scope in scopes:
            continue
        current = await repository.current_desired_set(scope)
        if current is None:
            raise ValueError("legacy recovery scope lacks current desired state")
        scopes.append(scope)
        records.append(current)
    backup = {
        "cleanup": plan,
        "desired": [
            {
                "scope": {
                    "kind": record.scope.kind.value,
                    "tenant_id": record.scope.tenant_id,
                    "project_id": record.scope.project_id,
                    "session_id": record.scope.session_id,
                },
                "payload": desired_bundle_set_v2_to_payload(record.desired_set),
            }
            for record in records
        ],
    }
    if backup_path.is_symlink() or not backup_path.parent.is_dir():
        raise ValueError("backup requires an existing directory and a new regular file")
    descriptor = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(backup, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    baseline = production_bundle_sources_v2().desired_set.bundles
    refs = {ref.bundle_id: ref for ref in baseline}
    results = []
    for record in records:
        desired = replace(
            record.desired_set,
            revision=record.desired_set.revision + 1,
            bundles=tuple(refs.get(ref.bundle_id, ref) for ref in record.desired_set.bundles),
        )
        desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
        await repository.record_desired_set(
            scope=record.scope,
            desired_set=desired,
            expected_revision=record.desired_set.revision,
            actor_id="local-marketplace-cleanup",
        )
        await db.commit()
        publication = await publish(record.scope)
        if not publication.accepted:
            raise ValueError(
                "legacy scope replacement was not acknowledged; cleanup remains blocked"
            )
        results.append(
            {
                "scope": record.scope.kind.value,
                "session_id": record.scope.session_id,
                "publication_version": publication.envelope.version,
                "accepted": True,
            }
        )
    return results


async def maintenance_scoped_runtime(
    db: AsyncSession,
) -> tuple[ScopedProfileRuntimeV2, PlatformPluginRuntimeHostV2]:
    """Start only the operation boundary; never launch HTTP, schedulers or health loops."""
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.domain.model.plugins.generated_v2 import ServiceRequiredV2
    from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
        initialize_scoped_profile_runtime_v2,
    )
    from src.infrastructure.plugins.v2.builtin_modules import (
        RUNTIME_BOUNDARY_SERVICE_V2,
        builtin_runtime_definitions_v2,
    )
    from src.infrastructure.plugins.v2.composer import compose_profile_v2
    from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
    from src.infrastructure.plugins.v2.protocol import control_envelope_v2
    from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
    from src.infrastructure.plugins.v2.sandbox_runtime import SANDBOX_RUNTIME_SERVICE_V2
    from src.infrastructure.plugins.v2.service_closure import project_service_closure_v2

    source = production_bundle_sources_v2()
    root = ScopeV2(kind=ScopeKindV2.ROOT)
    composition = compose_profile_sources_v2(
        desired_set=source.desired_set,
        bundles=(source.bundle,),
        profile_source=source.profile_source,
        scope=root,
    )
    snapshot = compose_profile_v2(
        composition.document,
        {manifest.plugin_id: manifest for manifest in composition.manifests},
        generation=1,
    )
    projected = project_service_closure_v2(
        snapshot,
        scope=root,
        required_services=(
            ServiceRequiredV2(
                alias="boundary", service=RUNTIME_BOUNDARY_SERVICE_V2, version="1.0.0"
            ),
            ServiceRequiredV2(alias="sandbox", service=SANDBOX_RUNTIME_SERVICE_V2, version="1.0.0"),
        ),
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.apply(projected, control_envelope_v2(projected, version=1))
    if not publication.accepted:
        await host.close()
        raise ValueError("maintenance boundary failed to initialize")
    app = FastAPI()
    app.state.platform_plugin_runtime_v2 = host
    app.state.plugin_marketplace_trusted_public_keys_v2 = ()
    app.state.plugin_marketplace_allowed_registries_v2 = frozenset()
    runtime = initialize_scoped_profile_runtime_v2(
        app, session_factory=async_sessionmaker(db.bind, expire_on_commit=False), redis_client=None
    )
    return runtime, host
