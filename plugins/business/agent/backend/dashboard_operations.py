"""Tenant dashboard commands. Authority calls stay on the host port."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from plugins.business.agent.guest.binding import CommandContext, CommandError, Progress, current

DASHBOARD_PERMISSIONS = frozenset(
    {
        "app.agent.dashboard.read",
        "app.agent.dashboard.trace",
        "app.agent.dashboard.configure",
    }
)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Read(_Input):
    view: Literal["runs", "active", "config", "permission", "revision", "catalog", "system"]


class Trace(_Input):
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9_:-]{1,128}$")
    trace_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


class Update(_Input):
    config: dict[str, Any]
    expected_revision: int = Field(ge=1)


def _tenant_only() -> None:
    if current().project_id:
        raise CommandError("forbidden", "Tenant installation required")


async def read_dashboard(
    _ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    _tenant_only()
    item = Read.model_validate(payload)
    return await current().dashboard("read", {"view": item.view})


async def inspect_trace(
    _ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    _tenant_only()
    item = Trace.model_validate(payload)
    return await current().dashboard("trace", item.model_dump())


async def update_dashboard(
    _ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    _tenant_only()
    item = Update.model_validate(payload)
    return await current().dashboard("configure", item.model_dump())


# Registered with the deployment adapter. Empty: these commands are not in-process.
DASHBOARD_OPERATIONS: dict[str, Any] = {}
