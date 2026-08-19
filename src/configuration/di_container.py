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
from src.configuration.service_bindings import declare_container_services
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
from src.infrastructure.plugins.service_registry import ServiceRegistry

logger = logging.getLogger(__name__)


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
        self._reflection_runner: Any | None = None
        self._workspace_v2_orchestrator: Any | None = None

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
            session_factory=session_factory,
            settings=self._settings,
            neo4j_client_factory=lambda: self.neo4j_client,
            storage_service_factory=self._infra.storage_service,
            sandbox_orchestrator_factory=self._sandbox.sandbox_orchestrator,
            sandbox_event_publisher_factory=self._infra.sandbox_event_publisher,
            sequence_service_factory=self._infra.sequence_service,
            agent_message_bus_factory=self._infra.agent_message_bus,
        )

        # I1 shadow composition root: every zero-arg accessor is declared as
        # a lazy service. Facades keep their current behavior until the B6
        # cutover; the registry is per-container, so with_db() clones get
        # request-scoped caching while the global container caches singletons.
        self._services: ServiceRegistry = ServiceRegistry()
        _ = declare_container_services(self._services, self)

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

    @property
    def services(self) -> ServiceRegistry:
        """Shadow composition root (I1): lazy service view of the container."""
        return self._services

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
        return cast(UserRepository, self._services.get_or_activate("user_repository"))

    def api_key_repository(self) -> APIKeyRepository:
        return cast(APIKeyRepository, self._services.get_or_activate("api_key_repository"))

    def tenant_repository(self) -> TenantRepository:
        return cast(TenantRepository, self._services.get_or_activate("tenant_repository"))

    # === Memory Container delegates ===

    def memory_repository(self) -> MemoryRepository:
        return cast(MemoryRepository, self._services.get_or_activate("memory_repository"))

    def memory_service(self) -> MemoryService:
        return cast(MemoryService, self._services.get_or_activate("memory_service"))

    def search_service(self) -> SearchService:
        return cast(SearchService, self._services.get_or_activate("search_service"))

    def create_memory_use_case(self) -> MemCreateMemoryUseCase:
        return cast(
            MemCreateMemoryUseCase, self._services.get_or_activate("create_memory_use_case")
        )

    def get_memory_use_case(self) -> MemGetMemoryUseCase:
        return cast(MemGetMemoryUseCase, self._services.get_or_activate("get_memory_use_case"))

    def list_memories_use_case(self) -> ListMemoriesUseCase:
        return cast(ListMemoriesUseCase, self._services.get_or_activate("list_memories_use_case"))

    def delete_memory_use_case(self) -> MemDeleteMemoryUseCase:
        return cast(
            MemDeleteMemoryUseCase, self._services.get_or_activate("delete_memory_use_case")
        )

    def search_memory_use_case(self) -> SearchMemoryUseCase:
        return cast(SearchMemoryUseCase, self._services.get_or_activate("search_memory_use_case"))

    # === Task Container delegates ===

    def task_repository(self) -> TaskRepository:
        return cast(TaskRepository, self._services.get_or_activate("task_repository"))

    def task_service(self) -> TaskService:
        return cast(TaskService, self._services.get_or_activate("task_service"))

    def create_task_use_case(self) -> CreateTaskUseCase:
        return cast(CreateTaskUseCase, self._services.get_or_activate("create_task_use_case"))

    def get_task_use_case(self) -> GetTaskUseCase:
        return cast(GetTaskUseCase, self._services.get_or_activate("get_task_use_case"))

    def list_tasks_use_case(self) -> ListTasksUseCase:
        return cast(ListTasksUseCase, self._services.get_or_activate("list_tasks_use_case"))

    def update_task_use_case(self) -> UpdateTaskUseCase:
        return cast(UpdateTaskUseCase, self._services.get_or_activate("update_task_use_case"))

    # === Cron Container delegates ===

    def cron_job_service(self) -> CronJobService:
        return cast(CronJobService, self._services.get_or_activate("cron_job_service"))

    # === Reflection (friction → playbook loop) ===

    async def reflection_service(self, project_id: str, *, session: AsyncSession) -> Any:
        """Build a per-project ``ReflectionService`` bound to a SQL session.

        - Friction ledger: Redis-backed when a redis client is available,
          process-singleton in-memory ledger otherwise (local dev / tests).
        - Playbook repository: ``SqlPlaybookRepository(session)`` \u2014 the
          caller owns the session lifecycle and must commit after invoking
          ``reflect_window``.
        - Reflector: LLM-backed via ``AIServiceFactory``.
        """
        from src.application.services.reflection_factory import (
            build_litellm_reflector,
            build_reflection_service,
            default_in_memory_ledger,
        )
        from src.infrastructure.adapters.secondary.cache.redis_friction_ledger import (
            RedisFrictionLedger,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_playbook_repository import (
            SqlPlaybookRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_reflection_verdict_repository import (
            SqlReflectionVerdictRepository,
        )

        del project_id  # ledger is keyed per project at append/query time

        redis_client = self._infra.redis()
        ledger: Any = (
            RedisFrictionLedger(redis_client)
            if redis_client is not None
            else default_in_memory_ledger()
        )

        provider_config = await self.ai_service_factory().resolve_provider()
        litellm_client = self.ai_service_factory().create_llm_client(provider_config)
        reflector = build_litellm_reflector(litellm_client)

        return build_reflection_service(
            ledger=ledger,
            playbooks=SqlPlaybookRepository(session),
            reflector=reflector,
            verdict_log=SqlReflectionVerdictRepository(session),
        )

    def lane_experience_service(self, *, session: AsyncSession) -> Any:
        """Build a session-scoped ``LaneExperienceService``.

        Reuses the same friction ledger as ``reflection_service`` (Redis or
        in-memory fallback) and a SQL-backed ``PlaybookRepository`` bound to
        the caller's session.

        The caller owns the DB session lifecycle. The returned service has
        no transactional side effects (read-only on both ports), so callers
        do not need to commit when they only call ``build``.
        """
        from src.application.services.lane_experience_service import (
            LaneExperienceService,
        )
        from src.application.services.reflection_factory import (
            default_in_memory_ledger,
        )
        from src.infrastructure.adapters.secondary.cache.redis_friction_ledger import (
            RedisFrictionLedger,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_playbook_repository import (
            SqlPlaybookRepository,
        )

        redis_client = self._infra.redis()
        ledger: Any = (
            RedisFrictionLedger(redis_client)
            if redis_client is not None
            else default_in_memory_ledger()
        )
        return LaneExperienceService(
            friction_ledger=ledger,
            playbook_repository=SqlPlaybookRepository(session),
        )

    def reflection_runner(self) -> Any:
        """Singleton ``ReflectionRunner`` driven by an all-tenants sweep.

        Opens a fresh DB session per project iteration so SQL-backed playbook
        writes commit cleanly between projects. Lifecycle is owned by the
        caller (FastAPI lifespan); ``start()`` must be invoked once the
        event loop is running.
        """
        existing = self._reflection_runner
        if existing is not None:
            return existing

        from src.application.services.reflection_events import (
            ReflectionCompleteStatus,
            publish_reflection_complete,
        )
        from src.application.services.reflection_runner import ReflectionRunner

        async def _all_active_project_ids() -> list[str]:
            session_factory = self._session_factory
            if session_factory is None:
                return []
            from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
                SqlProjectRepository,
            )

            async with session_factory() as session:
                repo = SqlProjectRepository(session)
                projects = await repo.list_active_projects(limit=1000)
                return [p.id for p in projects]

        async def _service_for(project_id: str) -> Any:
            """Per-project session-scoped ``ReflectionService`` adapter.

            Returns an object whose ``reflect_window`` opens its own DB
            session, builds the SQL-backed service, runs reflection, then
            commits. Mirrors the contract ``ReflectionRunner`` expects.
            """
            session_factory = self._session_factory
            if session_factory is None:
                logger.warning(
                    "ReflectionRunner: no session_factory; skipping project %s",
                    project_id,
                )
                return None

            active_session_factory = session_factory
            container_self = self

            class _SessionScopedReflection:
                async def reflect_window(self, pid: str) -> list[Any]:
                    async with active_session_factory() as session:
                        service = await container_self.reflection_service(pid, session=session)
                        verdicts = await service.reflect_window(pid)
                        await session.commit()
                        return cast(list[Any], verdicts)

            return _SessionScopedReflection()

        async def _emit_completion(
            project_id: str,
            verdicts: list[Any],
            status: ReflectionCompleteStatus,
            error: str | None,
        ) -> None:
            redis_client = self.redis()
            if redis_client is None:
                return
            await publish_reflection_complete(
                redis_client=redis_client,
                project_id=project_id,
                verdicts=verdicts,
                status=status,
                source="runner",
                error=error,
            )

        runner = ReflectionRunner(
            project_ids_provider=_all_active_project_ids,
            service_factory=_service_for,
            completion_emitter=_emit_completion,
        )
        self._reflection_runner = runner
        return runner

    # === Project Container delegates ===

    def project_repository(self) -> ProjectRepository:
        return cast(ProjectRepository, self._services.get_or_activate("project_repository"))

    def project_service(self) -> ProjectService:
        return cast(ProjectService, self._services.get_or_activate("project_service"))

    def tenant_service(self) -> TenantService:
        return cast(TenantService, self._services.get_or_activate("tenant_service"))

    def workspace_repository(self) -> WorkspaceRepository:
        return cast(WorkspaceRepository, self._services.get_or_activate("workspace_repository"))

    def workspace_member_repository(self) -> WorkspaceMemberRepository:
        return cast(
            WorkspaceMemberRepository, self._services.get_or_activate("workspace_member_repository")
        )

    def workspace_agent_repository(self) -> WorkspaceAgentRepository:
        return cast(
            WorkspaceAgentRepository, self._services.get_or_activate("workspace_agent_repository")
        )

    def blackboard_repository(self) -> BlackboardRepository:
        return cast(BlackboardRepository, self._services.get_or_activate("blackboard_repository"))

    def blackboard_service(self) -> BlackboardService:
        return cast(BlackboardService, self._services.get_or_activate("blackboard_service"))

    def blackboard_file_repository(self) -> BlackboardFileRepository:
        return cast(
            BlackboardFileRepository, self._services.get_or_activate("blackboard_file_repository")
        )

    def blackboard_file_service(self) -> BlackboardFileService:
        return cast(
            BlackboardFileService, self._services.get_or_activate("blackboard_file_service")
        )

    def workspace_task_repository(self) -> WorkspaceTaskRepository:
        return cast(
            WorkspaceTaskRepository, self._services.get_or_activate("workspace_task_repository")
        )

    def workspace_task_session_attempt_repository(
        self,
    ) -> WorkspaceTaskSessionAttemptRepository:
        return cast(
            WorkspaceTaskSessionAttemptRepository,
            self._services.get_or_activate("workspace_task_session_attempt_repository"),
        )

    def workspace_task_session_attempt_service(self) -> WorkspaceTaskSessionAttemptService:
        return cast(
            WorkspaceTaskSessionAttemptService,
            self._services.get_or_activate("workspace_task_session_attempt_service"),
        )

    # === Workspace V2 (multi-agent orchestrator) ===

    def workspace_orchestrator(self) -> Any:
        """Reject the retired platform-owned Workspace Plan V2 orchestrator."""
        raise RuntimeError("Workspace Plan V2 orchestration is owned by Avernet Workspace Core")

    def topology_repository(self) -> TopologyRepository:
        return cast(TopologyRepository, self._services.get_or_activate("topology_repository"))

    def topology_service(self) -> TopologyService:
        return cast(TopologyService, self._services.get_or_activate("topology_service"))

    def cyber_objective_repository(self) -> CyberObjectiveRepository:
        return cast(
            CyberObjectiveRepository, self._services.get_or_activate("cyber_objective_repository")
        )

    def cyber_gene_repository(self) -> CyberGeneRepository:
        return cast(CyberGeneRepository, self._services.get_or_activate("cyber_gene_repository"))

    def workspace_message_service(
        self,
        workspace_event_publisher: (
            Callable[[str, str, dict[str, Any]], Awaitable[None]] | None
        ) = None,
    ) -> WorkspaceMessageService:
        return self._project.workspace_message_service(workspace_event_publisher)

    # === Instance Container delegates ===

    def instance_repository(self) -> InstanceRepository:
        return cast(InstanceRepository, self._services.get_or_activate("instance_repository"))

    def instance_member_repository(self) -> InstanceMemberRepository:
        return cast(
            InstanceMemberRepository, self._services.get_or_activate("instance_member_repository")
        )

    def deploy_record_repository(self) -> DeployRecordRepository:
        return cast(
            DeployRecordRepository, self._services.get_or_activate("deploy_record_repository")
        )

    def cluster_repository(self) -> ClusterRepository:
        return cast(ClusterRepository, self._services.get_or_activate("cluster_repository"))

    def gene_repository(self) -> GeneRepository:
        return cast(GeneRepository, self._services.get_or_activate("gene_repository"))

    def genome_repository(self) -> GenomeRepository:
        return cast(GenomeRepository, self._services.get_or_activate("genome_repository"))

    def instance_gene_repository(self) -> InstanceGeneRepository:
        return cast(
            InstanceGeneRepository, self._services.get_or_activate("instance_gene_repository")
        )

    def gene_rating_repository(self) -> GeneRatingRepository:
        return cast(GeneRatingRepository, self._services.get_or_activate("gene_rating_repository"))

    def gene_review_repository(self) -> GeneReviewRepository:
        return cast(GeneReviewRepository, self._services.get_or_activate("gene_review_repository"))

    def evolution_event_repository(self) -> EvolutionEventRepository:
        return cast(
            EvolutionEventRepository, self._services.get_or_activate("evolution_event_repository")
        )

    def instance_template_repository(self) -> InstanceTemplateRepository:
        return cast(
            InstanceTemplateRepository,
            self._services.get_or_activate("instance_template_repository"),
        )

    def instance_service(self) -> InstanceService:
        return cast(InstanceService, self._services.get_or_activate("instance_service"))

    def deploy_service(self) -> DeployService:
        return cast(DeployService, self._services.get_or_activate("deploy_service"))

    def cluster_service(self) -> ClusterService:
        return cast(ClusterService, self._services.get_or_activate("cluster_service"))

    def gene_service(self) -> GeneService:
        return cast(GeneService, self._services.get_or_activate("gene_service"))

    def instance_template_service(self) -> InstanceTemplateService:
        return cast(
            InstanceTemplateService, self._services.get_or_activate("instance_template_service")
        )

    def instance_file_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("instance_file_service"))

    def instance_channel_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("instance_channel_service"))

    # === Infra Container delegates ===

    def redis(self) -> redis.Redis | None:
        return cast(redis.Redis | None, self._services.get_or_activate("redis"))

    def sequence_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("sequence_service"))

    def hitl_message_bus(self) -> HITLMessageBusPort | None:
        return cast(HITLMessageBusPort | None, self._services.get_or_activate("hitl_message_bus"))

    def agent_message_bus(self) -> Any:
        return cast(Any, self._services.get_or_activate("agent_message_bus"))

    def storage_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("storage_service"))

    def distributed_lock_adapter(self) -> Any:
        return cast(Any, self._services.get_or_activate("distributed_lock_adapter"))

    def workflow_engine_port(self) -> WorkflowEnginePort | None:
        return cast(
            WorkflowEnginePort | None, self._services.get_or_activate("workflow_engine_port")
        )

    def sandbox_adapter(self) -> Any:
        return cast(Any, self._services.get_or_activate("sandbox_adapter"))

    def sandbox_event_publisher(self) -> Any:
        return cast(Any, self._services.get_or_activate("sandbox_event_publisher"))

    # === Sandbox Container delegates ===

    def project_sandbox_repository(self) -> SqlProjectSandboxRepository:
        return cast(
            SqlProjectSandboxRepository,
            self._services.get_or_activate("project_sandbox_repository"),
        )

    def sandbox_orchestrator(self) -> SandboxOrchestrator:
        return cast(SandboxOrchestrator, self._services.get_or_activate("sandbox_orchestrator"))

    def sandbox_tool_registry(self) -> Any:
        return cast(Any, self._services.get_or_activate("sandbox_tool_registry"))

    def sandbox_resource(self) -> SandboxResourcePort:
        return cast(SandboxResourcePort, self._services.get_or_activate("sandbox_resource"))

    def project_sandbox_lifecycle_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("project_sandbox_lifecycle_service"))

    def sandbox_mcp_server_manager(self) -> Any:
        return cast(Any, self._services.get_or_activate("sandbox_mcp_server_manager"))

    def mcp_app_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("mcp_app_service"))

    def mcp_runtime_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("mcp_runtime_service"))

    def dependency_orchestrator(self) -> Any:
        return cast(Any, self._services.get_or_activate("dependency_orchestrator"))

    # === Agent Container delegates ===

    def conversation_repository(self) -> SqlConversationRepository:
        return cast(
            SqlConversationRepository, self._services.get_or_activate("conversation_repository")
        )

    def agent_execution_repository(self) -> SqlAgentExecutionRepository:
        return cast(
            SqlAgentExecutionRepository,
            self._services.get_or_activate("agent_execution_repository"),
        )

    def tool_execution_record_repository(self) -> SqlToolExecutionRecordRepository:
        return cast(
            SqlToolExecutionRecordRepository,
            self._services.get_or_activate("tool_execution_record_repository"),
        )

    def agent_execution_event_repository(self) -> SqlAgentExecutionEventRepository:
        return cast(
            SqlAgentExecutionEventRepository,
            self._services.get_or_activate("agent_execution_event_repository"),
        )

    def execution_checkpoint_repository(self) -> SqlExecutionCheckpointRepository:
        return cast(
            SqlExecutionCheckpointRepository,
            self._services.get_or_activate("execution_checkpoint_repository"),
        )

    def workflow_pattern_repository(self) -> SqlWorkflowPatternRepository:
        return cast(
            SqlWorkflowPatternRepository,
            self._services.get_or_activate("workflow_pattern_repository"),
        )

    def context_summary_adapter(self) -> Any:
        return cast(Any, self._services.get_or_activate("context_summary_adapter"))

    def tool_composition_repository(self) -> SqlToolCompositionRepository:
        return cast(
            SqlToolCompositionRepository,
            self._services.get_or_activate("tool_composition_repository"),
        )

    def tool_environment_variable_repository(self) -> SqlToolEnvironmentVariableRepository:
        return cast(
            SqlToolEnvironmentVariableRepository,
            self._services.get_or_activate("tool_environment_variable_repository"),
        )

    def hitl_request_repository(self) -> SqlHITLRequestRepository:
        return cast(
            SqlHITLRequestRepository, self._services.get_or_activate("hitl_request_repository")
        )

    def tenant_agent_config_repository(self) -> SqlTenantAgentConfigRepository:
        return cast(
            SqlTenantAgentConfigRepository,
            self._services.get_or_activate("tenant_agent_config_repository"),
        )

    def skill_repository(self) -> SqlSkillRepository:
        return cast(SqlSkillRepository, self._services.get_or_activate("skill_repository"))

    def skill_version_repository(self) -> Any:
        return cast(Any, self._services.get_or_activate("skill_version_repository"))

    def tenant_skill_config_repository(self) -> SqlTenantSkillConfigRepository:
        return cast(
            SqlTenantSkillConfigRepository,
            self._services.get_or_activate("tenant_skill_config_repository"),
        )

    def subagent_repository(self) -> SqlSubAgentRepository:
        return cast(SqlSubAgentRepository, self._services.get_or_activate("subagent_repository"))

    def subagent_template_repository(self) -> SqlSubAgentTemplateRepository:
        return cast(
            SqlSubAgentTemplateRepository,
            self._services.get_or_activate("subagent_template_repository"),
        )

    def agent_registry(self) -> Any:
        return cast(Any, self._services.get_or_activate("agent_registry"))

    def agent_binding_repository(self) -> Any:
        return cast(Any, self._services.get_or_activate("agent_binding_repository"))

    def binding_router(self) -> Any:
        return cast(Any, self._services.get_or_activate("binding_router"))

    def attachment_repository(self) -> Any:
        return cast(Any, self._services.get_or_activate("attachment_repository"))

    def attachment_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("attachment_service"))

    def artifact_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("artifact_service"))

    def skill_service(self) -> SkillService:
        return cast(SkillService, self._services.get_or_activate("skill_service"))

    def skill_evolution_plugin(self) -> Any:
        """Get or initialize the skill evolution plugin (cached singleton).

        Wires the plugin with its heavy dependencies (skill service,
        LLM provider manager, DB session factory) on first access.
        The hook registration happens separately in the builtin hooks
        init so that data capture works even before full init.
        """
        if self._session_factory is None:
            return None
        if self._db is None:
            logger.info("Skill evolution plugin not initialized: DB-scoped container is required")
            return None

        from src.application.services.llm_provider_manager import (
            get_llm_provider_manager,
        )
        from src.infrastructure.agent.plugins.registry import (
            get_plugin_registry,
        )
        from src.infrastructure.agent.plugins.skill_evolution.config import (
            SkillEvolutionConfig,
        )
        from src.infrastructure.agent.plugins.skill_evolution.plugin import (
            register_builtin_skill_evolution_plugin,
        )

        config = SkillEvolutionConfig.from_env()
        if not config.enabled:
            return None

        try:
            registry = get_plugin_registry()
            llm_provider_manager = get_llm_provider_manager()
            return register_builtin_skill_evolution_plugin(
                registry=registry,
                config=config,
                skill_service=self.skill_service(),
                llm_provider_manager=llm_provider_manager,
                session_factory=self._session_factory,
            )
        except Exception:
            logger.exception("Failed to initialize skill evolution plugin")
            return None

    def workspace_manager(self) -> Any:
        return cast(Any, self._services.get_or_activate("workspace_manager"))

    def agent_session_registry(self) -> Any:
        return cast(Any, self._services.get_or_activate("agent_session_registry"))

    def spawn_manager(self) -> Any:
        return cast(Any, self._services.get_or_activate("spawn_manager"))

    def subagent_run_registry(self) -> Any:
        return cast(Any, self._services.get_or_activate("subagent_run_registry"))

    def agent_orchestrator(self) -> Any:
        return cast(Any, self._services.get_or_activate("agent_orchestrator"))

    def graph_repository(self) -> Any:
        return cast(Any, self._services.get_or_activate("graph_repository"))

    def graph_run_repository(self) -> Any:
        return cast(Any, self._services.get_or_activate("graph_run_repository"))

    def graph_orchestrator(self) -> Any:
        return cast(Any, self._services.get_or_activate("graph_orchestrator"))

    def agent_service(self, llm: LLMClient) -> AgentService:
        return self._agent.agent_service(llm)

    def event_converter(self) -> Any:
        return cast(Any, self._services.get_or_activate("event_converter"))

    def attachment_processor(self) -> Any:
        return cast(Any, self._services.get_or_activate("attachment_processor"))

    def llm_invoker(self, llm: LLMClient) -> Any:
        return self._agent.llm_invoker(llm)

    def tool_executor(self, tools: dict[str, Any]) -> Any:
        return self._agent.tool_executor(tools)

    def artifact_extractor(self) -> Any:
        return cast(Any, self._services.get_or_activate("artifact_extractor"))

    def react_loop(self, llm: LLMClient, tools: dict[str, Any]) -> Any:
        return self._agent.react_loop(llm, tools)

    def message_builder(self) -> Any:
        return cast(Any, self._services.get_or_activate("message_builder"))

    def attachment_injector(self) -> Any:
        return cast(Any, self._services.get_or_activate("attachment_injector"))

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
        return cast(
            FindSimilarPattern, self._services.get_or_activate("find_similar_pattern_use_case")
        )

    def learn_pattern_use_case(self) -> LearnPattern:
        return cast(LearnPattern, self._services.get_or_activate("learn_pattern_use_case"))

    def workflow_learner(self) -> WorkflowLearner:
        return cast(WorkflowLearner, self._services.get_or_activate("workflow_learner"))

    def compose_tools_use_case(self, llm: LLMClient) -> ComposeToolsUseCase:
        return self._agent.compose_tools_use_case(llm)

    # === Multi-Agent Services (Phase 1-4) ===

    def span_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("span_service"))

    def fork_merge_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("fork_merge_service"))

    def layered_tool_policy_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("layered_tool_policy_service"))

    def default_message_router(self) -> Any:
        return cast(Any, self._services.get_or_activate("default_message_router"))

    def message_binding_repository(self) -> Any:
        return cast(Any, self._services.get_or_activate("message_binding_repository"))

    def agent_router_service(self) -> Any:
        return cast(Any, self._services.get_or_activate("agent_router_service"))

    def redis_agent_namespace(self) -> Any:
        return cast(Any, self._services.get_or_activate("redis_agent_namespace"))

    def redis_agent_credential_scope(self) -> Any:
        return cast(Any, self._services.get_or_activate("redis_agent_credential_scope"))

    def default_context_engine(self, window_manager: Any | None = None) -> Any:
        return self._agent.default_context_engine(window_manager)

    # === Event Log & Webhooks ===

    def event_log_repository(self) -> Any:
        from src.infrastructure.adapters.secondary.persistence.sql_event_log_repository import (
            SqlEventLogRepository,
        )

        return SqlEventLogRepository(self._require_db("event_log_repository"))

    def event_log_service(self) -> Any:
        from src.application.services.event_log_service import EventLogService

        return EventLogService(self.event_log_repository())

    def webhook_repository(self) -> Any:
        from src.infrastructure.adapters.secondary.persistence.sql_webhook_repository import (
            SqlWebhookRepository,
        )

        return SqlWebhookRepository(self._require_db("webhook_repository"))

    def webhook_service(self) -> Any:
        from src.application.services.webhook_service import WebhookService

        return WebhookService(self.webhook_repository())
