"""Tenant capability invocation is confined to explicitly registered tenant operations."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.host.identity.application_scope import application_actor_scope
from src.host.operations.project_package_audit import identify_signed_operation, project_operation
from src.host.operations.remote_application_commands import forward_command
from src.infrastructure.plugins.v2.command_schema import validate_command_document
from src.infrastructure.plugins.v2.project_package_execution import with_wasm_runtime
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.host.operations.deployment_adapters import ApplicationHandler
    from src.infrastructure.adapters.secondary.persistence.models import User
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
        SignedPackageBytesV2,
        TenantBindingV2,
    )


@dataclass(frozen=True)
class TenantPackageContext:
    request: "Request"
    db: "AsyncSession"
    user: "User"
    scope: "TenantBindingV2"


async def tenant_command(
    ctx: TenantPackageContext,
    pkg: "SignedPackageBytesV2",
    command_id: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    c = next((c for c in pkg.contribution.commands if c.command_id == command_id), None)
    if (
        c is None
        or not c.permissions <= pkg.approved_permissions
        or (payload is not None and not c.accepts_input)
    ):
        raise OptionalBusinessError("forbidden", "Tenant command is unavailable")
    with project_operation("command", actor_id=ctx.user.id, tenant_id=ctx.scope.tenant_id) as audit:
        audit.release(pkg)
        audit.executor = "application" if c.host_operation else "wasm"
        identify_signed_operation(pkg, command=command_id)
        inputs = dict(c.payload) if payload is None else payload
        validate_command_document(c.input_schema, inputs, "input_schema")
        from src.host.operations.agent_package.runtime import guest_operation, run_agent_command
        from src.host.operations.business_guest.runtime import (
            guest_operation as business_guest_operation,
            run_business_command,
        )

        business = business_guest_operation(pkg.plugin_id, c)
        if operation := guest_operation(pkg.plugin_id, c):
            audit.executor = "application"
            origin = getattr(ctx.request.app.state, "package_application_runtime_origin", None)
            result = (
                await forward_command(
                    origin,
                    ctx,
                    plugin=pkg.plugin_id,
                    digest=pkg.digest,
                    command=command_id,
                    payload=payload,
                    progress=None,
                )
                if origin
                else await run_agent_command(ctx, operation, inputs, None)
            )
        elif business:
            audit.executor = "application"
            origin = getattr(ctx.request.app.state, "package_application_runtime_origin", None)
            result = (
                await forward_command(
                    origin,
                    ctx,
                    plugin=pkg.plugin_id,
                    digest=pkg.digest,
                    command=command_id,
                    payload=payload,
                    progress=None,
                )
                if origin
                else await run_business_command(ctx, pkg.plugin_id, business, inputs, None)
            )
        elif c.host_operation:
            if resolver := getattr(
                ctx.request.app.state, "resolve_package_application_operation", None
            ):
                handler: ApplicationHandler = resolver(pkg.plugin_id, c.host_operation, ctx.scope)
                with application_actor_scope(ctx.user.id, ctx.scope.tenant_id):
                    result = await handler(ctx, inputs, None)
            else:
                operations: dict[str, ApplicationHandler] = getattr(
                    ctx.request.app.state, "tenant_package_operations_v1", {}
                )
                if c.host_operation in operations:
                    with application_actor_scope(ctx.user.id, ctx.scope.tenant_id):
                        result = await operations[c.host_operation](ctx, inputs, None)
                elif origin := getattr(
                    ctx.request.app.state, "package_application_runtime_origin", None
                ):
                    result = await forward_command(
                        origin,
                        ctx,
                        plugin=pkg.plugin_id,
                        digest=pkg.digest,
                        command=command_id,
                        payload=payload,
                        progress=None,
                    )
                else:
                    raise OptionalBusinessError(
                        "runtime_unavailable", "Tenant application capability unavailable"
                    )
        else:
            result = await with_wasm_runtime(
                pkg, lambda runtime: runtime.invoke(pkg.plugin_id, ctx.scope, c.tool, inputs)
            )
        validate_command_document(c.output_schema, result, "output_schema")
        return result
