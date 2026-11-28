"""Host data plane for a business command guest.

Routes and capabilities run as the admitted actor. The caller bearer is not copied.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.host.operations.admitted_loopback import admitted_client
from src.host.operations.application_commands import PackageOperationContext
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
        del name, payload, progress
        raise OptionalBusinessError("forbidden", "operation bodies stay in the guest")

    async def data(
        self,
        name: str,
        params: dict[str, Any],
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        from src.host.operations.business_guest.data_plane import invoke_data

        result = await invoke_data(self.ctx, name, params, progress)
        if not isinstance(result, dict):
            raise OptionalBusinessError("runtime_unavailable", "host data returned no object")
        return result

    async def http(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        async with admitted_client(self.ctx) as client:
            response = await client.request(method, path, json=body, params=query, headers=headers)
        decoded: Any
        if not response.content:
            decoded = None
        else:
            try:
                decoded = response.json()
            except ValueError:
                decoded = {"detail": response.text}
        return {
            "status": response.status_code,
            "body": decoded,
            "headers": {key: value for key, value in response.headers.items()},
        }
