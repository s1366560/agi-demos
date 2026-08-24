"""Generation-owned Workspace Core runtime Provider primitive coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import (
    ProfileDocumentV2,
    load_profile_document_v2,
)
from src.infrastructure.plugins.v2.protocol import (
    parse_plugin_manifest_v2,
    plugin_contract_digest_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_contracts import generated_target_catalog_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.workspace_core_runtime import (
    WORKSPACE_CORE_RUNTIME_MODULE_V2,
    WORKSPACE_CORE_RUNTIME_SERVICE_V2,
    WorkspaceCoreRuntimeServiceV2,
)

if TYPE_CHECKING:
    from src.configuration.workspace_core import WorkspaceCoreSettings
    from src.domain.ports.services.workspace_authority_port import WorkspaceAuthorityPort
    from src.infrastructure.workspace_core.agent_runtime_provider import (
        MemStackAgentRuntimeProvider,
    )
    from src.infrastructure.workspace_core.autonomy_judge import AgentWorkspaceAutonomyJudge
    from src.infrastructure.workspace_core.client import (
        AvernetWorkspaceAccessVerifier,
        WorkspaceCoreClient,
    )
    from src.infrastructure.workspace_core.context_judge import AgentWorkspaceContextJudge
    from src.infrastructure.workspace_core.plan_judge import AgentWorkspacePlanJudge
    from src.infrastructure.workspace_core.provider import (
        AvernetBotEventHttpSink,
        AvernetProviderAdapter,
    )

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)


class _TrackedProviderAdapter:
    def __init__(self, events: list[str] | None = None, *, label: str = "workspace") -> None:
        self.wait_calls = 0
        self._events = events
        self._label = label

    async def wait_until_idle(self) -> None:
        self.wait_calls += 1
        if self._events is not None:
            self._events.append(f"dispose:{self._label}")


class _FakeGraphService:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


def _runtime(adapter: _TrackedProviderAdapter) -> WorkspaceCoreRuntimeServiceV2:
    marker = object()
    return WorkspaceCoreRuntimeServiceV2(
        settings=cast("WorkspaceCoreSettings", marker),
        client=cast("WorkspaceCoreClient", marker),
        authority=cast("WorkspaceAuthorityPort", marker),
        context_judge=cast("AgentWorkspaceContextJudge", marker),
        plan_judge=cast("AgentWorkspacePlanJudge", marker),
        autonomy_judge=cast("AgentWorkspaceAutonomyJudge", marker),
        access_verifier=cast("AvernetWorkspaceAccessVerifier", marker),
        event_sink=cast("AvernetBotEventHttpSink", marker),
        agent_runtime_provider=cast("MemStackAgentRuntimeProvider", marker),
        provider_adapter=cast("AvernetProviderAdapter", adapter),
    )


def _enable_workspace_core(document: ProfileDocumentV2) -> ProfileDocumentV2:
    return replace(
        document,
        entries=tuple(
            replace(entry, enabled=True)
            if entry.module_ref == WORKSPACE_CORE_RUNTIME_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )


def _profile_entry():
    document = load_profile_document_v2(_PROFILE_PATH)
    return next(
        entry for entry in document.entries if entry.module_ref == WORKSPACE_CORE_RUNTIME_MODULE_V2
    )


def test_workspace_core_runtime_contract_is_exact_and_disabled_by_default() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    module = next(
        item for item in manifest.modules if item.module_ref == WORKSPACE_CORE_RUNTIME_MODULE_V2
    )
    catalog = generated_target_catalog_v2(DataPlaneTargetV2.PYTHON)[
        WORKSPACE_CORE_RUNTIME_MODULE_V2
    ]
    definition = next(
        item
        for item in builtin_runtime_definitions_v2()
        if item.module_ref == WORKSPACE_CORE_RUNTIME_MODULE_V2
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
    ) == ((WORKSPACE_CORE_RUNTIME_SERVICE_V2, "1.0.0"),)
    assert module.contract.services.requires == ()
    assert entry.enabled is False
    assert entry.scope == _ROOT_SCOPE
    assert entry.config == {"strategy": "avernet-client"}


async def test_disabled_workspace_core_entry_does_not_call_factory_or_publish_service() -> None:
    factory_calls = 0
    runtime = _runtime(_TrackedProviderAdapter())

    async def factory() -> WorkspaceCoreRuntimeServiceV2:
        nonlocal factory_calls
        factory_calls += 1
        return runtime

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(workspace_core_runtime_factory=factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )

    assert publication.accepted is True
    assert factory_calls == 0
    generation = host.manager.current
    assert generation is not None
    with pytest.raises(RuntimeV2Error) as error:
        generation.resolve(WORKSPACE_CORE_RUNTIME_SERVICE_V2, _ROOT_SCOPE)
    assert error.value.code == "missing_service"

    await host.close()


async def test_enabled_workspace_core_entry_requires_explicit_factory_without_fallback() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
        profile_projector=_enable_workspace_core,
    )

    assert publication.accepted is False
    assert publication.receipt.error_code == "staging_failed"
    assert publication.receipt.error_message is not None
    assert "enabled Workspace Core runtime has no data-plane factory" in (
        publication.receipt.error_message
    )
    assert host.manager.current is None

    await host.close()


async def test_enabled_workspace_core_entry_publishes_exact_service_and_disposes_it() -> None:
    adapter = _TrackedProviderAdapter()
    runtime = _runtime(adapter)

    async def factory() -> WorkspaceCoreRuntimeServiceV2:
        return runtime

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(workspace_core_runtime_factory=factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
        profile_projector=_enable_workspace_core,
    )

    assert publication.accepted is True
    generation = host.manager.current
    assert generation is not None
    assert (
        generation.resolve(
            WORKSPACE_CORE_RUNTIME_SERVICE_V2,
            _ROOT_SCOPE,
            version="1.0.0",
        )
        is runtime
    )
    assert adapter.wait_calls == 0

    await host.close()

    assert adapter.wait_calls == 1


async def test_later_candidate_failure_disposes_workspace_core_effect_in_lifo_order() -> None:
    events: list[str] = []
    adapter = _TrackedProviderAdapter(events)
    runtime = _runtime(adapter)

    async def workspace_factory() -> WorkspaceCoreRuntimeServiceV2:
        events.append("acquire:workspace")
        return runtime

    async def graph_factory() -> Any:
        events.append("fail:graph")
        raise RuntimeError("graph candidate failed")

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            graph_runtime_factory=graph_factory,
            workspace_core_runtime_factory=workspace_factory,
        )
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
        profile_projector=_enable_workspace_core,
    )

    assert publication.accepted is False
    assert publication.receipt.error_code == "staging_failed"
    assert host.manager.current is None
    assert events == ["acquire:workspace", "fail:graph", "dispose:workspace"]
    assert adapter.wait_calls == 1

    await host.close()


async def test_failed_candidate_keeps_last_good_workspace_core_runtime() -> None:
    adapters = [_TrackedProviderAdapter(label="first"), _TrackedProviderAdapter(label="second")]
    runtimes = [_runtime(adapter) for adapter in adapters]
    workspace_calls = 0
    graph_calls = 0
    graph_service = _FakeGraphService()

    async def workspace_factory() -> WorkspaceCoreRuntimeServiceV2:
        nonlocal workspace_calls
        runtime = runtimes[workspace_calls]
        workspace_calls += 1
        return runtime

    async def graph_factory() -> Any:
        nonlocal graph_calls
        graph_calls += 1
        if graph_calls == 1:
            return graph_service
        raise RuntimeError("next graph candidate failed")

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            graph_runtime_factory=graph_factory,
            workspace_core_runtime_factory=workspace_factory,
        )
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
        profile_projector=_enable_workspace_core,
    )
    first_generation = host.manager.current
    failed = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=2,
        version=2,
        profile_projector=_enable_workspace_core,
    )

    assert first.accepted is True
    assert failed.accepted is False
    assert host.manager.current is first_generation
    assert first_generation is not None
    assert first_generation.resolve(WORKSPACE_CORE_RUNTIME_SERVICE_V2, _ROOT_SCOPE) is runtimes[0]
    assert adapters[0].wait_calls == 0
    assert adapters[1].wait_calls == 1
    assert graph_service.close_calls == 0

    await host.close()

    assert adapters[0].wait_calls == 1
    assert graph_service.close_calls == 1


def test_workspace_core_v2_primitive_does_not_install_global_access_verifier() -> None:
    source = (_ROOT / "src/infrastructure/plugins/v2/workspace_core_runtime.py").read_text(
        encoding="utf-8"
    )

    assert "configure_workspace_access_verifier" not in source
