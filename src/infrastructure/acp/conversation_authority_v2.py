"""Generation-owned conversation authorities for the native ACP server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_ACCESS_SERVICE_V2,
    ConversationAccessResolverProtocolV2,
    ConversationAccessServiceV2,
)
from src.infrastructure.plugins.v2.conversation_collection_services import (
    CONVERSATION_COLLECTION_SERVICE_V2,
    ConversationCollectionResolverProtocolV2,
    ConversationCollectionServiceV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class ACPConversationCollectionAuthorityV2:
    operation: OperationContextV2
    service: ConversationCollectionServiceV2


@dataclass(frozen=True, kw_only=True)
class ACPConversationAccessAuthorityV2:
    operation: OperationContextV2
    service: ConversationAccessServiceV2


def _operation_v2(
    *,
    operation_id: str,
    tenant_id: str,
    project_id: str,
) -> OperationContextV2:
    return OperationContextV2(
        generation=current_generation_v2(),
        operation_id=operation_id,
        scope=ScopeV2(
            kind=ScopeKindV2.PROJECT,
            tenant_id=tenant_id,
            project_id=project_id,
        ),
    )


def _provide_operation_services_v2(
    operation: OperationContextV2,
    *,
    db: AsyncSession,
    tenant_id: str,
    user_id: str,
    project_id: str,
    kind: str,
    conversation_id: str | None = None,
) -> None:
    _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
    _ = operation.provide(
        OPERATION_IDENTITY_SERVICE_V2,
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
        },
    )
    metadata = {"kind": kind, "project_id": project_id}
    if conversation_id is not None:
        metadata["conversation_id"] = conversation_id
    _ = operation.provide(OPERATION_METADATA_SERVICE_V2, metadata)


@asynccontextmanager
async def acp_conversation_collection_authority_v2(
    *,
    operation_id: str,
    db: AsyncSession,
    tenant_id: str,
    user_id: str,
    project_id: str,
) -> AsyncIterator[ACPConversationCollectionAuthorityV2]:
    operation = _operation_v2(
        operation_id=operation_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    async with operation:
        _provide_operation_services_v2(
            operation,
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            kind="acp-conversation-create",
        )
        resolver = operation.require(CONVERSATION_COLLECTION_SERVICE_V2)
        if not isinstance(resolver, ConversationCollectionResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_conversation_collection_resolver",
                "ACP conversation collection service has an invalid implementation",
            )
        yield ACPConversationCollectionAuthorityV2(
            operation=operation,
            service=resolver.resolve(operation),
        )


@asynccontextmanager
async def acp_conversation_access_authority_v2(
    *,
    operation_id: str,
    db: AsyncSession,
    tenant_id: str,
    user_id: str,
    project_id: str,
    conversation_id: str,
) -> AsyncIterator[ACPConversationAccessAuthorityV2]:
    operation = _operation_v2(
        operation_id=operation_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    async with operation:
        _provide_operation_services_v2(
            operation,
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            kind="acp-conversation-access",
            conversation_id=conversation_id,
        )
        resolver = operation.require(CONVERSATION_ACCESS_SERVICE_V2)
        if not isinstance(resolver, ConversationAccessResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_conversation_access_resolver",
                "ACP conversation access service has an invalid implementation",
            )
        yield ACPConversationAccessAuthorityV2(
            operation=operation,
            service=resolver.resolve(operation),
        )


__all__ = [
    "ACPConversationAccessAuthorityV2",
    "ACPConversationCollectionAuthorityV2",
    "acp_conversation_access_authority_v2",
    "acp_conversation_collection_authority_v2",
]
