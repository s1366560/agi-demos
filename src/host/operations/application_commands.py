"""Dispatch a verified package command to a scoped application authority."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.host.identity.application_scope import application_actor_scope
from src.host.operations.remote_application_commands import forward_command
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.host.operations.deployment_adapters import ApplicationHandler
    from src.infrastructure.adapters.secondary.persistence.models import User
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import ScopeBindingV2

type Progress = Callable[[dict[str, Any]], Awaitable[None]]
type Operation = Callable[
    [PackageOperationContext, dict[str, Any], Progress | None], Awaitable[dict[str, Any]]
]


@dataclass(frozen=True)
class PackageOperationContext:
    request: "Request"
    db: "AsyncSession"
    user: "User"
    scope: "ScopeBindingV2"

    async def invoke(
        self,
        name: str,
        payload: dict[str, Any],
        progress: Progress | None,
        *,
        plugin: str,
        digest: str,
        command: str,
        supplied_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if resolver := getattr(
            self.request.app.state, "resolve_package_application_operation", None
        ):
            handler: ApplicationHandler = resolver(plugin, name, self.scope)
            with application_actor_scope(self.user.id, self.scope.tenant_id):
                return await handler(self, payload, progress)
        operations: dict[str, Operation] = getattr(
            self.request.app.state, "package_operations_v1", {}
        )
        if name in operations:
            with application_actor_scope(self.user.id, self.scope.tenant_id):
                return await operations[name](self, payload, progress)
        if origin := getattr(self.request.app.state, "package_application_runtime_origin", None):
            return await forward_command(
                origin,
                self,
                plugin=plugin,
                digest=digest,
                command=command,
                payload=supplied_payload,
                progress=progress,
            )
        raise OptionalBusinessError(
            "runtime_unavailable", f"Application capability unavailable: {name}"
        )
