"""Generation-owned Agent Pool runtime coverage."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_model_v2 import (
    PlatformPluginV2ProfileSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.agent.pool.api import router as pool_router
from src.infrastructure.agent.pool.integration.session_adapter import PooledAgentSessionAdapter
from src.infrastructure.agent.pool.manager import AgentPoolManager
from src.infrastructure.agent.pool.runtime_resolver import (
    agent_pool_runtime_service_v2_from_current_generation,
)
from src.infrastructure.plugins.v2.agent_pool_profile import (
    AGENT_POOL_HTTP_ROUTES_ENTRY_ID_V2,
    AGENT_POOL_HTTP_ROUTES_MODULE_V2,
    AGENT_POOL_RUNTIME_ENTRY_ID_V2,
    agent_pool_runtime_matches_v2,
    project_agent_pool_runtime_v2,
)
from src.infrastructure.plugins.v2.agent_pool_runtime import (
    AGENT_POOL_RUNTIME_MODULE_V2,
    AGENT_POOL_RUNTIME_SERVICE_V2,
    AgentPoolRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import (
    ProfileDocumentV2,
    compose_profile_v2,
    load_profile_document_v2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.protocol import (
    control_envelope_v2,
    parse_plugin_manifest_v2,
    plugin_contract_digest_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_contracts import generated_target_catalog_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)
_CONFIG: dict[str, object] = {
    "strategy": "pooled-session-adapter",
    "max_total_instances": 100,
    "health_check_interval_seconds": 30,
    "cleanup_interval_seconds": 300,
    "enable_resource_isolation": True,
    "enable_health_monitoring": True,
    "enable_auto_classification": True,
    "enable_prewarming": True,
    "prewarm_on_startup": False,
    "fallback_on_pool_error": False,
    "enable_metrics": True,
}


class _TrackedAdapter:
    def __init__(self, events: list[str], *, fail_start: bool = False) -> None:
        self.events = events
        self.fail_start = fail_start
        self.manager = AgentPoolManager()

    @property
    def pool_manager(self) -> AgentPoolManager:
        return self.manager

    async def start(self) -> None:
        self.events.append("start:pool")
        if self.fail_start:
            raise RuntimeError("planned pool startup failure")

    async def stop(self) -> None:
        self.events.append("stop:pool")


def _runtime(events: list[str], *, fail_start: bool = False) -> AgentPoolRuntimeServiceV2:
    adapter = cast("PooledAgentSessionAdapter", _TrackedAdapter(events, fail_start=fail_start))
    return AgentPoolRuntimeServiceV2(adapter=adapter)


def _profile_entry():
    document = load_profile_document_v2(_PROFILE_PATH)
    return next(
        entry for entry in document.entries if entry.module_ref == AGENT_POOL_RUNTIME_MODULE_V2
    )


def _enable_pool(document):
    return project_agent_pool_runtime_v2(document, enabled=True, config=_CONFIG)


def test_agent_pool_runtime_contract_is_exact_and_disabled_by_default() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    module = next(
        item for item in manifest.modules if item.module_ref == AGENT_POOL_RUNTIME_MODULE_V2
    )
    catalog = generated_target_catalog_v2(DataPlaneTargetV2.PYTHON)[AGENT_POOL_RUNTIME_MODULE_V2]
    definition = next(
        item
        for item in builtin_runtime_definitions_v2()
        if item.module_ref == AGENT_POOL_RUNTIME_MODULE_V2
    )
    entry = _profile_entry()

    expected_contract_digest = plugin_contract_digest_v2(module.contract)
    artifact_path = _ROOT / module.artifact.source.removeprefix("repo+python://")
    assert module.contract_digest == expected_contract_digest
    assert catalog.contract_digest == expected_contract_digest
    assert definition.contract_digest == expected_contract_digest
    assert module.artifact.digest == artifact_digest_v2(artifact_path.read_bytes())
    assert catalog.artifact_digest == module.artifact.digest
    assert tuple(
        (provided.service, provided.version) for provided in module.contract.services.provides
    ) == ((AGENT_POOL_RUNTIME_SERVICE_V2, "1.0.0"),)
    assert module.contract.services.requires == ()
    assert entry.entry_id == AGENT_POOL_RUNTIME_ENTRY_ID_V2
    assert entry.enabled is False
    assert entry.scope == _ROOT_SCOPE
    assert entry.config == _CONFIG


async def test_disabled_agent_pool_entry_does_not_call_factory_or_publish_service() -> None:
    factory = AsyncMock(return_value=_runtime([]))
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(agent_pool_runtime_factory=factory)
    )

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )

    assert publication.accepted is True
    factory.assert_not_awaited()
    generation = host.manager.current
    assert generation is not None
    with pytest.raises(RuntimeV2Error) as error:
        generation.resolve(AGENT_POOL_RUNTIME_SERVICE_V2, _ROOT_SCOPE)
    assert error.value.code == "missing_service"
    await host.close()


async def test_enabled_agent_pool_runtime_is_pinned_and_disposed_with_generation() -> None:
    events: list[str] = []
    runtime = _runtime(events)
    received_config: dict[str, object] = {}

    async def factory(config) -> AgentPoolRuntimeServiceV2:
        received_config.update(config)
        return runtime

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(agent_pool_runtime_factory=factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
        profile_projector=_enable_pool,
    )

    assert publication.accepted is True
    assert received_config == _CONFIG
    assert events == ["start:pool"]
    generation = host.manager.current
    assert generation is not None
    assert generation.resolve(AGENT_POOL_RUNTIME_SERVICE_V2, _ROOT_SCOPE) is runtime
    async with pin_generation_v2(host):
        assert agent_pool_runtime_service_v2_from_current_generation() is runtime

    await host.close()
    assert events == ["start:pool", "stop:pool"]


async def test_pinned_generation_missing_pool_never_uses_legacy_global_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = AsyncMock()
    monkeypatch.setattr(pool_router, "get_global_adapter", legacy)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    assert publication.accepted is True

    async with pin_generation_v2(host):
        with pytest.raises(RuntimeV2Error) as error:
            await pool_router._get_pool_manager_optional()

    assert error.value.code == "missing_service"
    legacy.assert_not_awaited()
    await host.close()


async def test_agent_pool_partial_startup_failure_cleans_candidate() -> None:
    events: list[str] = []

    async def factory(_config) -> AgentPoolRuntimeServiceV2:
        return _runtime(events, fail_start=True)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(agent_pool_runtime_factory=factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
        profile_projector=_enable_pool,
    )

    assert publication.accepted is False
    assert publication.receipt.error_code == "staging_failed"
    assert events == ["start:pool", "stop:pool"]
    assert host.manager.current is None


async def test_default_definition_set_can_admit_enabled_pool_distribution() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
        profile_projector=_enable_pool,
    )

    assert publication.accepted is True
    generation = host.manager.current
    assert generation is not None
    runtime = generation.resolve(AGENT_POOL_RUNTIME_SERVICE_V2, _ROOT_SCOPE)
    assert isinstance(runtime, AgentPoolRuntimeServiceV2)
    await host.close()


async def test_restart_republishes_durable_snapshot_for_explicit_pool_desired_state(
    db_session: AsyncSession,
) -> None:
    @asynccontextmanager
    async def session_factory():
        yield db_session

    first_app = FastAPI()
    first = await initialize_plugin_runtime_v2(
        first_app,
        session_factory=session_factory,
    )
    first_distribution = first.current_distribution
    assert first_distribution is not None
    assert agent_pool_runtime_matches_v2(
        first_distribution.snapshot,
        enabled=False,
        config=_CONFIG,
    )
    await first.close()

    desired_repository = PlatformPluginDesiredBundleSetRepositoryV2(db_session)
    desired = (await desired_repository.current_desired_set(_ROOT_SCOPE)).desired_set
    reference = desired.profile_source
    source_repository = PlatformPluginProfileSourceRepositoryV2(db_session)
    source = await source_repository.read_exact(
        scope=_ROOT_SCOPE,
        source_id=reference.source_id,
        revision=reference.revision,
        digest=reference.digest,
    )
    assert source is not None
    pool_entry = next(
        entry
        for entry in first_distribution.snapshot.entries
        if entry.entry_id == AGENT_POOL_RUNTIME_ENTRY_ID_V2
    )
    updated_source = replace(
        source,
        revision=source.revision + 1,
        layers=(
            *source.layers,
            ProfileLayerV2(
                layer_id="explicit-enable-pool",
                kind=ProfileLayerKindV2.PROFILE,
                scope=_ROOT_SCOPE,
                entries=(),
                replacements=(replace(pool_entry, enabled=True, config=dict(_CONFIG)),),
                disabled_entry_ids=(),
            ),
        ),
    )
    updated_source = replace(updated_source, digest=profile_source_digest_v2(updated_source))
    await source_repository.record_source(
        scope=_ROOT_SCOPE, source=updated_source, expected_revision=source.revision
    )
    updated_desired = replace(
        desired,
        revision=desired.revision + 1,
        profile_source=replace(
            reference, revision=updated_source.revision, digest=updated_source.digest
        ),
    )
    updated_desired = replace(updated_desired, digest=desired_bundle_set_digest_v2(updated_desired))
    await desired_repository.record_desired_set(
        scope=_ROOT_SCOPE,
        desired_set=updated_desired,
        expected_revision=desired.revision,
        actor_id="explicit-pool-config",
    )
    await db_session.commit()

    events: list[str] = []

    async def factory(_config) -> AgentPoolRuntimeServiceV2:
        return _runtime(events)

    restarted_app = FastAPI()
    restarted = await initialize_plugin_runtime_v2(
        restarted_app,
        session_factory=session_factory,
        agent_pool_runtime_enabled=False,
        agent_pool_runtime_config=_CONFIG,
        agent_pool_runtime_factory=factory,
    )
    restarted_distribution = restarted.current_distribution

    assert restarted_distribution is not None
    assert restarted_distribution.descriptor.generation == (
        first_distribution.descriptor.generation + 1
    )
    assert restarted_distribution.envelope.version == first_distribution.envelope.version + 1
    assert agent_pool_runtime_matches_v2(
        restarted_distribution.snapshot,
        enabled=True,
        config=_CONFIG,
    )
    assert (
        await PlatformPluginRepositoryV2(db_session).last_good_distribution("python-api-v2")
        == restarted_distribution.to_payload()
    )
    await restarted.close()
    assert events == ["start:pool", "stop:pool"]


async def test_restart_upgrades_snapshot_that_predates_agent_pool_modules(
    db_session: AsyncSession,
) -> None:
    """Historical auto-upgrade fixture now requires explicit ROOT configuration migration."""

    @asynccontextmanager
    async def session_factory():
        yield db_session

    document = load_profile_document_v2(_PROFILE_PATH)
    legacy_entries = tuple(
        entry
        for entry in document.entries
        if entry.entry_id
        not in {AGENT_POOL_RUNTIME_ENTRY_ID_V2, AGENT_POOL_HTTP_ROUTES_ENTRY_ID_V2}
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    legacy_manifest = replace(
        manifest,
        modules=tuple(
            module
            for module in manifest.modules
            if module.module_ref
            not in {AGENT_POOL_RUNTIME_MODULE_V2, AGENT_POOL_HTTP_ROUTES_MODULE_V2}
        ),
    )
    legacy_snapshot = compose_profile_v2(
        ProfileDocumentV2(profile_id=document.profile_id, entries=legacy_entries),
        {legacy_manifest.plugin_id: legacy_manifest},
        generation=7,
    )
    legacy_host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    legacy = await legacy_host.apply(
        legacy_snapshot,
        control_envelope_v2(legacy_snapshot, version=11),
    )
    assert legacy.accepted is True
    await PlatformPluginRepositoryV2(db_session).record_publication_and_receipt(
        legacy,
        data_plane_id="python-api-v2",
    )
    await db_session.commit()
    await legacy_host.close()

    repository = PlatformPluginRepositoryV2(db_session)
    before_last_good = await repository.last_good_distribution("python-api-v2")
    before_requested = await repository.latest_requested_distribution()
    app = FastAPI()
    with pytest.raises(RuntimeV2Error) as caught:
        await initialize_plugin_runtime_v2(app, session_factory=session_factory)
    assert caught.value.code == "root_profile_migration_required"
    assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
    assert (
        await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(
            _ROOT_SCOPE
        )
        is None
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PlatformPluginV2ProfileSourceModel)
        )
        == 0
    )
    assert await repository.last_good_distribution("python-api-v2") == before_last_good
    assert await repository.latest_requested_distribution() == before_requested
