"""V2 Profile authority coverage for fixed Agent runtime utility tools."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _resolve_current_tools_from_runtime_v2,
)
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.plugins.selection_pipeline import ToolSelectionContext
from src.infrastructure.plugins.v2.agent_runtime_utility_tools import (
    AGENT_ENV_VAR_TOOL_NAMES_V2,
    AGENT_ENV_VAR_TOOLS_MODULE_V2,
    AGENT_ENV_VAR_TOOLS_SOURCE_V2,
    AGENT_MCP_REGISTRATION_TOOL_MODULE_V2,
    AGENT_MCP_REGISTRATION_TOOL_NAMES_V2,
    AGENT_MCP_REGISTRATION_TOOL_SOURCE_V2,
    AGENT_SKILL_MANAGEMENT_TOOL_NAMES_V2,
    AGENT_SKILL_MANAGEMENT_TOOLS_MODULE_V2,
    AGENT_SKILL_MANAGEMENT_TOOLS_SOURCE_V2,
    AGENT_WEB_TOOL_NAMES_V2,
    AGENT_WEB_TOOLS_MODULE_V2,
    AGENT_WEB_TOOLS_SOURCE_V2,
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


@dataclass(frozen=True, kw_only=True)
class _ToolGroupCase:
    label: str
    module_ref: str
    source_id: str
    tool_names: frozenset[str]


_CASES = (
    _ToolGroupCase(
        label="web",
        module_ref=AGENT_WEB_TOOLS_MODULE_V2,
        source_id=AGENT_WEB_TOOLS_SOURCE_V2,
        tool_names=AGENT_WEB_TOOL_NAMES_V2,
    ),
    _ToolGroupCase(
        label="skill-management",
        module_ref=AGENT_SKILL_MANAGEMENT_TOOLS_MODULE_V2,
        source_id=AGENT_SKILL_MANAGEMENT_TOOLS_SOURCE_V2,
        tool_names=AGENT_SKILL_MANAGEMENT_TOOL_NAMES_V2,
    ),
    _ToolGroupCase(
        label="env-var",
        module_ref=AGENT_ENV_VAR_TOOLS_MODULE_V2,
        source_id=AGENT_ENV_VAR_TOOLS_SOURCE_V2,
        tool_names=AGENT_ENV_VAR_TOOL_NAMES_V2,
    ),
    _ToolGroupCase(
        label="mcp-registration",
        module_ref=AGENT_MCP_REGISTRATION_TOOL_MODULE_V2,
        source_id=AGENT_MCP_REGISTRATION_TOOL_SOURCE_V2,
        tool_names=AGENT_MCP_REGISTRATION_TOOL_NAMES_V2,
    ),
)


class _NamedTool:
    description = "Prepared Agent runtime utility tool."

    def __init__(self, name: str) -> None:
        self.name = name

    def get_parameters_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self) -> str:
        return "ok"


class _ToolAgent:
    def __init__(self, case: _ToolGroupCase, *, include_group: bool = True) -> None:
        group_tools = {name: _NamedTool(name) for name in case.tool_names} if include_group else {}
        self.raw_tools = {"read": _NamedTool("read"), **group_tools}
        self._tool_selection_pipeline = None
        self._last_tool_selection_trace: tuple[object, ...] = ()

    def _get_current_tools(
        self,
        *,
        selection_context: object,
    ) -> tuple[dict[str, object], list[object]]:
        assert selection_context is None
        return self.raw_tools, list(convert_tools(self.raw_tools))


def _snapshot(*, case: _ToolGroupCase, generation: int, group_enabled: bool):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)
    selected_modules = {
        RUNTIME_BOUNDARY_MODULE_V2,
        TOOL_SET_MODULE_V2,
        TOOL_CONTRIBUTION_MODULE_V2,
        case.module_ref,
    }
    entries = tuple(
        replace(
            entry,
            enabled=(group_enabled if entry.module_ref == case.module_ref else entry.enabled),
        )
        for entry in document.entries
        if entry.module_ref in selected_modules
    )
    return compose_profile_v2(
        replace(document, entries=entries),
        {manifest.plugin_id: manifest},
        generation=generation,
    )


async def _manager(
    *,
    case: _ToolGroupCase,
    generation: int,
    group_enabled: bool,
) -> GenerationManagerV2:
    runtime_generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(
        _snapshot(case=case, generation=generation, group_enabled=group_enabled)
    )
    manager = GenerationManagerV2()
    await manager.publish(runtime_generation)
    return manager


@pytest.mark.unit
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.label)
def test_runtime_utility_tools_are_separate_explicit_profile_contributions(
    case: _ToolGroupCase,
) -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = [entry for entry in document.entries if entry.module_ref == case.module_ref]
    agent_owned = next(
        entry for entry in document.entries if entry.module_ref == TOOL_CONTRIBUTION_MODULE_V2
    )

    assert len(entries) == 1
    assert entries[0].enabled is True
    assert entries[0].config == {"source_id": case.source_id}
    assert entries[0].inject == {"catalog": "service:tool-set-catalog"}
    assert case.tool_names.issubset(agent_owned.config["excluded_tools"])


@pytest.mark.unit
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.label)
async def test_disabling_runtime_utility_contribution_removes_only_its_tools(
    case: _ToolGroupCase,
) -> None:
    manager = await _manager(case=case, generation=91, group_enabled=False)
    agent = _ToolAgent(case)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id=f"{case.label}-tools-disabled",
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
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.label)
async def test_enabling_runtime_utility_contribution_restores_exact_prepared_tools(
    case: _ToolGroupCase,
) -> None:
    manager = await _manager(case=case, generation=92, group_enabled=True)
    agent = _ToolAgent(case)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id=f"{case.label}-tools-enabled",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            tools, definitions = _resolve_current_tools_from_runtime_v2(
                agent,
                ToolSelectionContext(),
            )
    finally:
        await manager.close()

    assert set(tools) == {"read", *case.tool_names}
    assert {definition.name for definition in definitions} == set(tools)
    assert all(tools[name] is agent.raw_tools[name] for name in case.tool_names)


@pytest.mark.unit
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.label)
async def test_enabled_runtime_utility_contribution_fails_when_prepared_tools_are_missing(
    case: _ToolGroupCase,
) -> None:
    manager = await _manager(case=case, generation=93, group_enabled=True)
    agent = _ToolAgent(case, include_group=False)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id=f"{case.label}-tools-incomplete",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            with pytest.raises(RuntimeV2Error) as error:
                _resolve_current_tools_from_runtime_v2(agent, ToolSelectionContext())
    finally:
        await manager.close()

    assert error.value.code == "missing_prepared_tool_contribution"
    assert all(name in str(error.value) for name in case.tool_names)
