"""Thin projections from pinned boundaries to the sandbox Consumer service."""

from __future__ import annotations

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

from .boundary import current_generation_v2
from .runtime import RuntimeV2Error
from .sandbox_runtime import (
    SANDBOX_APPLICATION_SERVICE_V2,
    SandboxApplicationResolverProtocolV2,
    SandboxApplicationServicesV2,
)


def current_sandbox_application_services_v2() -> SandboxApplicationServicesV2:
    """Resolve sandbox services from the generation pinned to this operation."""
    resolver = current_generation_v2().resolve(
        SANDBOX_APPLICATION_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    if not isinstance(resolver, SandboxApplicationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_sandbox_application_resolver",
            "sandbox application service has an invalid implementation",
        )
    return resolver.resolve()


__all__ = ["current_sandbox_application_services_v2"]
