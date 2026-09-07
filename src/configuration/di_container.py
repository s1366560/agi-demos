"""Application infrastructure shell; business services belong to V2 generations."""

import logging

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.configuration.config import get_settings
from src.configuration.containers import (
    AuthContainer,
    InfraContainer,
)

logger = logging.getLogger(__name__)


class DIContainer:
    """Keep scoped DB handles and shared infrastructure outside business assembly."""

    def __init__(
        self,
        db: AsyncSession | None = None,
        redis_client: redis.Redis | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        _infra: InfraContainer | None = None,
    ) -> None:
        # Store raw deps for with_db() and properties
        self._db = db
        self._redis_client = redis_client
        self._session_factory = session_factory
        self._settings = get_settings()

        # Create sub-containers
        self._auth = AuthContainer(db=db)
        # Reuse InfraContainer when provided (e.g. from with_db()) to preserve
        # cached singletons like MCPSandboxAdapter across per-request clones.
        self._infra = _infra or InfraContainer(
            redis_client=redis_client,
            settings=self._settings,
        )

    def with_db(self, db: AsyncSession) -> "DIContainer":
        """Create a new container instance with a specific db session.

        Reuses the same InfraContainer so that cached singletons
        (e.g. MCPSandboxAdapter) are shared across per-request clones.
        """
        return DIContainer(
            db=db,
            redis_client=self._redis_client,
            session_factory=self._session_factory,
            _infra=self._infra,
        )

    # === Properties that stay on the main class ===

    @property
    def redis_client(self) -> "redis.Redis | None":
        """Get the Redis client instance."""
        return self._redis_client

    # === Infra Container delegates ===

    def redis(self) -> redis.Redis | None:
        return self._infra.redis()
