from typing import TYPE_CHECKING, Optional

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from temporalio.client import Client as TemporalClient

# Application Services
from src.application.services.agent_service import AgentService
from src.application.services.memory_service import MemoryService
from src.application.services.project_service import ProjectService
from src.application.services.sandbox_orchestrator import (
    SandboxOrchestrator,
)
from src.application.services.search_service import SearchService
from src.application.services.skill_service import SkillService
from src.application.services.task_service import TaskService
from src.application.services.tenant_service import TenantService
from src.application.services.unified_sandbox_service import (
    UnifiedSandboxService,
)
from src.application.services.workflow_learner import WorkflowLearner

# Agent use cases
from src.application.use_cases.agent import (
    ChatUseCase,
    ComposeToolsUseCase,
    CreateConversationUseCase,
    ExecuteStepUseCase,
    FindSimilarPattern,
    GetConversationUseCase,
    LearnPattern,
    ListConversationsUseCase,
    PlanWorkUseCase,
    SynthesizeResultsUseCase,
)

# Memory use cases
from src.application.use_cases.memory.create_memory import (
    CreateMemoryUseCase as MemCreateMemoryUseCase,
)
from src.application.use_cases.memory.delete_memory import (
    DeleteMemoryUseCase as MemDeleteMemoryUseCase,
)
from src.application.use_cases.memory.get_memory import GetMemoryUseCase as MemGetMemoryUseCase
from src.application.use_cases.memory.list_memories import ListMemoriesUseCase
from src.application.use_cases.memory.search_memory import SearchMemoryUseCase

# Task use cases
from src.application.use_cases.task import (
    CreateTaskUseCase,
    GetTaskUseCase,
    ListTasksUseCase,
    UpdateTaskUseCase,
)
from src.configuration.config import get_settings
from src.domain.ports.services.graph_service_port import GraphServicePort
from src.domain.ports.services.hitl_message_bus_port import HITLMessageBusPort
from src.domain.ports.services.sandbox_resource_port import (
    SandboxResourcePort,
)

# Workflow Engine Port
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAlchemyAgentExecutionEventRepository,
)

# Infrastructure adapters
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAlchemyAgentExecutionRepository,
)

