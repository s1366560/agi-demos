"""Pinned-generation V2 plugin inventory with retired legacy mutations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.plugins.v1_retirement import (
    PLUGIN_MARKETPLACE_V2_PATH,
    PLUGIN_PROTOCOL_V1_RETIRED_CODE,
)
from src.infrastructure.plugins.v2.runtime_context import FiberPhaseV2, RuntimeV2Error

if TYPE_CHECKING:
    from src.infrastructure.plugins.v2.runtime import RuntimeGenerationV2

TOOL_NAME = "plugin_manager"


def _current_generation_v2() -> RuntimeGenerationV2:
    """Load the boundary lazily so agent tool discovery cannot create an import cycle."""
    from src.infrastructure.plugins.v2.boundary import current_generation_v2

    return current_generation_v2()


def _inventory_v2(generation: RuntimeGenerationV2) -> list[dict[str, Any]]:
    """Project manifest declarations and active fibers from one immutable generation."""
    active_entries_by_plugin: dict[str, list[dict[str, str]]] = {}
    for fiber in generation.fibers:
        if fiber.phase is not FiberPhaseV2.ACTIVE:
            continue
        active_entries_by_plugin.setdefault(fiber.entry.plugin_ref, []).append(
            {
                "entry_id": fiber.entry.entry_id,
                "module_ref": fiber.entry.module_ref,
                "phase": fiber.phase.value,
            }
        )

    inventory: list[dict[str, Any]] = []
    for manifest in generation.snapshot.manifests:
        active_entries = active_entries_by_plugin.get(manifest.plugin_id, [])
        active_module_refs = {entry["module_ref"] for entry in active_entries}
        declared_modules = [module.module_ref for module in manifest.modules]
        inventory.append(
            {
                "plugin_id": manifest.plugin_id,
                "version": manifest.version,
                "runtime": manifest.runtime.value,
                "trust": manifest.trust.value,
                "declared_modules": declared_modules,
                "active_modules": [
                    module_ref
                    for module_ref in declared_modules
                    if module_ref in active_module_refs
                ],
                "active_entries": active_entries,
            }
        )
    return inventory


def _format_inventory_v2(
    generation: RuntimeGenerationV2,
    plugins: list[dict[str, Any]],
) -> str:
    descriptor = generation.descriptor
    lines = [
        (
            f"Pinned V2 plugin generation {descriptor.profile_id}@{descriptor.generation} "
            f"digest={descriptor.digest}"
        )
    ]
    for plugin in plugins:
        declared = ", ".join(plugin["declared_modules"]) or "-"
        active = ", ".join(plugin["active_modules"]) or "-"
        lines.extend(
            (
                (
                    f"- {plugin['plugin_id']} {plugin['version']} "
                    f"[{plugin['runtime']}/{plugin['trust']}]"
                ),
                f"  declared modules: {declared}",
                f"  active modules: {active}",
            )
        )
    return "\n".join(lines)


def _pm_handle_list(ctx: ToolContext) -> ToolResult:
    """Return inventory from the generation pinned to this tool operation."""
    _ = ctx
    try:
        generation = _current_generation_v2()
    except RuntimeV2Error as exc:
        return ToolResult(
            output=f"Error: {exc}",
            is_error=True,
            title="Plugin Manager Failed",
            metadata={
                "action": "list",
                "error": str(exc),
                "error_code": exc.code,
                "protocol_version": 2,
            },
        )

    plugins = _inventory_v2(generation)
    return ToolResult(
        output=_format_inventory_v2(generation, plugins),
        title="Plugin runtime status",
        metadata={
            "action": "list",
            "protocol_version": 2,
            "generation": generation.descriptor.to_payload(),
            "plugins": plugins,
        },
    )


def _pm_v1_retired(action: str) -> ToolResult:
    return ToolResult(
        output=f"Error: plugin protocol V1 is retired; use {PLUGIN_MARKETPLACE_V2_PATH}",
        is_error=True,
        title="Plugin Protocol V1 Retired",
        metadata={
            "action": action,
            "error_code": PLUGIN_PROTOCOL_V1_RETIRED_CODE,
            "migration_target": PLUGIN_MARKETPLACE_V2_PATH,
        },
    )


@tool_define(
    name="plugin_manager",
    description=(
        "List plugins and active modules from the V2 generation pinned to this operation. "
        "Legacy install, enable, disable, reload, and uninstall actions return a migration "
        "error; mutate DesiredBundleSetV2 through the V2 plugin marketplace instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "install", "enable", "disable", "reload", "uninstall"],
                "description": "Read with list; legacy mutation actions are retired. Default: list",
            },
            "requirement": {
                "type": "string",
                "description": "Retained only to return the V1 retirement error.",
            },
            "plugin_name": {
                "type": "string",
                "description": "Retained only to return the V1 retirement error.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Retained only to return the V1 retirement error.",
            },
        },
        "required": [],
    },
    permission="plugin_manager",
    category="plugin",
    tags=frozenset({"plugin", "inventory"}),
)
async def plugin_manager_tool(
    ctx: ToolContext,
    *,
    action: str = "list",
    requirement: str = "",
    plugin_name: str = "",
    dry_run: bool | str = False,
) -> ToolResult:
    """Read V2 inventory and reject every legacy mutation action."""
    _ = (requirement, plugin_name, dry_run)
    action = str(action).strip().lower() or "list"

    if action == "list":
        return _pm_handle_list(ctx)

    if action in {"install", "enable", "disable", "reload", "uninstall"}:
        return _pm_v1_retired(action)

    return ToolResult(
        output=f"Error: Unsupported action: {action}",
        is_error=True,
        title="Plugin Manager Failed",
        metadata={"action": "error", "error": f"Unsupported action: {action}"},
    )


__all__ = ["TOOL_NAME", "plugin_manager_tool"]
