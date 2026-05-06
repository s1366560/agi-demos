"""Agent tool: trigger a reflection cycle for the current project.

Wraps ``ReflectionService.reflect_window`` so a planner agent can ask the
system to inspect recent friction signals and (via the configured
``ReflectorPort``) propose / reinforce / deprecate playbooks.

Per Agent-First: the agent is the *trigger*. The *verdicts* still come from
the LLM-backed ``ReflectorPort`` inside the service — this tool never
fabricates a verdict.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.application.services.reflection_service import ReflectionService
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


ReflectionServiceProvider = Callable[[str], Awaitable[ReflectionService | None]]


_provider: ReflectionServiceProvider | None = None


def configure_reflection_tool(provider: ReflectionServiceProvider) -> None:
    """Inject a per-project ``ReflectionService`` factory at startup.

    Mirrors the ``configure_cron_tool`` pattern. Pass a coroutine that takes
    a ``project_id`` and returns a fully-built ``ReflectionService`` (or
    ``None`` if reflection is unavailable in this deployment).
    """
    global _provider
    _provider = provider


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


@tool_define(
    name="reflect_friction",
    description=(
        "Run the friction → playbook reflection loop for the current project. "
        "Inspects recent friction signals (task bounces, blocked tasks, retries) "
        "and asks the configured Reflector to create / reinforce / deprecate "
        "playbooks. Returns the list of applied verdicts. "
        "Idempotent within the configured window — safe to call repeatedly."
    ),
    parameters={
        "type": "object",
        "properties": {},
    },
    permission=None,
    category="reflection",
)
async def reflect_friction_tool(ctx: ToolContext) -> ToolResult:
    """Trigger one reflection cycle for ``ctx.project_id``."""
    project_id = ctx.project_id
    if not project_id:
        return ToolResult(
            output=_json({"error": "No project_id in context"}),
            is_error=True,
        )
    if _provider is None:
        return ToolResult(
            output=_json(
                {"error": "reflection tool not configured; call configure_reflection_tool()"}
            ),
            is_error=True,
        )

    try:
        service = await _provider(project_id)
    except Exception as exc:
        logger.exception("reflect_friction: provider failed for %s", project_id)
        return ToolResult(
            output=_json({"error": f"Failed to build reflection service: {exc}"}),
            is_error=True,
        )

    if service is None:
        return ToolResult(
            output=_json({"status": "unavailable", "verdicts": []}),
        )

    try:
        verdicts = await service.reflect_window(project_id)
    except Exception as exc:
        logger.exception("reflect_friction: reflect_window failed for %s", project_id)
        return ToolResult(
            output=_json({"error": f"Reflection failed: {exc}"}),
            is_error=True,
        )

    return ToolResult(
        output=_json(
            {
                "project_id": project_id,
                "applied_count": len(verdicts),
                "verdicts": [
                    {
                        "action": v.action.value,
                        "playbook_id": v.playbook_id,
                        "rationale": v.rationale,
                        "proposed_name": (v.proposed_playbook or {}).get("name")
                        if v.proposed_playbook
                        else None,
                    }
                    for v in verdicts
                ],
            }
        ),
    )


__all__ = ["configure_reflection_tool", "reflect_friction_tool"]
