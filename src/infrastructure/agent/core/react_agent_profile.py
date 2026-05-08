# pyright: reportUninitializedInstanceVariable=false
"""Runtime profile + helper functions extracted from ``react_agent.py``.

This module owns:

* ``AgentRuntimeProfile`` — the request-scoped profile snapshot used
  throughout :class:`ReActAgent`.
* The provider-name normalization helpers.
* ``_register_selected_agent_session`` — best-effort session registry call.
* The workspace tool-name allow-lists (used by tool-policy filtering).

Kept as a sibling module of ``react_agent.py`` (PR-7a phase 1) so the
500+ lines of constants and helpers stop bloating the main file. No
behavioural change — every symbol is re-exported from ``react_agent``
for backward compatibility.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.model.agent.agent_definition import Agent
    from src.domain.model.agent.skill import Skill
    from src.domain.model.agent.tenant_agent_config import TenantAgentConfig

logger = logging.getLogger(__name__)

_MODEL_PROVIDER_ALIASES: dict[str, str] = {
    "azure_openai": "openai",
}

_WORKSPACE_WORKER_CODE_TOOL_NAMES: tuple[str, ...] = (
    "read",
    "write",
    "edit",
    "bash",
    "glob",
    "grep",
)

_WORKSPACE_WORKER_REPORT_TOOL_NAMES: tuple[str, ...] = (
    "workspace_report_progress",
    "workspace_report_complete",
    "workspace_report_blocked",
    "workspace_request_clarification",
    "workspace_health_verdict",
    "workspace_submit_planning_contract",
)

_WORKSPACE_WORKER_DENIED_TOOL_NAMES: tuple[str, ...] = (
    "plugin_tool_exec",
)

_WORKSPACE_LEADER_REPLAN_TOOL_NAMES: tuple[str, ...] = (
    "todoread",
    "todowrite",
)


@dataclass(frozen=True)
class AgentRuntimeProfile:
    """Request-scoped runtime profile derived from selected agent + tenant config."""

    selected_agent: Agent | None
    tenant_agent_config: TenantAgentConfig
    available_skills: list[Skill]
    allow_tools: list[str]
    deny_tools: list[str]
    effective_model: str
    effective_temperature: float
    effective_max_tokens: int
    effective_max_steps: int
    primary_agent_prompt: str | None = None
    agent_definition_prompt: str | None = None


def _normalize_model_provider(provider: str | None) -> str | None:
    """Normalize provider identifiers for cross-surface comparisons."""
    if provider is None:
        return None
    normalized = provider.strip().lower()
    if not normalized:
        return None
    if normalized.endswith("_coding"):
        normalized = normalized.removesuffix("_coding")
    return _MODEL_PROVIDER_ALIASES.get(normalized, normalized)


def _infer_provider_from_model_name(model_name: str | None) -> str | None:
    """Infer provider from explicit ``<provider>/<model>`` naming."""
    if model_name is None:
        return None
    normalized_model = model_name.strip()
    if not normalized_model or "/" not in normalized_model:
        return None
    provider_part = normalized_model.split("/", 1)[0]
    return _normalize_model_provider(provider_part)


async def _register_selected_agent_session(
    *,
    conversation_id: str,
    project_id: str,
    selected_agent_id: str,
) -> None:
    """Best-effort registration of the resolved agent owning a conversation."""
    try:
        from src.infrastructure.agent.state.agent_worker_state import get_agent_orchestrator

        orchestrator = get_agent_orchestrator()
        if orchestrator is None:
            return
        session_registry = getattr(orchestrator, "_session_registry", None)
        if session_registry is None:
            return
        await session_registry.register(
            agent_id=selected_agent_id,
            conversation_id=conversation_id,
            project_id=project_id,
        )
    except Exception:
        logger.warning(
            "[ReActAgent] Failed to register selected agent session: agent=%s conversation=%s "
            "project=%s",
            selected_agent_id,
            conversation_id,
            project_id,
            exc_info=True,
        )


__all__ = [
    "_MODEL_PROVIDER_ALIASES",
    "_WORKSPACE_LEADER_REPLAN_TOOL_NAMES",
    "_WORKSPACE_WORKER_CODE_TOOL_NAMES",
    "_WORKSPACE_WORKER_REPORT_TOOL_NAMES",
    "AgentRuntimeProfile",
    "_infer_provider_from_model_name",
    "_normalize_model_provider",
    "_register_selected_agent_session",
]
