"""Dependency Injection Container using composition with sub-containers.

The DIContainer delegates to domain-specific sub-containers while preserving
the exact same public interface for all callers.
"""

import logging

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.agent_service import AgentService
from src.configuration.config import get_settings
from src.configuration.containers import (
    AgentContainer,
    AuthContainer,
    InfraContainer,
)
from src.domain.llm_providers.llm_types import LLMClient
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)

logger = logging.getLogger(__name__)


class DIContainer:
    """Dependency Injection Container using composition with sub-containers.

    Delegates to domain-specific sub-containers while preserving the exact
    same public interface for all callers.
    """

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
        self._agent = AgentContainer(
            db=db,
            redis_client=redis_client,
            session_factory=session_factory,
            settings=self._settings,
            storage_service_factory=self._infra.storage_service,
            sequence_service_factory=self._infra.sequence_service,
            agent_message_bus_factory=self._infra.agent_message_bus,
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

    # === Agent Container delegates ===

    def conversation_repository(self) -> SqlConversationRepository:
        return self._agent.conversation_repository()

    def agent_execution_event_repository(self) -> SqlAgentExecutionEventRepository:
        return self._agent.agent_execution_event_repository()

    def agent_service(self, llm: LLMClient) -> AgentService:
        return self._agent.agent_service(llm)
