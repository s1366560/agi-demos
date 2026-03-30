from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.model.invitation.invitation import Invitation


class InvitationRepository(ABC):
    @abstractmethod
    async def save(self, invitation: Invitation) -> Invitation: ...

    @abstractmethod
    async def find_by_id(self, invitation_id: str) -> Invitation | None: ...

    @abstractmethod
    async def find_by_token(self, token: str) -> Invitation | None: ...

    @abstractmethod
    async def find_pending_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Invitation]: ...

    @abstractmethod
    async def count_pending_by_tenant(self, tenant_id: str) -> int: ...

    @abstractmethod
    async def find_pending_by_email_and_tenant(
        self,
        email: str,
        tenant_id: str,
    ) -> Invitation | None: ...

    @abstractmethod
    async def soft_delete(self, invitation_id: str, deleted_at: datetime) -> None: ...

    @abstractmethod
    async def update_status(
        self,
        invitation_id: str,
        status: str,
        *,
        accepted_by: str | None = None,
    ) -> None: ...
