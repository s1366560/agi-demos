"""Provider/Consumer coverage for the generation-scoped tool-set seam."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _resolve_current_tools_from_runtime_v2,
)
from src.infrastructure.agent.plugins.selection_pipeline import (
    ToolSelectionContext,
    ToolSelectionTraceStep,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_MODULE_V2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    GenerationManagerV2,
    LoaderV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.tool_set import (
    TOOL_SET_MODULE_V2,
    TOOL_SET_RESOLVER_SERVICE_V2,
    ToolSetCatalogV2,
    ToolSetResolverV2,
    ToolSetV2,
)

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_RETIRED_GENERIC_TOOL_CONTRIBUTION_MODULE_V2 = "builtin://memstack/agent/tool-contribution"


def _snapshot(*, generation: int):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)
    selected_modules = {
        RUNTIME_BOUNDARY_MODULE_V2,
        TOOL_SET_MODULE_V2,
    }
    entries = tuple(entry for entry in document.entries if entry.module_ref in selected_modules)
    return compose_profile_v2(
        replace(document, entries=entries),
        {manifest.plugin_id: manifest},
        generation=generation,
    )


async def _manager(*, generation: int) -> GenerationManagerV2:
    runtime_generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(
        _snapshot(generation=generation)
    )
    manager = GenerationManagerV2()
    await manager.publish(runtime_generation)
    return manager


class _Tool:
    description = "Read a resource"

    async def execute(self) -> str:
        return "ok"


class _ToolAgent:
    def __init__(self) -> None:
        self.contexts: list[object] = []
        self.raw_tools = {"read": _Tool()}
        self._use_dynamic_tools = False
        self._tool_provider = None
        self._tool_selection_pipeline = None
        self._last_tool_selection_trace: tuple[object, ...] = ()

    def _get_current_tools(
        self,
        *,
        selection_context: object,
    ) -> tuple[dict[str, object], list[object]]:
        self.contexts.append(selection_context)
        return {"read": object()}, [object()]


class _AlternativeToolSetResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def resolve(
        self,
        *,
        agent: object,
        selection_context: object,
    ) -> ToolSetV2:
        self.calls.append((agent, selection_context))
        definition = SimpleNamespace(name="alternative", description="Alternative tool")
        return ToolSetV2(
            tools=MappingProxyType({"alternative": object()}),
            definitions=(definition,),
        )


@pytest.mark.unit
def test_generic_agent_owned_tool_contribution_is_retired_from_production() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)

    assert _RETIRED_GENERIC_TOOL_CONTRIBUTION_MODULE_V2 not in {
        module.module_ref for module in manifest.modules
    }
    assert _RETIRED_GENERIC_TOOL_CONTRIBUTION_MODULE_V2 not in {
        entry.module_ref for entry in document.entries
    }
    assert _RETIRED_GENERIC_TOOL_CONTRIBUTION_MODULE_V2 not in {
        definition.module_ref for definition in builtin_runtime_definitions_v2()
    }


@pytest.mark.unit
def test_tool_set_requires_pinned_v2_operation_without_native_fallback() -> None:
    agent = _ToolAgent()
    selection = ToolSelectionContext(tenant_id="tenant-a", project_id="project-a")

    with pytest.raises(RuntimeV2Error) as error:
        _resolve_current_tools_from_runtime_v2(agent, selection)

    assert error.value.code == "operation_context_not_pinned"
    assert agent.contexts == []


@pytest.mark.unit
def test_tool_set_propagates_missing_v2_service_without_native_fallback() -> None:
    agent = _ToolAgent()
    selection = ToolSelectionContext(tenant_id="tenant-a", project_id="project-a")
    operation = Mock()
    operation.require.side_effect = RuntimeV2Error(
        "missing_service",
        "tool-set resolver is unavailable",
    )

    with (
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=operation,
        ),
        pytest.raises(RuntimeV2Error) as error,
    ):
        _resolve_current_tools_from_runtime_v2(agent, selection)

    assert error.value.code == "missing_service"
    operation.require.assert_called_once_with(TOOL_SET_RESOLVER_SERVICE_V2)
    assert agent.contexts == []


@pytest.mark.unit
def test_tool_set_accepts_structural_non_builtin_provider() -> None:
    agent = _ToolAgent()
    selection = ToolSelectionContext(tenant_id="tenant-a", project_id="project-a")
    provider = _AlternativeToolSetResolver()
    operation = Mock()
    operation.require.return_value = provider

    with patch(
        "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
        return_value=operation,
    ):
        tool_set = _resolve_current_tools_from_runtime_v2(agent, selection)

    assert set(tool_set.tools) == {"alternative"}
    assert len(tool_set.definitions) == 1
    assert provider.calls == [(agent, selection)]
    assert agent.contexts == []


@pytest.mark.unit
def test_tool_set_snapshots_selection_trace_without_mutating_agent() -> None:
    kept_tool = _Tool()
    removed_tool = _Tool()
    trace = (
        ToolSelectionTraceStep(
            stage="profile_filter",
            before_count=2,
            after_count=1,
            removed_tools=("disabled",),
        ),
    )

    class _SelectionPipeline:
        @staticmethod
        def select_with_trace(tools, _selection_context):
            return SimpleNamespace(tools={"enabled": tools["enabled"]}, trace=trace)

    agent = SimpleNamespace(
        _tool_selection_pipeline=_SelectionPipeline(),
        _last_tool_selection_trace=("sentinel",),
    )
    catalog = ToolSetCatalogV2()
    _ = catalog.register_tools(
        "profile-tools",
        lambda **_kwargs: ToolSetV2(
            tools=MappingProxyType(
                {
                    "disabled": removed_tool,
                    "enabled": kept_tool,
                }
            ),
            definitions=(
                SimpleNamespace(name="disabled", description="Disabled tool"),
                SimpleNamespace(name="enabled", description="Enabled tool"),
            ),
        ),
    )

    resolved = catalog.resolve(
        agent=agent,
        selection_context=ToolSelectionContext(
            tenant_id="tenant-a",
            project_id="project-a",
        ),
    )

    assert resolved.tools == {"enabled": kept_tool}
    assert [definition.name for definition in resolved.definitions] == ["enabled"]
    assert resolved.selection_trace == trace
    assert agent._last_tool_selection_trace == ("sentinel",)
    with pytest.raises(TypeError):
        resolved.tools["other"] = object()


@pytest.mark.unit
async def test_tool_contribution_disposer_removes_exact_source() -> None:
    catalog = ToolSetCatalogV2()
    tool = _Tool()
    dispose = catalog.register_tools(
        "tools-a",
        lambda **_kwargs: ToolSetV2(tools={"read": tool}, definitions=()),
    )

    before = catalog.resolve(agent=object(), selection_context=None)
    assert before.tools == {"read": tool}

    await dispose()

    after = catalog.resolve(agent=object(), selection_context=None)
    assert after.tools == {}
    assert after.definitions == ()


@pytest.mark.unit
def test_tool_catalog_rejects_duplicate_names_across_sources() -> None:
    catalog = ToolSetCatalogV2()
    _ = catalog.register_tools(
        "tools-a",
        lambda **_kwargs: ToolSetV2(tools={"read": _Tool()}, definitions=()),
    )
    _ = catalog.register_tools(
        "tools-b",
        lambda **_kwargs: ToolSetV2(tools={"read": _Tool()}, definitions=()),
    )

    with pytest.raises(RuntimeV2Error) as error:
        catalog.resolve(agent=object(), selection_context=None)

    assert error.value.code == "tool_contribution_conflict"


@pytest.mark.unit
def test_tool_catalog_rejects_duplicate_source_registration() -> None:
    catalog = ToolSetCatalogV2()
    _ = catalog.register_tools(
        "tools-a",
        lambda **_kwargs: ToolSetV2(tools={}, definitions=()),
    )

    with pytest.raises(RuntimeV2Error) as error:
        _ = catalog.register_tools(
            "tools-a",
            lambda **_kwargs: ToolSetV2(tools={}, definitions=()),
        )

    assert error.value.code == "tool_contribution_source_conflict"


@pytest.mark.unit
def test_tool_catalog_rejects_invalid_contribution_result() -> None:
    catalog = ToolSetCatalogV2()
    _ = catalog.register_tools("invalid-tools", lambda **_kwargs: object())

    with pytest.raises(RuntimeV2Error) as error:
        catalog.resolve(agent=object(), selection_context=None)

    assert error.value.code == "invalid_tool_contribution"


@pytest.mark.unit
async def test_runtime_consumer_resolves_tools_from_generation_provider() -> None:
    manager = await _manager(generation=1)
    agent = _ToolAgent()
    selection = ToolSelectionContext(tenant_id="tenant-a", project_id="project-a")

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="tool-set-consumer",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as operation:
            assert isinstance(
                operation.require(TOOL_SET_RESOLVER_SERVICE_V2),
                ToolSetResolverV2,
            )
            tool_set = _resolve_current_tools_from_runtime_v2(agent, selection)
    finally:
        await manager.close()

    assert tool_set.tools == {}
    assert tool_set.definitions == ()
    assert agent.contexts == []
