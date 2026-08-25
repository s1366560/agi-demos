"""Generation-owned Agent lifecycle notification service and typed event handlers."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable

from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

logger = logging.getLogger(__name__)

AGENT_LIFECYCLE_NOTIFIER_MODULE_V2 = "builtin://memstack/agent/lifecycle-notifier"
AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2 = "service:agent.lifecycle-notifier"
AGENT_LIFECYCLE_CHANGED_EVENT_V2 = "agent.lifecycle.changed"
AGENT_SUBAGENT_LIFECYCLE_EVENT_V2 = "agent.subagent.lifecycle"


class AgentLifecycleConnectionManagerV2(Protocol):
    """The local data-plane capability used by typed lifecycle event handlers."""

    async def broadcast_to_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
        message: dict[str, Any],
    ) -> int: ...


@runtime_checkable
class AgentLifecycleNotifierProtocolV2(Protocol):
    """Stable consumer surface injected into the generation-owned Agent loop."""

    async def notify_initializing(self, tenant_id: str, project_id: str) -> int: ...

    async def notify_ready(
        self,
        tenant_id: str,
        project_id: str,
        tool_count: int = 0,
        builtin_tool_count: int = 0,
        mcp_tool_count: int = 0,
        skill_count: int = 0,
        total_skill_count: int = 0,
        loaded_skill_count: int = 0,
        subagent_count: int = 0,
    ) -> int: ...

    async def notify_executing(
        self,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
    ) -> int: ...

    async def notify_paused(self, tenant_id: str, project_id: str) -> int: ...

    async def notify_shutting_down(self, tenant_id: str, project_id: str) -> int: ...

    async def notify_error(
        self,
        tenant_id: str,
        project_id: str,
        error_message: str,
    ) -> int: ...

    async def notify_subagent_lifecycle_event(
        self,
        tenant_id: str,
        project_id: str,
        event: dict[str, Any],
    ) -> int: ...


@dataclass(frozen=True, kw_only=True)
class AgentLifecycleNotifierV2:
    """Dispatch lifecycle changes through the declaring V2 module context."""

    context: ContextV2

    async def notify_initializing(self, tenant_id: str, project_id: str) -> int:
        return await self._notify_lifecycle(
            tenant_id=tenant_id,
            project_id=project_id,
            lifecycle_state="initializing",
            is_initialized=False,
            is_active=False,
        )

    async def notify_ready(
        self,
        tenant_id: str,
        project_id: str,
        tool_count: int = 0,
        builtin_tool_count: int = 0,
        mcp_tool_count: int = 0,
        skill_count: int = 0,
        total_skill_count: int = 0,
        loaded_skill_count: int = 0,
        subagent_count: int = 0,
    ) -> int:
        return await self._notify_lifecycle(
            tenant_id=tenant_id,
            project_id=project_id,
            lifecycle_state="ready",
            is_initialized=True,
            is_active=True,
            tool_count=tool_count,
            builtin_tool_count=builtin_tool_count,
            mcp_tool_count=mcp_tool_count,
            skill_count=skill_count,
            total_skill_count=total_skill_count,
            loaded_skill_count=loaded_skill_count,
            subagent_count=subagent_count,
        )

    async def notify_executing(
        self,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
    ) -> int:
        return await self._notify_lifecycle(
            tenant_id=tenant_id,
            project_id=project_id,
            lifecycle_state="executing",
            is_initialized=True,
            is_active=True,
            conversation_id=conversation_id,
        )

    async def notify_paused(self, tenant_id: str, project_id: str) -> int:
        return await self._notify_lifecycle(
            tenant_id=tenant_id,
            project_id=project_id,
            lifecycle_state="paused",
            is_initialized=True,
            is_active=False,
        )

    async def notify_shutting_down(self, tenant_id: str, project_id: str) -> int:
        return await self._notify_lifecycle(
            tenant_id=tenant_id,
            project_id=project_id,
            lifecycle_state="shutting_down",
            is_initialized=False,
            is_active=False,
        )

    async def notify_error(
        self,
        tenant_id: str,
        project_id: str,
        error_message: str,
    ) -> int:
        return await self._notify_lifecycle(
            tenant_id=tenant_id,
            project_id=project_id,
            lifecycle_state="error",
            is_initialized=False,
            is_active=False,
            error_message=error_message,
        )

    async def notify_subagent_lifecycle_event(
        self,
        tenant_id: str,
        project_id: str,
        event: dict[str, Any],
    ) -> int:
        return await self._dispatch_count(
            AGENT_SUBAGENT_LIFECYCLE_EVENT_V2,
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "event": dict(event),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def _notify_lifecycle(  # noqa: PLR0913
        self,
        *,
        tenant_id: str,
        project_id: str,
        lifecycle_state: str,
        is_initialized: bool,
        is_active: bool,
        tool_count: int = 0,
        builtin_tool_count: int = 0,
        mcp_tool_count: int = 0,
        skill_count: int = 0,
        total_skill_count: int = 0,
        loaded_skill_count: int = 0,
        subagent_count: int = 0,
        conversation_id: str | None = None,
        error_message: str | None = None,
    ) -> int:
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "lifecycle_state": lifecycle_state,
            "is_initialized": is_initialized,
            "is_active": is_active,
            "tool_count": tool_count,
            "builtin_tool_count": builtin_tool_count,
            "mcp_tool_count": mcp_tool_count,
            "skill_count": skill_count,
            "total_skill_count": total_skill_count,
            "loaded_skill_count": loaded_skill_count,
            "subagent_count": subagent_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        if error_message is not None:
            payload["error_message"] = error_message
        return await self._dispatch_count(AGENT_LIFECYCLE_CHANGED_EVENT_V2, payload)

    async def _dispatch_count(self, event: str, payload: dict[str, Any]) -> int:
        results = await self.context.dispatch(event, payload)
        if not isinstance(results, tuple):
            raise RuntimeV2Error(
                "invalid_agent_lifecycle_notification_result",
                f"event {event} did not return emit results",
            )
        emitted_results = cast("tuple[object, ...]", results)
        if any(isinstance(item, bool) or not isinstance(item, int) for item in emitted_results):
            raise RuntimeV2Error(
                "invalid_agent_lifecycle_notification_result",
                f"event {event} did not return integer emit results",
            )
        return sum(cast("tuple[int, ...]", emitted_results))


def agent_lifecycle_notifier_definition_v2(
    connection_manager: AgentLifecycleConnectionManagerV2 | None = None,
) -> PluginDefinitionV2:
    """Bind the target-local broadcaster to a reversible generation Fiber."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "typed-event-broadcast":
            raise ValueError("agent lifecycle notifier requires typed-event-broadcast strategy")

        async def broadcast_lifecycle(payload: object) -> int:
            row = cast("Mapping[str, Any]", payload)
            data = {
                "lifecycle_state": row["lifecycle_state"],
                "is_initialized": row["is_initialized"],
                "is_active": row["is_active"],
                "tool_count": row["tool_count"],
                "builtin_tool_count": row["builtin_tool_count"],
                "mcp_tool_count": row["mcp_tool_count"],
                "skill_count": row["skill_count"],
                "total_skill_count": row["total_skill_count"],
                "loaded_skill_count": row["loaded_skill_count"],
                "subagent_count": row["subagent_count"],
            }
            for optional in ("conversation_id", "error_message"):
                if optional in row:
                    data[optional] = row[optional]
            return await _broadcast_to_project(
                connection_manager,
                tenant_id=cast("str", row["tenant_id"]),
                project_id=cast("str", row["project_id"]),
                message={
                    "type": "lifecycle_state_change",
                    "tenant_id": row["tenant_id"],
                    "project_id": row["project_id"],
                    "data": data,
                    "timestamp": row["timestamp"],
                },
            )

        async def broadcast_subagent_lifecycle(payload: object) -> int:
            row = cast("Mapping[str, Any]", payload)
            return await _broadcast_to_project(
                connection_manager,
                tenant_id=cast("str", row["tenant_id"]),
                project_id=cast("str", row["project_id"]),
                message={
                    "type": "subagent_lifecycle",
                    "tenant_id": row["tenant_id"],
                    "project_id": row["project_id"],
                    "data": dict(cast("Mapping[str, Any]", row["event"])),
                    "timestamp": row["timestamp"],
                },
            )

        _ = context.on(AGENT_LIFECYCLE_CHANGED_EVENT_V2, broadcast_lifecycle)
        _ = context.on(AGENT_SUBAGENT_LIFECYCLE_EVENT_V2, broadcast_subagent_lifecycle)
        _ = context.provide(
            AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2,
            AgentLifecycleNotifierV2(context=context),
            label="agent-lifecycle-notifier",
        )

    return PluginDefinitionV2(
        module_ref=AGENT_LIFECYCLE_NOTIFIER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_LIFECYCLE_NOTIFIER_MODULE_V2),
        apply=apply,
    )


async def _broadcast_to_project(
    connection_manager: AgentLifecycleConnectionManagerV2 | None,
    *,
    tenant_id: str,
    project_id: str,
    message: dict[str, Any],
) -> int:
    if connection_manager is None:
        return 0
    try:
        return await connection_manager.broadcast_to_project(
            tenant_id=tenant_id,
            project_id=project_id,
            message=message,
        )
    except Exception:
        logger.exception(
            "Failed to broadcast Agent lifecycle event for tenant=%s project=%s",
            tenant_id,
            project_id,
        )
        return 0


__all__ = [
    "AGENT_LIFECYCLE_CHANGED_EVENT_V2",
    "AGENT_LIFECYCLE_NOTIFIER_MODULE_V2",
    "AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2",
    "AGENT_SUBAGENT_LIFECYCLE_EVENT_V2",
    "AgentLifecycleConnectionManagerV2",
    "AgentLifecycleNotifierProtocolV2",
    "AgentLifecycleNotifierV2",
    "agent_lifecycle_notifier_definition_v2",
]
