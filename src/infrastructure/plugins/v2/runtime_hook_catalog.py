"""Read-only runtime-hook catalog projected from one active V2 generation."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from .agent_events import (
    AGENT_BEFORE_REQUEST_EVENT_V2,
    AGENT_SESSION_START_EVENT_V2,
    TOOLS_AFTER_EXECUTE_EVENT_V2,
)
from .runtime import RuntimeGenerationV2, RuntimeV2Error
from .sisyphus_runtime import (
    SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2,
    SISYPHUS_BEFORE_REQUEST_MODULE_V2,
    SISYPHUS_SESSION_START_MODULE_V2,
)
from .workspace_runtime import (
    WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2,
    WORKSPACE_BEFORE_REQUEST_MODULE_V2,
    WORKSPACE_SESSION_START_MODULE_V2,
)


@dataclass(frozen=True, kw_only=True)
class RuntimeHookCatalogEntryV2:
    """Public metadata for one activated, contract-backed lifecycle module."""

    module_ref: str
    plugin_name: str
    hook_name: str
    event: str
    hook_family: str
    display_name: str
    description: str
    default_priority: int
    default_settings: dict[str, Any]
    settings_schema: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class _RuntimeHookCatalogSpecV2:
    plugin_name: str
    hook_name: str
    event: str
    hook_family: str
    display_name: str
    description: str
    default_priority: int


_SPECS_V2: Final = MappingProxyType(
    {
        SISYPHUS_SESSION_START_MODULE_V2: _RuntimeHookCatalogSpecV2(
            plugin_name="sisyphus-runtime",
            hook_name="on_session_start",
            event=AGENT_SESSION_START_EVENT_V2,
            hook_family="mutating",
            display_name="Sisyphus session start",
            description="Contributes the active Sisyphus session instructions.",
            default_priority=20,
        ),
        SISYPHUS_BEFORE_REQUEST_MODULE_V2: _RuntimeHookCatalogSpecV2(
            plugin_name="sisyphus-runtime",
            hook_name="before_response",
            event=AGENT_BEFORE_REQUEST_EVENT_V2,
            hook_family="mutating",
            display_name="Sisyphus before response",
            description="Contributes the active Sisyphus response instructions.",
            default_priority=30,
        ),
        SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2: _RuntimeHookCatalogSpecV2(
            plugin_name="sisyphus-runtime",
            hook_name="after_tool_execution",
            event=TOOLS_AFTER_EXECUTE_EVENT_V2,
            hook_family="mutating",
            display_name="Sisyphus after tool execution",
            description="Contributes the active Sisyphus tool follow-up instructions.",
            default_priority=40,
        ),
        WORKSPACE_SESSION_START_MODULE_V2: _RuntimeHookCatalogSpecV2(
            plugin_name="workspace-runtime",
            hook_name="on_session_start",
            event=AGENT_SESSION_START_EVENT_V2,
            hook_family="mutating",
            display_name="Workspace session start",
            description="Contributes generation-owned Workspace session instructions.",
            default_priority=15,
        ),
        WORKSPACE_BEFORE_REQUEST_MODULE_V2: _RuntimeHookCatalogSpecV2(
            plugin_name="workspace-runtime",
            hook_name="before_response",
            event=AGENT_BEFORE_REQUEST_EVENT_V2,
            hook_family="mutating",
            display_name="Workspace before response",
            description="Contributes generation-owned Workspace response instructions.",
            default_priority=15,
        ),
        WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2: _RuntimeHookCatalogSpecV2(
            plugin_name="workspace-runtime",
            hook_name="after_tool_execution",
            event=TOOLS_AFTER_EXECUTE_EVENT_V2,
            hook_family="mutating",
            display_name="Workspace after tool execution",
            description="Contributes generation-owned Workspace tool follow-up instructions.",
            default_priority=15,
        ),
    }
)


def runtime_hook_catalog_v2(
    generation: RuntimeGenerationV2,
) -> tuple[RuntimeHookCatalogEntryV2, ...]:
    """Return catalog rows only for lifecycle Fibers active in ``generation``."""
    result: list[RuntimeHookCatalogEntryV2] = []
    for fiber in generation.fibers:
        spec = _SPECS_V2.get(fiber.entry.module_ref)
        if spec is None:
            continue
        handled_events = tuple(contract.event for contract in fiber.contract.events.handles)
        if handled_events != (spec.event,):
            raise RuntimeV2Error(
                "runtime_hook_contract_mismatch",
                f"module {fiber.entry.module_ref} does not handle only {spec.event}",
            )
        result.append(
            RuntimeHookCatalogEntryV2(
                module_ref=fiber.entry.module_ref,
                plugin_name=spec.plugin_name,
                hook_name=spec.hook_name,
                event=spec.event,
                hook_family=spec.hook_family,
                display_name=spec.display_name,
                description=spec.description,
                default_priority=spec.default_priority,
                default_settings=dict(fiber.entry.config),
                settings_schema=dict(fiber.contract.config_schema),
            )
        )
    return tuple(result)


__all__ = ["RuntimeHookCatalogEntryV2", "runtime_hook_catalog_v2"]
