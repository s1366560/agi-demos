"""Strict tenant runtime-hook projection into protocol-v2 profile entries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.model.agent.config.tenant_agent_config import RuntimeHookConfig
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
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2
from src.infrastructure.plugins.v2.runtime_hook_projection import (
    RuntimeHookProjectionV2Error,
    project_tenant_runtime_hooks_v2,
)
from src.infrastructure.plugins.v2.sisyphus_runtime import (
    SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2,
    SISYPHUS_BEFORE_REQUEST_MODULE_V2,
    SISYPHUS_RUNTIME_MODULES_V2,
    SISYPHUS_SESSION_START_MODULE_V2,
)
from src.infrastructure.plugins.v2.workspace_runtime import (
    WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2,
    WORKSPACE_BEFORE_REQUEST_MODULE_V2,
    WORKSPACE_RUNTIME_MODULES_V2,
    WORKSPACE_SESSION_START_MODULE_V2,
)

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _document() -> ProfileDocumentV2:
    return load_profile_document_v2(_PROFILE_PATH)


def _entry(document: ProfileDocumentV2, module_ref: str):
    return next(entry for entry in document.entries if entry.module_ref == module_ref)


def _hook(
    plugin_name: str,
    hook_name: str,
    *,
    enabled: bool = True,
    priority: int | None = None,
    settings: dict[str, object] | None = None,
    hook_family: str | None = None,
    executor_kind: str = "builtin",
    source_ref: str | None = None,
    entrypoint: str | None = None,
) -> RuntimeHookConfig:
    return RuntimeHookConfig(
        plugin_name=plugin_name,
        hook_name=hook_name,
        enabled=enabled,
        priority=priority,
        settings=dict(settings or {}),
        hook_family=hook_family,
        executor_kind=executor_kind,
        source_ref=source_ref,
        entrypoint=entrypoint,
    )


async def _stage(document: ProfileDocumentV2, *, generation: int = 1):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        document,
        {manifest.plugin_id: manifest},
        generation=generation,
    )
    return await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)


def _event_payload(generation, *, tool_name: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "conversation_id": "conversation-a",
        "event_id": "event-a",
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
        payload["tool_result_event_id"] = "tool-result-a"
    return payload


def _scope() -> ScopeV2:
    return ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id="tenant-a",
        project_id="project-a",
        session_id="session-a",
    )


@pytest.mark.unit
async def test_projection_preserves_per_hook_enabled_and_settings_without_fallback() -> None:
    projected = project_tenant_runtime_hooks_v2(
        _document(),
        tenant_id="tenant-a",
        runtime_hooks=(
            _hook("sisyphus-runtime", "on_session_start", enabled=False),
            _hook(
                "sisyphus-runtime",
                "before_response",
                settings={
                    "response_reminder": "Tenant response reminder",
                    "require_direct_outcome": False,
                },
            ),
            _hook("workspace-runtime", "after_tool_execution", enabled=False),
        ),
    )
    for module_ref in (*SISYPHUS_RUNTIME_MODULES_V2, *WORKSPACE_RUNTIME_MODULES_V2):
        assert _entry(projected, module_ref).scope == ScopeV2(
            kind=ScopeKindV2.TENANT,
            tenant_id="tenant-a",
        )
    assert _entry(projected, SISYPHUS_SESSION_START_MODULE_V2).enabled is False
    assert _entry(projected, WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2).enabled is False
    sisyphus_before_request = _entry(projected, SISYPHUS_BEFORE_REQUEST_MODULE_V2)
    assert sisyphus_before_request.config == {
        "response_reminder": "Tenant response reminder",
        "require_direct_outcome": False,
    }

    generation = await _stage(projected)
    operation = OperationContextV2(
        generation=generation,
        operation_id="turn-a",
        scope=_scope(),
    )
    async with operation:
        session_start = await operation.dispatch(
            AGENT_SESSION_START_EVENT_V2,
            _event_payload(generation),
        )
        before_request = await operation.dispatch(
            AGENT_BEFORE_REQUEST_EVENT_V2,
            _event_payload(generation),
        )
        after_tool = await operation.dispatch(
            TOOLS_AFTER_EXECUTE_EVENT_V2,
            _event_payload(generation, tool_name="todowrite"),
        )

    assert [result["source_entry_id"] for result in session_start] == [
        "builtin-workspace-session-start"
    ]
    assert before_request[0]["response_instructions"] == ["Tenant response reminder"]
    assert [result["source_entry_id"] for result in after_tool] == [
        "builtin-sisyphus-after-tool-execute"
    ]
    await generation.dispose()


@pytest.mark.unit
async def test_disabling_every_hook_disables_each_profile_entry() -> None:
    projected = project_tenant_runtime_hooks_v2(
        _document(),
        tenant_id="tenant-a",
        runtime_hooks=tuple(
            _hook("sisyphus-runtime", hook_name, enabled=False)
            for hook_name in (
                "on_session_start",
                "before_response",
                "after_tool_execution",
            )
        ),
    )

    assert all(
        _entry(projected, module_ref).enabled is False for module_ref in SISYPHUS_RUNTIME_MODULES_V2
    )
    generation = await _stage(projected)
    assert all(
        fiber.entry.module_ref not in SISYPHUS_RUNTIME_MODULES_V2 for fiber in generation.fibers
    )
    await generation.dispose()


@pytest.mark.unit
async def test_priority_is_converted_once_to_profile_listener_order() -> None:
    workspace_hooks = tuple(
        _hook("workspace-runtime", hook_name, priority=100)
        for hook_name in (
            "on_session_start",
            "before_response",
            "after_tool_execution",
        )
    )
    projected = project_tenant_runtime_hooks_v2(
        _document(),
        tenant_id="tenant-a",
        runtime_hooks=workspace_hooks,
    )
    module_order = [
        entry.module_ref
        for entry in projected.entries
        if entry.module_ref in {*SISYPHUS_RUNTIME_MODULES_V2, *WORKSPACE_RUNTIME_MODULES_V2}
    ]
    assert module_order == [
        WORKSPACE_SESSION_START_MODULE_V2,
        SISYPHUS_SESSION_START_MODULE_V2,
        WORKSPACE_BEFORE_REQUEST_MODULE_V2,
        SISYPHUS_BEFORE_REQUEST_MODULE_V2,
        WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2,
        SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2,
    ]

    generation = await _stage(projected)
    operation = OperationContextV2(
        generation=generation,
        operation_id="turn-a",
        scope=_scope(),
    )
    async with operation:
        results = await operation.dispatch(
            AGENT_SESSION_START_EVENT_V2,
            _event_payload(generation),
        )
    assert [result["source_entry_id"] for result in results] == [
        "builtin-workspace-session-start",
        "builtin-sisyphus-session-start",
    ]
    await generation.dispose()


@pytest.mark.unit
async def test_independent_per_event_priorities_can_require_opposite_orders() -> None:
    projected = project_tenant_runtime_hooks_v2(
        _document(),
        tenant_id="tenant-a",
        runtime_hooks=(
            _hook("workspace-runtime", "on_session_start", priority=100),
            _hook("workspace-runtime", "before_response", priority=-100),
        ),
    )
    generation = await _stage(projected)
    operation = OperationContextV2(
        generation=generation,
        operation_id="turn-a",
        scope=_scope(),
    )
    async with operation:
        session_start = await operation.dispatch(
            AGENT_SESSION_START_EVENT_V2,
            _event_payload(generation),
        )
        before_request = await operation.dispatch(
            AGENT_BEFORE_REQUEST_EVENT_V2,
            _event_payload(generation),
        )

    assert [result["source_entry_id"] for result in session_start] == [
        "builtin-workspace-session-start",
        "builtin-sisyphus-session-start",
    ]
    assert [result["source_entry_id"] for result in before_request] == [
        "builtin-sisyphus-before-request",
        "builtin-workspace-before-request",
    ]
    await generation.dispose()


@pytest.mark.unit
@pytest.mark.parametrize("hook_family", ["policy", "side_effect", "observational"])
def test_hook_family_rewrite_is_rejected(hook_family: str) -> None:
    with pytest.raises(RuntimeHookProjectionV2Error) as error:
        project_tenant_runtime_hooks_v2(
            _document(),
            tenant_id="tenant-a",
            runtime_hooks=(
                _hook(
                    "sisyphus-runtime",
                    "before_response",
                    hook_family=hook_family,
                ),
            ),
        )

    assert error.value.code == "runtime_hook_mode_fixed_by_contract"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("executor_kind", "source_ref", "entrypoint"),
    [
        ("script", "hooks/custom.py", "run"),
        ("plugin", "custom-plugin", "run"),
        ("builtin", "another-plugin", None),
        ("builtin", "sisyphus-runtime", "run"),
    ],
)
def test_custom_executor_or_implementation_rewrite_requires_v2_bundle(
    executor_kind: str,
    source_ref: str,
    entrypoint: str | None,
) -> None:
    with pytest.raises(RuntimeHookProjectionV2Error) as error:
        project_tenant_runtime_hooks_v2(
            _document(),
            tenant_id="tenant-a",
            runtime_hooks=(
                _hook(
                    "sisyphus-runtime",
                    "before_response",
                    executor_kind=executor_kind,
                    source_ref=source_ref,
                    entrypoint=entrypoint,
                ),
            ),
        )

    assert error.value.code == "runtime_hook_v1_custom_executor_requires_v2_bundle"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("plugin_name", "hook_name", "settings"),
    [
        ("unknown-runtime", "before_response", {}),
        ("sisyphus-runtime", "unknown_hook", {}),
        ("workspace-runtime", "on_session_start", {"unexpected": True}),
        ("sisyphus-runtime", "on_session_start", {"unexpected": True}),
    ],
)
def test_unmapped_hook_or_settings_requires_a_v2_bundle(
    plugin_name: str,
    hook_name: str,
    settings: dict[str, object],
) -> None:
    with pytest.raises(RuntimeHookProjectionV2Error) as error:
        project_tenant_runtime_hooks_v2(
            _document(),
            tenant_id="tenant-a",
            runtime_hooks=(_hook(plugin_name, hook_name, settings=settings),),
        )

    assert error.value.code == "runtime_hook_v1_entry_requires_v2_bundle"


@pytest.mark.unit
def test_projection_is_deterministic_and_does_not_mutate_the_base_document() -> None:
    document = _document()
    hooks = (
        _hook(
            "sisyphus-runtime",
            "on_session_start",
            source_ref="sisyphus-runtime",
            settings={"startup_reminder": "Tenant start"},
        ),
    )

    first = project_tenant_runtime_hooks_v2(
        document,
        tenant_id="tenant-a",
        runtime_hooks=hooks,
    )
    second = project_tenant_runtime_hooks_v2(
        document,
        tenant_id="tenant-a",
        runtime_hooks=hooks,
    )

    assert first == second
    assert _entry(document, SISYPHUS_SESSION_START_MODULE_V2).scope.kind is ScopeKindV2.ROOT
    assert (
        _entry(first, SISYPHUS_SESSION_START_MODULE_V2).config["startup_reminder"] == "Tenant start"
    )
