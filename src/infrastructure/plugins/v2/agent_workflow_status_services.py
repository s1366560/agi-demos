"""Generation-owned application seam for Agent workflow status."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast, runtime_checkable

from src.infrastructure.agent.actor.types import ProjectAgentStatus

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    generated_contract_digest_v2,
)

AGENT_WORKFLOW_STATUS_MODULE_V2 = "builtin://memstack/application/agent-workflow-status"
AGENT_WORKFLOW_STATUS_SERVICE_V2 = "service:application.agent-workflow-status"


@dataclass(frozen=True, kw_only=True)
class AgentWorkflowStatusStateV2:
    """Transport-neutral workflow status returned by the application service."""

    workflow_id: str
    status: str
    started_at: datetime | None


@runtime_checkable
class AgentWorkflowStatusServiceProtocolV2(Protocol):
    """Resolve the active workflow status for one project Agent actor."""

    async def get_status(
        self,
        *,
        tenant_id: str,
        project_id: str,
        agent_mode: str,
    ) -> AgentWorkflowStatusStateV2 | None: ...


def _status_text(raw_status: ProjectAgentStatus) -> str:
    if bool(getattr(raw_status, "is_executing", False)):
        return "RUNNING"
    if bool(getattr(raw_status, "is_initialized", False)):
        return "IDLE"
    return "UNINITIALIZED"


def _started_at(raw_status: ProjectAgentStatus) -> datetime | None:
    value = getattr(raw_status, "created_at", None)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True, kw_only=True)
class RayAgentWorkflowStatusServiceV2:
    """Query Ray through the explicit generation-owned application seam."""

    async def get_status(
        self,
        *,
        tenant_id: str,
        project_id: str,
        agent_mode: str,
    ) -> AgentWorkflowStatusStateV2 | None:
        from src.infrastructure.adapters.secondary.ray.client import await_ray
        from src.infrastructure.agent.actor.actor_manager import get_actor_if_exists

        actor = await get_actor_if_exists(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
        )
        if actor is None:
            return None

        raw_status = cast(ProjectAgentStatus, await await_ray(actor.status.remote()))
        return AgentWorkflowStatusStateV2(
            workflow_id=str(raw_status.actor_id),
            status=_status_text(raw_status),
            started_at=_started_at(raw_status),
        )


def _apply_agent_workflow_status_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "ray-actor-status":
        raise ValueError("Agent workflow status requires strategy ray-actor-status")
    _ = context.provide(
        AGENT_WORKFLOW_STATUS_SERVICE_V2,
        RayAgentWorkflowStatusServiceV2(),
        label="agent-workflow-status",
    )


def agent_workflow_status_definition_v2() -> PluginDefinitionV2:
    """Return the Agent workflow-status application definition."""
    return PluginDefinitionV2(
        module_ref=AGENT_WORKFLOW_STATUS_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_WORKFLOW_STATUS_MODULE_V2),
        apply=_apply_agent_workflow_status_v2,
    )


__all__ = [
    "AGENT_WORKFLOW_STATUS_MODULE_V2",
    "AGENT_WORKFLOW_STATUS_SERVICE_V2",
    "AgentWorkflowStatusServiceProtocolV2",
    "AgentWorkflowStatusStateV2",
    "RayAgentWorkflowStatusServiceV2",
    "agent_workflow_status_definition_v2",
]
