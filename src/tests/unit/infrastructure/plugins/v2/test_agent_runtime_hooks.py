"""Generation-owned Agent runtime hook modules for plugin protocol v2."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_events import (
    AGENT_BEFORE_REQUEST_EVENT_V2,
    AGENT_SESSION_START_EVENT_V2,
    TOOLS_AFTER_EXECUTE_EVENT_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import (
    ProfileDocumentV2,
    compose_profile_v2,
    load_profile_document_v2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    FiberPhaseV2,
    GenerationManagerV2,
    LoaderV2,
    OperationContextV2,
    RuntimeGenerationV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.sisyphus_runtime import SISYPHUS_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.workspace_runtime import WORKSPACE_RUNTIME_MODULE_V2

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _manifest():
    return parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))


def _document() -> ProfileDocumentV2:
    return load_profile_document_v2(_PROFILE_PATH)


def _snapshot(document: ProfileDocumentV2, *, generation: int):
    manifest = _manifest()
    return compose_profile_v2(
        document,
        {manifest.plugin_id: manifest},
        generation=generation,
    )


async def _stage(document: ProfileDocumentV2, *, generation: int) -> RuntimeGenerationV2:
    snapshot = _snapshot(document, generation=generation)
    return await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)


def _session_scope() -> ScopeV2:
    return ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id="tenant-a",
        project_id="project-a",
        session_id="session-a",
    )


def _event_payload(
    generation: RuntimeGenerationV2,
    *,
    event_id: str,
    tool_name: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "conversation_id": "conversation-a",
        "event_id": event_id,
        "generation_digest": generation.digest,
        "operation_id": "turn-a",
        "project_id": "project-a",
        "session_id": "session-a",
        "task_authority": "workspace",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "workspace_session_role": "worker",
    }
    if tool_name is not None:
        payload["tool_name"] = tool_name
        payload["tool_result_event_id"] = f"result:{event_id}"
    return payload


def _replace_entry(
    document: ProfileDocumentV2,
    module_ref: str,
    **changes: object,
) -> ProfileDocumentV2:
    entries = tuple(
        replace(entry, **changes) if entry.module_ref == module_ref else entry
        for entry in document.entries
    )
    return replace(document, entries=entries)


def _fiber(generation: RuntimeGenerationV2, module_ref: str):
    return next(fiber for fiber in generation.fibers if fiber.entry.module_ref == module_ref)


@pytest.mark.unit
async def test_default_profile_orders_sisyphus_before_workspace_handlers() -> None:
    document = _document()
    runtime_modules = [
        entry.module_ref
        for entry in document.entries
        if entry.module_ref in {SISYPHUS_RUNTIME_MODULE_V2, WORKSPACE_RUNTIME_MODULE_V2}
    ]

    assert runtime_modules == [SISYPHUS_RUNTIME_MODULE_V2, WORKSPACE_RUNTIME_MODULE_V2]

    generation = await _stage(document, generation=1)
    operation = OperationContextV2(
        generation=generation,
        operation_id="turn-a",
        scope=_session_scope(),
    )
    async with operation:
        results = await operation.dispatch(
            AGENT_SESSION_START_EVENT_V2,
            _event_payload(generation, event_id="session-start-a"),
        )

    assert [result["source_entry_id"] for result in results] == [
        "builtin-sisyphus-runtime",
        "builtin-workspace-runtime",
    ]
    assert results[0]["session_instructions"] == [
        next(
            entry.config["startup_reminder"]
            for entry in document.entries
            if entry.module_ref == SISYPHUS_RUNTIME_MODULE_V2
        )
    ]
    assert len(results[1]["session_instructions"]) == 2
    await generation.dispose()


@pytest.mark.unit
async def test_runtime_hook_modules_return_typed_instruction_contributions() -> None:
    generation = await _stage(_document(), generation=2)
    operation = OperationContextV2(
        generation=generation,
        operation_id="turn-a",
        scope=_session_scope(),
    )

    async with operation:
        before_request = await operation.dispatch(
            AGENT_BEFORE_REQUEST_EVENT_V2,
            _event_payload(generation, event_id="before-request-a"),
        )
        after_tool = await operation.dispatch(
            TOOLS_AFTER_EXECUTE_EVENT_V2,
            _event_payload(
                generation,
                event_id="after-tool-a",
                tool_name="todowrite",
            ),
        )

    assert [result["source_entry_id"] for result in before_request] == [
        "builtin-sisyphus-runtime",
        "builtin-workspace-runtime",
    ]
    assert all(result["session_instructions"] == [] for result in before_request)
    assert len(before_request[0]["response_instructions"]) == 2
    assert len(before_request[1]["response_instructions"]) == 1
    assert [result["source_entry_id"] for result in after_tool] == [
        "builtin-sisyphus-runtime",
        "builtin-workspace-runtime",
    ]
    assert all(
        set(result)
        == {
            "response_instructions",
            "session_instructions",
            "source_entry_id",
        }
        for result in (*before_request, *after_tool)
    )
    await generation.dispose()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("event", "payload_field", "payload_value"),
    [
        (AGENT_SESSION_START_EVENT_V2, "runtime_context", {"workspace_id": "raw"}),
        (TOOLS_AFTER_EXECUTE_EVENT_V2, "tool_arguments", {"secret": "raw"}),
        (TOOLS_AFTER_EXECUTE_EVENT_V2, "tool_result", object()),
    ],
)
async def test_runtime_hook_events_reject_opaque_runtime_or_tool_objects(
    event: str,
    payload_field: str,
    payload_value: object,
) -> None:
    generation = await _stage(_document(), generation=3)
    operation = OperationContextV2(
        generation=generation,
        operation_id="turn-a",
        scope=_session_scope(),
    )
    payload = _event_payload(
        generation,
        event_id="unsafe-payload",
        tool_name="todowrite" if event == TOOLS_AFTER_EXECUTE_EVENT_V2 else None,
    )
    payload[payload_field] = payload_value

    async with operation:
        with pytest.raises(RuntimeV2Error) as error:
            await operation.dispatch(event, payload)

    assert error.value.code == "invalid_event_payload"
    await generation.dispose()


@pytest.mark.unit
async def test_disabling_sisyphus_entry_removes_its_handlers_without_fallback() -> None:
    document = _replace_entry(
        _document(),
        SISYPHUS_RUNTIME_MODULE_V2,
        enabled=False,
    )
    generation = await _stage(document, generation=4)
    operation = OperationContextV2(
        generation=generation,
        operation_id="turn-a",
        scope=_session_scope(),
    )

    async with operation:
        results = await operation.dispatch(
            AGENT_SESSION_START_EVENT_V2,
            _event_payload(generation, event_id="session-start-disabled"),
        )

    assert [result["source_entry_id"] for result in results] == ["builtin-workspace-runtime"]
    assert all(fiber.entry.module_ref != SISYPHUS_RUNTIME_MODULE_V2 for fiber in generation.fibers)
    await generation.dispose()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("module_ref", "config"),
    [
        (SISYPHUS_RUNTIME_MODULE_V2, {"require_direct_outcome": True}),
        (WORKSPACE_RUNTIME_MODULE_V2, {"unexpected": True}),
    ],
)
async def test_runtime_hook_config_schema_rejects_before_activation(
    module_ref: str,
    config: dict[str, object],
) -> None:
    document = _replace_entry(_document(), module_ref, config=config)

    with pytest.raises(RuntimeV2Error) as error:
        await _stage(document, generation=5)

    assert error.value.code == "invalid_module_config"


@pytest.mark.unit
async def test_retired_generation_keeps_then_disposes_its_hook_listeners() -> None:
    first = await _stage(_document(), generation=6)
    second_document = _replace_entry(
        _document(),
        SISYPHUS_RUNTIME_MODULE_V2,
        enabled=False,
    )
    second = await _stage(second_document, generation=7)
    manager = GenerationManagerV2()
    await manager.publish(first)
    old_lease = await manager.acquire()

    await manager.publish(second)
    new_lease = await manager.acquire()
    assert _fiber(first, SISYPHUS_RUNTIME_MODULE_V2).phase is FiberPhaseV2.ACTIVE

    old_operation = OperationContextV2(
        generation=old_lease.generation,
        operation_id="old-turn",
        scope=_session_scope(),
    )
    new_operation = OperationContextV2(
        generation=new_lease.generation,
        operation_id="new-turn",
        scope=_session_scope(),
    )
    async with old_operation, new_operation:
        old_results = await old_operation.dispatch(
            AGENT_SESSION_START_EVENT_V2,
            _event_payload(first, event_id="old-session-start"),
        )
        new_results = await new_operation.dispatch(
            AGENT_SESSION_START_EVENT_V2,
            _event_payload(second, event_id="new-session-start"),
        )

    assert [result["source_entry_id"] for result in old_results] == [
        "builtin-sisyphus-runtime",
        "builtin-workspace-runtime",
    ]
    assert [result["source_entry_id"] for result in new_results] == ["builtin-workspace-runtime"]

    await old_lease.release()
    assert _fiber(first, SISYPHUS_RUNTIME_MODULE_V2).phase is FiberPhaseV2.DISPOSED
    assert all(
        diagnostic.label.startswith("event:")
        for diagnostic in _fiber(first, SISYPHUS_RUNTIME_MODULE_V2).diagnostics().effects
    )
    await new_lease.release()
    await manager.close()
