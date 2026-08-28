"""V2-only graph authority coverage for Agent data planes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.state import agent_worker_state
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    current_agent_worker_runtime_services_v2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_AGENT_WORKER_MODULE_V2 = "builtin://memstack/agent/worker-runtime"


class _TrackedGraphService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


async def test_agent_turn_resolves_graph_from_its_exact_generation() -> None:
    first_graph = _TrackedGraphService("first")
    second_graph = _TrackedGraphService("second")
    graph_services = iter((first_graph, second_graph))

    async def graph_factory() -> Any:
        return next(graph_services)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=graph_factory)
    )
    first_publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=301,
        version=301,
    )
    assert first_publication.accepted is True

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="agent-graph:first",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            first_services = current_agent_worker_runtime_services_v2()
            assert first_services.graph_runtime.graph_service is first_graph

            second_publication = await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=302,
                version=302,
            )
            assert second_publication.accepted is True
            assert first_services.graph_runtime.graph_service is first_graph
            assert first_graph.close_calls == 0

            async with pin_operation_context_v2(
                host,
                operation_id="agent-graph:second",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ):
                second_services = current_agent_worker_runtime_services_v2()
                assert second_services.graph_runtime.graph_service is second_graph

            assert second_graph.close_calls == 0

        assert first_graph.close_calls == 1
    finally:
        await host.close()

    assert second_graph.close_calls == 1


def test_agent_worker_contract_requires_graph_runtime_alias() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    module = next(
        item for item in manifest["modules"] if item["module_ref"] == _AGENT_WORKER_MODULE_V2
    )
    assert {
        "alias": "graph_runtime",
        "service": "service:graph.runtime",
        "version": "1.0.0",
    } in module["contract"]["services"]["requires"]

    profile = load_profile_document_v2(_PROFILE_PATH)
    entry = next(item for item in profile.entries if item.module_ref == _AGENT_WORKER_MODULE_V2)
    assert entry.inject["graph_runtime"] == "service:graph.runtime"


def test_agent_graph_process_global_state_is_retired() -> None:
    retired_names = {
        "_agent_graph_service",
        "_tenant_graph_service_lock",
        "_tenant_graph_services",
        "get_agent_graph_service",
        "get_or_create_agent_graph_service",
        "set_agent_graph_service",
    }

    assert retired_names.isdisjoint(vars(agent_worker_state))
    assert retired_names.isdisjoint(agent_worker_state.__all__)


def test_agent_data_plane_admissions_bind_generation_graph_factories() -> None:
    expected_bindings = {
        "src/application/services/agent/runtime_bootstrapper.py": (
            "graph_runtime_factory=agent_worker_graph_runtime_factory_v2(config.tenant_id)",
        ),
        "src/infrastructure/agent/actor/local_chat_worker.py": (
            "graph_runtime_factory=agent_worker_graph_runtime_factory_v2(config.tenant_id)",
        ),
        "src/infrastructure/agent/actor/project_agent_actor.py": (
            "graph_runtime_factory=self._create_graph_runtime_v2",
        ),
        "src/infrastructure/agent/hitl/generation_recovery_v2.py": (
            "graph_runtime_factory=agent_worker_graph_runtime_factory_v2(state.tenant_id)",
        ),
    }

    for relative_path, required_fragments in expected_bindings.items():
        source = (_ROOT / relative_path).read_text(encoding="utf-8")
        for fragment in required_fragments:
            assert fragment in source, relative_path
        assert "set_agent_graph_service" not in source, relative_path
        assert "get_agent_graph_service" not in source, relative_path

    project_agent_source = (
        _ROOT / "src/infrastructure/agent/core/project_react_agent.py"
    ).read_text(encoding="utf-8")
    assert "current_agent_worker_runtime_services_v2" in project_agent_source
    assert "get_or_create_agent_graph_service" not in project_agent_source
