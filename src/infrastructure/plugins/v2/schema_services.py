"""Generation-owned persistence and application seams for project schemas."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.application.schemas.schema import (
    EdgeTypeCreate,
    EdgeTypeMapCreate,
    EdgeTypeUpdate,
    EntityTypeCreate,
    EntityTypeUpdate,
)
from src.domain.model.project_schema.commands import ProjectSchemaAction, ProjectSchemaScope
from src.domain.model.project_schema.http_mutations import (
    SchemaHttpMutation,
    SchemaHttpOperation,
    SchemaHttpReceipt,
)
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.domain.ports.services.project_schema_authorization import ProjectSchemaAuthorization
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    EdgeType,
    EdgeTypeMap,
    EntityType,
    UserProject,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_commands import (
    SqlProjectSchemaCommands,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_http_commands import (
    SqlProjectSchemaHttpCommands,
)
from src.infrastructure.adapters.secondary.schema.active_schema_reads import (
    ActiveSchemaSnapshot,
    active_schema_snapshot,
    require_legacy_schema,
)
from src.infrastructure.plugins.v2.schema_authorization import SqlProjectSchemaAuthorizationV2
from src.infrastructure.plugins.v2.schema_document_services import SchemaDocumentServicesV2

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SCHEMA_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/schema-provider"
SCHEMA_PROVIDER_SERVICE_V2 = "service:persistence.schema-provider"
SCHEMA_APPLICATION_MODULE_V2 = "builtin://memstack/application/schema-services"
SCHEMA_APPLICATION_SERVICE_V2 = "service:application.schema-services"
SCHEMA_PROVIDER_INJECT_V2 = "provider"
SCHEMA_WRITE_ROLES_V2 = frozenset({"owner", "admin", "member"})
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


class SchemaServiceErrorV2(Exception):
    """Base class for typed project-schema application failures."""


class SchemaAccessDeniedV2(SchemaServiceErrorV2):
    """The operation identity is not allowed to access the project schema."""


class SchemaEntityTypeConflictV2(SchemaServiceErrorV2):
    """An entity type with the requested project-local name already exists."""


class SchemaEntityTypeNotFoundV2(SchemaServiceErrorV2):
    """The requested entity type does not belong to the project."""


class SchemaEdgeTypeConflictV2(SchemaServiceErrorV2):
    """An edge type with the requested project-local name already exists."""


class SchemaEdgeTypeNotFoundV2(SchemaServiceErrorV2):
    """The requested edge type does not belong to the project."""


class SchemaEdgeMapConflictV2(SchemaServiceErrorV2):
    """The requested project-local edge mapping already exists."""


class SchemaEdgeMapNotFoundV2(SchemaServiceErrorV2):
    """The requested edge mapping does not belong to the project."""


@runtime_checkable
class SchemaPersistenceProtocolV2(Protocol):
    """Persistence operations hidden behind the exact schema Provider contract."""

    async def active_snapshot(
        self, *, project_id: str, tenant_id: str
    ) -> ActiveSchemaSnapshot | None: ...

    async def require_legacy(self, *, project_id: str) -> None: ...

    async def find_membership(self, *, user_id: str, project_id: str) -> UserProject | None: ...

    async def list_entity_types(self, *, project_id: str) -> Sequence[EntityType]: ...

    async def create_entity_type(
        self, *, project_id: str, data: EntityTypeCreate
    ) -> EntityType: ...

    async def update_entity_type(
        self, *, project_id: str, entity_id: str, data: EntityTypeUpdate
    ) -> EntityType: ...

    async def delete_entity_type(self, *, project_id: str, entity_id: str) -> None: ...

    async def list_edge_types(self, *, project_id: str) -> Sequence[EdgeType]: ...

    async def create_edge_type(self, *, project_id: str, data: EdgeTypeCreate) -> EdgeType: ...

    async def update_edge_type(
        self, *, project_id: str, edge_id: str, data: EdgeTypeUpdate
    ) -> EdgeType: ...

    async def delete_edge_type(self, *, project_id: str, edge_id: str) -> None: ...

    async def list_edge_maps(self, *, project_id: str) -> Sequence[EdgeTypeMap]: ...

    async def create_edge_map(self, *, project_id: str, data: EdgeTypeMapCreate) -> EdgeTypeMap: ...

    async def delete_edge_map(self, *, project_id: str, map_id: str) -> None: ...


@dataclass(frozen=True, kw_only=True)
class SqlSchemaPersistenceV2:
    """SQL implementation bound to one operation-owned session."""

    _session: AsyncSession

    async def active_snapshot(
        self, *, project_id: str, tenant_id: str
    ) -> ActiveSchemaSnapshot | None:
        return await active_schema_snapshot(self._session, project_id, tenant_id=tenant_id)

    async def require_legacy(self, *, project_id: str) -> None:
        await require_legacy_schema(self._session, project_id)

    async def find_membership(self, *, user_id: str, project_id: str) -> UserProject | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(UserProject).where(
                    and_(
                        UserProject.user_id == user_id,
                        UserProject.project_id == project_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_entity_types(self, *, project_id: str) -> Sequence[EntityType]:
        result = await self._session.execute(
            refresh_select_statement(select(EntityType).where(EntityType.project_id == project_id))
        )
        return result.scalars().all()

    async def create_entity_type(self, *, project_id: str, data: EntityTypeCreate) -> EntityType:
        existing = await self._session.execute(
            refresh_select_statement(
                select(EntityType).where(
                    and_(EntityType.project_id == project_id, EntityType.name == data.name)
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise SchemaEntityTypeConflictV2
        entity_type = EntityType(
            id=str(uuid4()),
            project_id=project_id,
            name=data.name,
            description=data.description,
            schema=data.schema_def,
        )
        self._session.add(entity_type)
        await self._session.commit()
        await self._session.refresh(entity_type)
        return entity_type

    async def update_entity_type(
        self, *, project_id: str, entity_id: str, data: EntityTypeUpdate
    ) -> EntityType:
        entity_type = await self._session.get(EntityType, entity_id)
        if entity_type is None or entity_type.project_id != project_id:
            raise SchemaEntityTypeNotFoundV2
        if data.description is not None:
            entity_type.description = data.description
        if data.schema_def is not None:
            entity_type.schema = data.schema_def
        await self._session.commit()
        await self._session.refresh(entity_type)
        return entity_type

    async def delete_entity_type(self, *, project_id: str, entity_id: str) -> None:
        entity_type = await self._session.get(EntityType, entity_id)
        if entity_type is None or entity_type.project_id != project_id:
            raise SchemaEntityTypeNotFoundV2
        await self._session.delete(entity_type)
        await self._session.commit()

    async def list_edge_types(self, *, project_id: str) -> Sequence[EdgeType]:
        result = await self._session.execute(
            refresh_select_statement(select(EdgeType).where(EdgeType.project_id == project_id))
        )
        return result.scalars().all()

    async def create_edge_type(self, *, project_id: str, data: EdgeTypeCreate) -> EdgeType:
        existing = await self._session.execute(
            refresh_select_statement(
                select(EdgeType).where(
                    and_(EdgeType.project_id == project_id, EdgeType.name == data.name)
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise SchemaEdgeTypeConflictV2
        edge_type = EdgeType(
            id=str(uuid4()),
            project_id=project_id,
            name=data.name,
            description=data.description,
            schema=data.schema_def,
        )
        self._session.add(edge_type)
        await self._session.commit()
        await self._session.refresh(edge_type)
        return edge_type

    async def update_edge_type(
        self, *, project_id: str, edge_id: str, data: EdgeTypeUpdate
    ) -> EdgeType:
        edge_type = await self._session.get(EdgeType, edge_id)
        if edge_type is None or edge_type.project_id != project_id:
            raise SchemaEdgeTypeNotFoundV2
        if data.description is not None:
            edge_type.description = data.description
        if data.schema_def is not None:
            edge_type.schema = data.schema_def
        await self._session.commit()
        await self._session.refresh(edge_type)
        return edge_type

    async def delete_edge_type(self, *, project_id: str, edge_id: str) -> None:
        edge_type = await self._session.get(EdgeType, edge_id)
        if edge_type is None or edge_type.project_id != project_id:
            raise SchemaEdgeTypeNotFoundV2
        await self._session.delete(edge_type)
        await self._session.commit()

    async def list_edge_maps(self, *, project_id: str) -> Sequence[EdgeTypeMap]:
        result = await self._session.execute(
            refresh_select_statement(
                select(EdgeTypeMap).where(EdgeTypeMap.project_id == project_id)
            )
        )
        return result.scalars().all()

    async def create_edge_map(self, *, project_id: str, data: EdgeTypeMapCreate) -> EdgeTypeMap:
        existing = await self._session.execute(
            refresh_select_statement(
                select(EdgeTypeMap).where(
                    and_(
                        EdgeTypeMap.project_id == project_id,
                        EdgeTypeMap.source_type == data.source_type,
                        EdgeTypeMap.target_type == data.target_type,
                        EdgeTypeMap.edge_type == data.edge_type,
                    )
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise SchemaEdgeMapConflictV2
        edge_map = EdgeTypeMap(
            id=str(uuid4()),
            project_id=project_id,
            source_type=data.source_type,
            target_type=data.target_type,
            edge_type=data.edge_type,
        )
        self._session.add(edge_map)
        await self._session.commit()
        await self._session.refresh(edge_map)
        return edge_map

    async def delete_edge_map(self, *, project_id: str, map_id: str) -> None:
        edge_map = await self._session.get(EdgeTypeMap, map_id)
        if edge_map is None or edge_map.project_id != project_id:
            raise SchemaEdgeMapNotFoundV2
        await self._session.delete(edge_map)
        await self._session.commit()


@dataclass(frozen=True, kw_only=True)
class SchemaApplicationServicesV2:
    """Project-schema operations with structural membership and role enforcement."""

    persistence: SchemaPersistenceProtocolV2
    authorization: ProjectSchemaAuthorization
    scope: ProjectSchemaScope
    mutations: SqlProjectSchemaHttpCommands

    @property
    def documents(self) -> SchemaDocumentServicesV2:
        return SchemaDocumentServicesV2(
            commands=SqlProjectSchemaCommands(
                sessions=self.mutations.sessions, authorization=self.authorization
            ),
            scope=self.scope,
        )

    async def _authorize(self, *, user_id: str, project_id: str, write: bool) -> None:
        if (user_id, project_id) != (self.scope.actor_id, self.scope.project_id):
            raise SchemaAccessDeniedV2
        try:
            await self.authorization.authorize(
                self.scope, ProjectSchemaAction.REPLACE if write else ProjectSchemaAction.READ
            )
        except ProjectSchemaError as error:
            if error.code != "project_schema_access_denied":
                raise
            raise SchemaAccessDeniedV2 from error

    async def _read(self, *, user_id: str, project_id: str, kind: str) -> Sequence[Any]:
        await self._authorize(user_id=user_id, project_id=project_id, write=False)
        snapshot = await self.persistence.active_snapshot(
            project_id=project_id, tenant_id=self.scope.tenant_id
        )
        await self._authorize(user_id=user_id, project_id=project_id, write=False)
        if snapshot is not None:
            return snapshot.mappings() if kind == "mappings" else snapshot.types(kind)
        result: Sequence[Any]
        if kind == "entity_types":
            result = await self.persistence.list_entity_types(project_id=project_id)
        elif kind == "edge_types":
            result = await self.persistence.list_edge_types(project_id=project_id)
        else:
            result = await self.persistence.list_edge_maps(project_id=project_id)
        await self._authorize(user_id=user_id, project_id=project_id, write=False)
        return result

    async def list_entity_types(self, *, user_id: str, project_id: str) -> Sequence[EntityType]:
        return await self._read(user_id=user_id, project_id=project_id, kind="entity_types")

    async def _mutate[MutationResultT](
        self,
        *,
        user_id: str,
        project_id: str,
        operation: SchemaHttpOperation,
        target_id: str | None,
        fields: dict[str, Any],
        expected_revision: str | None,
        change_id: str | None,
        legacy: Callable[[AsyncSession], Awaitable[MutationResultT]],
    ) -> MutationResultT | SchemaHttpReceipt:
        if (user_id, project_id) != (self.scope.actor_id, self.scope.project_id):
            raise SchemaAccessDeniedV2
        command = SchemaHttpMutation.from_fields(
            scope=self.scope,
            operation=operation,
            target_id=target_id,
            fields=fields,
            expected_revision=expected_revision,
            change_id=change_id,
        )
        try:
            return await self.mutations.execute(command, legacy=legacy)
        except ProjectSchemaError as error:
            if error.code == "project_schema_access_denied":
                raise SchemaAccessDeniedV2 from error
            raise

    async def create_entity_type(
        self,
        *,
        user_id: str,
        project_id: str,
        data: EntityTypeCreate,
        expected_revision: str | None = None,
        change_id: str | None = None,
    ) -> EntityType | SchemaHttpReceipt:
        return await self._mutate(
            user_id=user_id,
            project_id=project_id,
            operation=SchemaHttpOperation.CREATE_ENTITY,
            target_id=None,
            fields=data.model_dump(mode="python", by_alias=True, exclude_unset=True),
            expected_revision=expected_revision,
            change_id=change_id,
            legacy=lambda db: SqlSchemaPersistenceV2(_session=db).create_entity_type(
                project_id=project_id, data=data
            ),
        )

    async def update_entity_type(
        self,
        *,
        user_id: str,
        project_id: str,
        entity_id: str,
        data: EntityTypeUpdate,
        expected_revision: str | None = None,
        change_id: str | None = None,
    ) -> EntityType | SchemaHttpReceipt:
        return await self._mutate(
            user_id=user_id,
            project_id=project_id,
            operation=SchemaHttpOperation.UPDATE_ENTITY,
            target_id=entity_id,
            fields=data.model_dump(mode="python", by_alias=True, exclude_unset=True),
            expected_revision=expected_revision,
            change_id=change_id,
            legacy=lambda db: SqlSchemaPersistenceV2(_session=db).update_entity_type(
                project_id=project_id, entity_id=entity_id, data=data
            ),
        )

    async def delete_entity_type(
        self,
        *,
        user_id: str,
        project_id: str,
        entity_id: str,
        expected_revision: str | None = None,
        change_id: str | None = None,
    ) -> SchemaHttpReceipt | None:
        return await self._mutate(
            user_id=user_id,
            project_id=project_id,
            operation=SchemaHttpOperation.DELETE_ENTITY,
            target_id=entity_id,
            fields={},
            expected_revision=expected_revision,
            change_id=change_id,
            legacy=lambda db: SqlSchemaPersistenceV2(_session=db).delete_entity_type(
                project_id=project_id, entity_id=entity_id
            ),
        )

    async def list_edge_types(self, *, user_id: str, project_id: str) -> Sequence[EdgeType]:
        return await self._read(user_id=user_id, project_id=project_id, kind="edge_types")

    async def create_edge_type(
        self,
        *,
        user_id: str,
        project_id: str,
        data: EdgeTypeCreate,
        expected_revision: str | None = None,
        change_id: str | None = None,
    ) -> EdgeType | SchemaHttpReceipt:
        return await self._mutate(
            user_id=user_id,
            project_id=project_id,
            operation=SchemaHttpOperation.CREATE_EDGE,
            target_id=None,
            fields=data.model_dump(mode="python", by_alias=True, exclude_unset=True),
            expected_revision=expected_revision,
            change_id=change_id,
            legacy=lambda db: SqlSchemaPersistenceV2(_session=db).create_edge_type(
                project_id=project_id, data=data
            ),
        )

    async def update_edge_type(
        self,
        *,
        user_id: str,
        project_id: str,
        edge_id: str,
        data: EdgeTypeUpdate,
        expected_revision: str | None = None,
        change_id: str | None = None,
    ) -> EdgeType | SchemaHttpReceipt:
        return await self._mutate(
            user_id=user_id,
            project_id=project_id,
            operation=SchemaHttpOperation.UPDATE_EDGE,
            target_id=edge_id,
            fields=data.model_dump(mode="python", by_alias=True, exclude_unset=True),
            expected_revision=expected_revision,
            change_id=change_id,
            legacy=lambda db: SqlSchemaPersistenceV2(_session=db).update_edge_type(
                project_id=project_id, edge_id=edge_id, data=data
            ),
        )

    async def delete_edge_type(
        self,
        *,
        user_id: str,
        project_id: str,
        edge_id: str,
        expected_revision: str | None = None,
        change_id: str | None = None,
    ) -> SchemaHttpReceipt | None:
        return await self._mutate(
            user_id=user_id,
            project_id=project_id,
            operation=SchemaHttpOperation.DELETE_EDGE,
            target_id=edge_id,
            fields={},
            expected_revision=expected_revision,
            change_id=change_id,
            legacy=lambda db: SqlSchemaPersistenceV2(_session=db).delete_edge_type(
                project_id=project_id, edge_id=edge_id
            ),
        )

    async def list_edge_maps(self, *, user_id: str, project_id: str) -> Sequence[EdgeTypeMap]:
        return await self._read(user_id=user_id, project_id=project_id, kind="mappings")

    async def create_edge_map(
        self,
        *,
        user_id: str,
        project_id: str,
        data: EdgeTypeMapCreate,
        expected_revision: str | None = None,
        change_id: str | None = None,
    ) -> EdgeTypeMap | SchemaHttpReceipt:
        return await self._mutate(
            user_id=user_id,
            project_id=project_id,
            operation=SchemaHttpOperation.CREATE_MAP,
            target_id=None,
            fields=data.model_dump(mode="python", by_alias=True, exclude_unset=True),
            expected_revision=expected_revision,
            change_id=change_id,
            legacy=lambda db: SqlSchemaPersistenceV2(_session=db).create_edge_map(
                project_id=project_id, data=data
            ),
        )

    async def delete_edge_map(
        self,
        *,
        user_id: str,
        project_id: str,
        map_id: str,
        expected_revision: str | None = None,
        change_id: str | None = None,
    ) -> SchemaHttpReceipt | None:
        return await self._mutate(
            user_id=user_id,
            project_id=project_id,
            operation=SchemaHttpOperation.DELETE_MAP,
            target_id=map_id,
            fields={},
            expected_revision=expected_revision,
            change_id=change_id,
            legacy=lambda db: SqlSchemaPersistenceV2(_session=db).delete_edge_map(
                project_id=project_id, map_id=map_id
            ),
        )


@runtime_checkable
class SchemaServiceFactoryProtocolV2(Protocol):
    """Provider contract hiding concrete persistence implementations."""

    def build(self, operation: OperationContextV2) -> SchemaPersistenceProtocolV2: ...

    def authorization(self, operation: OperationContextV2) -> SqlProjectSchemaAuthorizationV2: ...

    def mutations(
        self, operation: OperationContextV2, authorization: ProjectSchemaAuthorization
    ) -> SqlProjectSchemaHttpCommands: ...


@runtime_checkable
class SchemaApplicationResolverProtocolV2(Protocol):
    """Application resolver injected through a declared service alias."""

    def resolve(self, operation: OperationContextV2) -> SchemaApplicationServicesV2: ...

    async def discover_scope(
        self, operation: OperationContextV2, project_id: str
    ) -> ProjectSchemaScope: ...


@dataclass(frozen=True, kw_only=True)
class SqlSchemaServiceFactoryV2:
    """Build schema persistence from the operation's exact AsyncSession."""

    strategy: str

    def mutations(
        self, operation: OperationContextV2, authorization: ProjectSchemaAuthorization
    ) -> SqlProjectSchemaHttpCommands:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession) or not isinstance(db.bind, AsyncEngine):
            raise RuntimeV2Error(
                "invalid_operation_db_engine",
                "schema mutations require the operation's AsyncEngine",
            )
        return SqlProjectSchemaHttpCommands(
            sessions=async_sessionmaker(db.bind, expire_on_commit=False),
            authorization=authorization,
        )

    def authorization(self, operation: OperationContextV2) -> SqlProjectSchemaAuthorizationV2:
        identity = operation.require("service:operation.identity")
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession) or not isinstance(identity, Mapping):
            raise SchemaAccessDeniedV2
        actor_id = cast(Mapping[str, object], identity).get("user_id")
        if not isinstance(actor_id, str) or not actor_id:
            raise SchemaAccessDeniedV2
        return SqlProjectSchemaAuthorizationV2(
            operation=operation, session=db, actor_id=actor_id, scope=operation.context.scope
        )

    def build(self, operation: OperationContextV2) -> SchemaPersistenceProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "schema services require an AsyncSession operation service",
            )
        return SqlSchemaPersistenceV2(_session=db)


