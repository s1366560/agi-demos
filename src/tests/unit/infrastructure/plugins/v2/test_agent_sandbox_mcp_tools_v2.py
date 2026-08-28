"""V2 Profile authority coverage for dynamically named sandbox MCP tools."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _resolve_current_tools_from_runtime_v2,
)
from src.infrastructure.agent.plugins.selection_pipeline import ToolSelectionContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.plugins.v2.agent_sandbox_mcp_tools import (
    AGENT_SANDBOX_MCP_TOOLS_MODULE_V2,
    AGENT_SANDBOX_MCP_TOOLS_SOURCE_V2,
    SANDBOX_MCP_TOOL_REQUIRED_TAGS_V2,
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
    TOOL_SET_MODULE_V2,
    ToolSetCatalogV2,
)

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def _execute_tool(**_kwargs: object) -> str:
    return "ok"


def _tool(name: str, *, tags: frozenset[str]) -> ToolInfo:
    return ToolInfo(
        name=name,
        description=f"Prepared tool {name}.",
        parameters={"type": "object", "properties": {}},
        execute=_execute_tool,
        tags=tags,
    )


_UNTAGGED_TOOL = _tool("read", tags=frozenset())
_BUILTIN_SANDBOX_MCP_TOOL = _tool(
    "mcp__sandbox__arbitrary_echo",
    tags=frozenset({"mcp", "sandbox"}),
)
_USER_SANDBOX_MCP_TOOL = _tool(
    "mcp__calendar__list_events",
    tags=frozenset({"calendar", "mcp", "sandbox"}),
)
_SANDBOX_CUSTOM_TOOL = _tool(
    "project_custom_tool",
    tags=frozenset({"custom", "sandbox"}),
)


class _ToolAgent:
    def __init__(
        self,
        *,
        raw_tools: object | None = None,
    ) -> None:
        self.raw_tools = (
            raw_tools
            if raw_tools is not None
            else {
                _UNTAGGED_TOOL.name: _UNTAGGED_TOOL,
                _BUILTIN_SANDBOX_MCP_TOOL.name: _BUILTIN_SANDBOX_MCP_TOOL,
                _USER_SANDBOX_MCP_TOOL.name: _USER_SANDBOX_MCP_TOOL,
                _SANDBOX_CUSTOM_TOOL.name: _SANDBOX_CUSTOM_TOOL,
            }
        )
        self._tool_selection_pipeline = None
        self._last_tool_selection_trace: tuple[object, ...] = ()

    def _get_current_tools(
        self,
        *,
        selection_context: object,
    ) -> object:
        _ = selection_context
        raise AssertionError("V2 contributions must not read legacy agent tools")


def _snapshot(
    *,
    generation: int,
    sandbox_mcp_enabled: bool,
):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)
    selected_modules = {
        RUNTIME_BOUNDARY_MODULE_V2,
        TOOL_SET_MODULE_V2,
        AGENT_SANDBOX_MCP_TOOLS_MODULE_V2,
    }
    entries = tuple(
        replace(
            entry,
            enabled=(
                sandbox_mcp_enabled
                if entry.module_ref == AGENT_SANDBOX_MCP_TOOLS_MODULE_V2
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


async def _manager(
    *,
    generation: int,
    sandbox_mcp_enabled: bool,
) -> GenerationManagerV2:
    runtime_generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(
        _snapshot(
            generation=generation,
            sandbox_mcp_enabled=sandbox_mcp_enabled,
        )
    )
    manager = GenerationManagerV2()
    await manager.publish(runtime_generation)
    return manager


@pytest.mark.unit
def test_sandbox_mcp_tools_are_an_explicit_tagged_profile_contribution() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = [
        entry for entry in document.entries if entry.module_ref == AGENT_SANDBOX_MCP_TOOLS_MODULE_V2
    ]
    assert len(entries) == 1
    assert entries[0].enabled is True
    assert entries[0].config == {
        "source_id": AGENT_SANDBOX_MCP_TOOLS_SOURCE_V2,
        "required_tags": sorted(SANDBOX_MCP_TOOL_REQUIRED_TAGS_V2),
    }
    assert entries[0].inject == {"catalog": "service:tool-set-catalog"}


@pytest.mark.unit
async def test_disabling_sandbox_mcp_contribution_removes_tagged_prepared_tools() -> None:
    manager = await _manager(generation=101, sandbox_mcp_enabled=False)
    agent = _ToolAgent()
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="sandbox-mcp-tools-disabled",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            tool_set = _resolve_current_tools_from_runtime_v2(
                agent,
                ToolSelectionContext(),
                operation_catalog=ToolSetCatalogV2(),
            )
            tools, _definitions = tool_set.tools, tool_set.definitions
    finally:
        await manager.close()

    assert tools == {}


@pytest.mark.unit
async def test_enabling_sandbox_mcp_contribution_restores_exact_prepared_instances() -> None:
    manager = await _manager(generation=102, sandbox_mcp_enabled=True)
    agent = _ToolAgent()
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="sandbox-mcp-tools-enabled",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            tool_set = _resolve_current_tools_from_runtime_v2(
                agent,
                ToolSelectionContext(),
                operation_catalog=ToolSetCatalogV2(),
            )
            tools, definitions = tool_set.tools, tool_set.definitions
    finally:
        await manager.close()

    assert set(tools) == {_BUILTIN_SANDBOX_MCP_TOOL.name, _USER_SANDBOX_MCP_TOOL.name}
    assert {definition.name for definition in definitions} == set(tools)
    assert tools[_BUILTIN_SANDBOX_MCP_TOOL.name] is _BUILTIN_SANDBOX_MCP_TOOL
    assert tools[_USER_SANDBOX_MCP_TOOL.name] is _USER_SANDBOX_MCP_TOOL
    assert _SANDBOX_CUSTOM_TOOL.name not in tools


@pytest.mark.unit
async def test_empty_sandbox_mcp_tool_set_is_valid() -> None:
    manager = await _manager(generation=103, sandbox_mcp_enabled=True)
    agent = _ToolAgent(raw_tools={_UNTAGGED_TOOL.name: _UNTAGGED_TOOL})
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="sandbox-mcp-tools-empty",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            tool_set = _resolve_current_tools_from_runtime_v2(
                agent,
                ToolSelectionContext(),
                operation_catalog=ToolSetCatalogV2(),
            )
            tools, definitions = tool_set.tools, tool_set.definitions
    finally:
        await manager.close()

    assert tools == {}
    assert definitions == ()


@pytest.mark.unit
async def test_sandbox_mcp_config_rejects_wrong_tags_before_activation() -> None:
    snapshot = _snapshot(
        generation=104,
        sandbox_mcp_enabled=True,
    )
    sandbox_entry = next(
        entry for entry in snapshot.entries if entry.module_ref == AGENT_SANDBOX_MCP_TOOLS_MODULE_V2
    )
    object.__setattr__(
        sandbox_entry,
        "config",
        {
            "source_id": AGENT_SANDBOX_MCP_TOOLS_SOURCE_V2,
            "required_tags": ["sandbox"],
        },
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "invalid_module_config"


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw_tools",
    [[], object(), {1: _BUILTIN_SANDBOX_MCP_TOOL}],
)
async def test_sandbox_mcp_contribution_rejects_invalid_prepared_provider_tools(
    raw_tools: object,
) -> None:
    manager = await _manager(
        generation=105,
        sandbox_mcp_enabled=True,
    )
    agent = _ToolAgent(raw_tools=raw_tools)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="sandbox-mcp-tools-invalid",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            with pytest.raises(RuntimeV2Error) as error:
                _resolve_current_tools_from_runtime_v2(
                    agent,
                    ToolSelectionContext(),
                    operation_catalog=ToolSetCatalogV2(),
                )
    finally:
        await manager.close()

    assert error.value.code == "invalid_prepared_tool_provider"
