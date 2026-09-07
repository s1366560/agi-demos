"""Generation-owned lifecycle service for Skill-embedded MCP servers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.agent.mcp.skill_mcp_manager import SkillMCPManager

from .runtime import ContextV2, PluginDefinitionV2, generated_contract_digest_v2

SKILL_MCP_MANAGER_MODULE_V2 = "builtin://memstack/agent/skill-mcp-manager"
SKILL_MCP_MANAGER_SERVICE_V2 = "service:agent.skill-mcp-manager"


def _apply_skill_mcp_manager_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> Callable[[], Awaitable[None]]:
    if config:
        raise ValueError("Skill MCP manager does not accept config")
    manager = SkillMCPManager()
    _ = context.provide(
        SKILL_MCP_MANAGER_SERVICE_V2,
        manager,
        label="skill-mcp-manager",
    )
    return manager.shutdown


def builtin_skill_mcp_manager_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=SKILL_MCP_MANAGER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SKILL_MCP_MANAGER_MODULE_V2),
        apply=_apply_skill_mcp_manager_v2,
    )


__all__ = [
    "SKILL_MCP_MANAGER_MODULE_V2",
    "SKILL_MCP_MANAGER_SERVICE_V2",
    "builtin_skill_mcp_manager_definition_v2",
]
