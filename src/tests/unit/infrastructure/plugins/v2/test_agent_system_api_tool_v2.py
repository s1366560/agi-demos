"""V2 Profile authority coverage for the generation-owned system API tool."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _resolve_current_tools_from_runtime_v2,
)
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.plugins.selection_pipeline import ToolSelectionContext
from src.infrastructure.agent.tools.system_api import make_system_api_tool
from src.infrastructure.plugins.v2.agent_system_api_tool import (
    AGENT_SYSTEM_API_TOOL_MODULE_V2,
    AGENT_SYSTEM_API_TOOL_SOURCE_V2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_MODULE_V2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.tool_set import TOOL_SET_MODULE_V2

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _client_factory(**_kwargs: object) -> object:
    return object()


_SYSTEM_API_TOOL = make_system_api_tool(
    openapi_schema_provider=dict,
    base_url="http://127.0.0.1:8000",
    client_factory=_client_factory,
)


class _ReadTool:
    name = "read"
    description = "Read a resource."

    def get_parameters_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self) -> str:
        return "ok"


class _ToolAgent:
    def __init__(self, *, include_system_api: bool = True) -> None:
        system_tools = {_SYSTEM_API_TOOL.name: _SYSTEM_API_TOOL} if include_system_api else {}
        self.raw_tools = {"read": _ReadTool(), **system_tools}
        self._tool_selection_pipeline = None
        self._last_tool_selection_trace: tuple[object, ...] = ()

    def _get_current_tools(
        self,
        *,
        selection_context: object,
    ) -> tuple[dict[str, object], list[object]]:
        assert selection_context is None
        return self.raw_tools, list(convert_tools(self.raw_tools))


def _snapshot(*, generation: int, system_api_enabled: bool):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)
    selected_modules = {
        RUNTIME_BOUNDARY_MODULE_V2,
        TOOL_SET_MODULE_V2,
        AGENT_SYSTEM_API_TOOL_MODULE_V2,
    }
    entries = tuple(
        replace(
            entry,
            enabled=(
                system_api_enabled
                if entry.module_ref == AGENT_SYSTEM_API_TOOL_MODULE_V2
                else entry.enabled
            ),
        )
        for entry in document.entries
        if entry.module_ref in selected_modules
    )
    return compose_profile_v2(
        replace(document, entries=entries),
        {manifest.plugin_id: manifest},
        generation=generation,
    )


async def _manager(*, generation: int, system_api_enabled: bool) -> GenerationManagerV2:
    runtime_generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(
        _snapshot(generation=generation, system_api_enabled=system_api_enabled)
    )
    manager = GenerationManagerV2()
    await manager.publish(runtime_generation)
    return manager


@pytest.mark.unit
def test_system_api_tool_is_an_explicit_profile_contribution() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    system_entries = [
        entry for entry in document.entries if entry.module_ref == AGENT_SYSTEM_API_TOOL_MODULE_V2
    ]
    assert len(system_entries) == 1
    assert system_entries[0].enabled is True
    assert system_entries[0].config == {"source_id": AGENT_SYSTEM_API_TOOL_SOURCE_V2}
    assert system_entries[0].inject == {"catalog": "service:tool-set-catalog"}


@pytest.mark.unit
async def test_disabling_system_api_contribution_removes_prepared_tool() -> None:
    manager = await _manager(generation=51, system_api_enabled=False)
    agent = _ToolAgent()
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="system-api-tool-disabled",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            tools, _definitions = _resolve_current_tools_from_runtime_v2(
                agent,
                ToolSelectionContext(),
            )
    finally:
        await manager.close()

    assert tools == {}


@pytest.mark.unit
async def test_enabling_system_api_contribution_restores_exact_prepared_tool() -> None:
    manager = await _manager(generation=52, system_api_enabled=True)
    agent = _ToolAgent()
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="system-api-tool-enabled",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            tools, definitions = _resolve_current_tools_from_runtime_v2(
                agent,
                ToolSelectionContext(),
            )
    finally:
        await manager.close()

    assert set(tools) == {_SYSTEM_API_TOOL.name}
    assert {definition.name for definition in definitions} == set(tools)
    assert tools[_SYSTEM_API_TOOL.name] is _SYSTEM_API_TOOL


@pytest.mark.unit
async def test_enabled_system_api_contribution_fails_when_prepared_tool_is_missing() -> None:
    manager = await _manager(generation=53, system_api_enabled=True)
    agent = _ToolAgent(include_system_api=False)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="system-api-tool-incomplete",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            with pytest.raises(RuntimeV2Error) as error:
                _resolve_current_tools_from_runtime_v2(agent, ToolSelectionContext())
    finally:
        await manager.close()

    assert error.value.code == "missing_prepared_tool_contribution"
    assert _SYSTEM_API_TOOL.name in str(error.value)
