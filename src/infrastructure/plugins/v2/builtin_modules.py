"""Trusted builtin module definitions for the first production v2 generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .agent_definition import builtin_agent_definition_v2
from .agent_loop import builtin_agent_loop_definition_v2
from .runtime import ContextV2, PluginDefinitionV2
from .session_event_log import builtin_session_event_log_definition_v2
from .system_prompt import builtin_system_prompt_definition_v2
from .tool_set import builtin_tool_set_definition_v2

RUNTIME_BOUNDARY_MODULE_V2 = "builtin://memstack/runtime/generation-boundary"
RUNTIME_BOUNDARY_SERVICE_V2 = "service:runtime-generation-boundary"


@dataclass(frozen=True, kw_only=True)
class RuntimeBoundaryServiceV2:
    """Marker resolved by data-plane boundaries from their pinned generation."""

    protocol_version: int
    owner_entry_id: str


def _apply_runtime_boundary(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    protocol_version = config.get("protocol_version")
    if protocol_version != 2:
        raise ValueError("runtime generation boundary requires protocol_version 2")
    context.provide(
        RUNTIME_BOUNDARY_SERVICE_V2,
        RuntimeBoundaryServiceV2(
            protocol_version=protocol_version,
            owner_entry_id=context.entry_id,
        ),
        label="runtime-generation-boundary",
    )


def builtin_runtime_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return deterministic, repository-owned definitions allowed in-process."""
    return (
        PluginDefinitionV2(
            module_ref=RUNTIME_BOUNDARY_MODULE_V2,
            apply=_apply_runtime_boundary,
            provides=(RUNTIME_BOUNDARY_SERVICE_V2,),
        ),
        builtin_agent_loop_definition_v2(),
        builtin_system_prompt_definition_v2(),
        builtin_tool_set_definition_v2(),
        builtin_agent_definition_v2(),
        builtin_session_event_log_definition_v2(),
    )
