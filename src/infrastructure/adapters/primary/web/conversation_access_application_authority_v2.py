# pyright: reportImportCycles=false
"""WebSocket authority for generation-owned conversation access."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

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
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error

if TYPE_CHECKING:
    from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext


@dataclass(frozen=True, kw_only=True)
class ConversationAccessApplicationAuthorityV2:
    """One message-owned conversation service and its disposable operation."""

    operation: OperationContextV2
    service: ConversationAccessServiceV2


@asynccontextmanager
async def conversation_access_application_authority_v2(
    context: MessageContext,
    *,
    conversation_id: str,
) -> AsyncIterator[ConversationAccessApplicationAuthorityV2]:
    """Resolve conversation access from the generation pinned to this connection."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"websocket-conversation-access:{conversation_id}:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, context.db)
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"tenant_id": context.tenant_id, "user_id": context.user_id},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {
                "kind": "websocket-conversation-access",
                "conversation_id": conversation_id,
            },
        )
        resolver = operation.require(CONVERSATION_ACCESS_SERVICE_V2)
        if not isinstance(resolver, ConversationAccessResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_conversation_access_resolver",
                "conversation access service has an invalid implementation",
            )
        yield ConversationAccessApplicationAuthorityV2(
            operation=operation,
            service=resolver.resolve(operation),
        )


__all__ = [
    "ConversationAccessApplicationAuthorityV2",
    "conversation_access_application_authority_v2",
]
