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


class _Grant(BaseModel):
    contract_version: Literal[2]
    project_id: str
    run_id: str
    run_revision: int
    expires_at: str


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
        async with httpx.AsyncClient(
            base_url=str(origin) if origin else "http://localhost",
            transport=None if origin else httpx.ASGITransport(app=ctx.request.app),
            headers={"Authorization": ctx.request.headers.get("Authorization", "")},
            trust_env=False,
            follow_redirects=False,
            timeout=60,
        ) as client:
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
    return sandbox.model_dump(include={"sandbox_id", "status", "is_healthy"})


async def read_sandbox(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    _Input.model_validate(payload)
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


async def authorize_terminal(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    run = _Run.model_validate(payload)
    capability = await _capability(ctx)
    if capability.availability != "available":
        raise OptionalBusinessError(
            "runtime_unavailable", capability.reason_code or "terminal_authority_unavailable"
        )
    try:
        grant = _Grant.model_validate(
            await _request(ctx, "POST", "/terminal/sessions", run.model_dump())
        )
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
    return grant.model_dump()


SANDBOX_OPERATIONS: dict[str, "Operation"] = {
    "app.environments.sandbox.read": read_sandbox,
    "app.environments.sandbox.prepare": prepare_sandbox,
    "app.environments.terminal.authorize": authorize_terminal,
}