@dataclass(frozen=True, kw_only=True)
class SchemaApplicationResolverV2:
    """Resolve operation-owned application services without exposing the Provider."""

    provider: SchemaServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> SchemaApplicationServicesV2:
        authorization = self.provider.authorization(operation)
        scope = authorization.scope
        if scope.tenant_id is None or scope.project_id is None:
            raise SchemaAccessDeniedV2
        return SchemaApplicationServicesV2(
            persistence=self.provider.build(operation),
            authorization=authorization,
            mutations=self.provider.mutations(operation, authorization),
            scope=ProjectSchemaScope(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                actor_id=authorization.actor_id,
            ),
        )

    async def discover_scope(
        self, operation: OperationContextV2, project_id: str
    ) -> ProjectSchemaScope:
        return await self.provider.authorization(operation).discover_scope(project_id)


def _apply_schema_provider_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("schema provider requires strategy request-async-session")
    _ = context.provide(
        SCHEMA_PROVIDER_SERVICE_V2,
        SqlSchemaServiceFactoryV2(strategy=strategy),
        label="schema-provider",
    )


def _apply_schema_application_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    strategy = config.get("strategy")
    if strategy != "operation-scoped-provider":
        raise ValueError("schema application resolver requires strategy operation-scoped-provider")
    provider = context.require(SCHEMA_PROVIDER_INJECT_V2)
    if not isinstance(provider, SchemaServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_schema_provider",
            "schema provider inject does not implement the factory contract",
        )
    _ = context.provide(
        SCHEMA_APPLICATION_SERVICE_V2,
        SchemaApplicationResolverV2(provider=provider),
        label="schema-application",
    )


