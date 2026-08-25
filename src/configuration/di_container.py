"""Dependency Injection Container using composition with sub-containers.

The DIContainer delegates to domain-specific sub-containers while preserving
the exact same public interface for all callers.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.agent_service import AgentService
from src.application.services.topology_service import TopologyService
from src.application.services.workspace_message_service import WorkspaceMessageService
from src.application.use_cases.agent import (
    CreateConversationUseCase,
    GetConversationUseCase,
    ListConversationsUseCase,
)
from src.configuration.config import get_settings
from src.configuration.containers import (
    AgentContainer,
    AuthContainer,
    InfraContainer,
    ProjectContainer,
)
from src.domain.llm_providers.llm_types import LLMClient
from src.domain.ports.repositories.workspace.cyber_objective_repository import (
    CyberObjectiveRepository,
)
from src.domain.ports.repositories.workspace.topology_repository import (
    TopologyRepository,
)
from src.domain.ports.repositories.workspace.workspace_agent_repository import (
    WorkspaceAgentRepository,
)
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import (
    WorkspaceRepository,
)
from src.domain.ports.repositories.workspace.workspace_task_repository import (
    WorkspaceTaskRepository,
)
from src.domain.ports.repositories.workspace.workspace_task_session_attempt_repository import (
    WorkspaceTaskSessionAttemptRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
    SqlSkillRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_subagent_repository import (
    SqlSubAgentRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_subagent_template_repository import (
    SqlSubAgentTemplateRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tool_execution_record_repository import (
    SqlToolExecutionRecordRepository,
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
        self._project = ProjectContainer(
            db=db,
            user_repository_factory=self._auth.user_repository,
        )
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

    # === Project Container delegates ===

    def workspace_repository(self) -> WorkspaceRepository:
        return self._project.workspace_repository()

    def workspace_member_repository(self) -> WorkspaceMemberRepository:
        return self._project.workspace_member_repository()

    def workspace_agent_repository(self) -> WorkspaceAgentRepository:
        return self._project.workspace_agent_repository()

    def workspace_task_repository(self) -> WorkspaceTaskRepository:
        return self._project.workspace_task_repository()

    def workspace_task_session_attempt_repository(
        self,
    ) -> WorkspaceTaskSessionAttemptRepository:
        return cast(
            WorkspaceTaskSessionAttemptRepository,
            self._project.workspace_task_session_attempt_repository(),
        )

    def topology_repository(self) -> TopologyRepository:
        return cast(TopologyRepository, self._project.topology_repository())

    def topology_service(self) -> TopologyService:
        return cast(TopologyService, self._project.topology_service())

    def cyber_objective_repository(self) -> CyberObjectiveRepository:
        return cast(CyberObjectiveRepository, self._project.cyber_objective_repository())

    def workspace_message_service(
        self,
        workspace_event_publisher: (
            Callable[[str, str, dict[str, Any]], Awaitable[None]] | None
        ) = None,
    ) -> WorkspaceMessageService:
        return self._project.workspace_message_service(workspace_event_publisher)

    # === Infra Container delegates ===

    def redis(self) -> redis.Redis | None:
        return self._infra.redis()

    # === Agent Container delegates ===

    def conversation_repository(self) -> SqlConversationRepository:
        return self._agent.conversation_repository()

    def tool_execution_record_repository(self) -> SqlToolExecutionRecordRepository:
        return self._agent.tool_execution_record_repository()

    def agent_execution_event_repository(self) -> SqlAgentExecutionEventRepository:
        return self._agent.agent_execution_event_repository()

    def context_summary_adapter(self) -> Any:
        return cast(Any, self._agent.context_summary_adapter())

    def hitl_request_repository(self) -> SqlHITLRequestRepository:
        return self._agent.hitl_request_repository()

    def skill_repository(self) -> SqlSkillRepository:
        return self._agent.skill_repository()

    def subagent_repository(self) -> SqlSubAgentRepository:
        return self._agent.subagent_repository()

    def subagent_template_repository(self) -> SqlSubAgentTemplateRepository:
        return self._agent.subagent_template_repository()

    def agent_registry(self) -> Any:
        return self._agent.agent_registry()

    def agent_binding_repository(self) -> Any:
        return self._agent.agent_binding_repository()

    def binding_router(self) -> Any:
        return self._agent.binding_router()

    def artifact_service(self) -> Any:
        return self._agent.artifact_service()

    def subagent_run_registry(self) -> Any:
        return self._agent.subagent_run_registry()

    def agent_orchestrator(self) -> Any:
        return self._agent.agent_orchestrator()

    def graph_repository(self) -> Any:
        return cast(Any, self._agent.graph_repository())

    def graph_orchestrator(self) -> Any:
        return self._agent.graph_orchestrator()

    def agent_service(self, llm: LLMClient) -> AgentService:
        return self._agent.agent_service(llm)

    def create_conversation_use_case(self, llm: LLMClient) -> CreateConversationUseCase:
        return self._agent.create_conversation_use_case(llm)

    def list_conversations_use_case(self, llm: LLMClient) -> ListConversationsUseCase:
        return self._agent.list_conversations_use_case(llm)

    def get_conversation_use_case(self, llm: LLMClient) -> GetConversationUseCase:
        return self._agent.get_conversation_use_case(llm)
