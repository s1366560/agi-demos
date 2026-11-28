"""Resolve application capabilities from the deployment generation that owns the request."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import current_generation_v2
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    TenantBindingV2,
)

if TYPE_CHECKING:
    from src.infrastructure.plugins.v2.runtime_context import ContextV2


type ApplicationHandler = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True, kw_only=True)
class ApplicationAdapter:
    plugin_id: str
    project: Mapping[str, ApplicationHandler] = field(default_factory=dict)
    tenant: Mapping[str, ApplicationHandler] = field(default_factory=dict)


def provide_application_adapter(ctx: "ContextV2", adapter: ApplicationAdapter) -> None:
    """Publish only under the service allowed by the verified V2 module contract."""
    frozen = ApplicationAdapter(
        plugin_id=adapter.plugin_id,
        project=MappingProxyType(dict(adapter.project)),
        tenant=MappingProxyType(dict(adapter.tenant)),
    )
    _ = ctx.provide(f"service:package-application:{adapter.plugin_id}", frozen)


def resolve_application_operation(
    plugin_id: str, operation: str, binding: TenantBindingV2
) -> ApplicationHandler:
    project = isinstance(binding, ScopeBindingV2)
    scope = (
        ScopeV2(
            kind=ScopeKindV2.PROJECT, tenant_id=binding.tenant_id, project_id=binding.project_id
        )
        if isinstance(binding, ScopeBindingV2)
        else ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=binding.tenant_id)
    )
    try:
        adapter = current_generation_v2().resolve(f"service:package-application:{plugin_id}", scope)
    except RuntimeV2Error as exc:
        raise OptionalBusinessError(
            "runtime_unavailable", "The selected application adapter is unavailable"
        ) from exc
    if not isinstance(adapter, ApplicationAdapter) or adapter.plugin_id != plugin_id:
        raise OptionalBusinessError(
            "forbidden", "Application adapter identity differs from the signed package"
        )
    handler = (adapter.project if project else adapter.tenant).get(operation)
    if handler is None:
        raise OptionalBusinessError(
            "forbidden", "Application operation is unavailable for this package and scope"
        )
    return handler
