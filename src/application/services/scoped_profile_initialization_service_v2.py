"""Initialize a private configuration snapshot once, never live-inherit a parent.

Callers authorize the target scope before invoking this service. The transaction
locks every ancestor head in root-to-leaf order, creating missing head rows even
when that ancestor has no desired configuration. Existing target configuration
is never overwritten; missing or corrupt exact sources fail closed.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.plugins.generated_v2 import (
    ProfileSourceReferenceV2,
    ProfileSourceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRecordV2,
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
    ScopeLedgerBindingV2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import ProductionBundleSourcesV2
from src.infrastructure.plugins.v2.protocol import (
    canonical_json_v2,
    parse_profile_source_v2,
    profile_source_v2_to_payload,
)
from src.infrastructure.plugins.v2.scope import scope_key_v2, scope_v2_to_payload, validate_scope_v2


class ScopedProfileInitializationV2Error(ValueError):
    """Stable initialization failure without any runtime fallback."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ScopedProfileInitializationServiceV2:
    """Atomically copy the nearest complete ancestor configuration to a new scope."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        production_sources: ProductionBundleSourcesV2,
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._production_sources = production_sources

    async def ensure_initialized(
        self, scope: ScopeV2, actor_id: str
    ) -> PlatformPluginDesiredBundleSetRecordV2:
        scope = validate_scope_v2(scope)
        if scope.kind is ScopeKindV2.ROOT:
            raise ScopedProfileInitializationV2Error(
                "scoped_initialization_root_forbidden", "root initialization is not supported"
            )
        chain = _scope_chain(scope)
        async with self._session_factory() as session:
            desired_repo = PlatformPluginDesiredBundleSetRepositoryV2(session)
            source_repo = PlatformPluginProfileSourceRepositoryV2(session)
            current = await desired_repo.current_desired_set(scope)
            if current is not None:
                _ = await self._source(source_repo, current)
                return current
            for ancestor in chain:
                _ = await ScopeLedgerBindingV2(ancestor, ScopedProfileInitializationV2Error).lock(
                    session
                )
            current = await desired_repo.current_desired_set(scope)
            if current is not None:
                _ = await self._source(source_repo, current)
                await session.commit()
                return current
            for ancestor in reversed(chain[:-1]):
                parent = await desired_repo.current_desired_set(ancestor)
                if parent is not None:
                    parent_source = await self._source(source_repo, parent)
                    source = _clone_source(scope, parent, parent_source)
                    desired = replace(
                        parent.desired_set,
                        desired_set_id=f"initialized-desired-{scope_key_v2(scope)}",
                        revision=1,
                        profile_source=ProfileSourceReferenceV2(
                            source_id=source.source_id, revision=1, digest=source.digest
                        ),
                    )
                    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
                    _ = await source_repo.record_source(
                        scope=scope, source=source, expected_revision=None
                    )
                    record = await desired_repo.record_desired_set(
                        scope=scope, desired_set=desired, expected_revision=None, actor_id=actor_id
                    )
                    await session.commit()
                    return record
            raise ScopedProfileInitializationV2Error(
                "scoped_initialization_parent_missing", "no ancestor configuration exists"
            )

    async def _source(
        self,
        repository: PlatformPluginProfileSourceRepositoryV2,
        record: PlatformPluginDesiredBundleSetRecordV2,
    ) -> ProfileSourceV2:
        reference = record.desired_set.profile_source
        source = await repository.read_exact(
            scope=record.scope,
            source_id=reference.source_id,
            revision=reference.revision,
            digest=reference.digest,
        )
        if source is not None:
            return source
        builtin = self._production_sources.profile_source
        if record.scope.kind is ScopeKindV2.ROOT and (
            reference.source_id,
            reference.revision,
            reference.digest,
        ) == (builtin.source_id, builtin.revision, builtin.digest):
            return parse_profile_source_v2(profile_source_v2_to_payload(builtin))
        raise ScopedProfileInitializationV2Error(
            "scoped_initialization_source_missing", "exact configuration source is unavailable"
        )


def _scope_chain(scope: ScopeV2) -> tuple[ScopeV2, ...]:
    chain = [ScopeV2(kind=ScopeKindV2.ROOT)]
    if scope.tenant_id is not None:
        chain.append(ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=scope.tenant_id))
    if scope.project_id is not None:
        chain.append(
            ScopeV2(
                kind=ScopeKindV2.PROJECT, tenant_id=scope.tenant_id, project_id=scope.project_id
            )
        )
    if scope.session_id is not None:
        chain.append(scope)
    return tuple(chain)


def _clone_source(
    scope: ScopeV2, parent: PlatformPluginDesiredBundleSetRecordV2, source: ProfileSourceV2
) -> ProfileSourceV2:
    desired = parent.desired_set
    provenance = canonical_json_v2(
        {
            "parent_scope": scope_v2_to_payload(parent.scope),
            "desired": {
                "id": desired.desired_set_id,
                "revision": desired.revision,
                "digest": desired.digest,
            },
            "source": {
                "id": source.source_id,
                "revision": source.revision,
                "digest": source.digest,
            },
            "original_provenance": source.provenance,
        }
    ).decode("utf-8")
    cloned = replace(
        source,
        source_id=f"initialized-source-{scope_key_v2(scope)}",
        revision=1,
        provenance=provenance,
    )
    return replace(cloned, digest=profile_source_digest_v2(cloned))
