"""SQL persistence for durable client agent-turn idempotency."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import override

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import (
    AgentClientTurn,
    AgentClientTurnClaim,
    AgentClientTurnNotFoundError,
    AgentClientTurnPayloadConflictError,
    AgentClientTurnStatus,
)
from src.domain.ports.repositories.agent_repository import AgentClientTurnRepository
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import AgentClientTurnModel

_EXECUTION_MESSAGE_NAMESPACE = uuid.UUID("960c27ad-b77a-4c2a-af53-7f39e420f3a1")


class SqlAgentClientTurnRepository(AgentClientTurnRepository):
    """Atomically bind one client message ID to one canonical turn payload."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def find(
        self,
        conversation_id: str,
        client_message_id: str,
    ) -> AgentClientTurn | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(AgentClientTurnModel).where(
                    AgentClientTurnModel.conversation_id == conversation_id,
                    AgentClientTurnModel.client_message_id == client_message_id,
                )
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    @override
    async def claim_and_commit(
        self,
        *,
        conversation_id: str,
        client_message_id: str,
        payload_hash: str,
    ) -> AgentClientTurnClaim:
        values = {
            "id": str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "client_message_id": client_message_id,
            "payload_hash": payload_hash,
            "execution_message_id": self.execution_message_id(
                conversation_id,
                client_message_id,
            ),
            "status": AgentClientTurnStatus.ACCEPTED.value,
        }
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "sqlite":
            statement = sqlite_insert(AgentClientTurnModel).values(**values)
        else:
            statement = pg_insert(AgentClientTurnModel).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=["conversation_id", "client_message_id"]
        ).returning(AgentClientTurnModel)

        result = await self._session.execute(statement)
        inserted = result.scalar_one_or_none()
        if inserted is not None:
            turn = self._to_domain(inserted)
            await self._session.commit()
            return AgentClientTurnClaim(turn=turn, created=True)

        existing = await self.find(conversation_id, client_message_id)
        await self._session.commit()
        if existing is None:
            raise AgentClientTurnNotFoundError(
                "Client turn disappeared after an idempotency conflict"
            )
        self._ensure_payload_matches(existing, payload_hash)
        return AgentClientTurnClaim(turn=existing, created=False)

    @override
    async def try_start(
        self,
        *,
        conversation_id: str,
        client_message_id: str,
        payload_hash: str,
    ) -> bool:
        existing = await self.find(conversation_id, client_message_id)
        if existing is None:
            await self._session.rollback()
            raise AgentClientTurnNotFoundError("Client turn was not durably accepted")
        try:
            self._ensure_payload_matches(existing, payload_hash)
        except AgentClientTurnPayloadConflictError:
            await self._session.rollback()
            raise

        result = await self._session.execute(
            refresh_select_statement(
                update(AgentClientTurnModel)
                .where(
                    AgentClientTurnModel.conversation_id == conversation_id,
                    AgentClientTurnModel.client_message_id == client_message_id,
                    AgentClientTurnModel.payload_hash == payload_hash,
                    AgentClientTurnModel.status == AgentClientTurnStatus.ACCEPTED.value,
                )
                .values(
                    status=AgentClientTurnStatus.STARTED.value,
                    started_at=datetime.now(UTC),
                )
                .returning(AgentClientTurnModel.id)
            )
        )
        started = result.scalar_one_or_none() is not None
        if not started:
            await self._session.rollback()
        return started

    @staticmethod
    def execution_message_id(conversation_id: str, client_message_id: str) -> str:
        """Derive an actor-safe stable ID from the full idempotency key."""
        return str(
            uuid.uuid5(
                _EXECUTION_MESSAGE_NAMESPACE,
                f"{conversation_id}\0{client_message_id}",
            )
        )

    @staticmethod
    def _ensure_payload_matches(turn: AgentClientTurn, payload_hash: str) -> None:
        if turn.payload_hash != payload_hash:
            raise AgentClientTurnPayloadConflictError(
                "Client message ID is already bound to a different payload"
            )

    @staticmethod
    def _to_domain(row: AgentClientTurnModel) -> AgentClientTurn:
        return AgentClientTurn(
            id=row.id,
            conversation_id=row.conversation_id,
            client_message_id=row.client_message_id,
            payload_hash=row.payload_hash,
            execution_message_id=row.execution_message_id,
            status=AgentClientTurnStatus(row.status),
            created_at=row.created_at,
            started_at=row.started_at,
        )
