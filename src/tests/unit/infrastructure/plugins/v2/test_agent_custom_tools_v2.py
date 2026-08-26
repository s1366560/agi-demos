"""V2 Profile authority coverage for dynamically named custom tools."""

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
from src.infrastructure.agent.tools.custom_tool_status import custom_tools_status
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.plugins.v2.agent_custom_tools import (
    AGENT_CUSTOM_TOOLS_MODULE_V2,
    AGENT_CUSTOM_TOOLS_SOURCE_V2,
    CUSTOM_TOOL_SOURCE_TAG_V2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_MODULE_V2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.tool_set import (
    TOOL_CONTRIBUTION_MODULE_V2,
    TOOL_SET_MODULE_V2,
)

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def _execute_custom(**_kwargs: object) -> str:
    return "custom"


_CUSTOM_TOOL = ToolInfo(
    name="project_defined_tool",
    description="Project-defined tool.",
    parameters={"type": "object", "properties": {}},
    execute=_execute_custom,
    tags=frozenset({"custom"}),
)


class _ReadTool:
    name = "read"
    description = "Read a resource."

    def get_parameters_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self) -> str:
        return "ok"


class _ToolAgent:
    def __init__(self, *, include_status: bool = True) -> None:
        custom_tools = {_CUSTOM_TOOL.name: _CUSTOM_TOOL}
        if include_status:
            custom_tools[custom_tools_status.name] = custom_tools_status
        self.raw_tools = {"read": _ReadTool(), **custom_tools}
        self._tool_selection_pipeline = None
        self._last_tool_selection_trace: tuple[object, ...] = ()

    def _get_current_tools(
        self,
        *,
        selection_context: object,
    ) -> tuple[dict[str, object], list[object]]:
        assert selection_context is None
        return self.raw_tools, list(convert_tools(self.raw_tools))


def _snapshot(*, generation: int, custom_enabled: bool):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)
    selected_modules = {
        RUNTIME_BOUNDARY_MODULE_V2,
        TOOL_SET_MODULE_V2,
        TOOL_CONTRIBUTION_MODULE_V2,
        AGENT_CUSTOM_TOOLS_MODULE_V2,
    }
    entries = tuple(
        replace(
            entry,
            enabled=(
                custom_enabled
                if entry.module_ref == AGENT_CUSTOM_TOOLS_MODULE_V2
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


async def _manager(*, generation: int, custom_enabled: bool) -> GenerationManagerV2:
    runtime_generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(
        _snapshot(generation=generation, custom_enabled=custom_enabled)
    )
    manager = GenerationManagerV2()
    await manager.publish(runtime_generation)
    return manager


@pytest.mark.unit
def test_custom_tools_are_an_explicit_tagged_profile_contribution() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    custom_entries = [
        entry for entry in document.entries if entry.module_ref == AGENT_CUSTOM_TOOLS_MODULE_V2
    ]
    agent_owned = next(
        entry for entry in document.entries if entry.module_ref == TOOL_CONTRIBUTION_MODULE_V2
    )

    assert len(custom_entries) == 1
    assert custom_entries[0].enabled is True
    assert custom_entries[0].config == {
        "source_id": AGENT_CUSTOM_TOOLS_SOURCE_V2,
        "source_tag": CUSTOM_TOOL_SOURCE_TAG_V2,
        "required_tool": custom_tools_status.name,
    }
    assert custom_entries[0].inject == {"catalog": "service:tool-set-catalog"}
    assert agent_owned.config["excluded_tags"] == [CUSTOM_TOOL_SOURCE_TAG_V2]


@pytest.mark.unit
async def test_disabling_custom_contribution_removes_tagged_prepared_tools() -> None:
    manager = await _manager(generation=71, custom_enabled=False)
    agent = _ToolAgent()
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="custom-tools-disabled",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            tools, _definitions = _resolve_current_tools_from_runtime_v2(
                agent,
                ToolSelectionContext(),
            )
    finally:
        await manager.close()

    assert set(tools) == {"read"}


@pytest.mark.unit
async def test_enabling_custom_contribution_restores_exact_tagged_tools() -> None:
    manager = await _manager(generation=72, custom_enabled=True)
    agent = _ToolAgent()
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="custom-tools-enabled",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            tools, definitions = _resolve_current_tools_from_runtime_v2(
                agent,
                ToolSelectionContext(),
            )
    finally:
        await manager.close()

    assert set(tools) == {"read", _CUSTOM_TOOL.name, custom_tools_status.name}
    assert {definition.name for definition in definitions} == set(tools)
    assert tools[_CUSTOM_TOOL.name] is _CUSTOM_TOOL
    assert tools[custom_tools_status.name] is custom_tools_status


@pytest.mark.unit
async def test_enabled_custom_contribution_requires_prepared_status_tool() -> None:
    manager = await _manager(generation=73, custom_enabled=True)
    agent = _ToolAgent(include_status=False)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="custom-tools-incomplete",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            with pytest.raises(RuntimeV2Error) as error:
                _resolve_current_tools_from_runtime_v2(agent, ToolSelectionContext())
    finally:
        await manager.close()

    assert error.value.code == "missing_prepared_tool_contribution"
    assert custom_tools_status.name in str(error.value)