# Infrastructure adapters
# Domain ports
# Repositories
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAlchemyAPIKeyRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlAlchemyConversationRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_execution_checkpoint_repository import (
    SqlAlchemyExecutionCheckpointRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SQLHITLRequestRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
    SqlAlchemyMemoryRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
    SqlAlchemyProjectRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
    SqlAlchemyProjectSandboxRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
    SQLSkillRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_subagent_repository import (
    SQLSubAgentRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_task_repository import (
    SqlAlchemyTaskRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_repository import (
    SQLTenantAgentConfigRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_repository import (
    SqlAlchemyTenantRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tool_composition_repository import (
    SQLToolCompositionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
    SQLToolEnvironmentVariableRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tool_execution_record_repository import (
    SqlAlchemyToolExecutionRecordRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
    SqlAlchemyUserRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_work_plan_repository import (
    SQLWorkPlanRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workflow_pattern_repository import (
    SQLWorkflowPatternRepository,
)

# MCP Temporal Infrastructure
from src.infrastructure.adapters.secondary.temporal.mcp.adapter import MCPTemporalAdapter


class DIContainer:
    """
    Dependency Injection Container for use cases and services.

    This container creates use cases/services with their dependencies injected,
    allowing routers to depend on abstractions rather than concrete implementations.
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        graph_service: Optional[GraphServicePort] = None,
        redis_client: Optional[redis.Redis] = None,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
        workflow_engine: Optional[WorkflowEnginePort] = None,
        temporal_client: Optional["TemporalClient"] = None,
        mcp_temporal_adapter: Optional[MCPTemporalAdapter] = None,
    ):
        self._db = db
        self._graph_service = graph_service
        self._redis_client = redis_client
        self._session_factory = session_factory
        self._workflow_engine = workflow_engine
        self._temporal_client = temporal_client
        self._mcp_temporal_adapter = mcp_temporal_adapter
        self._settings = get_settings()

    def with_db(self, db: AsyncSession) -> "DIContainer":
        """Create a new container instance with a specific db session.

        This is useful for WebSocket handlers and other contexts where
        the db session is injected separately from the container.
        """
        return DIContainer(
            db=db,
            graph_service=self._graph_service,
            redis_client=self._redis_client,
            session_factory=self._session_factory,
            workflow_engine=self._workflow_engine,
            temporal_client=self._temporal_client,
            mcp_temporal_adapter=self._mcp_temporal_adapter,
        )

    @property
    def neo4j_client(self):
        """Get Neo4j client for direct driver access.

        Returns the client property from NativeGraphAdapter for tools
        that need direct Neo4j access.
        """
        if self._graph_service and hasattr(self._graph_service, "client"):
            return self._graph_service.client
        return None

    @property
    def graph_service(self):
        """Get the GraphServicePort for graph operations."""
        return self._graph_service

    def redis(self) -> Optional[redis.Redis]:
        """Get the Redis client for cache operations."""
        return self._redis_client

    def hitl_message_bus(self) -> Optional[HITLMessageBusPort]:
        """Get the HITL message bus for cross-process communication.

        Returns the Redis Streams based message bus for HITL tools
        (decision, clarification, env_var). This replaces the old
        pub/sub mechanism for more reliable message delivery.
        """
        if not self._redis_client:
            return None
        from src.infrastructure.adapters.secondary.messaging.redis_hitl_message_bus import (
            RedisHITLMessageBusAdapter,
        )

        return RedisHITLMessageBusAdapter(self._redis_client)

    def sandbox_adapter(self):
        """Get the MCP Sandbox adapter for desktop and terminal management."""
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        settings = get_settings()
        return MCPSandboxAdapter(
            mcp_image=settings.sandbox_default_image,
            default_timeout=settings.sandbox_timeout_seconds,
            default_memory_limit=settings.sandbox_memory_limit,
            default_cpu_limit=settings.sandbox_cpu_limit,
        )

    # === Repositories ===

    def memory_repository(self) -> SqlAlchemyMemoryRepository:
        return SqlAlchemyMemoryRepository(self._db)

    def user_repository(self) -> SqlAlchemyUserRepository:
        return SqlAlchemyUserRepository(self._db)

    def project_repository(self) -> SqlAlchemyProjectRepository:
        return SqlAlchemyProjectRepository(self._db)

    def task_repository(self) -> SqlAlchemyTaskRepository:
        return SqlAlchemyTaskRepository(self._db)

    def tenant_repository(self) -> SqlAlchemyTenantRepository:
        return SqlAlchemyTenantRepository(self._db)

    def api_key_repository(self) -> SqlAlchemyAPIKeyRepository:
        return SqlAlchemyAPIKeyRepository(self._db)

    # === Agent Repositories ===

    def conversation_repository(self) -> SqlAlchemyConversationRepository:
        return SqlAlchemyConversationRepository(self._db)

    def agent_execution_repository(self) -> SqlAlchemyAgentExecutionRepository:
        return SqlAlchemyAgentExecutionRepository(self._db)

    def tool_execution_record_repository(self) -> SqlAlchemyToolExecutionRecordRepository:
        return SqlAlchemyToolExecutionRecordRepository(self._db)

    def agent_execution_event_repository(self) -> SqlAlchemyAgentExecutionEventRepository:
        return SqlAlchemyAgentExecutionEventRepository(self._db)

    def execution_checkpoint_repository(self) -> SqlAlchemyExecutionCheckpointRepository:
        return SqlAlchemyExecutionCheckpointRepository(self._db)

    def work_plan_repository(self) -> SQLWorkPlanRepository:
        return SQLWorkPlanRepository(self._db)

    def workflow_pattern_repository(self) -> SQLWorkflowPatternRepository:
        return SQLWorkflowPatternRepository(self._db)

    def project_sandbox_repository(self) -> SqlAlchemyProjectSandboxRepository:
        return SqlAlchemyProjectSandboxRepository(self._db)

    def tool_composition_repository(self) -> SQLToolCompositionRepository:
        return SQLToolCompositionRepository(self._db)

    def tool_environment_variable_repository(self) -> SQLToolEnvironmentVariableRepository:
        """Get SQLToolEnvironmentVariableRepository for tool env var persistence."""
        return SQLToolEnvironmentVariableRepository(self._db)

    def hitl_request_repository(self) -> SQLHITLRequestRepository:
        """Get SQLHITLRequestRepository for HITL request persistence."""
        return SQLHITLRequestRepository(self._db)

    def tenant_agent_config_repository(self) -> SQLTenantAgentConfigRepository:
        return SQLTenantAgentConfigRepository(self._db)

    def skill_repository(self) -> SQLSkillRepository:
        """Get SQLSkillRepository for skill persistence."""
        return SQLSkillRepository(self._db)

    def tenant_skill_config_repository(self):
        """Get SQLTenantSkillConfigRepository for tenant skill config persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_tenant_skill_config_repository import (
            SQLTenantSkillConfigRepository,
        )

        return SQLTenantSkillConfigRepository(self._db)

    def subagent_repository(self) -> SQLSubAgentRepository:
        """Get SQLSubAgentRepository for subagent persistence."""
        return SQLSubAgentRepository(self._db)

    def plan_repository(self):
        """Get SqlPlanRepository for plan document persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import (
            SqlPlanRepository,
        )

        return SqlPlanRepository(self._db)

    def plan_execution_repository(self):
        """Get SQLPlanExecutionRepository for unified plan execution persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_plan_execution_repository import (
            SQLPlanExecutionRepository,
        )

        return SQLPlanExecutionRepository(self._db)

    def plan_snapshot_repository(self):
        """Get SQLPlanSnapshotRepository for plan snapshot persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_plan_snapshot_repository import (
            SQLPlanSnapshotRepository,
        )

        return SQLPlanSnapshotRepository(self._db)

    # === Infrastructure ===

    def workflow_engine_port(self) -> Optional[WorkflowEnginePort]:
        """Get WorkflowEnginePort for workflow orchestration (Temporal)."""
        return self._workflow_engine

    async def temporal_client(self) -> Optional["TemporalClient"]:
        """Get Temporal client for direct workflow operations.

        Returns the cached client if available, otherwise creates a new connection.
        Used by MCPTemporalAdapter and other components needing direct Temporal access.
        """
        if self._temporal_client is not None:
            return self._temporal_client

        # Lazy initialization if not provided at construction
        from src.infrastructure.adapters.secondary.temporal.client import TemporalClientFactory

        try:
            self._temporal_client = await TemporalClientFactory.get_client()
            return self._temporal_client
        except Exception:
            return None

    async def mcp_temporal_adapter(self) -> Optional[MCPTemporalAdapter]:
        """Get MCPTemporalAdapter for Temporal-based MCP server management.

        This adapter manages MCP server connections via Temporal Workflows,
        enabling horizontal scaling and fault tolerance.

        Returns:
            MCPTemporalAdapter instance if Temporal is available, None otherwise.
        """
        # Return cached instance if available
        if self._mcp_temporal_adapter is not None:
            return self._mcp_temporal_adapter

        client = await self.temporal_client()
        if client is None:
            return None
        self._mcp_temporal_adapter = MCPTemporalAdapter(client)
        return self._mcp_temporal_adapter

    def get_mcp_temporal_adapter_sync(self) -> Optional[MCPTemporalAdapter]:
        """Get cached MCPTemporalAdapter synchronously.

        This method returns the cached adapter instance without async initialization.
        Use this in synchronous contexts where the adapter was pre-initialized.

        Returns:
            Cached MCPTemporalAdapter instance or None if not initialized.
        """
        return self._mcp_temporal_adapter

    def storage_service(self):
        """Get StorageServicePort for file storage operations (S3/MinIO).

        Returns:
            S3StorageAdapter configured with settings from environment.
        """
        from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import (
            S3StorageAdapter,
        )

        return S3StorageAdapter(
            bucket_name=self._settings.s3_bucket_name,
            region=self._settings.aws_region,
            access_key_id=self._settings.aws_access_key_id,
            secret_access_key=self._settings.aws_secret_access_key,
            endpoint_url=self._settings.s3_endpoint_url,
        )

    def attachment_repository(self):
        """Get AttachmentRepository for attachment persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_attachment_repository import (
            SqlAlchemyAttachmentRepository,
        )

        return SqlAlchemyAttachmentRepository(self._db)

    def attachment_service(self):
        """Get AttachmentService for file upload handling.

        Supports both simple and multipart uploads for agent chat attachments.
        """
        from src.application.services.attachment_service import AttachmentService

        return AttachmentService(
            storage_service=self.storage_service(),
            attachment_repository=self.attachment_repository(),
        )

    def artifact_service(self):
        """Get ArtifactService for managing tool output artifacts.

        Returns:
            ArtifactService configured with storage backend and event publisher.
        """
        from src.application.services.artifact_service import ArtifactService

        # Get event publisher function if available
        event_publisher = None
        try:
            sandbox_event_pub = self.sandbox_event_publisher()
            if sandbox_event_pub and sandbox_event_pub._event_bus:

                async def publish_event(project_id: str, event):
                    await sandbox_event_pub._publish(project_id, event)

                event_publisher = publish_event
        except Exception:
            pass  # Event publishing is optional

        return ArtifactService(
            storage_service=self.storage_service(),
            event_publisher=event_publisher,
            bucket_prefix="artifacts",
            url_expiration_seconds=7 * 24 * 3600,  # 7 days
        )

    # === Application Services ===

    def project_service(self) -> ProjectService:
        return ProjectService(
            project_repo=self.project_repository(), user_repo=self.user_repository()
        )

    def memory_service(self) -> MemoryService:
        if not self._graph_service:
            raise ValueError("graph_service is required for MemoryService")
        return MemoryService(
            memory_repo=self.memory_repository(),
            graph_service=self._graph_service,
        )

    def task_service(self) -> TaskService:
        return TaskService(task_repo=self.task_repository())

    def tenant_service(self) -> TenantService:
        return TenantService(tenant_repo=self.tenant_repository(), user_repo=self.user_repository())

    def search_service(self) -> SearchService:
        if not self._graph_service:
            raise ValueError("graph_service is required for SearchService")
        return SearchService(
            graph_service=self._graph_service, memory_repo=self.memory_repository()
        )

    def skill_service(self) -> SkillService:
        """Get SkillService for progressive skill loading.

        Combines file system skills (.memstack/skills/)
        with database skills for unified access.
        """
        from pathlib import Path

        from src.application.services.filesystem_skill_loader import FileSystemSkillLoader
        from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner

        # Use current working directory as base path for skill scanning
        base_path = Path.cwd()

        # Create scanner with additional vendor skills path
        scanner = FileSystemSkillScanner(
            skill_dirs=[".memstack/skills/"],  # Add vendor skills
        )

        # Create file system loader (tenant_id will be set per-request in AgentService)
        fs_loader = FileSystemSkillLoader(
            base_path=base_path,
            tenant_id="",  # Will be overridden per-request
            project_id=None,
            scanner=scanner,
        )

        return SkillService(
            skill_repository=self.skill_repository(),
            filesystem_loader=fs_loader,
        )

    def sandbox_event_publisher(self):
        """Get SandboxEventPublisher for SSE event emission."""
        from src.application.services.sandbox_event_service import SandboxEventPublisher

        event_bus = None
        if self._redis_client:
            try:
                from src.infrastructure.adapters.secondary.event.redis_event_bus import (
                    RedisEventBusAdapter,
                )

                event_bus = RedisEventBusAdapter(self._redis_client)
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(f"Could not create event bus: {e}")

        return SandboxEventPublisher(event_bus=event_bus)

    def sandbox_orchestrator(self):
        """Get SandboxOrchestrator for unified sandbox service management."""
        return SandboxOrchestrator(
            sandbox_adapter=self.sandbox_adapter(),
            event_publisher=self.sandbox_event_publisher(),
            default_timeout=self._settings.sandbox_timeout_seconds,
        )

    def sandbox_tool_registry(self):
        """Get SandboxToolRegistry for dynamic MCP tool registration to Agent."""
        from src.application.services.sandbox_tool_registry import SandboxToolRegistry

        return SandboxToolRegistry(
            redis_client=self._redis_client,
            mcp_adapter=self.sandbox_adapter(),
        )

    def sandbox_resource(self) -> SandboxResourcePort:
        """Get SandboxResourcePort for agent workflow sandbox access.

        This provides a clean abstraction that decouples agent logic from
        sandbox lifecycle management. Agents should depend on this port
        rather than directly on sandbox implementations.
        """
        return UnifiedSandboxService(
            repository=self.project_sandbox_repository(),
            sandbox_adapter=self.sandbox_adapter(),
            distributed_lock=self.distributed_lock_adapter(),
            default_profile=self._settings.sandbox_profile_type,
            health_check_interval_seconds=60,
            auto_recover=True,
        )

    def distributed_lock_adapter(self):
        """Get Redis-based distributed lock adapter.

        Returns None if Redis client is not available, allowing fallback
        to PostgreSQL advisory locks.
        """
        if self._redis_client is None:
            return None

        from src.infrastructure.adapters.secondary.cache.redis_lock_adapter import (
            RedisDistributedLockAdapter,
        )

        return RedisDistributedLockAdapter(
            redis=self._redis_client,
            namespace="memstack:lock",
            default_ttl=120,  # 2 minutes for container creation
            retry_interval=0.1,
            max_retries=300,  # 30 seconds max wait
        )

    def project_sandbox_lifecycle_service(self):
        """Get ProjectSandboxLifecycleService for project-dedicated sandbox management.

        This service manages persistent sandboxes for projects, ensuring each
        project has exactly one long-running sandbox instance.

        Uses Redis distributed locks when available, falling back to PostgreSQL
        advisory locks if Redis is not configured.
        """
        from src.application.services.project_sandbox_lifecycle_service import (
            ProjectSandboxLifecycleService,
        )

        return ProjectSandboxLifecycleService(
            repository=self.project_sandbox_repository(),
            sandbox_adapter=self.sandbox_adapter(),
            distributed_lock=self.distributed_lock_adapter(),
            default_profile=self._settings.sandbox_profile_type,
            health_check_interval_seconds=60,
            auto_recover=True,
        )

    def agent_service(self, llm) -> AgentService:
        """Get AgentService with dependencies injected."""
        if not self._graph_service:
            raise ValueError("graph_service is required for AgentService")
        return AgentService(
            conversation_repository=self.conversation_repository(),
            execution_repository=self.agent_execution_repository(),
            graph_service=self._graph_service,
            llm=llm,
            neo4j_client=self.neo4j_client,
            plan_work_use_case=self.plan_work_use_case(llm),
            execute_step_use_case=self.execute_step_use_case(llm),
            synthesize_results_use_case=self.synthesize_results_use_case(llm),
            workflow_learner=self.workflow_learner(),
            work_plan_repository=self.work_plan_repository(),
            skill_repository=self.skill_repository(),
            skill_service=self.skill_service(),
            subagent_repository=self.subagent_repository(),
            redis_client=self._redis_client,
            tool_execution_record_repository=self.tool_execution_record_repository(),
            agent_execution_event_repository=self.agent_execution_event_repository(),
            execution_checkpoint_repository=self.execution_checkpoint_repository(),
            storage_service=self.storage_service(),
            mcp_temporal_adapter=self.get_mcp_temporal_adapter_sync(),
            db_session=self._db,
        )

    # === Agent Orchestrators (Hexagonal Architecture Adapters) ===

    def event_converter(self):
        """Get EventConverter for domain event to SSE conversion.

        Part of the refactored ReActAgent architecture (Phase 1.1).
        """
        from src.infrastructure.agent.events.converter import get_event_converter

        return get_event_converter()

    def skill_orchestrator(self):
        """Get SkillOrchestrator for skill matching and execution.

        Part of the refactored ReActAgent architecture (Phase 1.3).
        Implements SkillOrchestratorPort.
        """
        from src.infrastructure.agent.skill.orchestrator import create_skill_orchestrator

        return create_skill_orchestrator()

    def subagent_orchestrator(self):
        """Get SubAgentOrchestrator for sub-agent routing.

        Part of the refactored ReActAgent architecture (Phase 1.4).
        Implements SubAgentOrchestratorPort.
        """
        from src.infrastructure.agent.routing.subagent_orchestrator import (
            create_subagent_orchestrator,
        )

        return create_subagent_orchestrator()

    def attachment_processor(self):
        """Get AttachmentProcessor for handling chat attachments.

        Part of the refactored ReActAgent architecture (Phase 1.2).
        """
        from src.infrastructure.agent.attachment.processor import get_attachment_processor

        return get_attachment_processor()

    def llm_invoker(self, llm):
        """Get LLMInvoker for LLM invocation with streaming.

        Part of the refactored ReActAgent architecture (Phase 2.1).
        Implements LLMInvokerPort.
        """
        from src.infrastructure.agent.llm.invoker import LLMInvoker

        return LLMInvoker(llm_client=llm)

    def tool_executor(self, tools: dict):
        """Get ToolExecutor for tool execution with permission checking.

        Part of the refactored ReActAgent architecture (Phase 2.2).
        Implements ToolExecutorPort.
        """
        from src.infrastructure.agent.tools.executor import ToolExecutor

        return ToolExecutor(tools=tools)

    def hitl_handler(self):
        """Get HITLHandler for human-in-the-loop tool handling.

        Part of the refactored ReActAgent architecture (Phase 2.3).
        """
        from src.infrastructure.agent.hitl.handler import get_hitl_handler

        return get_hitl_handler()

    def artifact_extractor(self):
        """Get ArtifactExtractor for extracting artifacts from tool results.

        Part of the refactored ReActAgent architecture (Phase 2.4).
        """
        from src.infrastructure.agent.artifact.extractor import get_artifact_extractor

        return get_artifact_extractor()

    def work_plan_generator(self, llm):
        """Get WorkPlanGenerator for generating agent work plans.

        Part of the refactored ReActAgent architecture (Phase 2.5).
        """
        from src.infrastructure.agent.planning.work_plan_generator import WorkPlanGenerator

        return WorkPlanGenerator(llm_client=llm)

    def react_loop(self, llm, tools: dict):
        """Get ReActLoop for core reasoning loop.

        Part of the refactored ReActAgent architecture (Phase 2.6).
        Implements ReActLoopPort.
        """
        from src.infrastructure.agent.core.react_loop import ReActLoop

        return ReActLoop(
            llm_invoker=self.llm_invoker(llm),
            tool_executor=self.tool_executor(tools),
        )

    # === Context Management (Phase 5 refactoring) ===

    def message_builder(self):
        """Get MessageBuilder for converting messages to LLM format.

        Part of context management refactoring.
        Implements MessageBuilderPort.
        """
        from src.infrastructure.agent.context.builder import MessageBuilder

        return MessageBuilder()

    def attachment_injector(self):
        """Get AttachmentInjector for injecting attachment context.

        Part of context management refactoring.
        Implements AttachmentInjectorPort.
        """
        from src.infrastructure.agent.context.builder import AttachmentInjector

        return AttachmentInjector()

    def context_facade(self, window_manager=None):
        """Get ContextFacade for unified context management.

        Part of context management refactoring.
        Implements ContextManagerPort.
        """
        from src.infrastructure.agent.context import ContextFacade

        return ContextFacade(
            message_builder=self.message_builder(),
            attachment_injector=self.attachment_injector(),
            window_manager=window_manager,
        )

    # === Agent Use Cases ===

    def create_conversation_use_case(self, llm) -> CreateConversationUseCase:
        """Get CreateConversationUseCase with dependencies injected."""
        return CreateConversationUseCase(self.agent_service(llm))

    def list_conversations_use_case(self, llm) -> ListConversationsUseCase:
        """Get ListConversationsUseCase with dependencies injected."""
        return ListConversationsUseCase(self.agent_service(llm))

    def get_conversation_use_case(self, llm) -> GetConversationUseCase:
        """Get GetConversationUseCase with dependencies injected."""
        return GetConversationUseCase(self.agent_service(llm))

    def chat_use_case(self, llm) -> ChatUseCase:
        """Get ChatUseCase with dependencies injected."""
        return ChatUseCase(self.agent_service(llm))

    # === Multi-Level Thinking Use Cases ===

    def plan_work_use_case(self, llm) -> PlanWorkUseCase:
        """Get PlanWorkUseCase with dependencies injected."""
        return PlanWorkUseCase(
            work_plan_repository=self.work_plan_repository(),
            llm=llm,
        )

    def execute_step_use_case(self, llm) -> ExecuteStepUseCase:
        """Get ExecuteStepUseCase with dependencies injected."""
        from src.infrastructure.agent.tools import (
            DesktopTool,
            TerminalTool,
            WebScrapeTool,
            WebSearchTool,
        )

        sandbox_orchestrator = self.sandbox_orchestrator()

        tools = {
            "web_search": WebSearchTool(self._redis_client),
            "web_scrape": WebScrapeTool(),
            "desktop": DesktopTool(orchestrator=sandbox_orchestrator),
            "terminal": TerminalTool(orchestrator=sandbox_orchestrator),
        }

        return ExecuteStepUseCase(
            work_plan_repository=self.work_plan_repository(),
            llm=llm,
            tools=tools,
        )

    def synthesize_results_use_case(self, llm) -> SynthesizeResultsUseCase:
        """Get SynthesizeResultsUseCase with dependencies injected."""
        return SynthesizeResultsUseCase(llm=llm)

    def find_similar_pattern_use_case(self) -> FindSimilarPattern:
        """Get FindSimilarPattern use case for workflow pattern matching."""
        return FindSimilarPattern(repository=self.workflow_pattern_repository())

    def learn_pattern_use_case(self) -> LearnPattern:
        """Get LearnPattern use case for learning workflow patterns."""
        return LearnPattern(repository=self.workflow_pattern_repository())

    def workflow_learner(self) -> WorkflowLearner:
        """Get WorkflowLearner service for pattern learning."""
        from src.application.services.workflow_learner import WorkflowLearner

        return WorkflowLearner(
            learn_pattern=self.learn_pattern_use_case(),
            find_similar_pattern=self.find_similar_pattern_use_case(),
            repository=self.workflow_pattern_repository(),
        )

    def compose_tools_use_case(self, llm) -> ComposeToolsUseCase:
        """Get ComposeToolsUseCase for tool composition (T113)."""
        return ComposeToolsUseCase(
            tool_composition_repository=self.tool_composition_repository(),
            llm=llm,
        )

    # === Plan Mode Use Cases ===

    def enter_plan_mode_use_case(self):
        """Get EnterPlanModeUseCase for entering Plan Mode."""
        from src.application.use_cases.agent.enter_plan_mode import EnterPlanModeUseCase

        return EnterPlanModeUseCase(
            plan_repository=self.plan_repository(),
            conversation_repository=self.conversation_repository(),
        )

    def exit_plan_mode_use_case(self):
        """Get ExitPlanModeUseCase for exiting Plan Mode."""
        from src.application.use_cases.agent.exit_plan_mode import ExitPlanModeUseCase

        return ExitPlanModeUseCase(
            plan_repository=self.plan_repository(),
            conversation_repository=self.conversation_repository(),
        )

    def update_plan_use_case(self):
        """Get UpdatePlanUseCase for updating plan content."""
        from src.application.use_cases.agent.update_plan import UpdatePlanUseCase

        return UpdatePlanUseCase(plan_repository=self.plan_repository())

    def get_plan_use_case(self):
        """Get GetPlanUseCase for retrieving plans."""
        from src.application.use_cases.agent.get_plan import GetPlanUseCase

        return GetPlanUseCase(plan_repository=self.plan_repository())

    def generate_plan_execution_use_case(self, llm):
        """Get GeneratePlanExecutionUseCase for unified plan execution generation."""
        from src.application.use_cases.agent.generate_plan_execution import (
            GeneratePlanExecutionUseCase,
        )
        from src.infrastructure.agent.planning.plan_generator import PlanGenerator

        plan_generator = PlanGenerator(
            llm_client=llm,
            available_tools=[],  # Will be set at runtime
        )

        return GeneratePlanExecutionUseCase(
            plan_execution_repository=self.plan_execution_repository(),
            plan_generator=plan_generator,
        )

    def execute_plan_use_case(self, llm):
        """Get ExecutePlanUseCase for unified plan execution."""
        from src.application.use_cases.agent.execute_plan import ExecutePlanUseCase

        return ExecutePlanUseCase(
            plan_execution_repository=self.plan_execution_repository(),
            plan_snapshot_repository=self.plan_snapshot_repository(),
            plan_mode_orchestrator=self.plan_mode_orchestrator(llm),
        )

    # === Plan Mode Detection ===

    def plan_mode_cache(self):
        """Get LLMResponseCache for Plan Mode detection."""
        from src.infrastructure.agent.planning import LLMResponseCache

        if not self._settings.plan_mode_cache_enabled:
            return None

        return LLMResponseCache(
            max_size=self._settings.plan_mode_cache_max_size,
            default_ttl=self._settings.plan_mode_cache_ttl,
        )

    def fast_heuristic_detector(self):
        """Get FastHeuristicDetector for Plan Mode Layer 1 & 2."""
        from src.infrastructure.agent.planning import FastHeuristicDetector

        return FastHeuristicDetector(
            high_threshold=self._settings.plan_mode_heuristic_threshold_high,
            low_threshold=self._settings.plan_mode_heuristic_threshold_low,
            min_length=self._settings.plan_mode_min_length,
        )

    def llm_classifier(self, llm):
        """Get LLMClassifier for Plan Mode Layer 3."""
        from src.infrastructure.agent.planning import LLMClassifier

        return LLMClassifier(
            llm_client=llm,
            confidence_threshold=self._settings.plan_mode_llm_confidence_threshold,
        )

    def hybrid_plan_mode_detector(self, llm):
        """Get HybridPlanModeDetector for Plan Mode detection."""
        from src.infrastructure.agent.planning import HybridPlanModeDetector

        return HybridPlanModeDetector(
            heuristic_detector=self.fast_heuristic_detector(),
            llm_classifier=self.llm_classifier(llm),
            cache=self.plan_mode_cache(),
            enabled=self._settings.plan_mode_enabled,
        )

    def plan_mode_orchestrator(self, llm):
        """Get PlanModeOrchestrator for plan execution workflow."""
        from src.infrastructure.agent.planning.plan_adjuster import PlanAdjuster
        from src.infrastructure.agent.planning.plan_executor import PlanExecutor
        from src.infrastructure.agent.planning.plan_generator import PlanGenerator
        from src.infrastructure.agent.planning.plan_mode_orchestrator import (
            PlanModeOrchestrator,
        )
        from src.infrastructure.agent.planning.plan_reflector import PlanReflector

        plan_generator = PlanGenerator(
            llm_client=llm,
            available_tools=[],  # Will be set at runtime
        )

        # Create a basic session processor wrapper
        # Note: The actual session processor should be provided at runtime
        class DummySessionProcessor:
            async def execute_tool(
                self, tool_name: str, tool_input: dict, conversation_id: str
            ) -> str:
                return f"Executed {tool_name}"

        plan_executor = PlanExecutor(
            session_processor=DummySessionProcessor(),
            event_emitter=None,  # Will be set at runtime
            parallel_execution=False,
            max_parallel_steps=3,
        )

        plan_reflector = PlanReflector(
            llm_client=llm,
            max_tokens=2048,
        )

        plan_adjuster = PlanAdjuster()

        return PlanModeOrchestrator(
            plan_generator=plan_generator,
            plan_executor=plan_executor,
            plan_reflector=plan_reflector,
            plan_adjuster=plan_adjuster,
            event_emitter=None,  # Will be set at runtime
            max_reflection_cycles=3,
        )

    # === Memory Use Cases ===

    def create_memory_use_case(self) -> MemCreateMemoryUseCase:
        """Get CreateMemoryUseCase with dependencies injected"""
        if not self._graph_service:
            raise ValueError("graph_service is required for CreateMemoryUseCase")
        return MemCreateMemoryUseCase(self.memory_repository(), self._graph_service)

    def get_memory_use_case(self) -> MemGetMemoryUseCase:
        """Get GetMemoryUseCase with dependencies injected"""
        return MemGetMemoryUseCase(self.memory_repository())

    def list_memories_use_case(self) -> ListMemoriesUseCase:
        """Get ListMemoriesUseCase with dependencies injected"""
        return ListMemoriesUseCase(self.memory_repository())

    def delete_memory_use_case(self) -> MemDeleteMemoryUseCase:
        """Get DeleteMemoryUseCase with dependencies injected"""
        if not self._graph_service:
            raise ValueError("graph_service is required for DeleteMemoryUseCase")
        return MemDeleteMemoryUseCase(self.memory_repository(), self._graph_service)

    def search_memory_use_case(self) -> SearchMemoryUseCase:
        """Get SearchMemoryUseCase with dependencies injected"""
        if not self._graph_service:
            raise ValueError("graph_service is required for SearchMemoryUseCase")
        return SearchMemoryUseCase(self._graph_service)

    # === Task Use Cases ===

    def create_task_use_case(self) -> CreateTaskUseCase:
        """Get CreateTaskUseCase with dependencies injected"""
        return CreateTaskUseCase(self.task_repository())

    def get_task_use_case(self) -> GetTaskUseCase:
        """Get GetTaskUseCase with dependencies injected"""
        return GetTaskUseCase(self.task_repository())

    def list_tasks_use_case(self) -> ListTasksUseCase:
        """Get ListTasksUseCase with dependencies injected"""
        return ListTasksUseCase(self.task_repository())

    def update_task_use_case(self) -> UpdateTaskUseCase:
        """Get UpdateTaskUseCase with dependencies injected"""
        return UpdateTaskUseCase(self.task_repository())
