"""Generation-owned persistence Provider for conversation collection queries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy import String, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import ColumnElement, Select, Subquery
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.functions import FunctionElement

from src.domain.model.agent import Conversation, ConversationStatus
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent as AgentExecutionEventModel,
    Conversation as ConversationModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
    conversation_activity_order,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/conversation-collection-repository-provider"
)
CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_SERVICE_V2 = (
    "service:persistence.conversation-collection-repository-provider"
)
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


class _LegacyWorkspaceId(FunctionElement[str]):
    type = String()
    inherit_cache = True


class _MetadataWorkspaceId(FunctionElement[str]):
    type = String()
    inherit_cache = True


@compiles(_MetadataWorkspaceId, "postgresql")
def _compile_metadata_workspace_id_postgresql(  # pyright: ignore[reportUnusedFunction]
    element: _MetadataWorkspaceId,
    compiler: SQLCompiler,
    **_kwargs: object,
) -> str:
    metadata = next(iter(element.clauses))
    compiled_metadata = compiler.process(metadata)
    return (
        "CASE "
        f"WHEN json_typeof({compiled_metadata} -> 'workspace_id') = 'string' "
        f"THEN NULLIF(TRIM({compiled_metadata} ->> 'workspace_id'), '') "
        "ELSE NULL END"
    )


@compiles(_MetadataWorkspaceId, "sqlite")
def _compile_metadata_workspace_id_sqlite(  # pyright: ignore[reportUnusedFunction]
    element: _MetadataWorkspaceId,
    compiler: SQLCompiler,
    **_kwargs: object,
) -> str:
    metadata = next(iter(element.clauses))
    compiled_metadata = compiler.process(metadata)
    return (
        "CASE "
        f"WHEN json_type({compiled_metadata}, '$.workspace_id') = 'text' "
        f"THEN NULLIF(TRIM(json_extract({compiled_metadata}, '$.workspace_id')), '') "
        "ELSE NULL END"
    )


@compiles(_LegacyWorkspaceId, "postgresql")
def _compile_legacy_workspace_id_postgresql(  # pyright: ignore[reportUnusedFunction]
    element: _LegacyWorkspaceId,
    compiler: SQLCompiler,
    **_kwargs: object,
) -> str:
    conversation_id = next(iter(element.clauses))
    compiled_id = compiler.process(conversation_id)
    return f"NULLIF(TRIM(SPLIT_PART({compiled_id}, ':', 2)), '')"


@compiles(_LegacyWorkspaceId, "sqlite")
def _compile_legacy_workspace_id_sqlite(  # pyright: ignore[reportUnusedFunction]
    element: _LegacyWorkspaceId,
    compiler: SQLCompiler,
    **_kwargs: object,
) -> str:
    conversation_id = next(iter(element.clauses))
    compiled_id = compiler.process(conversation_id)
    remainder = f"SUBSTR({compiled_id}, INSTR({compiled_id}, ':') + 1)"
    segment_length = (
        f"CASE INSTR({remainder}, ':') "
        f"WHEN 0 THEN LENGTH({remainder}) ELSE INSTR({remainder}, ':') - 1 END"
    )
    return f"NULLIF(TRIM(SUBSTR({remainder}, 1, {segment_length})), '')"


def _last_activity_subquery() -> Subquery:
    return (
        select(
            AgentExecutionEventModel.conversation_id,
            func.max(AgentExecutionEventModel.event_time_us).label("last_event_time_us"),
        )
        .group_by(AgentExecutionEventModel.conversation_id)
        .subquery("last_activity")
    )


def _ordered_conversation_query() -> Select[tuple[ConversationModel]]:
    last_activity_subquery = _last_activity_subquery()
    return (
        select(ConversationModel)
        .outerjoin(
            last_activity_subquery,
            ConversationModel.id == last_activity_subquery.c.conversation_id,
        )
        .order_by(
            *conversation_activity_order(
                cast("ColumnElement[int]", last_activity_subquery.c.last_event_time_us)
            )
        )
    )


def _effective_workspace_id_expression() -> ColumnElement[str | None]:
    persisted_workspace_id = func.nullif(func.trim(ConversationModel.workspace_id), "")
    metadata_workspace_id = _MetadataWorkspaceId(ConversationModel.meta)
    legacy_workspace_id = case(
        (
            ConversationModel.id.like("workspace-%:%"),
            _LegacyWorkspaceId(ConversationModel.id),
        ),
        else_=None,
    )
    return cast(
        "ColumnElement[str | None]",
        func.coalesce(
            persisted_workspace_id,
            metadata_workspace_id,
            legacy_workspace_id,
        ),
    )


def _workspace_link_filter(workspace_ids: set[str]) -> ColumnElement[bool]:
    return _effective_workspace_id_expression().in_(workspace_ids)


def _unbound_workspace_filter() -> ColumnElement[bool]:
    return _effective_workspace_id_expression().is_(None)


@runtime_checkable
class ConversationCollectionRepositoryProtocolV2(Protocol):
    """Persistence surface for all create/list collection shapes."""

    async def save(self, conversation: Conversation) -> Conversation: ...

    async def list_default(
        self,
        *,
        project_id: str,
        tenant_id: str,
        status: ConversationStatus | None,
        limit: int,
        offset: int,
    ) -> list[Conversation]: ...

    async def count_default(
        self,
        *,
        project_id: str,
        tenant_id: str,
        status: ConversationStatus | None,
    ) -> int: ...

    async def list_workspace(
        self,
        *,
        project_id: str,
        tenant_id: str,
        workspace_ids: set[str],
        status: ConversationStatus | None,
        limit: int | None,
        offset: int,
    ) -> list[Conversation]: ...

    async def count_workspace(
        self,
        *,
        project_id: str,
        tenant_id: str,
        workspace_id: str,
        status: ConversationStatus | None,
    ) -> int: ...

    async def list_unbound(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        status: ConversationStatus | None,
        limit: int,
        offset: int,
    ) -> list[Conversation]: ...

    async def count_unbound(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        status: ConversationStatus | None,
    ) -> int: ...


class SqlConversationCollectionRepositoryV2:
    """SQL adapter kept behind the collection repository Provider contract."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._conversation = SqlConversationRepository(session)

    async def save(self, conversation: Conversation) -> Conversation:
        return await self._conversation.save(conversation)

    async def list_default(
        self,
        *,
        project_id: str,
        tenant_id: str,
        status: ConversationStatus | None,
        limit: int,
        offset: int,
    ) -> list[Conversation]:
        query = _ordered_conversation_query().where(
            ConversationModel.project_id == project_id,
            ConversationModel.tenant_id == tenant_id,
        )
        if status is not None:
            query = query.where(ConversationModel.status == status.value)
        return await self._list(query.offset(offset).limit(limit))

    async def count_default(
        self,
        *,
        project_id: str,
        tenant_id: str,
        status: ConversationStatus | None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ConversationModel)
            .where(
                ConversationModel.project_id == project_id,
                ConversationModel.tenant_id == tenant_id,
            )
        )
        if status is not None:
            query = query.where(ConversationModel.status == status.value)
        return await self._count(query)

    async def list_workspace(
        self,
        *,
        project_id: str,
        tenant_id: str,
        workspace_ids: set[str],
        status: ConversationStatus | None,
        limit: int | None,
        offset: int,
    ) -> list[Conversation]:
        if not workspace_ids:
            return []
        query = _ordered_conversation_query().where(
            ConversationModel.project_id == project_id,
            ConversationModel.tenant_id == tenant_id,
            _workspace_link_filter(workspace_ids),
        )
        if status is not None:
            query = query.where(ConversationModel.status == status.value)
        if limit is not None:
            query = query.offset(offset).limit(limit)
        return await self._list(query)

    async def count_workspace(
        self,
        *,
        project_id: str,
        tenant_id: str,
        workspace_id: str,
        status: ConversationStatus | None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ConversationModel)
            .where(
                ConversationModel.project_id == project_id,
                ConversationModel.tenant_id == tenant_id,
                _workspace_link_filter({workspace_id}),
            )
        )
        if status is not None:
            query = query.where(ConversationModel.status == status.value)
        return await self._count(query)

    async def list_unbound(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        status: ConversationStatus | None,
        limit: int,
        offset: int,
    ) -> list[Conversation]:
        query = _ordered_conversation_query().where(
            ConversationModel.project_id == project_id,
            ConversationModel.tenant_id == tenant_id,
            ConversationModel.user_id == user_id,
            _unbound_workspace_filter(),
        )
        if status is not None:
            query = query.where(ConversationModel.status == status.value)
        return await self._list(query.offset(offset).limit(limit))

    async def count_unbound(
        self,
        *,
        project_id: str,
        tenant_id: str,
        user_id: str,
        status: ConversationStatus | None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ConversationModel)
            .where(
                ConversationModel.project_id == project_id,
                ConversationModel.tenant_id == tenant_id,
                ConversationModel.user_id == user_id,
                _unbound_workspace_filter(),
            )
        )
        if status is not None:
            query = query.where(ConversationModel.status == status.value)
        return await self._count(query)

    async def _list(self, query: Select[tuple[ConversationModel]]) -> list[Conversation]:
        result = await self.session.execute(refresh_select_statement(query))
        return [
            domain
            for row in result.scalars().all()
            if (domain := self._conversation._to_domain(row)) is not None
        ]

    async def _count(self, query: Select[tuple[int]]) -> int:
        result = await self.session.execute(refresh_select_statement(query))
        return result.scalar() or 0


