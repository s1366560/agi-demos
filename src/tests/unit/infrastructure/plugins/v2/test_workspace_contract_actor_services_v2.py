"""Workspace contract actor resolution through one pinned V2 generation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import (
    parse_plugin_manifest_v2,
    plugin_contract_digest_v2,
)
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_contracts import generated_target_catalog_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.workspace_contract_actor_services import (
    WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2,
    WORKSPACE_CONTRACT_ACTOR_RESOLVER_SERVICE_V2,
    WorkspaceContractActorResolverProtocolV2,
)
from src.infrastructure.plugins.v2.workspace_core_runtime import (
    WORKSPACE_CORE_RUNTIME_MODULE_V2,
    WORKSPACE_CORE_RUNTIME_SERVICE_V2,
    WorkspaceCoreRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.workspace_core_shadow import (
    WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2,
    WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2,
    activate_workspace_core_shadow_v2,
    compose_workspace_core_shadow_upgrade_v2,
    workspace_core_shadow_active_v2,
)
from src.infrastructure.plugins.v2.workspace_prompt_context_services import (
    WORKSPACE_PROMPT_CONTEXT_MODULE_V2,
)
from src.infrastructure.workspace_core.client import (
    WorkspaceContractActorResolveRequest,
    WorkspaceContractActorResolveResponse,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)


class _Client:
    def __init__(self, actor_user_id: str) -> None:
        self.actor_user_id = actor_user_id
        self.requests: list[WorkspaceContractActorResolveRequest] = []

    async def resolve_contract_actor(
        self,
        request: WorkspaceContractActorResolveRequest,
    ) -> WorkspaceContractActorResolveResponse:
        self.requests.append(request)
        return WorkspaceContractActorResolveResponse(
            contract_version="2.0.0",
            actor_user_id=self.actor_user_id,
            participant_actor_id=f"human:{self.actor_user_id}",
            authority_revision=11,
            policy_version="workspace-contract-actor-owner.v1",
            duplicate=False,
        )


class _ProviderAdapter:
    def __init__(self) -> None:
        self.wait_calls = 0

    async def wait_until_idle(self) -> None:
        self.wait_calls += 1


def _runtime(client: _Client, adapter: _ProviderAdapter) -> WorkspaceCoreRuntimeServiceV2:
    marker = object()
    return WorkspaceCoreRuntimeServiceV2(
        settings=cast(Any, marker),
        client=cast(Any, client),
        authority=cast(Any, marker),
        context_judge=cast(Any, marker),
        plan_judge=cast(Any, marker),
        autonomy_judge=cast(Any, marker),
        access_verifier=cast(Any, marker),
        event_sink=cast(Any, marker),
        agent_runtime_provider=cast(Any, marker),
        provider_adapter=cast(Any, adapter),
    )


def _request(operation_id: str) -> WorkspaceContractActorResolveRequest:
    return WorkspaceContractActorResolveRequest(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        purpose="planner_turn",
        operation_id=operation_id,
    )


def test_contract_actor_resolver_contract_profile_and_catalog_are_exact() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    module = next(
        item
        for item in manifest.modules
        if item.module_ref == WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2
    )
    entry = next(
        item
        for item in load_profile_document_v2(_PROFILE_PATH).entries
        if item.module_ref == WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2
    )
    definition = next(
        item
        for item in builtin_runtime_definitions_v2()
        if item.module_ref == WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2
    )
    catalog = generated_target_catalog_v2("python")[WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2]
    artifact_path = _ROOT / module.artifact.source.removeprefix("repo+python://")
    expected_digest = plugin_contract_digest_v2(module.contract)

    assert module.contract_digest == expected_digest
    assert definition.contract_digest == expected_digest
    assert catalog.contract_digest == expected_digest
    assert module.artifact.digest == artifact_digest_v2(artifact_path.read_bytes())
    assert catalog.artifact_digest == module.artifact.digest
    assert tuple(
        (provided.service, provided.version) for provided in module.contract.services.provides
    ) == ((WORKSPACE_CONTRACT_ACTOR_RESOLVER_SERVICE_V2, "1.0.0"),)
    assert tuple(
        (required.alias, required.service, required.version)
        for required in module.contract.services.requires
    ) == (("runtime", WORKSPACE_CORE_RUNTIME_SERVICE_V2, "1.0.0"),)
    assert entry.parent_entry_id == "runtime-generation-boundary"
    assert entry.enabled is False
    assert entry.inject == {"runtime": WORKSPACE_CORE_RUNTIME_SERVICE_V2}
    assert entry.config == {"strategy": "workspace-core-authority"}


async def test_contract_actor_resolver_uses_the_generation_owned_workspace_client() -> None:
    client = _Client("owner-1")
    adapter = _ProviderAdapter()

    async def factory() -> WorkspaceCoreRuntimeServiceV2:
        return _runtime(client, adapter)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(workspace_core_runtime_factory=factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=801,
        version=801,
        profile_projector=activate_workspace_core_shadow_v2,
    )

    assert publication.accepted is True
    generation = host.manager.current
    assert generation is not None
    resolver = generation.resolve(
        WORKSPACE_CONTRACT_ACTOR_RESOLVER_SERVICE_V2,
        _ROOT_SCOPE,
    )
    assert isinstance(resolver, WorkspaceContractActorResolverProtocolV2)

    response = await resolver.resolve(_request("planner:workspace-1:turn-1"))

    assert response.actor_user_id == "owner-1"
    assert client.requests == [_request("planner:workspace-1:turn-1")]
    await host.close()
    assert adapter.wait_calls == 1


async def test_enabled_contract_actor_resolver_rejects_missing_runtime_without_fallback() -> None:
    document = activate_workspace_core_shadow_v2(load_profile_document_v2(_PROFILE_PATH))
    document = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == WORKSPACE_CORE_RUNTIME_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(document, {manifest.plugin_id: manifest}, generation=802)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert WORKSPACE_CORE_RUNTIME_SERVICE_V2 in str(error.value)


async def test_contract_actor_resolver_keeps_the_exact_pinned_generation_during_reload() -> None:
    clients = [_Client("owner-old"), _Client("owner-new")]
    adapters = [_ProviderAdapter(), _ProviderAdapter()]
    calls = 0

    async def factory() -> WorkspaceCoreRuntimeServiceV2:
        nonlocal calls
        runtime = _runtime(clients[calls], adapters[calls])
        calls += 1
        return runtime

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(workspace_core_runtime_factory=factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=803,
        version=803,
        profile_projector=activate_workspace_core_shadow_v2,
    )
    assert first.accepted is True

    async with pin_generation_v2(host) as pinned:
        resolver = pinned.resolve(WORKSPACE_CONTRACT_ACTOR_RESOLVER_SERVICE_V2, _ROOT_SCOPE)
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=804,
            version=804,
            profile_projector=activate_workspace_core_shadow_v2,
        )
        assert second.accepted is True
        response = await cast(WorkspaceContractActorResolverProtocolV2, resolver).resolve(
            _request("planner:workspace-1:turn-old")
        )
        assert response.actor_user_id == "owner-old"
        assert adapters[0].wait_calls == 0

    assert adapters[0].wait_calls == 1
    current = host.manager.current
    assert current is not None
    current_resolver = cast(
        WorkspaceContractActorResolverProtocolV2,
        current.resolve(WORKSPACE_CONTRACT_ACTOR_RESOLVER_SERVICE_V2, _ROOT_SCOPE),
    )
    current_response = await current_resolver.resolve(_request("planner:workspace-1:turn-new"))
    assert current_response.actor_user_id == "owner-new"

    await host.close()
    assert adapters[1].wait_calls == 1


def test_shadow_upgrade_adds_complete_capability_to_an_old_active_runtime_snapshot() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        activate_workspace_core_shadow_v2(load_profile_document_v2(_PROFILE_PATH)),
        {manifest.plugin_id: manifest},
        generation=805,
    )
    old_snapshot = replace(
        snapshot,
        entries=tuple(
            entry
            for entry in snapshot.entries
            if entry.entry_id
            not in {
                WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2,
                WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2,
            }
        ),
        manifests=(
            replace(
                manifest,
                modules=tuple(
                    module
                    for module in manifest.modules
                    if module.module_ref
                    not in {
                        WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2,
                        WORKSPACE_PROMPT_CONTEXT_MODULE_V2,
                    }
                ),
            ),
        ),
    )

    upgraded = compose_workspace_core_shadow_upgrade_v2(old_snapshot, generation=806)

    assert upgraded.generation == 806
    assert workspace_core_shadow_active_v2(upgraded) is True
    module_refs = {
        module.module_ref for manifest in upgraded.manifests for module in manifest.modules
    }
    assert WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2 in module_refs
    assert WORKSPACE_PROMPT_CONTEXT_MODULE_V2 in module_refs
