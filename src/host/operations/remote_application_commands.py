"""Deliver a release-pinned command to a deployment's trusted application runtime."""

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit

import httpx

from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress
    from src.host.operations.tenant_commands import TenantPackageContext


def application_runtime_origin(value: str) -> str:
    parts = urlsplit(value)
    if (
        not parts.hostname
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
        or parts.username is not None
        or parts.password is not None
        or (
            parts.scheme != "https"
            and not (parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"})
        )
    ):
        raise ValueError("Application runtime requires an HTTPS origin or loopback HTTP origin")
    return value.rstrip("/")


def application_result(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OptionalBusinessError("runtime_unavailable", "Invalid application response")
    return value


async def forward_command(
    origin: str,
    ctx: "PackageOperationContext | TenantPackageContext",
    *,
    plugin: str,
    digest: str,
    command: str,
    payload: dict[str, Any] | None,
    progress: "Progress | None",
) -> dict[str, Any]:
    if "x-memstack-application-hop" in ctx.request.headers:
        raise OptionalBusinessError("runtime_unavailable", "Application routing loop")
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import ScopeBindingV2

    project = isinstance(ctx.scope, ScopeBindingV2)
    base = "/api/v1/platform-plugins/v2/optional-business" if project else "/api/v1/tenant-packages"
    path = base + "/" + quote(plugin, safe="") + "/commands"
    body = {
        "tenant_id": ctx.scope.tenant_id,
        **({"project_id": ctx.scope.project_id} if isinstance(ctx.scope, ScopeBindingV2) else {}),
        "command_id": command,
        "expected_digest": digest,
        "payload": payload,
    }
    headers = {
        "authorization": ctx.request.headers.get("authorization", ""),
        "x-memstack-application-hop": "1",
    }
    try:
        async with (
            httpx.AsyncClient(base_url=origin, trust_env=False, timeout=30) as client,
            client.stream(
                "POST",
                path,
                headers=headers,
                json=body,
                params={"stream": str(progress is not None).lower()},
            ) as response,
        ):
            if not response.is_success:
                code = {
                    401: "forbidden",
                    403: "forbidden",
                    404: "page_not_found",
                    409: "conflict",
                    429: "busy",
                }.get(response.status_code, "runtime_unavailable")
                raise OptionalBusinessError(
                    code, f"Application runtime returned HTTP {response.status_code}"
                )
            if progress is None:
                return application_result(json.loads(await response.aread()))
            async for line in response.aiter_lines():
                frame = application_result(json.loads(line))
                if frame["type"] == "progress":
                    await progress(application_result(frame["data"]))
                elif frame["type"] == "error":
                    raise OptionalBusinessError("apply_failed", "Application operation failed")
                elif frame["type"] == "result":
                    return application_result(frame["data"])
            raise OptionalBusinessError(
                "runtime_unavailable", "Application stream ended before its result"
            )
    except httpx.HTTPError as error:
        raise OptionalBusinessError(
            "runtime_unavailable", "Application runtime unreachable"
        ) from error
