"""Project sandbox operations exposed to signed pages through the canonical sandbox authority."""

from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.configuration.config import get_settings
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from src.host.operations.application_commands import (
        Operation,
        PackageOperationContext,
        Progress,
    )


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Prepare(_Input):
    profile: Literal["lite", "standard", "full"] = "standard"


class _Run(_Input):
    run_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    expected_run_revision: Annotated[int, Field(ge=1, le=2147483647)]


class _RunAuthorization(_Run):
    open_channel: bool = False


class _Capability(BaseModel):
    contract_version: Literal[2]
    availability: Literal["available", "unavailable", "degraded"]
    reason_code: str | None = None


class _Capabilities(BaseModel):
    terminal_resume: _Capability


class _Sandbox(BaseModel):
    sandbox_id: str
    project_id: str
    tenant_id: str
    status: str
    is_healthy: bool
    created_at: str | None = None
    last_accessed_at: str | None = None


class _Stats(BaseModel):
    project_id: str
    sandbox_id: str
    cpu_percent: float
    memory_usage: int
    memory_limit: int
    disk_usage: int | None = None
    network_rx_bytes: int | None = None
    network_tx_bytes: int | None = None
    pids: int
    collected_at: str


class _Read(_Input):
    metrics_for: Annotated[str, Field(min_length=1, max_length=256)] | None = None


class _Grant(BaseModel):
    contract_version: Literal[2]
    project_id: str
    run_id: str
    run_revision: int
    expires_at: str


class _PrivateGrant(_Grant):
    session_id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")]
    resume_token: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{20,256}$")]


async def _request(
    ctx: "PackageOperationContext",
    method: str,
    suffix: str,
    body: dict[str, Any] | None = None,
    *,
    absent_ok: bool = False,
) -> dict[str, Any] | None:
    # The browser cannot select the destination, resource ID, request headers or API method.
    origin = get_settings().project_sandbox_authority_url
    project = quote(ctx.scope.project_id, safe="")
    path = f"/api/v1/projects/{project}/sandbox{suffix}"
    if not ctx.scope.project_id or ctx.scope.project_id in {".", ".."}:
        raise OptionalBusinessError("forbidden", "Invalid project scope")
    try:
        from src.host.operations.admitted_loopback import admitted_client

        if origin:
            # A remote sandbox authority is a host capability. The caller bearer stays here.
            client_cm = httpx.AsyncClient(
                base_url=str(origin),
                trust_env=False,
                follow_redirects=False,
                timeout=60,
            )
        else:
            client_cm = admitted_client(ctx)
        async with client_cm as client:
            response = await client.request(method, path, json=body)
    except httpx.HTTPError as exc:
        raise OptionalBusinessError("runtime_unavailable", "Sandbox authority unavailable") from exc
    if response.status_code == 404 and absent_ok:
        return None
    if not response.is_success:
        code = {401: "forbidden", 403: "forbidden", 409: "conflict"}.get(
            response.status_code, "runtime_unavailable"
        )
        raise OptionalBusinessError(code, f"Sandbox authority returned HTTP {response.status_code}")
    try:
        value = response.json()
    except ValueError as exc:
        raise OptionalBusinessError("runtime_unavailable", "Invalid sandbox response") from exc
    if not isinstance(value, dict):
        raise OptionalBusinessError("runtime_unavailable", "Invalid sandbox response")
    return value


async def _capability(ctx: "PackageOperationContext") -> _Capability:
    try:
        return _Capabilities.model_validate(
            await _request(ctx, "GET", "/capabilities")
        ).terminal_resume
    except ValidationError as exc:
        raise OptionalBusinessError("runtime_unavailable", "Invalid terminal capability") from exc


def _sandbox(ctx: "PackageOperationContext", value: dict[str, Any] | None) -> dict[str, Any] | None:
    from plugins.business.environments.guest.sandbox import project_sandbox

    return project_sandbox(ctx.scope.tenant_id, ctx.scope.project_id, value)


async def _shaped(
    ctx: "PackageOperationContext",
    name: str,
    payload: dict[str, Any],
    progress: "Progress | None",
) -> dict[str, Any]:
    from plugins.business.environments.guest import commands
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, getattr(commands, name), payload, progress)


async def read_sandbox(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    return await _shaped(ctx, "read_sandbox", payload, progress)


async def prepare_sandbox(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    return await _shaped(ctx, "prepare_sandbox", payload, progress)


async def restart_sandbox(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    return await _shaped(ctx, "restart_sandbox", payload, progress)


async def terminate_sandbox(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    return await _shaped(ctx, "terminate_sandbox", payload, progress)


async def authorize_terminal(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    return await _shaped(ctx, "authorize_terminal", payload, progress)


SANDBOX_OPERATIONS: dict[str, "Operation"] = {
    "app.environments.sandbox.read": read_sandbox,
    "app.environments.sandbox.prepare": prepare_sandbox,
    "app.environments.sandbox.restart": restart_sandbox,
    "app.environments.sandbox.terminate": terminate_sandbox,
    "app.environments.terminal.authorize": authorize_terminal,
}
