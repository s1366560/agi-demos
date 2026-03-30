from __future__ import annotations

from datetime import datetime
from typing import Any, override

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.invitation.invitation import Invitation
from src.domain.ports.repositories.invitation_repository import InvitationRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    InvitationModel,
)


class SqlInvitationRepository(InvitationRepository):
    def __init__(self, db: AsyncSession) -> None:
        self._session = db

    @override
    async def save(self, invitation: Invitation) -> Invitation:
        db_model = self._to_db(invitation)
        self._session.add(db_model)
        await self._session.flush()
        return invitation

    @override
    async def find_by_id(self, invitation_id: str) -> Invitation | None:
        stmt = select(InvitationModel).where(InvitationModel.id == invitation_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    @override
    async def find_by_token(self, token: str) -> Invitation | None:
        stmt = select(InvitationModel).where(InvitationModel.token == token)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    @override
    async def find_pending_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Invitation]:
        stmt = (
            select(InvitationModel)
            .where(
                InvitationModel.tenant_id == tenant_id,
                InvitationModel.status == "pending",
                InvitationModel.deleted_at.is_(None),
            )
            .order_by(InvitationModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    @override
    async def count_pending_by_tenant(self, tenant_id: str) -> int:
        stmt: Select[Any] = (
            select(func.count())
            .select_from(InvitationModel)
            .where(
                InvitationModel.tenant_id == tenant_id,
                InvitationModel.status == "pending",
                InvitationModel.deleted_at.is_(None),
            )
        )
        result = await self._session.execute(stmt)
        count: Any = result.scalar_one()
        return int(count)

    @override
    async def find_pending_by_email_and_tenant(
        self,
        email: str,
        tenant_id: str,
    ) -> Invitation | None:
        stmt = select(InvitationModel).where(
            InvitationModel.email == email.lower().strip(),
            InvitationModel.tenant_id == tenant_id,
            InvitationModel.status == "pending",
            InvitationModel.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    @override
    async def soft_delete(self, invitation_id: str, deleted_at: datetime) -> None:
        stmt = (
            update(InvitationModel)
            .where(InvitationModel.id == invitation_id)
            .values(deleted_at=deleted_at, status="cancelled")
        )
        await self._session.execute(stmt)
        await self._session.flush()

    @override
    async def update_status(
        self,
        invitation_id: str,
        status: str,
        *,
        accepted_by: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status}
        if accepted_by is not None:
            values["accepted_by"] = accepted_by
        stmt = update(InvitationModel).where(InvitationModel.id == invitation_id).values(**values)
        await self._session.execute(stmt)
        await self._session.flush()

    @staticmethod
    def _to_domain(row: InvitationModel) -> Invitation:
        return Invitation(
            id=row.id,
            tenant_id=row.tenant_id,
            email=row.email,
            role=row.role,
            token=row.token,
            status=row.status,
            invited_by=row.invited_by,
            accepted_by=row.accepted_by,
            expires_at=row.expires_at,
            created_at=row.created_at,
            deleted_at=row.deleted_at,
        )

    @staticmethod
    def _to_db(invitation: Invitation) -> InvitationModel:
        return InvitationModel(
            id=invitation.id,
            tenant_id=invitation.tenant_id,
            email=invitation.email,
            role=invitation.role,
            token=invitation.token,
            status=invitation.status,
            invited_by=invitation.invited_by,
            accepted_by=invitation.accepted_by,
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
            deleted_at=invitation.deleted_at,
        )