def schema_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=SCHEMA_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SCHEMA_PROVIDER_MODULE_V2),
            apply=_apply_schema_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=SCHEMA_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SCHEMA_APPLICATION_MODULE_V2),
            apply=_apply_schema_application_v2,
        ),
    )


__all__ = [
    "SCHEMA_APPLICATION_MODULE_V2",
    "SCHEMA_APPLICATION_SERVICE_V2",
    "SCHEMA_PROVIDER_INJECT_V2",
    "SCHEMA_PROVIDER_MODULE_V2",
    "SCHEMA_PROVIDER_SERVICE_V2",
    "SCHEMA_WRITE_ROLES_V2",
    "SchemaAccessDeniedV2",
    "SchemaApplicationResolverProtocolV2",
    "SchemaApplicationResolverV2",
    "SchemaApplicationServicesV2",
    "SchemaEdgeMapConflictV2",
    "SchemaEdgeMapNotFoundV2",
    "SchemaEdgeTypeConflictV2",
    "SchemaEdgeTypeNotFoundV2",
    "SchemaEntityTypeConflictV2",
    "SchemaEntityTypeNotFoundV2",
    "SchemaPersistenceProtocolV2",
    "SchemaServiceErrorV2",
    "SchemaServiceFactoryProtocolV2",
    "SqlSchemaPersistenceV2",
    "SqlSchemaServiceFactoryV2",
    "schema_service_definitions_v2",
]
