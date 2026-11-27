"""Host data plane for a business command guest.

Routes and capabilities run as the admitted actor. The caller bearer is not copied.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.host.operations.admitted_loopback import admitted_client
from src.host.operations.application_commands import PackageOperationContext
from src.host.operations.business_guest.capabilities import CAPABILITIES
from src.host.operations.tenant_commands import TenantPackageContext
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

type Progress = Callable[[dict[str, Any]], Awaitable[None]]


class HostBridge:
    def __init__(self, ctx: PackageOperationContext | TenantPackageContext) -> None:
        self.ctx = ctx
        self.user_id = str(ctx.user.id)
        self.tenant_id = ctx.scope.tenant_id
        self.project_id = getattr(ctx.scope, "project_id", None)

    async def call(
        self, name: str, payload: dict[str, Any], progress: Progress | None = None
    ) -> dict[str, Any]:
        handler = CAPABILITIES.get(name)
        if handler is None:
            raise OptionalBusinessError("forbidden", "unknown host capability")
        result = await handler(self.ctx, payload, progress)
        if not isinstance(result, dict):
            raise OptionalBusinessError("runtime_unavailable", "host capability returned no object")
        return result

    async def http(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with admitted_client(self.ctx) as client:
            response = await client.request(method, path, json=body, params=query)
        if response.status_code >= 400:
            code = {401: "forbidden", 403: "forbidden", 404: "page_not_found", 409: "conflict"}.get(
                response.status_code, "runtime_unavailable"
            )
            raise OptionalBusinessError(code, f"Host route returned HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise OptionalBusinessError("runtime_unavailable", "Host route returned no object")
        return payload
