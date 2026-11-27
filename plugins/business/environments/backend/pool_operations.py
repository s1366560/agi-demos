"""Tenant-bound commands for the original runtime pool dashboard."""

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class PoolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Read(PoolInput):
    resource: Literal["status", "instances", "metrics"]
    tier: Literal["hot", "warm", "cold"] | None = None
    status: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class Control(PoolInput):
    action: Literal["pause", "resume", "terminate"]
    instance_key: str = Field(min_length=1, max_length=512, pattern=r"^[^/\\?#%]+$")
    graceful: bool = True


class Tier(PoolInput):
    project_id: str = Field(min_length=1, max_length=128, pattern=r"^[\w-]+$")
    tier: Literal["hot", "warm", "cold"]


async def read(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.environments.guest.commands import read_pool
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, read_pool, payload, progress)


async def control(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.environments.guest.commands import control_pool
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, control_pool, payload, progress)


async def set_tier(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.environments.guest.commands import set_tier as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
