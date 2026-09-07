"""Persistence adapter for the explicit local-development bootstrap use case."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.use_cases.auth.bootstrap_local_platform_administrator import (
    LocalPlatformAdministrator,
)
from src.infrastructure.adapters.secondary.persistence.models import User


class SqlLocalPlatformAdministratorRepository:
    """Insert fresh identities and retire only identities created by this bootstrap."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_new(self, *, identity: LocalPlatformAdministrator, password_hash: str) -> None:
        existing = await self._session.scalar(
            select(User.id).where(func.lower(User.email) == identity.email.lower())
        )
        if existing is not None:
            raise ValueError("Local bootstrap refuses to modify an existing identity")
        self._session.add(
            User(
                id=identity.user_id,
                email=identity.email,
                full_name="Local desktop deployment bootstrap",
                hashed_password=password_hash,
                is_active=True,
                is_superuser=True,
                profile={"local_platform_bootstrap_id": identity.bootstrap_id},
            )
        )
        await self._session.flush()

    async def deactivate_created(self, identity: LocalPlatformAdministrator) -> None:
        row = await self._session.scalar(select(User).where(User.id == identity.user_id))
        if (
            row is None
            or row.email != identity.email
            or (row.profile or {}).get("local_platform_bootstrap_id") != identity.bootstrap_id
        ):
            raise ValueError("Identity is not owned by this local bootstrap")
        row.is_active = False
        await self._session.flush()
