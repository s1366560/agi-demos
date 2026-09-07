"""Profile-owned persisted Agent Definition contribution for the V2 spine."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from src.domain.ports.agent.agent_registry import AgentRegistryPort

from .agent_definition import (
    AgentDefinitionCatalogProtocolV2,
    AgentDefinitionDisposerV2,
)
from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

AGENT_PERSISTED_DEFINITION_MODULE_V2 = "builtin://memstack/agent/persisted-definition-contribution"
AGENT_PERSISTED_DEFINITION_SOURCE_V2 = "persisted-agent-definitions"


def _build_agent_registry_v2(db_session: object) -> AgentRegistryPort:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
        SqlAgentRegistryRepository,
    )

    if not isinstance(db_session, AsyncSession):
        raise RuntimeV2Error(
            "invalid_operation_db_session",
            "persisted Agent Definition provider requires an AsyncSession operation service",
        )
    return SqlAgentRegistryRepository(db_session)


async def _resolve_persisted_agent_definition_v2(
    *,
    agent_id: str,
    tenant_id: str,
    project_id: str | None,
) -> object | None:
    """Resolve one exact scoped definition from the pinned operation database."""
    from .artifact_content_gc_runtime import (
        ASYNC_SESSION_FACTORY_SERVICE_V2,
        AsyncSessionFactoryServiceV2,
    )
    from .boundary import (
        OPERATION_DB_SESSION_SERVICE_V2,
        bind_operation_context_v2,
        current_operation_context_v2,
    )
    from .runtime import OperationContextV2

    operation = current_operation_context_v2()
    scope = operation.context.scope
    if scope.tenant_id != tenant_id or scope.project_id != project_id:
        raise RuntimeV2Error(
            "agent_definition_scope_mismatch",
            "persisted Agent Definition scope does not match the pinned operation",
        )
    try:
        db = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
    except RuntimeV2Error as exc:
        if exc.code != "missing_service":
            raise
        sessions = operation.require(ASYNC_SESSION_FACTORY_SERVICE_V2)
        if not isinstance(sessions, AsyncSessionFactoryServiceV2):
            raise RuntimeV2Error(
                "invalid_agent_definition_session_factory",
                "persisted Agent Definition requires a generation-owned session factory",
            ) from exc
        async with sessions.factory() as db:
            child = OperationContextV2(
                generation=operation.generation,
                operation_id=f"agent-definition-read:{uuid4().hex}",
                scope=scope,
            )
            async with child:
                _ = child.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
                with bind_operation_context_v2(child):
                    return await _resolve_persisted_agent_definition_v2(
                        agent_id=agent_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                    )
    repository = _build_agent_registry_v2(db)
    return await repository.get_by_id(
        agent_id=agent_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )


def _apply_agent_persisted_definition_contribution_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> AgentDefinitionDisposerV2:
    if config.get("strategy") != "operation-agent-registry":
        raise ValueError(
            "persisted Agent Definition contribution requires strategy operation-agent-registry"
        )
    source_id = config.get("source_id")
    if source_id != AGENT_PERSISTED_DEFINITION_SOURCE_V2:
        raise ValueError(
            "persisted Agent Definition contribution requires source_id persisted-agent-definitions"
        )
    catalog = context.require("catalog")
    if not isinstance(catalog, AgentDefinitionCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "persisted Agent Definition contribution received an invalid catalog",
        )
    return catalog.register_provider(source_id, _resolve_persisted_agent_definition_v2)


def builtin_agent_persisted_definition_contribution_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=AGENT_PERSISTED_DEFINITION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_PERSISTED_DEFINITION_MODULE_V2),
        apply=_apply_agent_persisted_definition_contribution_v2,
    )


__all__ = [
    "AGENT_PERSISTED_DEFINITION_MODULE_V2",
    "AGENT_PERSISTED_DEFINITION_SOURCE_V2",
    "builtin_agent_persisted_definition_contribution_v2",
]