@runtime_checkable
class ConversationCollectionRepositoryFactoryProtocolV2(Protocol):
    """Build one collection repository from the operation-owned DB session."""

    def build(
        self, operation: OperationContextV2
    ) -> ConversationCollectionRepositoryProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlConversationCollectionRepositoryFactoryV2:
    strategy: str

    def build(self, operation: OperationContextV2) -> ConversationCollectionRepositoryProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "conversation collection requires an AsyncSession operation service",
            )
        return SqlConversationCollectionRepositoryV2(db)


def _apply_conversation_collection_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "conversation collection repository provider requires strategy request-async-session"
        )
    _ = context.provide(
        CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlConversationCollectionRepositoryFactoryV2(strategy=strategy),
        label="conversation-collection-repository-provider",
    )


def conversation_collection_repository_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(
            CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_MODULE_V2
        ),
        apply=_apply_conversation_collection_repository_provider_v2,
    )


__all__ = [
    "CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_MODULE_V2",
    "CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_SERVICE_V2",
    "ConversationCollectionRepositoryFactoryProtocolV2",
    "ConversationCollectionRepositoryProtocolV2",
    "SqlConversationCollectionRepositoryFactoryV2",
    "SqlConversationCollectionRepositoryV2",
    "conversation_collection_repository_definition_v2",
]
