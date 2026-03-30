from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from src.domain.model.invitation.invitation import Invitation
from src.domain.ports.repositories.invitation_repository import InvitationRepository

logger = logging.getLogger(__name__)

INVITATION_EXPIRY_DAYS = 7


class InvitationService:
    def __init__(self, invitation_repo: InvitationRepository) -> None:
        self._repo = invitation_repo

    async def create_invitation(
        self,
        tenant_id: str,
        email: str,
        role: str,
        invited_by: str,
    ) -> Invitation:
        existing = await self._repo.find_pending_by_email_and_tenant(email, tenant_id)
        if existing is not None:
            raise ValueError(f"A pending invitation already exists for {email}")

        invitation = Invitation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            email=email.lower().strip(),
            role=role,
            token=secrets.token_urlsafe(32),
            status="pending",
            invited_by=invited_by,
            expires_at=datetime.now(UTC) + timedelta(days=INVITATION_EXPIRY_DAYS),
            created_at=datetime.now(UTC),
        )
        return await self._repo.save(invitation)

    async def list_pending(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Invitation], int]:
        items = await self._repo.find_pending_by_tenant(tenant_id, limit=limit, offset=offset)
        total = await self._repo.count_pending_by_tenant(tenant_id)
        return items, total

    async def cancel(self, invitation_id: str, tenant_id: str) -> None:
        invitation = await self._repo.find_by_id(invitation_id)
        if invitation is None:
            raise ValueError("Invitation not found")
        if invitation.tenant_id != tenant_id:
            raise PermissionError("Not authorized to cancel this invitation")
        if invitation.status != "pending":
            raise ValueError("Only pending invitations can be cancelled")
        await self._repo.soft_delete(invitation_id, datetime.now(UTC))

    async def validate_token(self, token: str) -> Invitation | None:
        invitation = await self._repo.find_by_token(token)
        if invitation is None:
            return None
        if invitation.status != "pending":
            return None
        if invitation.deleted_at is not None:
            return None
        if invitation.expires_at < datetime.now(UTC):
            await self._repo.update_status(invitation.id, "expired")
            return None
        return invitation

    async def accept_invitation(self, token: str, user_id: str) -> Invitation:
        invitation = await self.validate_token(token)
        if invitation is None:
            raise ValueError("Invalid or expired invitation token")
        await self._repo.update_status(invitation.id, "accepted", accepted_by=user_id)
        invitation.status = "accepted"
        invitation.accepted_by = user_id
        logger.info("Invitation %s accepted by user %s", invitation.id, user_id)
        return invitation
