"""Pinned protocol-v2 dispatch for Agent processor lifecycle events."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.plugins.v2.agent_runtime_dispatcher import (
    PinnedAgentRuntimeDispatcherV2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def _manager() -> GenerationManagerV2:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        load_profile_document_v2(_PROFILE_PATH),
        {manifest.plugin_id: manifest},
        generation=41,
    )
    generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)
    manager = GenerationManagerV2()
    await manager.publish(generation)
    return manager


def _scope() -> ScopeV2:
    return ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id="tenant-a",
        project_id="project-a",
        session_id="session-a",
    )


def _workspace_payload() -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "session_id": "session-a",
        "conversation_id": "session-a",
        "task_authority": "workspace",
        "workspace_id": "workspace-a",
        "workspace_session_role": "worker",
    }


@pytest.mark.unit
async def test_processor_events_dispatch_only_through_pinned_v2_generation() -> None:
    manager = await _manager()
    fallback = SimpleNamespace(dispatch=AsyncMock(side_effect=AssertionError("V1 fallback used")))
    dispatcher = PinnedAgentRuntimeDispatcherV2(fallback=fallback)

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ):
            session_start = await dispatcher.dispatch("on_session_start", _workspace_payload())
            before_request = await dispatcher.dispatch(
                "before_response",
                {
                    **_workspace_payload(),
                    "session_instructions": [],
                    "response_instructions": [],
                },
            )
            after_tool = await dispatcher.dispatch(
                "after_tool_execution",
                {
                    **_workspace_payload(),
                    "tool_name": "todowrite",
                    "call_id": "call-a",
                    "result": {"secret": "must-not-cross-contract"},
                    "result_metadata": {"opaque": object()},
                },
            )
    finally:
        await manager.close()

    fallback.dispatch.assert_not_awaited()
    assert len(session_start.payload["session_instructions"]) == 3
    assert len(before_request.payload["response_instructions"]) == 3
    assert len(after_tool.payload["response_instructions"]) == 2
    assert after_tool.payload["result"] == {"secret": "must-not-cross-contract"}


@pytest.mark.unit
async def test_unmigrated_event_uses_explicit_legacy_fallback() -> None:
    fallback_result = SimpleNamespace(
        payload={"captured": True},
        diagnostics=("legacy",),
        denied=False,
    )
    fallback = SimpleNamespace(dispatch=AsyncMock(return_value=fallback_result))
    dispatcher = PinnedAgentRuntimeDispatcherV2(fallback=fallback)
    overrides = [{"plugin_name": "memory-runtime"}]

    result = await dispatcher.dispatch(
        "after_turn_complete",
        {"conversation_id": "session-a"},
        runtime_hook_overrides=overrides,
    )

    fallback.dispatch.assert_awaited_once_with(
        "after_turn_complete",
        payload={"conversation_id": "session-a"},
        runtime_hook_overrides=overrides,
    )
    assert result.payload == {"captured": True}
    assert result.diagnostics == ("legacy",)


@pytest.mark.unit
async def test_dispatch_rejects_payload_scope_that_differs_from_pinned_turn() -> None:
    manager = await _manager()
    dispatcher = PinnedAgentRuntimeDispatcherV2()

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ):
            with pytest.raises(RuntimeV2Error) as error:
                await dispatcher.dispatch(
                    "before_response",
                    {**_workspace_payload(), "tenant_id": "tenant-b"},
                )
    finally:
        await manager.close()

    assert error.value.code == "agent_event_scope_mismatch"


@pytest.mark.unit
async def test_session_processor_does_not_require_v1_registry_for_v2_dispatch() -> None:
    manager = await _manager()
    processor = SessionProcessor(
        config=ProcessorConfig(
            model="test-model",
            plugin_registry=None,
            plugin_event_dispatcher=PinnedAgentRuntimeDispatcherV2(),
        ),
        tools=[],
    )

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ):
            payload = await processor._notify_plugin_hook(
                "before_response",
                {
                    **_workspace_payload(),
                    "session_instructions": [],
                    "response_instructions": [],
                },
            )
    finally:
        await manager.close()

    assert len(payload["response_instructions"]) == 3
    assert processor._response_instructions == payload["response_instructions"]
