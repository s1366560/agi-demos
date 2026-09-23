"""Scoped signed-package lifecycle records backed by actual V2 publication receipts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
        ScopedProfileRuntimeV2,
    )
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
        PlatformPluginDesiredBundleSetRecordV2,
    )
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.plugin_marketplace_desired_bundle_service_v2 import (
    PluginMarketplaceDesiredBundleServiceV2,
)
from src.application.services.scoped_profile_initialization_service_v2 import (
    ScopedProfileInitializationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2, ServiceRequiredV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins.v2.agent_turn_requirements_v2 import AGENT_TURN_REQUIRED_SERVICES_V2
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import parse_bundle_manifest_v2
from src.infrastructure.plugins.v2.scope import scope_key_v2


def marketplace_scope(tenant_id: str, project_id: str | None = None) -> ScopeV2:
    return ScopeV2(
        kind=ScopeKindV2.PROJECT if project_id else ScopeKindV2.TENANT,
        tenant_id=tenant_id,
        project_id=project_id,
    )


async def signed_installations(
    db: AsyncSession, tenant_id: str, project_id: str | None
) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(MarketplaceRecordV3).where(
            MarketplaceRecordV3.tenant_id == tenant_id,
            MarketplaceRecordV3.project_id == (project_id or ""),
            MarketplaceRecordV3.kind == "signed_installation",
        )
    )
    result = []
    governance = PlatformPluginGovernanceRepository(db)
    for row in rows:
        payload = dict(row.payload)
        package = await governance.get_package_version(payload["plugin_id"], payload["version"])
        if payload["status"] != "uninstalled" and (package is None or package.revoked):
            payload.update(status="failed", error="signed_package_unavailable_or_revoked")
        result.append(payload)
    return result


class SignedMarketplaceScopeV2:
    """Preserve signed verification and isolate changes to one initialized scope.

    Desired changes commit before publication, as required by the scoped coordinator.
    A rejected candidate is compensated with a new desired revision; the old runtime
    lease remains valid. Records never claim that mere desired presence is enabled.
    """

    def __init__(
        self,
        db: AsyncSession,
        runtime: ScopedProfileRuntimeV2,
        tenant_id: str,
        project_id: str | None = None,
    ) -> None:
        self.db = db
        self.runtime = runtime
        self.scope = marketplace_scope(tenant_id, project_id)
        self.desired = PlatformPluginDesiredBundleSetRepositoryV2(db)
        self.governance = PlatformPluginGovernanceRepository(db)
        self.mutations = PluginMarketplaceDesiredBundleServiceV2(
            self.desired,
            baseline=production_bundle_sources_v2().desired_set,
        )

    async def initialize(self, actor_id: str) -> None:
        await ScopedProfileInitializationServiceV2(
            session_factory=async_sessionmaker(self.db.bind, expire_on_commit=False),
            production_sources=production_bundle_sources_v2(),
        ).ensure_initialized(self.scope, actor_id)

    async def record(self, plugin_id: str) -> MarketplaceRecordV3 | None:
        return await self.db.scalar(
            select(MarketplaceRecordV3)
            .where(
                MarketplaceRecordV3.tenant_id == self.scope.tenant_id,
                MarketplaceRecordV3.project_id == (self.scope.project_id or ""),
                MarketplaceRecordV3.kind == "signed_installation",
                MarketplaceRecordV3.record_key == plugin_id,
            )
            .with_for_update()
        )

    async def begin(self, plugin_id: str, version: str) -> tuple[Any, dict[str, Any] | None]:
        previous = await self.desired.current_desired_set(self.scope)
        row = await self.record(plugin_id)
        old = dict(row.payload) if row else None
        if row is None:
            identifier = hashlib.sha256(
                f"{scope_key_v2(self.scope)}:{plugin_id}".encode()
            ).hexdigest()
            row = MarketplaceRecordV3(
                id=identifier,
                tenant_id=self.scope.tenant_id,
                project_id=self.scope.project_id or "",
                kind="signed_installation",
                record_key=plugin_id,
                payload={},
            )
            self.db.add(row)
        row.payload = {
            "id": row.id,
            "plugin_id": plugin_id,
            "source_id": "signed-v2",
            "name": plugin_id,
            "version": version,
            "format": "v2",
            "install_strategy": "signed-v2",
            "status": "downloaded",
            "capabilities": [],
            "required_credentials": [],
            "scope": self.scope.kind.value,
        }
        await self.db.flush()
        return previous, old

    async def publish(  # noqa: C901, PLR0912
        self,
        plugin_id: str,
        *,
        previous: PlatformPluginDesiredBundleSetRecordV2 | None,
        old: dict[str, Any] | None,
        actor_id: str,
        target_status: str = "enabled",
    ) -> dict[str, Any]:
        candidate = await self.desired.current_desired_set(self.scope)
        await self.db.commit()
        try:
            requirements = list(AGENT_TURN_REQUIRED_SERVICES_V2)
            head = await self.desired.current_desired_set(self.scope)
            if head is None:
                raise ValueError("signed scope desired state missing")
            # Protocol-declared roots only. Global HTTP route services fail the existing
            # scoped projector; they are never activated in the shared ROOT runtime.
            for ref in head.desired_set.bundles:
                package = await self.governance.get_package_version(ref.bundle_id, ref.version)
                if package is None:
                    continue
                manifest = parse_bundle_manifest_v2(package.manifest)
                for plugin in manifest.manifests:
                    for module in plugin.modules:
                        if not any(target.value == "python" for target in module.targets):
                            continue
                        for provided in module.contract.services.provides:
                            if not any(item.service == provided.service for item in requirements):
                                requirements.append(
                                    ServiceRequiredV2(
                                        alias=f"marketplace_{len(requirements)}",
                                        service=provided.service,
                                        version=provided.version,
                                    )
                                )
            publication = (
                await self.runtime.publish_current(
                    self.scope, required_services=tuple(requirements)
                )
            ).publication
            if not publication.accepted:
                raise ValueError(
                    publication.receipt.error_message or "signed scoped publication rejected"
                )
            row = await self.record(plugin_id)
            if row is None:
                raise ValueError("signed installation record missing")
            state = target_status
            if target_status == "enabled":
                package = await self.governance.get_package_version(
                    plugin_id, row.payload["version"]
                )
                manifest = parse_bundle_manifest_v2(package.manifest)
                expected = {item.plugin_id for item in manifest.manifests}
                if not expected.intersection(
                    item.plugin_id for item in publication.snapshot.manifests
                ):
                    state = "downloaded"
            row.payload = {
                **row.payload,
                "status": state,
                "error": None,
                "publication_version": publication.envelope.version,
            }
            await self.db.commit()
            return dict(row.payload)
        except Exception as exc:
            current = await self.desired.current_desired_set(self.scope)
            owns_candidate = (
                current is not None
                and candidate is not None
                and current.desired_set == candidate.desired_set
            )
            if previous is not None and owns_candidate:
                restored = replace(previous.desired_set, revision=current.desired_set.revision + 1)
                restored = replace(restored, digest=desired_bundle_set_digest_v2(restored))
                await self.desired.record_desired_set(
                    scope=self.scope,
                    desired_set=restored,
                    expected_revision=current.desired_set.revision,
                    actor_id=actor_id,
                )
            row = await self.record(plugin_id)
            if row is not None and owns_candidate:
                row.payload = {
                    **(old or row.payload),
                    "status": old["status"] if old else "failed",
                    "error": f"signed_publication_failed:{type(exc).__name__}",
                }
            await self.db.commit()
            raise

    async def mutate(
        self, plugin_id: str, action: str, actor_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        key = f"signed:{data['idempotency_key']}"
        digest = hashlib.sha256(
            json.dumps(
                {"plugin_id": plugin_id, "action": action, **data},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        job = await self.db.scalar(
            select(MarketplaceRecordV3).where(
                MarketplaceRecordV3.tenant_id == self.scope.tenant_id,
                MarketplaceRecordV3.project_id == (self.scope.project_id or ""),
                MarketplaceRecordV3.kind == "operation",
                MarketplaceRecordV3.record_key == key,
            )
        )
        if job:
            if job.payload["request_hash"] != digest:
                raise ValueError("idempotency key reused with different request")
            if job.payload["status"] != "completed":
                raise ValueError("signed operation did not complete; use a new key after recovery")
            return dict(job.payload["result"])
        row = await self.record(plugin_id)
        if row is None:
            raise LookupError("signed installation not found")
        identifier = str(uuid4())
        job = MarketplaceRecordV3(
            id=identifier,
            tenant_id=self.scope.tenant_id,
            project_id=self.scope.project_id or "",
            kind="operation",
            record_key=key,
            payload={
                "id": identifier,
                "installation_id": row.id,
                "action": action,
                "request_hash": digest,
                "status": "running",
                "stage": "applying",
                "stages": ["requested", "applying"],
            },
        )
        self.db.add(job)
        await self.db.commit()
        try:
            result = await self.toggle(plugin_id, action, actor_id)
            result["job_id"] = identifier
            job.payload = {
                **job.payload,
                "status": "completed",
                "stage": result["status"],
                "stages": ["requested", "applying", result["status"]],
                "result": result,
            }
            await self.db.commit()
            return result
        except Exception as exc:
            job.payload = {
                **job.payload,
                "status": "failed",
                "stage": "rolled_back",
                "stages": ["requested", "applying", "rolled_back"],
                "error": type(exc).__name__,
            }
            await self.db.commit()
            raise

    async def toggle(self, plugin_id: str, action: str, actor_id: str) -> dict[str, Any]:
        row = await self.record(plugin_id)
        if row is None or row.payload["status"] == "uninstalled":
            raise LookupError("signed installation not found in selected scope")
        old = dict(row.payload)
        previous = await self.desired.current_desired_set(self.scope)
        desired_removed = False
        if action in {"disable", "uninstall"}:
            mutation = await self.mutations.uninstall(
                scope=self.scope, bundle_id=plugin_id, actor_id=actor_id
            )
            desired_removed = mutation.changed
        elif action == "enable":
            from src.domain.model.plugins.generated_v2 import BundleReferenceV2

            package = await self.governance.get_package_version(plugin_id, old["version"])
            if package is None or package.revoked:
                raise ValueError("signed package unavailable or revoked")
            bundle = parse_bundle_manifest_v2(package.manifest)
            await self.mutations.install(
                scope=self.scope,
                actor_id=actor_id,
                bundle=BundleReferenceV2(
                    bundle_id=plugin_id,
                    version=bundle.version,
                    digest=bundle.digest,
                    source=f"marketplace://{plugin_id}/{bundle.version}",
                ),
            )
        elif action != "verify":
            raise ValueError("use the signed installer to verify signatures and update")
        status = {"disable": "disabled", "uninstall": "uninstalled", "verify": old["status"]}.get(
            action, "enabled"
        )
        result = await self.publish(
            plugin_id, previous=previous, old=old, actor_id=actor_id, target_status=status
        )
        if action == "uninstall":
            result["desired_removed"] = desired_removed
            result["revoked_permissions"] = await self.governance.revoke_permissions(
                plugin_id,
                scope_type=self.scope.kind.value,
                scope_id=self.scope.project_id or self.scope.tenant_id,
            )
            await self.db.commit()
        return result


async def reconcile_signed_session_scope(  # noqa: C901, PLR0912  # Explicit ownership and state guards.
    db: AsyncSession, scope: ScopeV2, actor_id: str
) -> None:
    """Reconcile only previously inherited signed references before new session work.

    Bindings retain ownership across disable/enable. They never add a newly installed
    parent bundle to an existing session. Private profile sources remain unchanged.
    """
    if scope.kind is not ScopeKindV2.SESSION:
        return
    from src.domain.model.plugins.generated_v2 import BundleReferenceV2
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
        ScopeLedgerBindingV2,
    )

    assert scope.tenant_id is not None
    assert scope.project_id is not None
    await ScopeLedgerBindingV2(scope, lambda code, message: ValueError(f"{code}: {message}")).lock(
        db
    )
    repository = PlatformPluginDesiredBundleSetRepositoryV2(db)
    head = await repository.current_desired_set(scope)
    if head is None:
        return
    bindings = {
        row.payload["bundle"]["bundle_id"]: row
        for row in await db.scalars(
            select(MarketplaceRecordV3).where(
                MarketplaceRecordV3.kind == "signed_session_binding",
                MarketplaceRecordV3.tenant_id == scope.tenant_id,
                MarketplaceRecordV3.project_id == scope.project_id,
            )
        )
        if row.payload["session_id"] == scope.session_id
    }
    candidates = list(head.desired_set.bundles)
    ids = {ref.bundle_id for ref in candidates}
    for key, row in bindings.items():
        if key not in ids:
            candidates.append(BundleReferenceV2(**row.payload["bundle"]))
    references = []
    for reference in candidates:
        owner = None
        for project_id in (scope.project_id, ""):
            owner = await db.scalar(
                select(MarketplaceRecordV3).where(
                    MarketplaceRecordV3.kind == "signed_installation",
                    MarketplaceRecordV3.tenant_id == scope.tenant_id,
                    MarketplaceRecordV3.project_id == project_id,
                    MarketplaceRecordV3.record_key == reference.bundle_id,
                )
            )
            if owner is not None:
                break
        if owner is None:
            if reference.bundle_id in ids:
                references.append(reference)
            continue
        if reference.bundle_id not in bindings:
            key = f"{scope.session_id}:{reference.bundle_id}"
            db.add(
                MarketplaceRecordV3(
                    id=hashlib.sha256(
                        f"signed-binding:{scope_key_v2(scope)}:{key}".encode()
                    ).hexdigest(),
                    tenant_id=scope.tenant_id,
                    project_id=scope.project_id,
                    kind="signed_session_binding",
                    record_key=key,
                    payload={
                        "session_id": scope.session_id,
                        "bundle": {
                            "bundle_id": reference.bundle_id,
                            "version": reference.version,
                            "digest": reference.digest,
                            "source": reference.source,
                        },
                    },
                )
            )
        if owner.payload["status"] in {"disabled", "uninstalled", "failed"}:
            continue
        package = await PlatformPluginGovernanceRepository(db).get_package_version(
            reference.bundle_id, owner.payload["version"]
        )
        if package is None or package.revoked:
            continue
        owner_scope = marketplace_scope(scope.tenant_id, owner.project_id or None)
        current = await repository.current_desired_set(owner_scope)
        replacement = (
            next(
                (
                    ref
                    for ref in current.desired_set.bundles
                    if ref.bundle_id == reference.bundle_id
                ),
                None,
            )
            if current
            else None
        )
        if replacement is not None:
            references.append(replacement)
    if tuple(references) != head.desired_set.bundles:
        desired = replace(
            head.desired_set, revision=head.desired_set.revision + 1, bundles=tuple(references)
        )
        desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
        await repository.record_desired_set(
            scope=scope,
            desired_set=desired,
            expected_revision=head.desired_set.revision,
            actor_id=actor_id,
        )
    await db.commit()
