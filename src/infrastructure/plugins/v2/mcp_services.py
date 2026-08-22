"""Operation-scoped MCP Provider and application Consumer seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.mcp_app_service import MCPAppService
from src.application.services.mcp_runtime_service import MCPRuntimeService
from src.application.services.sandbox_mcp_server_manager import SandboxMCPServerManager
from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
    SqlMCPAppRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_mcp_lifecycle_event_repository import (
    SqlMCPLifecycleEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
    SqlMCPServerRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
    SqlProjectRepository,
)
from src.infrastructure.mcp.resource_resolver import MCPAppResourceResolver

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .sandbox_operation_services import SandboxOperationApplicationResolverProtocolV2

if TYPE_CHECKING:
    from redis.asyncio import Redis

MCP_OPERATION_PROVIDER_MODULE_V2 = "builtin://memstack/mcp/operation-service-provider"
MCP_OPERATION_PROVIDER_SERVICE_V2 = "service:mcp.operation-service-provider"
MCP_APPLICATION_MODULE_V2 = "builtin://memstack/application/mcp-services"
MCP_APPLICATION_SERVICE_V2 = "service:application.mcp-services"
MCP_SANDBOX_APPLICATION_INJECT_V2 = "sandbox_application"
MCP_PROVIDER_INJECT_V2 = "provider"


@dataclass(frozen=True, kw_only=True)
class MCPApplicationServicesV2:
    """MCP services built from one exact operation session and sandbox runtime."""

    sandbox_manager: SandboxMCPServerManager
    app_service: MCPAppService
    runtime_service: MCPRuntimeService


@runtime_checkable
class MCPOperationServiceFactoryProtocolV2(Protocol):
    """Provider contract hiding persistence and sandbox implementations."""

    def build(self, operation: OperationContextV2) -> MCPApplicationServicesV2: ...


@runtime_checkable
class MCPApplicationResolverProtocolV2(Protocol):
    """Application-facing resolver injected through a declared service alias."""

    def resolve(self, operation: OperationContextV2) -> MCPApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class DefaultMCPOperationServiceFactoryV2:
    """Build the complete MCP graph from request-owned dependencies."""

    sandbox_application: SandboxOperationApplicationResolverProtocolV2
    redis_client: object | None = None

    def build(self, operation: OperationContextV2) -> MCPApplicationServicesV2:
        from .boundary import OPERATION_DB_SESSION_SERVICE_V2

        db = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "MCP application services require an AsyncSession operation service",
            )
        sandbox_services = self.sandbox_application.resolve(operation)
        app_repo = SqlMCPAppRepository(db)
        sandbox_manager: SandboxMCPServerManager | None = None

        def manager_factory() -> SandboxMCPServerManager:
            if sandbox_manager is None:
                raise RuntimeV2Error(
                    "mcp_service_graph_incomplete",
                    "MCP sandbox manager is not available during resource resolution",
                )
            return sandbox_manager

        app_service = MCPAppService(
            app_repo=app_repo,
            resource_resolver=MCPAppResourceResolver(manager_factory=manager_factory),
        )
        sandbox_manager = SandboxMCPServerManager(
            sandbox_resource=sandbox_services.sandbox_resource,
            app_service=app_service,
        )
        runtime_service = MCPRuntimeService(
            server_repo=SqlMCPServerRepository(db),
            app_repo=app_repo,
            app_service=app_service,
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=SqlMCPLifecycleEventRepository(db),
            project_repo=SqlProjectRepository(db),
            redis_client=cast("Redis | None", self.redis_client),
        )
        return MCPApplicationServicesV2(
            sandbox_manager=sandbox_manager,
            app_service=app_service,
            runtime_service=runtime_service,
        )


@dataclass(frozen=True, kw_only=True)
class MCPApplicationResolverV2:
    """Resolve request-owned MCP services without exposing their Provider."""

    provider: MCPOperationServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> MCPApplicationServicesV2:
        return self.provider.build(operation)


def mcp_operation_provider_definition_v2(
    *,
    redis_client: object | None = None,
) -> PluginDefinitionV2:
    """Build the MCP operation Provider definition."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "request-async-session":
            raise ValueError("MCP operation provider requires strategy request-async-session")
        sandbox_application = context.require(MCP_SANDBOX_APPLICATION_INJECT_V2)
        if not isinstance(
            sandbox_application,
            SandboxOperationApplicationResolverProtocolV2,
        ):
            raise RuntimeV2Error(
                "invalid_sandbox_operation_application",
                "MCP provider sandbox application inject has an invalid implementation",
            )
        _ = context.provide(
            MCP_OPERATION_PROVIDER_SERVICE_V2,
            DefaultMCPOperationServiceFactoryV2(
                sandbox_application=sandbox_application,
                redis_client=redis_client,
            ),
            label="mcp-operation-provider",
        )

    return PluginDefinitionV2(
        module_ref=MCP_OPERATION_PROVIDER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(MCP_OPERATION_PROVIDER_MODULE_V2),
        apply=apply,
    )


def mcp_application_definition_v2() -> PluginDefinitionV2:
    """Build the MCP application Consumer definition."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "operation-scoped-provider":
            raise ValueError("MCP application requires strategy operation-scoped-provider")
        provider = context.require(MCP_PROVIDER_INJECT_V2)
        if not isinstance(provider, MCPOperationServiceFactoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_mcp_operation_provider",
                "MCP operation provider inject has an invalid implementation",
            )
        _ = context.provide(
            MCP_APPLICATION_SERVICE_V2,
            MCPApplicationResolverV2(provider=provider),
            label="mcp-application",
        )

    return PluginDefinitionV2(
        module_ref=MCP_APPLICATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(MCP_APPLICATION_MODULE_V2),
        apply=apply,
    )


def mcp_service_definitions_v2(
    *,
    redis_client: object | None = None,
) -> tuple[PluginDefinitionV2, ...]:
    """Return the explicit MCP Provider/Consumer definition pair."""
    return (
        mcp_operation_provider_definition_v2(redis_client=redis_client),
        mcp_application_definition_v2(),
    )


__all__ = [
    "MCP_APPLICATION_MODULE_V2",
    "MCP_APPLICATION_SERVICE_V2",
    "MCP_OPERATION_PROVIDER_MODULE_V2",
    "MCP_OPERATION_PROVIDER_SERVICE_V2",
    "MCP_PROVIDER_INJECT_V2",
    "MCP_SANDBOX_APPLICATION_INJECT_V2",
    "DefaultMCPOperationServiceFactoryV2",
    "MCPApplicationResolverProtocolV2",
    "MCPApplicationResolverV2",
    "MCPApplicationServicesV2",
    "MCPOperationServiceFactoryProtocolV2",
    "mcp_application_definition_v2",
    "mcp_operation_provider_definition_v2",
    "mcp_service_definitions_v2",
]
