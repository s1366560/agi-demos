"""Operation-scoped MCP Provider and application Consumer seams."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.mcp_app_service import MCPAppService
from src.application.services.mcp_runtime_service import MCPRuntimeService
from src.application.services.sandbox_mcp_server_manager import SandboxMCPServerManager
from src.domain.model.mcp.server import MCPServer
from src.domain.ports.repositories.mcp_server_repository import MCPServerRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    MCPLifecycleEvent,
    Project,
    UserProject,
)
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
MCP_PROJECT_WRITE_ROLES_V2 = ("owner", "admin", "member")


class MCPProjectAccessDeniedV2(Exception):
    """The operation identity cannot access the requested project."""


@runtime_checkable
class MCPProjectAccessProtocolV2(Protocol):
    """Project membership and tenant boundary for MCP operations."""

    async def list_accessible_project_ids(self, *, tenant_id: str, user_id: str) -> set[str]: ...

    async def resolve_project_tenant_id(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        required_roles: Collection[str] | None = None,
    ) -> str: ...

    async def ensure_project_access(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        required_roles: Collection[str] | None = None,
    ) -> None: ...


@dataclass(frozen=True, kw_only=True)
class SqlMCPProjectAccessV2:
    """Read MCP project authorization from one operation-owned session."""

    _session: AsyncSession

    async def list_accessible_project_ids(self, *, tenant_id: str, user_id: str) -> set[str]:
        result = await self._session.execute(
            refresh_select_statement(
                select(UserProject.project_id)
                .join(Project, UserProject.project_id == Project.id)
                .where(
                    Project.tenant_id == tenant_id,
                    UserProject.user_id == user_id,
                )
            )
        )
        return set(result.scalars().all())

    async def resolve_project_tenant_id(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        required_roles: Collection[str] | None = None,
    ) -> str:
        allowed_roles = _validated_roles_v2(required_roles)
        query = (
            select(Project.tenant_id)
            .join(UserProject, UserProject.project_id == Project.id)
            .where(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
                UserProject.user_id == user_id,
                UserProject.project_id == project_id,
            )
        )
        if allowed_roles is not None:
            query = query.where(UserProject.role.in_(allowed_roles))
        result = await self._session.execute(refresh_select_statement(query))
        resolved_tenant_id = result.scalar_one_or_none()
        if resolved_tenant_id is None:
            raise MCPProjectAccessDeniedV2
        return str(resolved_tenant_id)

    async def ensure_project_access(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        required_roles: Collection[str] | None = None,
    ) -> None:
        allowed_roles = _validated_roles_v2(required_roles)
        query = (
            select(UserProject.id)
            .join(Project, UserProject.project_id == Project.id)
            .where(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
                UserProject.user_id == user_id,
                UserProject.project_id == project_id,
            )
        )
        if allowed_roles is not None:
            query = query.where(UserProject.role.in_(allowed_roles))
        result = await self._session.execute(refresh_select_statement(query))
        if result.scalar_one_or_none() is None:
            raise MCPProjectAccessDeniedV2


def _validated_roles_v2(required_roles: Collection[str] | None) -> tuple[str, ...] | None:
    if required_roles is None:
        return None
    roles = tuple(required_roles)
    if not roles:
        raise MCPProjectAccessDeniedV2
    return roles


@dataclass(frozen=True, kw_only=True)
class MCPLifecycleEventRecordV2:
    """Persistence-neutral lifecycle event projection for HTTP consumers."""

    id: str
    event_type: str
    status: str
    error_message: str | None
    metadata: Mapping[str, Any]
    created_at: datetime | None


@runtime_checkable
class MCPLifecycleQueryProtocolV2(Protocol):
    """Read lifecycle events through the operation Provider."""

    async def list_server_events(
        self,
        *,
        server_id: str,
        tenant_id: str,
        limit: int,
    ) -> tuple[MCPLifecycleEventRecordV2, ...]: ...


@dataclass(frozen=True, kw_only=True)
class SqlMCPLifecycleQueryV2:
    """Query lifecycle events from one operation-owned session."""

    _session: AsyncSession

    async def list_server_events(
        self,
        *,
        server_id: str,
        tenant_id: str,
        limit: int,
    ) -> tuple[MCPLifecycleEventRecordV2, ...]:
        result = await self._session.execute(
            refresh_select_statement(
                select(MCPLifecycleEvent)
                .where(
                    MCPLifecycleEvent.server_id == server_id,
                    MCPLifecycleEvent.tenant_id == tenant_id,
                )
                .order_by(desc(MCPLifecycleEvent.created_at))
                .limit(limit)
            )
        )
        return tuple(
            MCPLifecycleEventRecordV2(
                id=event.id,
                event_type=event.event_type,
                status=event.status,
                error_message=event.error_message,
                metadata=event.metadata_json or {},
                created_at=event.created_at,
            )
            for event in result.scalars().all()
        )


@runtime_checkable
class MCPDirectToolCallerProtocolV2(Protocol):
    """Call a configured MCP server through a generation-owned adapter."""

    async def call(
        self,
        *,
        server: MCPServer,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> object: ...


@dataclass(frozen=True, kw_only=True)
class MCPClientDirectToolCallerV2:
    """Call the managed process in its owning project sandbox."""

    sandbox_manager: SandboxMCPServerManager

    async def call(
        self,
        *,
        server: MCPServer,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> object:
        if not server.project_id:
            raise ValueError("MCP server has no project sandbox")
        result = await self.sandbox_manager.call_tool(
            project_id=server.project_id,
            server_name=server.name,
            tool_name=tool_name,
            arguments=dict(arguments),
        )
        return {"content": result.content, "isError": result.is_error}


@runtime_checkable
class MCPToolCacheProtocolV2(Protocol):
    """Invalidate model-visible MCP tools after a committed mutation."""

    def invalidate(self, tenant_id: str) -> int: ...


@dataclass(frozen=True, kw_only=True)
class AgentMCPToolCacheV2:
    """Bridge the current agent tool cache through an explicit V2 seam."""

    def invalidate(self, tenant_id: str) -> int:
        from src.infrastructure.agent.state.agent_session_pool import (
            invalidate_mcp_tools_cache,
        )

        return invalidate_mcp_tools_cache(tenant_id)


@dataclass(frozen=True, kw_only=True)
class MCPApplicationServicesV2:
    """MCP services built from one exact operation session and sandbox runtime."""

    sandbox_manager: SandboxMCPServerManager
    app_service: MCPAppService
    runtime_service: MCPRuntimeService
    server_repository: MCPServerRepositoryPort
    access: MCPProjectAccessProtocolV2
    lifecycle_queries: MCPLifecycleQueryProtocolV2
    direct_tool_caller: MCPDirectToolCallerProtocolV2
    tool_cache: MCPToolCacheProtocolV2


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
        from src.application.services.marketplace_oauth_runtime import OAuthSandboxMCPServerManager

        sandbox_manager = OAuthSandboxMCPServerManager(
            db=db,
            sandbox_resource=sandbox_services.sandbox_resource,
            app_service=app_service,
        )
        server_repository = SqlMCPServerRepository(db)
        runtime_service = MCPRuntimeService(
            server_repo=server_repository,
            app_repo=app_repo,
            app_service=app_service,
            sandbox_manager=sandbox_manager,
            lifecycle_event_repo=SqlMCPLifecycleEventRepository(db),
            project_repo=SqlProjectRepository(db),
            redis_client=cast("Redis | None", self.redis_client),
        )
        sandbox_manager.runtime_service = runtime_service
        return MCPApplicationServicesV2(
            sandbox_manager=sandbox_manager,
            app_service=app_service,
            runtime_service=runtime_service,
            server_repository=server_repository,
            access=SqlMCPProjectAccessV2(_session=db),
            lifecycle_queries=SqlMCPLifecycleQueryV2(_session=db),
            direct_tool_caller=MCPClientDirectToolCallerV2(sandbox_manager=sandbox_manager),
            tool_cache=AgentMCPToolCacheV2(),
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
    "MCP_PROJECT_WRITE_ROLES_V2",
    "MCP_PROVIDER_INJECT_V2",
    "MCP_SANDBOX_APPLICATION_INJECT_V2",
    "AgentMCPToolCacheV2",
    "DefaultMCPOperationServiceFactoryV2",
    "MCPApplicationResolverProtocolV2",
    "MCPApplicationResolverV2",
    "MCPApplicationServicesV2",
    "MCPClientDirectToolCallerV2",
    "MCPDirectToolCallerProtocolV2",
    "MCPLifecycleEventRecordV2",
    "MCPLifecycleQueryProtocolV2",
    "MCPOperationServiceFactoryProtocolV2",
    "MCPProjectAccessDeniedV2",
    "MCPProjectAccessProtocolV2",
    "MCPToolCacheProtocolV2",
    "SqlMCPLifecycleQueryV2",
    "SqlMCPProjectAccessV2",
    "mcp_application_definition_v2",
    "mcp_operation_provider_definition_v2",
    "mcp_service_definitions_v2",
]
