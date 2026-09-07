"""Offline migration composition with exact immutable sources; no database is opened."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services import root_profile_initialization_service_v2 as root_initialization
from src.application.services.plugin_protocol_v1_to_v2_migration_service import (
    PluginProtocolV1ToV2MigrationError,
    PluginProtocolV1ToV2MigrationService,
)
from src.domain.model.plugins.generated_v2 import (
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

pytestmark = pytest.mark.unit


@pytest.fixture
def candidate():
    production = production_bundle_sources_v2()
    entry_ids = {
        root_initialization.WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2,
        root_initialization.WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2,
        root_initialization.WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2,
        root_initialization.AGENT_POOL_RUNTIME_ENTRY_ID_V2,
    }
    replacements = tuple(
        replace(entry, enabled=entry.entry_id != root_initialization.AGENT_POOL_RUNTIME_ENTRY_ID_V2)
        for layer in production.bundle.layers
        for entry in layer.entries
        if entry.entry_id in entry_ids
    )
    assert len(replacements) == 4
    source = replace(
        production.profile_source,
        source_id="memstack-root-initialized-profile-source-v2",
        layers=(
            *production.profile_source.layers,
            ProfileLayerV2(
                layer_id="explicit-root-workspace-core",
                kind=ProfileLayerKindV2.PROFILE,
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
                entries=(),
                replacements=replacements,
                disabled_entry_ids=(),
            ),
        ),
    )
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = replace(
        production.desired_set,
        profile_source=ProfileSourceReferenceV2(
            source_id=source.source_id, revision=source.revision, digest=source.digest
        ),
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    repository = Mock(read_exact=AsyncMock(return_value=source))
    service = PluginProtocolV1ToV2MigrationService(
        migration_repository=Mock(),
        desired_repository=Mock(),
        governance_repository=Mock(),
        production_sources=production,
        source_repository=repository,
    )
    return SimpleNamespace(
        service=service,
        source=source,
        desired=desired,
        repository=repository,
        production=production,
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )


async def test_exact_initialized_source_is_preserved_by_noop_plan(candidate):
    plan = await candidate.service._scope_plan(
        scope=candidate.scope, current=SimpleNamespace(desired_set=candidate.desired), rows=[]
    )
    assert plan.desired_set == candidate.desired
    assert plan.changed is False
    candidate.repository.read_exact.assert_awaited_once_with(
        scope=candidate.scope,
        source_id=candidate.source.source_id,
        revision=candidate.source.revision,
        digest=candidate.source.digest,
    )


@pytest.mark.parametrize("fault", ["missing", "digest", "identity", "layers"])
async def test_invalid_persisted_source_is_rejected(candidate, fault):
    source = candidate.source
    if fault == "missing":
        source = None
    elif fault == "digest":
        source = replace(source, digest="sha256:" + "0" * 64)
    elif fault == "identity":
        source = replace(source, source_id="other")
    else:
        source = replace(source, profile_id="tampered")
    candidate.repository.read_exact.return_value = source
    with pytest.raises(PluginProtocolV1ToV2MigrationError) as caught:
        await candidate.service._scope_plan(
            scope=candidate.scope, current=SimpleNamespace(desired_set=candidate.desired), rows=[]
        )
    assert caught.value.code == "migration_target_profile_source_conflict"


async def test_production_base_bundle_must_stay_exact_and_first(candidate):
    desired = replace(candidate.desired, bundles=())
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    with pytest.raises(PluginProtocolV1ToV2MigrationError) as caught:
        await candidate.service._scope_plan(
            scope=candidate.scope, current=SimpleNamespace(desired_set=desired), rows=[]
        )
    assert caught.value.code == "migration_target_baseline_conflict"


async def test_empty_target_uses_only_exact_builtin_fallback(candidate):
    candidate.repository.read_exact.return_value = None
    plan = await candidate.service._scope_plan(scope=candidate.scope, current=None, rows=[])
    assert plan.desired_set == candidate.production.desired_set
    assert plan.changed is True


async def test_valid_digest_foreign_scope_layer_is_rejected(candidate):
    foreign = ProfileLayerV2(
        layer_id="foreign",
        kind=ProfileLayerKindV2.TENANT,
        scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="other-tenant"),
        entries=(),
        replacements=(),
        disabled_entry_ids=(),
    )
    source = replace(candidate.source, layers=(*candidate.source.layers, foreign))
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = replace(
        candidate.desired,
        profile_source=replace(candidate.desired.profile_source, digest=source.digest),
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    candidate.repository.read_exact.return_value = source
    with pytest.raises(PluginProtocolV1ToV2MigrationError) as caught:
        await candidate.service._scope_plan(
            scope=candidate.scope, current=SimpleNamespace(desired_set=desired), rows=[]
        )
    assert caught.value.code == "migration_target_profile_source_conflict"
