"""Project a conversation's authorized history into the selected statistics implementation."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from plugins.business.agent.execution_statistics.aggregate import summarize
from src.configuration.config import get_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.host.packages.project_plugin_installation import ProjectPluginInstallationService
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    project_package_actor_can_execute,
)
from src.infrastructure.plugins.package_registry import load_plugin_trust_keys
from src.infrastructure.plugins.v2.project_package_execution import invoke_project_tool
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedPackageBytesV2,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.infrastructure.adapters.secondary.persistence.models import Conversation, User


@dataclass
class StatisticsInput:
    rows: list[list[int | None]]
    statuses: list[str]
    tools: list[str]


def _facts(executions: list[dict[str, Any]]) -> StatisticsInput:
    statuses = {"COMPLETED": 0, "FAILED": 1, "completed": 2, "failed": 3}
    tools: dict[str, int] = {}
    rows: list[list[int | None]] = []
    for execution in executions:
        status = statuses.setdefault(execution.get("status", "UNKNOWN"), len(statuses))
        name = execution.get("tool_name")
        tool = tools.setdefault(name, len(tools)) if name else None
        started = execution.get("started_at")
        ended = execution.get("completed_at")
        minute = None
        duration_us = None
        if started:
            start = datetime.fromisoformat(started.replace("Z", "+00:00"))
            minute = (start.toordinal() - 1) * 1440 + start.hour * 60 + start.minute
            if ended:
                delta = datetime.fromisoformat(ended.replace("Z", "+00:00")) - start
                duration_us = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
        rows.append([status, tool, minute, duration_us])
    return StatisticsInput(rows, list(statuses), list(tools))


def _counts(raw: list[list[int]], labels: list[str], total: int) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, count in raw:
        if (
            type(index) is not int
            or not 0 <= index < len(labels)
            or type(count) is not int
            or not 1 <= count <= total
            or labels[index] in result
        ):
            raise ValueError("invalid statistics count")
        result[labels[index]] = count
    return result


def _response(facts: StatisticsInput, projection: dict[str, Any]) -> dict[str, Any]:
    total = len(facts.rows)
    for key in ("completed_count", "failed_count"):
        if type(projection[key]) is not int or not 0 <= projection[key] <= total:
            raise ValueError("invalid terminal execution count")
    statuses = _counts(projection["status_counts"], facts.statuses, total)
    tools = _counts(projection["tool_counts"], facts.tools, total)
    average = projection["average_duration_ms"]
    if (
        sum(statuses.values()) != total
        or sum(tools.values()) > total
        or type(average) not in (int, float)
        or not math.isfinite(average)
    ):
        raise ValueError("invalid execution statistics totals")
    timeline: list[dict[str, Any]] = []
    previous = -1
    for minute, count, completed, failed in projection["time_buckets"]:
        if (
            any(type(v) is not int or v < 0 for v in (minute, count, completed, failed))
            or minute <= previous
            or not completed + failed <= count <= total
        ):
            raise ValueError("invalid execution statistics timeline")
        day, clock = divmod(minute, 1440)
        hour, minute_of_hour = divmod(clock, 60)
        label = f"{date.fromordinal(day + 1):%Y-%m-%d} {hour:02d}:{minute_of_hour:02d}"
        timeline.append({"time": label, "count": count, "completed": completed, "failed": failed})
        previous = minute
    if sum(bucket["count"] for bucket in timeline) != sum(row[2] is not None for row in facts.rows):
        raise ValueError("statistics timeline differs from available dated executions")
    return {
        "total_executions": total,
        "completed_count": projection["completed_count"],
        "failed_count": projection["failed_count"],
        "average_duration_ms": average,
        "tool_usage": tools,
        "status_distribution": statuses,
        "timeline_data": timeline,
    }


async def conversation_execution_statistics(
    db: AsyncSession,
    conversation: Conversation,
    current_user: User,
    executions: list[dict[str, Any]],
) -> dict[str, Any]:
    facts = _facts(executions)
    plugin = (conversation.agent_config or {}).get("execution_stats_package")
    if plugin is None:
        return _response(facts, summarize(facts.rows, legacy_terminal_counts=True))
    if not isinstance(plugin, str) or not 1 <= len(plugin) <= 128:
        raise OptionalBusinessError("invalid_config", "invalid execution statistics package")
    scope = ScopeBindingV2(tenant_id=conversation.tenant_id, project_id=conversation.project_id)
    if not await project_package_actor_can_execute(
        db,
        current_user=current_user,
        requested_scope=ScopeV2(
            kind=ScopeKindV2.PROJECT, tenant_id=scope.tenant_id, project_id=scope.project_id
        ),
    ):
        raise OptionalBusinessError("forbidden", "project package execution permission is required")
    keys = await asyncio.to_thread(
        load_plugin_trust_keys, get_settings().plugin_marketplace_trusted_key_files
    )
    service = ProjectPluginInstallationService(db, scope, tuple(keys), actor_id=current_user.id)

    async def render(package: SignedPackageBytesV2) -> dict[str, Any]:
        operation = next(
            (tool for tool in package.contribution.tools if tool.name == "execution_statistics"),
            None,
        )
        if (
            operation is None
            or operation.permissions != frozenset({"tools.execute"})
            or operation.service_aliases
        ):
            raise OptionalBusinessError(
                "forbidden", "execution statistics require a compute-only operation"
            )
        projection = await invoke_project_tool(
            package, scope, "execution_statistics", {"events": facts.rows}
        )
        try:
            return _response(facts, projection)
        except (ValueError, OverflowError, TypeError, KeyError) as exc:
            raise OptionalBusinessError(
                "invalid_output", "invalid project statistics output"
            ) from exc

    return await service.call_active(plugin, render)
