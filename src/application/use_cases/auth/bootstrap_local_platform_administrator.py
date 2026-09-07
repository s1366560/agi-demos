"""Create-only, local-development platform authority for deployment provisioning."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

logger = logging.getLogger(__name__)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True, kw_only=True)
class LocalPlatformAdministrator:
    user_id: str
    email: str
    bootstrap_id: str


class LocalPlatformAdministratorRepository(Protocol):
    async def create_new(
        self, *, identity: LocalPlatformAdministrator, password_hash: str
    ) -> None: ...

    async def deactivate_created(self, identity: LocalPlatformAdministrator) -> None: ...


@dataclass(frozen=True, kw_only=True)
class BootstrapLocalPlatformAdministrator:
    """Local operator entry point; never changes an existing user's privileges."""

    repository: LocalPlatformAdministratorRepository
    hash_password: Callable[[str], str] = field(repr=False)
    environment: str
    database_host: str
    api_host: str

    def validate_target(self) -> None:
        if self.environment != "development":
            raise ValueError("Local platform bootstrap requires development environment")
        if self.database_host not in _LOCAL_HOSTS or self.api_host not in _LOCAL_HOSTS:
            raise ValueError("Local platform bootstrap requires loopback database and API")

    async def execute(self, *, email: str, password: str) -> LocalPlatformAdministrator:
        self.validate_target()
        if not email.strip() or "@" not in email or len(password) < 32:
            raise ValueError(
                "Local platform bootstrap requires email and generated strong password"
            )
        identity = LocalPlatformAdministrator(
            user_id=str(uuid4()), email=email.strip().lower(), bootstrap_id=str(uuid4())
        )
        await self.repository.create_new(
            identity=identity, password_hash=self.hash_password(password)
        )
        logger.info(
            "Local platform administrator bootstrapped user_id=%s bootstrap_id=%s",
            identity.user_id,
            identity.bootstrap_id,
        )
        return identity

    async def deactivate(self, identity: LocalPlatformAdministrator) -> None:
        self.validate_target()
        await self.repository.deactivate_created(identity)
        logger.info(
            "Local bootstrap administrator deactivated user_id=%s bootstrap_id=%s",
            identity.user_id,
            identity.bootstrap_id,
        )
