"""Unit tests for the V2-only plugin_manager tool."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import RuntimeKindV2, TrustKindV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.tools import plugin_manager
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.plugins.v2 import boundary
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_context import FiberPhaseV2

pytestmark = pytest.mark.unit


def _make_ctx(**overrides: Any) -> ToolContext:
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


def _generation() -> SimpleNamespace:
    active_module = SimpleNamespace(module_ref="builtin://demo/active")
    disabled_module = SimpleNamespace(module_ref="builtin://demo/disabled")
    dormant_module = SimpleNamespace(module_ref="builtin://dormant/runtime")
    manifests = (
        SimpleNamespace(
            plugin_id="demo-plugin",
            version="2.1.0",
            runtime=RuntimeKindV2.PYTHON_TRUSTED,
            trust=TrustKindV2.BUILTIN,
            modules=(active_module, disabled_module),
        ),
        SimpleNamespace(
            plugin_id="dormant-plugin",
            version="3.0.0",
            runtime=RuntimeKindV2.WASM,
            trust=TrustKindV2.SIGNED,
            modules=(dormant_module,),
        ),
    )
    active_entry = SimpleNamespace(
        entry_id="demo-active",
        plugin_ref="demo-plugin",
        module_ref=active_module.module_ref,
    )
    snapshot = SimpleNamespace(
        profile_id="profile-v2",
        generation=42,
        digest="a" * 64,
        manifests=manifests,
        entries=(
            active_entry,
            SimpleNamespace(
                entry_id="demo-disabled",
                plugin_ref="demo-plugin",
                module_ref=disabled_module.module_ref,
                enabled=False,
            ),
            SimpleNamespace(
                entry_id="dormant-disabled",
                plugin_ref="dormant-plugin",
                module_ref=dormant_module.module_ref,
                enabled=False,
            ),
        ),
    )
    return SimpleNamespace(
        snapshot=snapshot,
        descriptor=PluginGenerationDescriptorV2(
            profile_id=snapshot.profile_id,
            generation=snapshot.generation,
            digest=snapshot.digest,
        ),
        fibers=(SimpleNamespace(entry=active_entry, phase=FiberPhaseV2.ACTIVE),),
    )


async def test_plugin_manager_list_reads_pinned_v2_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = _generation()
    monkeypatch.setattr(boundary, "current_generation_v2", lambda: generation)

    result = await plugin_manager.plugin_manager_tool.execute(_make_ctx(), action="list")

    assert result.is_error is False
    assert result.title == "Plugin runtime status"
    assert result.metadata["protocol_version"] == 2
    assert result.metadata["generation"] == {
        "profile_id": "profile-v2",
        "generation": 42,
        "digest": "a" * 64,
    }
    assert result.metadata["plugins"] == [
        {
            "plugin_id": "demo-plugin",
            "version": "2.1.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "declared_modules": [
                "builtin://demo/active",
                "builtin://demo/disabled",
            ],
            "active_modules": ["builtin://demo/active"],
            "active_entries": [
                {
                    "entry_id": "demo-active",
                    "module_ref": "builtin://demo/active",
                    "phase": "active",
                }
            ],
        },
        {
            "plugin_id": "dormant-plugin",
            "version": "3.0.0",
            "runtime": "wasm",
            "trust": "signed",
            "declared_modules": ["builtin://dormant/runtime"],
            "active_modules": [],
            "active_entries": [],
        },
    ]
    assert "profile-v2@42" in result.output
    assert "demo-plugin 2.1.0" in result.output
    assert "dormant-plugin 3.0.0" in result.output


async def test_plugin_manager_list_fails_when_generation_is_not_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _not_pinned() -> None:
        raise RuntimeV2Error(
            "generation_not_pinned",
            "plugin generation is not pinned to the current operation",
        )

    monkeypatch.setattr(boundary, "current_generation_v2", _not_pinned)

    result = await plugin_manager.plugin_manager_tool.execute(_make_ctx(), action="list")

    assert result.is_error is True
    assert result.title == "Plugin Manager Failed"
    assert result.metadata == {
        "action": "list",
        "error": "plugin generation is not pinned to the current operation",
        "error_code": "generation_not_pinned",
        "protocol_version": 2,
    }


@pytest.mark.parametrize("action", ["install", "enable", "disable", "reload", "uninstall"])
async def test_plugin_manager_rejects_frozen_v1_mutations(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    def manager_boundary() -> None:
        pytest.fail("mutation must not inspect the current generation")

    monkeypatch.setattr(boundary, "current_generation_v2", manager_boundary)

    result = await plugin_manager.plugin_manager_tool.execute(
        _make_ctx(),
        action=action,
        requirement="demo-package",
        plugin_name="demo-plugin",
    )

    assert result.is_error is True
    assert result.metadata["error_code"] == "plugin_protocol_v1_mutation_frozen"
    assert result.metadata["migration_target"] == "/api/v1/plugin-marketplace"


async def test_plugin_manager_rejects_unsupported_action() -> None:
    result = await plugin_manager.plugin_manager_tool.execute(_make_ctx(), action="inspect")

    assert result.is_error is True
    assert result.metadata["error"] == "Unsupported action: inspect"


def test_configure_plugin_manager_is_compatibility_noop() -> None:
    plugin_manager.configure_plugin_manager(
        tenant_id="tenant-1",
        project_id="project-1",
        mutation_ledger=object(),
        mutation_loop_threshold=1,
        mutation_loop_window_seconds=1,
    )


def test_plugin_manager_source_has_no_v1_runtime_or_mutation_lifecycle() -> None:
    source = inspect.getsource(plugin_manager)

    forbidden = (
        "get_plugin_runtime_manager",
        "build_plugin_reload_plan",
        "MutationTransaction",
        "SelfModifyingLifecycleOrchestrator",
        "_pm_handle_install",
        "_pm_handle_enable_disable",
        "_pm_handle_uninstall",
        "_pm_handle_reload",
    )
    assert not [name for name in forbidden if name in source]
