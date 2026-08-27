"""V2-only coverage for generation-owned Agent orchestration tools."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    AGENT_OPERATION_ORCHESTRATOR_SERVICE_V2,
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
    TOOL_SET_RESOLVER_SERVICE_V2,
    ToolSetResolverProtocolV2,
)

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_WORKER_STATE_PATH = _ROOT / "src/infrastructure/agent/state/agent_worker_state.py"
_ORCHESTRATION_TOOL_MODULE_V2 = "builtin://memstack/agent/tool/orchestration"
_TOOL_MODULE_PATHS = (
    "src/infrastructure/agent/tools/agent_spawn.py",
    "src/infrastructure/agent/tools/agent_list.py",
    "src/infrastructure/agent/tools/agent_send.py",
    "src/infrastructure/agent/tools/agent_sessions.py",
    "src/infrastructure/agent/tools/agent_history.py",
    "src/infrastructure/agent/tools/agent_stop.py",
    "src/infrastructure/agent/tools/agent_definition_tool.py",
    "src/infrastructure/agent/tools/workspace_wtp.py",
    "src/infrastructure/agent/tools/workspace_leader_wtp.py",
    "src/infrastructure/agent/tools/workspace_clarification.py",
)
_EXPECTED_TOOL_NAMES = frozenset(
    {
        "agent_spawn",
        "agent_list",
        "agent_send",
        "agent_sessions",
        "agent_history",
        "agent_stop",
        "agent_definition_manage",
        "workspace_report_progress",
        "workspace_report_complete",
        "workspace_report_blocked",
        "workspace_request_clarification",
        "workspace_respond_clarification",
        "workspace_assign_task",
        "workspace_cancel_task",
        "workspace_health_verdict",
    }
)


def _snapshot(*, generation: int, contribution_enabled: bool):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)
    selected_modules = {
        RUNTIME_BOUNDARY_MODULE_V2,
        TOOL_SET_MODULE_V2,
        _ORCHESTRATION_TOOL_MODULE_V2,
    }
    entries = tuple(
        replace(
            entry,
            enabled=(
                contribution_enabled
                if entry.module_ref == _ORCHESTRATION_TOOL_MODULE_V2
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


async def _manager(*, generation: int, contribution_enabled: bool) -> GenerationManagerV2:
    runtime_generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(
        _snapshot(generation=generation, contribution_enabled=contribution_enabled)
    )
    manager = GenerationManagerV2()
    await manager.publish(runtime_generation)
    return manager


def _tool_context() -> ToolContext:
    return ToolContext(
        session_id="session-1",
        message_id="message-1",
        call_id="call-1",
        agent_name="agent-1",
        conversation_id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
    )


@pytest.mark.unit
def test_agent_orchestration_tools_are_an_explicit_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    matching = [
        entry for entry in document.entries if entry.module_ref == _ORCHESTRATION_TOOL_MODULE_V2
    ]

    assert len(matching) == 1
    assert matching[0].enabled is True
    assert matching[0].inject == {"catalog": "service:tool-set-catalog"}


@pytest.mark.unit
async def test_orchestration_tool_contribution_resolves_exact_profile_set() -> None:
    manager = await _manager(generation=301, contribution_enabled=True)

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="orchestration-tools-enabled",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as operation:
            resolver = operation.require(TOOL_SET_RESOLVER_SERVICE_V2)
            assert isinstance(resolver, ToolSetResolverProtocolV2)
            tool_set = resolver.resolve(agent=object(), selection_context=None)
    finally:
        await manager.close()

    assert frozenset(tool_set.tools) == _EXPECTED_TOOL_NAMES
    assert {definition.name for definition in tool_set.definitions} == _EXPECTED_TOOL_NAMES


@pytest.mark.unit
async def test_disabling_orchestration_tool_entry_removes_tools() -> None:
    manager = await _manager(generation=302, contribution_enabled=False)

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="orchestration-tools-disabled",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as operation:
            resolver = operation.require(TOOL_SET_RESOLVER_SERVICE_V2)
            assert isinstance(resolver, ToolSetResolverProtocolV2)
            tool_set = resolver.resolve(agent=object(), selection_context=None)
    finally:
        await manager.close()

    assert tool_set.tools == {}
    assert tool_set.definitions == ()


@pytest.mark.unit
async def test_orchestration_tool_execution_resolves_pinned_operation_service() -> None:
    manager = await _manager(generation=303, contribution_enabled=True)
    orchestrator = MagicMock(spec=AgentOrchestrator)
    orchestrator.list_agents = AsyncMock(return_value=[])

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="orchestration-tool-execution",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as operation:
            _ = operation.provide(
                AGENT_OPERATION_ORCHESTRATOR_SERVICE_V2,
                orchestrator,
                label="test-operation-agent-orchestrator",
            )
            resolver = operation.require(TOOL_SET_RESOLVER_SERVICE_V2)
            assert isinstance(resolver, ToolSetResolverProtocolV2)
            tool_set = resolver.resolve(agent=object(), selection_context=None)
            result = await tool_set.tools["agent_list"].execute(_tool_context())
    finally:
        await manager.close()

    assert result.is_error is False
    assert json.loads(result.output) == []
    orchestrator.list_agents.assert_awaited_once_with(
        project_id="project-1",
        tenant_id="tenant-1",
        discoverable_only=True,
    )


@pytest.mark.unit
async def test_orchestration_tool_execution_rejects_missing_operation_service() -> None:
    manager = await _manager(generation=304, contribution_enabled=True)

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="orchestration-tool-missing-service",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as operation:
            resolver = operation.require(TOOL_SET_RESOLVER_SERVICE_V2)
            assert isinstance(resolver, ToolSetResolverProtocolV2)
            tool_set = resolver.resolve(agent=object(), selection_context=None)
            with pytest.raises(RuntimeV2Error) as error:
                await tool_set.tools["agent_list"].execute(_tool_context())
    finally:
        await manager.close()

    assert error.value.code == "missing_service"
    assert AGENT_OPERATION_ORCHESTRATOR_SERVICE_V2 in str(error.value)


@pytest.mark.unit
def test_worker_has_no_native_orchestration_tool_registration() -> None:
    source = _WORKER_STATE_PATH.read_text(encoding="utf-8")

    assert "def _add_agent_tools(" not in source
    assert "_add_agent_tools(tools" not in source
    assert "configure_agent_spawn" not in source
    assert "configure_workspace_wtp" not in source


@pytest.mark.unit
def test_orchestration_tools_have_no_process_global_orchestrator_fallback() -> None:
    for relative_path in _TOOL_MODULE_PATHS:
        source = (_ROOT / relative_path).read_text(encoding="utf-8")
        assert "_orchestrator:" not in source, relative_path
        assert "def configure_" not in source, relative_path
        assert "current_agent_orchestrator_v2" in source, relative_path
