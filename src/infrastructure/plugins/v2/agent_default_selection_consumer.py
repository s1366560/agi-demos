"""Operation-scoped consumer for the V2 default agent selection service."""

from __future__ import annotations

from .agent_default_selection import (
    AGENT_DEFAULT_SELECTION_SERVICE_V2,
    AgentDefaultSelectionResolutionV2,
    AgentDefaultSelectionResolverProtocolV2,
)
from .boundary import current_operation_context_v2
from .runtime import RuntimeV2Error


def resolve_current_agent_default_selection_v2(
    *,
    tenant_id: str,
    project_id: str,
) -> AgentDefaultSelectionResolutionV2:
    """Resolve the Profile default through the pinned operation and exact scope."""
    operation = current_operation_context_v2()
    operation_scope = operation.context.scope
    if operation_scope.tenant_id != tenant_id or operation_scope.project_id != project_id:
        raise RuntimeV2Error(
            "agent_default_scope_mismatch",
            "agent default selection scope does not match the pinned operation",
        )
    resolver = operation.require(AGENT_DEFAULT_SELECTION_SERVICE_V2)
    if not isinstance(resolver, AgentDefaultSelectionResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_default_selection_resolver",
            "agent default selection service has an invalid implementation",
        )
    return resolver.resolve(tenant_id=tenant_id, project_id=project_id)


__all__ = ["resolve_current_agent_default_selection_v2"]
