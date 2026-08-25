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
from src.application.services.sandbox_orchestrator import SandboxOrchestrator
from src.application.services.skill_service import SkillService
from src.application.services.topology_service import TopologyService
from src.application.services.workflow_learner import WorkflowLearner
from src.application.services.workspace_message_service import WorkspaceMessageService
from src.application.services.workspace_task_session_attempt_service import (
    WorkspaceTaskSessionAttemptService,
)
from src.application.use_cases.agent import (
    ChatUseCase,
    ComposeToolsUseCase,
    CreateConversationUseCase,
    ExecuteStepUseCase,
    FindSimilarPattern,
    GetConversationUseCase,
    LearnPattern,
    ListConversationsUseCase,
    SynthesizeResultsUseCase,
)
from src.configuration.config import get_settings
from src.configuration.containers import (
    AgentContainer,
    AuthContainer,
    InfraContainer,
    InstanceContainer,
    ProjectContainer,
    SandboxContainer,
)
from src.domain.llm_providers.llm_types import LLMClient
from src.domain.ports.repositories.api_key_repository import APIKeyRepository
from src.domain.ports.repositories.user_repository import UserRepository
from src.domain.ports.repositories.workspace.cyber_gene_repository import (
    CyberGeneRepository,
)
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
from src.domain.ports.services.hitl_message_bus_port import HITLMessageBusPort
from src.domain.ports.services.sandbox_resource_port import SandboxResourcePort
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAgentExecutionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_execution_checkpoint_repository import (
    SqlExecutionCheckpointRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
    SqlProjectSandboxRepository,
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
from src.infrastructure.adapters.secondary.persistence.sql_tool_composition_repository import (
    SqlToolCompositionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
    SqlToolEnvironmentVariableRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tool_execution_record_repository import (
    SqlToolExecutionRecordRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workflow_pattern_repository import (
    SqlWorkflowPatternRepository,
)
from src.infrastructure.agent.context.window_manager import ContextWindowManager

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
        self._workspace_v2_orchestrator: Any | None = None

        # Create sub-containers
        self._auth = AuthContainer(db=db)
        self._project = ProjectContainer(
            db=db,
            user_repository_factory=self._auth.user_repository,
        )
        self._instance = InstanceContainer(db=db, redis_client=redis_client)
        # Reuse InfraContainer when provided (e.g. from with_db()) to preserve
        # cached singletons like MCPSandboxAdapter across per-request clones.
        self._infra = _infra or InfraContainer(
            redis_client=redis_client,
            settings=self._settings,
        )
        self._sandbox = SandboxContainer(
            db=db,
            redis_client=redis_client,
            settings=self._settings,
            distributed_lock_factory=self._infra.distributed_lock_adapter,
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

    def _require_db(self, provider_name: str) -> AsyncSession:
        """Return ``self._db`` or raise a clear error.

        The global ``app.state.container`` is constructed without a session
        (it carries singletons only). Callers that need DB-backed services
        must obtain a request-scoped clone via ``container.with_db(db)``.

        This helper turns a downstream
        ``AttributeError: 'NoneType' has no attribute 'execute'`` into a
        descriptive ``RuntimeError`` at the call site.
        """
        if self._db is None:
            raise RuntimeError(
                f"DIContainer.{provider_name}() requires a db session. "
                "Use container.with_db(db) (or get_container_with_db("
                "request, db)) before resolving this service."
            )
        return self._db

    def ai_service_factory(self) -> Any:
        """Get the AIServiceFactory singleton."""
        from src.infrastructure.llm.provider_factory import get_ai_service_factory

        return get_ai_service_factory()

    # === Properties that stay on the main class ===

    @property
    def redis_client(self) -> "redis.Redis | None":
        """Get the Redis client instance."""
        return self._redis_client

    # === Auth Container delegates ===

    def user_repository(self) -> UserRepository:
        return self._auth.user_repository()

    def api_key_repository(self) -> APIKeyRepository:
        return self._auth.api_key_repository()

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

    def workspace_task_session_attempt_service(self) -> WorkspaceTaskSessionAttemptService:
        return cast(
            WorkspaceTaskSessionAttemptService,
            self._project.workspace_task_session_attempt_service(),
        )

    # === Workspace V2 (multi-agent orchestrator) ===

    def workspace_orchestrator(self) -> Any:
        """Reject the retired platform-owned Workspace Plan V2 orchestrator."""
        raise RuntimeError("Workspace Plan V2 orchestration is owned by Avernet Workspace Core")

    def topology_repository(self) -> TopologyRepository:
        return cast(TopologyRepository, self._project.topology_repository())

    def topology_service(self) -> TopologyService:
        return cast(TopologyService, self._project.topology_service())

    def cyber_objective_repository(self) -> CyberObjectiveRepository:
        return cast(CyberObjectiveRepository, self._project.cyber_objective_repository())

    def cyber_gene_repository(self) -> CyberGeneRepository:
        return cast(CyberGeneRepository, self._project.cyber_gene_repository())

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

    def sequence_service(self) -> Any:
        return self._infra.sequence_service()

    def hitl_message_bus(self) -> HITLMessageBusPort | None:
        return self._infra.hitl_message_bus()

    def agent_message_bus(self) -> Any:
        return self._infra.agent_message_bus()

    def storage_service(self) -> Any:
        return self._infra.storage_service()

    def distributed_lock_adapter(self) -> Any:
        return self._infra.distributed_lock_adapter()

    # === Sandbox Container delegates ===

    def project_sandbox_repository(self) -> SqlProjectSandboxRepository:
        return self._sandbox.project_sandbox_repository()

    def sandbox_orchestrator(self) -> SandboxOrchestrator:
        return self._sandbox.sandbox_orchestrator()

    def sandbox_resource(self) -> SandboxResourcePort:
        return self._sandbox.sandbox_resource()

    def dependency_orchestrator(self) -> Any:
        return self._sandbox.dependency_orchestrator()

    # === Agent Container delegates ===

    def conversation_repository(self) -> SqlConversationRepository:
        return self._agent.conversation_repository()

    def agent_execution_repository(self) -> SqlAgentExecutionRepository:
        return self._agent.agent_execution_repository()

    def tool_execution_record_repository(self) -> SqlToolExecutionRecordRepository:
        return self._agent.tool_execution_record_repository()

    def agent_execution_event_repository(self) -> SqlAgentExecutionEventRepository:
        return self._agent.agent_execution_event_repository()

    def execution_checkpoint_repository(self) -> SqlExecutionCheckpointRepository:
        return self._agent.execution_checkpoint_repository()

    def workflow_pattern_repository(self) -> SqlWorkflowPatternRepository:
        return self._agent.workflow_pattern_repository()

    def context_summary_adapter(self) -> Any:
        return cast(Any, self._agent.context_summary_adapter())

    def tool_composition_repository(self) -> SqlToolCompositionRepository:
        return self._agent.tool_composition_repository()

    def tool_environment_variable_repository(self) -> SqlToolEnvironmentVariableRepository:
        return self._agent.tool_environment_variable_repository()

    def hitl_request_repository(self) -> SqlHITLRequestRepository:
        return self._agent.hitl_request_repository()

    def skill_repository(self) -> SqlSkillRepository:
        return self._agent.skill_repository()

    def skill_version_repository(self) -> Any:
        return cast(Any, self._agent.skill_version_repository())

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

    def attachment_repository(self) -> Any:
        return self._agent.attachment_repository()

    def attachment_service(self) -> Any:
        return self._agent.attachment_service()

    def artifact_service(self) -> Any:
        return self._agent.artifact_service()

    def skill_service(self) -> SkillService:
        return self._agent.skill_service()

    def workspace_manager(self) -> Any:
        return self._agent.workspace_manager()

    def agent_session_registry(self) -> Any:
        return cast(Any, self._agent.agent_session_registry())

    def spawn_manager(self) -> Any:
        return self._agent.spawn_manager()

    def subagent_run_registry(self) -> Any:
        return self._agent.subagent_run_registry()

    def agent_orchestrator(self) -> Any:
        return self._agent.agent_orchestrator()

    def graph_repository(self) -> Any:
        return cast(Any, self._agent.graph_repository())

    def graph_run_repository(self) -> Any:
        return cast(Any, self._agent.graph_run_repository())

    def graph_orchestrator(self) -> Any:
        return self._agent.graph_orchestrator()

    def agent_service(self, llm: LLMClient) -> AgentService:
        return self._agent.agent_service(llm)

    def event_converter(self) -> Any:
        return self._agent.event_converter()

    def attachment_processor(self) -> Any:
        return self._agent.attachment_processor()

    def llm_invoker(self, llm: LLMClient) -> Any:
        return self._agent.llm_invoker(llm)

    def tool_executor(self, tools: dict[str, Any]) -> Any:
        return self._agent.tool_executor(tools)

    def artifact_extractor(self) -> Any:
        return self._agent.artifact_extractor()

    def react_loop(self, llm: LLMClient, tools: dict[str, Any]) -> Any:
        return self._agent.react_loop(llm, tools)

    def message_builder(self) -> Any:
        return self._agent.message_builder()

    def attachment_injector(self) -> Any:
        return self._agent.attachment_injector()

    def context_facade(self, window_manager: ContextWindowManager | None = None) -> Any:
        return self._agent.context_facade(window_manager)

    def create_conversation_use_case(self, llm: LLMClient) -> CreateConversationUseCase:
        return self._agent.create_conversation_use_case(llm)

    def list_conversations_use_case(self, llm: LLMClient) -> ListConversationsUseCase:
        return self._agent.list_conversations_use_case(llm)

    def get_conversation_use_case(self, llm: LLMClient) -> GetConversationUseCase:
        return self._agent.get_conversation_use_case(llm)

    def chat_use_case(self, llm: LLMClient) -> ChatUseCase:
        return self._agent.chat_use_case(llm)

    def execute_step_use_case(self, llm: LLMClient) -> ExecuteStepUseCase:
        return self._agent.execute_step_use_case(llm)

    def synthesize_results_use_case(self, llm: LLMClient) -> SynthesizeResultsUseCase:
        return self._agent.synthesize_results_use_case(llm)

    def find_similar_pattern_use_case(self) -> FindSimilarPattern:
        return self._agent.find_similar_pattern_use_case()

    def learn_pattern_use_case(self) -> LearnPattern:
        return self._agent.learn_pattern_use_case()

    def workflow_learner(self) -> WorkflowLearner:
        return self._agent.workflow_learner()

    def compose_tools_use_case(self, llm: LLMClient) -> ComposeToolsUseCase:
        return self._agent.compose_tools_use_case(llm)

    # === Multi-Agent Services (Phase 1-4) ===

    def span_service(self) -> Any:
        return self._agent.span_service()

    def fork_merge_service(self) -> Any:
        return self._agent.fork_merge_service()

    def layered_tool_policy_service(self) -> Any:
        return self._agent.layered_tool_policy_service()

    def default_message_router(self) -> Any:
        return self._agent.default_message_router()

    def message_binding_repository(self) -> Any:
        return self._agent.message_binding_repository()

    def agent_router_service(self) -> Any:
        return self._agent.agent_router_service()

    def redis_agent_namespace(self) -> Any:
        return self._agent.redis_agent_namespace()

    def redis_agent_credential_scope(self) -> Any:
        return self._agent.redis_agent_credential_scope()

    def default_context_engine(self, window_manager: Any | None = None) -> Any:
        return self._agent.default_context_engine(window_manager)
