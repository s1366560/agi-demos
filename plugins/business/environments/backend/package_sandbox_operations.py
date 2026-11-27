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
    if value is None:
        return None
    try:
        sandbox = _Sandbox.model_validate(value)
    except ValidationError as exc:
        raise OptionalBusinessError("runtime_unavailable", "Invalid sandbox state") from exc
    if (sandbox.tenant_id, sandbox.project_id) != (ctx.scope.tenant_id, ctx.scope.project_id):
        raise OptionalBusinessError("forbidden", "Sandbox scope mismatch")
    return sandbox.model_dump(exclude={"project_id", "tenant_id"}, exclude_none=True)


async def read_sandbox(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    query = _Read.model_validate(payload)
    if query.metrics_for:
        sandbox = _sandbox(ctx, await _request(ctx, "GET", "", absent_ok=True))
        if not sandbox or sandbox["sandbox_id"] != query.metrics_for:
            raise OptionalBusinessError("conflict", "The selected sandbox has changed")
        try:
            stats = _Stats.model_validate(await _request(ctx, "GET", "/stats"))
        except ValidationError as exc:
            raise OptionalBusinessError("runtime_unavailable", "Invalid sandbox metrics") from exc
        if (stats.project_id, stats.sandbox_id) != (ctx.scope.project_id, query.metrics_for):
            raise OptionalBusinessError("forbidden", "Sandbox metrics scope mismatch")
        return {
            "metrics": stats.model_dump(exclude={"project_id", "sandbox_id"}, exclude_none=True)
        }
    capability = await _capability(ctx)
    return {
        "sandbox": _sandbox(ctx, await _request(ctx, "GET", "", absent_ok=True)),
        "terminal": capability.model_dump(),
    }


async def prepare_sandbox(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    data = _Prepare.model_validate(payload)
    return {"sandbox": _sandbox(ctx, await _request(ctx, "POST", "", data.model_dump()))}


async def restart_sandbox(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    _Input.model_validate(payload)
    response = await _request(ctx, "POST", "/restart")
    if not response or response.get("success") is not True:
        raise OptionalBusinessError("runtime_unavailable", "Sandbox restart failed")
    return {"success": True}


async def terminate_sandbox(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    _Input.model_validate(payload)
    response = await _request(ctx, "DELETE", "")
    if not response or response.get("success") is not True:
        raise OptionalBusinessError("runtime_unavailable", "Sandbox termination failed")
    return {"success": True}


async def authorize_terminal(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    run = _RunAuthorization.model_validate(payload)
    capability = await _capability(ctx)
    if capability.availability != "available":
        raise OptionalBusinessError(
            "runtime_unavailable", capability.reason_code or "terminal_authority_unavailable"
        )
    try:
        response = await _request(
            ctx, "POST", "/terminal/sessions", run.model_dump(exclude={"open_channel"})
        )
        grant = (_PrivateGrant if run.open_channel else _Grant).model_validate(response)
    except ValidationError as exc:
        raise OptionalBusinessError(
            "runtime_unavailable", "Invalid terminal authorization"
        ) from exc
    if (grant.project_id, grant.run_id, grant.run_revision) != (
        ctx.scope.project_id,
        run.run_id,
        run.expected_run_revision,
    ):
        raise OptionalBusinessError("forbidden", "Terminal grant scope mismatch")
    if isinstance(grant, _PrivateGrant):
        from .interaction_channel import open_run_terminal

        return await open_run_terminal(ctx, grant.session_id, grant.resume_token)
    return grant.model_dump()


SANDBOX_OPERATIONS: dict[str, "Operation"] = {
    "app.environments.sandbox.read": read_sandbox,
    "app.environments.sandbox.prepare": prepare_sandbox,
    "app.environments.sandbox.restart": restart_sandbox,
    "app.environments.sandbox.terminate": terminate_sandbox,
    "app.environments.terminal.authorize": authorize_terminal,
}
