"""Dependency Injection Container using composition with sub-containers.

The DIContainer delegates to domain-specific sub-containers while preserving
the exact same public interface for all callers.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.agent_service import AgentService
from src.application.services.blackboard_file_service import BlackboardFileService
from src.application.services.blackboard_service import BlackboardService
from src.application.services.cluster_service import ClusterService
from src.application.services.cron_service import CronJobService
from src.application.services.deploy_service import DeployService
from src.application.services.gene_service import GeneService
from src.application.services.instance_service import InstanceService
from src.application.services.instance_template_service import InstanceTemplateService
from src.application.services.memory_service import MemoryService
from src.application.services.project_service import ProjectService
from src.application.services.sandbox_orchestrator import SandboxOrchestrator
from src.application.services.search_service import SearchService
from src.application.services.skill_service import SkillService
from src.application.services.task_service import TaskService
from src.application.services.tenant_service import TenantService
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
from src.application.use_cases.memory.create_memory import (
    CreateMemoryUseCase as MemCreateMemoryUseCase,
)
from src.application.use_cases.memory.delete_memory import (
    DeleteMemoryUseCase as MemDeleteMemoryUseCase,
)
from src.application.use_cases.memory.get_memory import GetMemoryUseCase as MemGetMemoryUseCase
from src.application.use_cases.memory.list_memories import ListMemoriesUseCase
from src.application.use_cases.memory.search_memory import SearchMemoryUseCase
from src.application.use_cases.task import (
    CreateTaskUseCase,
    GetTaskUseCase,
    ListTasksUseCase,
    UpdateTaskUseCase,
)
from src.configuration.config import get_settings
from src.configuration.containers import (
    AgentContainer,
    AuthContainer,
    CronContainer,
    InfraContainer,
    InstanceContainer,
    MemoryContainer,
    ProjectContainer,
    SandboxContainer,
    TaskContainer,
)
from src.domain.llm_providers.llm_types import LLMClient
from src.domain.ports.repositories.api_key_repository import APIKeyRepository
from src.domain.ports.repositories.cluster_repository import ClusterRepository
from src.domain.ports.repositories.deploy_record_repository import DeployRecordRepository
from src.domain.ports.repositories.evolution_event_repository import (
    EvolutionEventRepository,
)
from src.domain.ports.repositories.gene_rating_repository import GeneRatingRepository
from src.domain.ports.repositories.gene_repository import GeneRepository
from src.domain.ports.repositories.gene_review_repository import GeneReviewRepository
from src.domain.ports.repositories.genome_repository import GenomeRepository
from src.domain.ports.repositories.instance_gene_repository import (
    InstanceGeneRepository,
)
from src.domain.ports.repositories.instance_member_repository import (
    InstanceMemberRepository,
)
from src.domain.ports.repositories.instance_repository import InstanceRepository
from src.domain.ports.repositories.instance_template_repository import (
    InstanceTemplateRepository,
)
from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.domain.ports.repositories.project_repository import ProjectRepository
from src.domain.ports.repositories.task_repository import TaskRepository
from src.domain.ports.repositories.tenant_repository import TenantRepository
from src.domain.ports.repositories.user_repository import UserRepository
from src.domain.ports.repositories.workspace.blackboard_file_repository import (
    BlackboardFileRepository,
)
from src.domain.ports.repositories.workspace.blackboard_repository import (
    BlackboardRepository,
)
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
from src.domain.ports.services.graph_service_port import GraphServicePort
from src.domain.ports.services.hitl_message_bus_port import HITLMessageBusPort
from src.domain.ports.services.sandbox_resource_port import SandboxResourcePort
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
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
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_repository import (
    SqlTenantAgentConfigRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_skill_config_repository import (
    SqlTenantSkillConfigRepository,
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


class DIContainer:
    """Dependency Injection Container using composition with sub-containers.

    Delegates to domain-specific sub-containers while preserving the exact
    same public interface for all callers.
    """

    def __init__(
        self,
        db: AsyncSession | None = None,
        graph_service: GraphServicePort | None = None,
        redis_client: redis.Redis | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        workflow_engine: WorkflowEnginePort | None = None,
        _infra: InfraContainer | None = None,
    ) -> None:
        # Store raw deps for with_db() and properties
        self._db = db
        self._graph_service = graph_service
        self._redis_client = redis_client
        self._session_factory = session_factory
        self._settings = get_settings()

        # Create sub-containers
        self._auth = AuthContainer(db=db)
        self._memory = MemoryContainer(db=db, graph_service=graph_service)
        self._task = TaskContainer(db=db)
        self._cron = CronContainer(db=db)
        self._project = ProjectContainer(
            db=db,
            user_repository_factory=self._auth.user_repository,
            tenant_repository_factory=self._auth.tenant_repository,
        )
        self._instance = InstanceContainer(db=db, redis_client=redis_client)
        # Reuse InfraContainer when provided (e.g. from with_db()) to preserve
        # cached singletons like MCPSandboxAdapter across per-request clones.
        self._infra = _infra or InfraContainer(
            redis_client=redis_client,
            workflow_engine=workflow_engine,
            settings=self._settings,
        )
        self._sandbox = SandboxContainer(
            db=db,
            redis_client=redis_client,
            settings=self._settings,
            sandbox_adapter_factory=self._infra.sandbox_adapter,
            sandbox_event_publisher_factory=self._infra.sandbox_event_publisher,
            distributed_lock_factory=self._infra.distributed_lock_adapter,
        )
        self._agent = AgentContainer(
            db=db,
            graph_service=graph_service,
            redis_client=redis_client,
            settings=self._settings,
            neo4j_client_factory=lambda: self.neo4j_client,
            storage_service_factory=self._infra.storage_service,
            sandbox_orchestrator_factory=self._sandbox.sandbox_orchestrator,
            sandbox_event_publisher_factory=self._infra.sandbox_event_publisher,
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
            graph_service=self._graph_service,
            redis_client=self._redis_client,
            session_factory=self._session_factory,
            workflow_engine=self._infra.workflow_engine_port(),
            _infra=self._infra,
        )

    def ai_service_factory(self) -> Any:
        """Get the AIServiceFactory singleton."""
        from src.infrastructure.llm.provider_factory import get_ai_service_factory

        return get_ai_service_factory()

    # === Properties that stay on the main class ===

    @property
    def neo4j_client(self) -> Any:
        """Get Neo4j client for direct driver access."""
        if self._graph_service and hasattr(self._graph_service, "client"):
            return self._graph_service.client  # pyright: ignore[reportAttributeAccessIssue]
        return None

    @property
    def graph_service(self) -> Any:
        """Get the GraphServicePort for graph operations."""
        return self._graph_service

    @property
    def redis_client(self) -> "redis.Redis | None":
        """Get the Redis client instance."""
        return self._redis_client

    # === Auth Container delegates ===

    def user_repository(self) -> UserRepository:
        return self._auth.user_repository()

    def api_key_repository(self) -> APIKeyRepository:
        return self._auth.api_key_repository()

    def tenant_repository(self) -> TenantRepository:
        return self._auth.tenant_repository()

    # === Memory Container delegates ===

    def memory_repository(self) -> MemoryRepository:
        return self._memory.memory_repository()

    def memory_service(self) -> MemoryService:
        return self._memory.memory_service()

    def search_service(self) -> SearchService:
        return self._memory.search_service()

    def create_memory_use_case(self) -> MemCreateMemoryUseCase:
        return self._memory.create_memory_use_case()

    def get_memory_use_case(self) -> MemGetMemoryUseCase:
        return self._memory.get_memory_use_case()

    def list_memories_use_case(self) -> ListMemoriesUseCase:
        return self._memory.list_memories_use_case()

    def delete_memory_use_case(self) -> MemDeleteMemoryUseCase:
        return self._memory.delete_memory_use_case()

    def search_memory_use_case(self) -> SearchMemoryUseCase:
        return self._memory.search_memory_use_case()

    # === Task Container delegates ===

    def task_repository(self) -> TaskRepository:
        return self._task.task_repository()

    def task_service(self) -> TaskService:
        return self._task.task_service()

    def create_task_use_case(self) -> CreateTaskUseCase:
        return self._task.create_task_use_case()

    def get_task_use_case(self) -> GetTaskUseCase:
        return self._task.get_task_use_case()

    def list_tasks_use_case(self) -> ListTasksUseCase:
        return self._task.list_tasks_use_case()

    def update_task_use_case(self) -> UpdateTaskUseCase:
        return self._task.update_task_use_case()

    # === Cron Container delegates ===

    def cron_job_service(self) -> CronJobService:
        return self._cron.cron_job_service()

    # === Project Container delegates ===

    def project_repository(self) -> ProjectRepository:
        return self._project.project_repository()

    def project_service(self) -> ProjectService:
        return self._project.project_service()

    def tenant_service(self) -> TenantService:
        return self._project.tenant_service()

    def workspace_repository(self) -> WorkspaceRepository:
        return self._project.workspace_repository()

    def workspace_member_repository(self) -> WorkspaceMemberRepository:
        return self._project.workspace_member_repository()

    def workspace_agent_repository(self) -> WorkspaceAgentRepository:
        return self._project.workspace_agent_repository()

    def blackboard_repository(self) -> BlackboardRepository:
        return self._project.blackboard_repository()

    def blackboard_service(self) -> BlackboardService:
        return self._project.blackboard_service()

    def blackboard_file_repository(self) -> BlackboardFileRepository:
        return self._project.blackboard_file_repository()

    def blackboard_file_service(self) -> BlackboardFileService:
        return self._project.blackboard_file_service()

    def workspace_task_repository(self) -> WorkspaceTaskRepository:
        return self._project.workspace_task_repository()

    def workspace_task_session_attempt_repository(
        self,
    ) -> WorkspaceTaskSessionAttemptRepository:
        return self._project.workspace_task_session_attempt_repository()

    def workspace_task_session_attempt_service(self) -> WorkspaceTaskSessionAttemptService:
        return self._project.workspace_task_session_attempt_service()

    # === Workspace V2 (multi-agent orchestrator) ===

    def workspace_orchestrator(self) -> Any:
        """Singleton lazy-built Workspace V2 orchestrator (multi-agent L5)."""
        existing = getattr(self, "_workspace_v2_orchestrator", None)
        if existing is not None:
            return existing
        from src.infrastructure.agent.workspace_plan import build_default_orchestrator

        existing = build_default_orchestrator()
        self._workspace_v2_orchestrator = existing  # type: ignore[attr-defined]
        return existing

    def topology_repository(self) -> TopologyRepository:
        return self._project.topology_repository()

    def topology_service(self) -> TopologyService:
        return self._project.topology_service()

    def cyber_objective_repository(self) -> CyberObjectiveRepository:
        return self._project.cyber_objective_repository()

    def cyber_gene_repository(self) -> CyberGeneRepository:
        return self._project.cyber_gene_repository()

    def workspace_message_service(
        self,
        workspace_event_publisher: (
            Callable[[str, str, dict[str, Any]], Awaitable[None]] | None
        ) = None,
    ) -> WorkspaceMessageService:
        return self._project.workspace_message_service(workspace_event_publisher)

    # === Instance Container delegates ===

    def instance_repository(self) -> InstanceRepository:
        return self._instance.instance_repository()

    def instance_member_repository(self) -> InstanceMemberRepository:
        return self._instance.instance_member_repository()

    def deploy_record_repository(self) -> DeployRecordRepository:
        return self._instance.deploy_record_repository()

    def cluster_repository(self) -> ClusterRepository:
        return self._instance.cluster_repository()

    def gene_repository(self) -> GeneRepository:
        return self._instance.gene_repository()

    def genome_repository(self) -> GenomeRepository:
        return self._instance.genome_repository()

    def instance_gene_repository(self) -> InstanceGeneRepository:
        return self._instance.instance_gene_repository()

    def gene_rating_repository(self) -> GeneRatingRepository:
        return self._instance.gene_rating_repository()

    def gene_review_repository(self) -> GeneReviewRepository:
        return self._instance.gene_review_repository()

    def evolution_event_repository(self) -> EvolutionEventRepository:
        return self._instance.evolution_event_repository()

    def instance_template_repository(self) -> InstanceTemplateRepository:
        return self._instance.instance_template_repository()

    def instance_service(self) -> InstanceService:
        return self._instance.instance_service()

    def deploy_service(self) -> DeployService:
        return self._instance.deploy_service()

    def cluster_service(self) -> ClusterService:
        return self._instance.cluster_service()

    def gene_service(self) -> GeneService:
        return self._instance.gene_service()

    def instance_template_service(self) -> InstanceTemplateService:
        return self._instance.instance_template_service()

    def instance_file_service(self) -> Any:
        return self._instance.instance_file_service()

    def instance_channel_service(self) -> Any:
        return self._instance.instance_channel_service()

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

    def workflow_engine_port(self) -> WorkflowEnginePort | None:
        return self._infra.workflow_engine_port()

    def sandbox_adapter(self) -> Any:
        return self._infra.sandbox_adapter()

    def sandbox_event_publisher(self) -> Any:
        return self._infra.sandbox_event_publisher()

    # === Sandbox Container delegates ===

    def project_sandbox_repository(self) -> SqlProjectSandboxRepository:
        return self._sandbox.project_sandbox_repository()

    def sandbox_orchestrator(self) -> SandboxOrchestrator:
        return self._sandbox.sandbox_orchestrator()

    def sandbox_tool_registry(self) -> Any:
        return self._sandbox.sandbox_tool_registry()

    def sandbox_resource(self) -> SandboxResourcePort:
        return self._sandbox.sandbox_resource()

    def project_sandbox_lifecycle_service(self) -> Any:
        return self._sandbox.project_sandbox_lifecycle_service()

    def sandbox_mcp_server_manager(self) -> Any:
        return self._sandbox.sandbox_mcp_server_manager()

    def mcp_app_service(self) -> Any:
        return self._sandbox.mcp_app_service()

    def mcp_runtime_service(self) -> Any:
        return self._sandbox.mcp_runtime_service()

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
        return self._agent.context_summary_adapter()

    def tool_composition_repository(self) -> SqlToolCompositionRepository:
        return self._agent.tool_composition_repository()

    def tool_environment_variable_repository(self) -> SqlToolEnvironmentVariableRepository:
        return self._agent.tool_environment_variable_repository()

    def hitl_request_repository(self) -> SqlHITLRequestRepository:
        return self._agent.hitl_request_repository()

    def tenant_agent_config_repository(self) -> SqlTenantAgentConfigRepository:
        return self._agent.tenant_agent_config_repository()

    def skill_repository(self) -> SqlSkillRepository:
        return self._agent.skill_repository()

    def skill_version_repository(self) -> Any:
        return self._agent.skill_version_repository()

    def tenant_skill_config_repository(self) -> SqlTenantSkillConfigRepository:
        return self._agent.tenant_skill_config_repository()

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
        return self._agent.agent_session_registry()

    def spawn_manager(self) -> Any:
        return self._agent.spawn_manager()

    def subagent_run_registry(self) -> Any:
        return self._agent.subagent_run_registry()

    def agent_orchestrator(self) -> Any:
        return self._agent.agent_orchestrator()

    def graph_repository(self) -> Any:
        return self._agent.graph_repository()

    def graph_run_repository(self) -> Any:
        return self._agent.graph_run_repository()

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

    # === Event Log & Webhooks ===

    def event_log_repository(self) -> Any:
        from src.infrastructure.adapters.secondary.persistence.sql_event_log_repository import (
            SqlEventLogRepository,
        )

        assert self._db is not None, "DB session required for event_log_repository"
        return SqlEventLogRepository(self._db)

    def event_log_service(self) -> Any:
        from src.application.services.event_log_service import EventLogService

        return EventLogService(self.event_log_repository())

    def webhook_repository(self) -> Any:
        from src.infrastructure.adapters.secondary.persistence.sql_webhook_repository import (
            SqlWebhookRepository,
        )

        assert self._db is not None, "DB session required for webhook_repository"
        return SqlWebhookRepository(self._db)

    def webhook_service(self) -> Any:
        from src.application.services.webhook_service import WebhookService

        return WebhookService(self.webhook_repository())
