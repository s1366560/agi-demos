"""DI sub-container for agent domain."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.agent_service import AgentService
from src.application.services.skill_service import SkillService
from src.application.services.workflow_learner import WorkflowLearner
from src.application.use_cases.agent import (
    CreateConversationUseCase,
    ExecuteStepUseCase,
    FindSimilarPattern,
    GetConversationUseCase,
    LearnPattern,
    ListConversationsUseCase,
    SynthesizeResultsUseCase,
)
from src.configuration.config import Settings
from src.domain.llm_providers.llm_types import LLMClient
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAgentExecutionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_context_summary_adapter import (
    SqlContextSummaryAdapter,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_execution_checkpoint_repository import (
    SqlExecutionCheckpointRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_graph_repository import (
    SqlAgentGraphRepository,
    SqlGraphRunRepository,
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
from src.infrastructure.adapters.secondary.persistence.sql_workflow_pattern_repository import (
    SqlWorkflowPatternRepository,
)
from src.infrastructure.agent.context.window_manager import ContextWindowManager
from src.infrastructure.agent.orchestration import AgentSessionRegistry

logger = logging.getLogger(__name__)


class AgentContainer:
    """Sub-container for agent-related repositories, services, and use cases.

    Provides factory methods for all agent domain objects including
    repositories, orchestrators, use cases, plan mode, and context management.
    Cross-domain dependencies are injected via callbacks.
    """

    def __init__(
        self,
        db: AsyncSession | None = None,
        redis_client: redis.Redis | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        settings: Settings | None = None,
        storage_service_factory: Callable[..., Any] | None = None,
        sequence_service_factory: Callable[..., Any] | None = None,
        agent_message_bus_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._db = db
        self._redis_client = redis_client
        self._session_factory = session_factory
        self._settings = settings
        self._storage_service_factory = storage_service_factory
        self._sequence_service_factory = sequence_service_factory
        self._agent_message_bus_factory = agent_message_bus_factory
        self._skill_service_instance: SkillService | None = None
        self._agent_session_registry_instance: AgentSessionRegistry | None = None
        self._spawn_manager_instance: Any | None = None
        self._spawn_manager_run_registry_instance: Any | None = None
        self._agent_orchestrator_instance: Any | None = None
        self._spawn_validator_instance: Any | None = None
        self._spawn_validator_run_registry_instance: Any | None = None
        self._control_channel_instance: Any | None = None
        self._graph_orchestrator_instance: Any | None = None
        self._span_service_instance: Any | None = None
        self._fork_merge_service_instance: Any | None = None
        self._layered_tool_policy_service_instance: Any | None = None
        self._redis_agent_namespace_instance: Any | None = None
        self._redis_agent_credential_scope_instance: Any | None = None

    # === Agent Repositories ===

    def conversation_repository(self) -> SqlConversationRepository:
        """Get SqlConversationRepository for conversation persistence."""
        assert self._db is not None
        return SqlConversationRepository(self._db)

    def agent_execution_repository(self) -> SqlAgentExecutionRepository:
        """Get SqlAgentExecutionRepository for agent execution persistence."""
        assert self._db is not None
        return SqlAgentExecutionRepository(self._db)

    def tool_execution_record_repository(self) -> SqlToolExecutionRecordRepository:
        """Get SqlToolExecutionRecordRepository for tool execution record persistence."""
        assert self._db is not None
        return SqlToolExecutionRecordRepository(self._db)

    def agent_execution_event_repository(self) -> SqlAgentExecutionEventRepository:
        """Get SqlAgentExecutionEventRepository for agent execution event persistence."""
        assert self._db is not None
        return SqlAgentExecutionEventRepository(self._db)

    def execution_checkpoint_repository(self) -> SqlExecutionCheckpointRepository:
        """Get SqlExecutionCheckpointRepository for execution checkpoint persistence."""
        assert self._db is not None
        return SqlExecutionCheckpointRepository(self._db)

    def workflow_pattern_repository(self) -> SqlWorkflowPatternRepository:
        """Get SqlWorkflowPatternRepository for workflow pattern persistence."""
        assert self._db is not None
        return SqlWorkflowPatternRepository(self._db)

    def context_summary_adapter(self) -> SqlContextSummaryAdapter:
        """Get SqlContextSummaryAdapter for context summary persistence."""
        assert self._db is not None
        return SqlContextSummaryAdapter(self._db)

    def context_loader(self) -> Any:
        """Get ContextLoader for smart context loading with summary caching."""
        from src.application.services.agent.context_loader import ContextLoader

        return ContextLoader(
            event_repo=self.agent_execution_event_repository(),
            summary_adapter=self.context_summary_adapter(),
        )

    def hitl_request_repository(self) -> SqlHITLRequestRepository:
        """Get SqlHITLRequestRepository for HITL request persistence."""
        assert self._db is not None
        return SqlHITLRequestRepository(self._db)

    def skill_repository(self) -> SqlSkillRepository:
        """Get SqlSkillRepository for skill persistence."""
        assert self._db is not None
        return SqlSkillRepository(self._db)

    def subagent_repository(self) -> SqlSubAgentRepository:
        """Get SqlSubAgentRepository for subagent persistence."""
        assert self._db is not None
        return SqlSubAgentRepository(self._db)

    def subagent_template_repository(self) -> SqlSubAgentTemplateRepository:
        """Get SqlSubAgentTemplateRepository for template marketplace."""
        assert self._db is not None
        return SqlSubAgentTemplateRepository(self._db)

    def agent_registry(self) -> Any:
        """Get SqlAgentRegistryRepository for agent definition persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
            SqlAgentRegistryRepository,
        )

        assert self._db is not None
        return SqlAgentRegistryRepository(self._db)

    def agent_binding_repository(self) -> Any:
        """Get SqlAgentBindingRepository for agent binding persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_binding_repository import (
            SqlAgentBindingRepository,
        )

        assert self._db is not None
        return SqlAgentBindingRepository(self._db)

    def binding_router(self) -> Any:
        """Get BindingRouter for agent-aware channel routing."""
        from src.infrastructure.agent.channels.channel_router import ChannelRouter
        from src.infrastructure.agent.routing.binding_router import BindingRouter

        return BindingRouter(
            binding_repository=self.agent_binding_repository(),
            agent_registry=self.agent_registry(),
            channel_router=ChannelRouter(),
        )

    # === Skill Service ===

    def skill_service(self) -> SkillService:
        """Get SkillService for progressive skill loading (cached singleton)."""
        if self._skill_service_instance is not None:
            return self._skill_service_instance

        from pathlib import Path

        from src.application.services.filesystem_skill_loader import FileSystemSkillLoader
        from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner

        base_path = Path.cwd()

        scanner = FileSystemSkillScanner(
            skill_dirs=[".memstack/skills/"],
        )

        fs_loader = FileSystemSkillLoader(
            base_path=base_path,
            tenant_id="",
            project_id=None,
            scanner=scanner,
        )

        self._skill_service_instance = SkillService(
            skill_repository=self.skill_repository(),
            filesystem_loader=fs_loader,
        )
        return self._skill_service_instance

    def agent_session_registry(self) -> AgentSessionRegistry:
        """Get AgentSessionRegistry singleton (in-memory, no DB dependency)."""
        if self._agent_session_registry_instance is not None:
            return self._agent_session_registry_instance
        self._agent_session_registry_instance = AgentSessionRegistry()
        return self._agent_session_registry_instance

    def spawn_manager(self) -> Any:
        """Get SpawnManager singleton (in-memory, no DB dependency)."""
        from src.infrastructure.agent.orchestration.spawn_manager import (
            SpawnManager,
        )
        from src.infrastructure.plugins.v2.subagent_run_registry_projection import (
            current_subagent_run_registry_v2,
        )

        run_registry = current_subagent_run_registry_v2()
        if (
            self._spawn_manager_instance is not None
            and self._spawn_manager_run_registry_instance is run_registry
        ):
            return self._spawn_manager_instance
        self._spawn_manager_instance = SpawnManager(
            session_registry=self.agent_session_registry(),
            run_registry=run_registry,
        )
        self._spawn_manager_run_registry_instance = run_registry
        return self._spawn_manager_instance

    def spawn_policy(self) -> Any:
        """Create SpawnPolicy from application settings."""
        from src.domain.model.agent.spawn_policy import SpawnPolicy

        return SpawnPolicy.from_settings(self._settings) if self._settings else SpawnPolicy()

    def spawn_validator(self) -> Any:
        """Get SpawnValidator singleton."""
        from src.infrastructure.agent.subagent.spawn_validator import SpawnValidator
        from src.infrastructure.plugins.v2.subagent_run_registry_projection import (
            current_subagent_run_registry_v2,
        )

        run_registry = current_subagent_run_registry_v2()
        if (
            self._spawn_validator_instance is not None
            and self._spawn_validator_run_registry_instance is run_registry
        ):
            return self._spawn_validator_instance
        self._spawn_validator_instance = SpawnValidator(
            policy=self.spawn_policy(),
            run_registry=run_registry,
        )
        self._spawn_validator_run_registry_instance = run_registry
        return self._spawn_validator_instance

    def control_channel(self) -> Any:
        """Get ControlChannel singleton for steer/kill/pause/resume signals."""
        if self._control_channel_instance is not None:
            return self._control_channel_instance
        from src.infrastructure.agent.subagent.control_channel import (
            RedisControlChannel,
        )

        assert self._redis_client is not None, "redis_client is required for ControlChannel"
        self._control_channel_instance = RedisControlChannel(
            redis_client=self._redis_client,
        )
        return self._control_channel_instance

    def agent_orchestrator(self) -> Any:
        """Get AgentOrchestrator singleton for multi-agent coordination."""
        if self._agent_orchestrator_instance is not None:
            return self._agent_orchestrator_instance
        from src.application.services.agent.runtime_bootstrapper import (
            AgentRuntimeBootstrapper,
        )
        from src.infrastructure.agent.orchestration.orchestrator import (
            AgentOrchestrator,
        )

        message_bus = self._agent_message_bus_factory() if self._agent_message_bus_factory else None
        assert message_bus is not None, (
            "agent_message_bus_factory must be set for AgentOrchestrator"
        )
        runtime_bootstrapper = AgentRuntimeBootstrapper()
        self._agent_orchestrator_instance = AgentOrchestrator(
            agent_registry=self.agent_registry(),
            session_registry=self.agent_session_registry(),
            spawn_manager=self.spawn_manager(),
            message_bus=message_bus,
            spawn_validator=self.spawn_validator(),
            db_session=self._db,
            spawn_executor=runtime_bootstrapper.launch_spawned_agent_session,
        )
        return self._agent_orchestrator_instance

    # === Graph Orchestration ===

    def graph_repository(self) -> SqlAgentGraphRepository:
        """Get SqlAgentGraphRepository for agent graph persistence."""
        assert self._db is not None
        return SqlAgentGraphRepository(self._db)

    def graph_run_repository(self) -> SqlGraphRunRepository:
        """Get SqlGraphRunRepository for graph run persistence."""
        assert self._db is not None
        return SqlGraphRunRepository(self._db)

    def graph_orchestrator(self) -> Any:
        """Get GraphOrchestrator singleton for graph-based multi-agent coordination."""
        if self._graph_orchestrator_instance is not None:
            return self._graph_orchestrator_instance
        from src.infrastructure.agent.orchestration.graph_orchestrator import (
            GraphOrchestrator,
        )

        self._graph_orchestrator_instance = GraphOrchestrator(
            agent_orchestrator=self.agent_orchestrator(),
            graph_repo=self.graph_repository(),
            run_repo=self.graph_run_repository(),
        )
        return self._graph_orchestrator_instance

    # === Agent Service ===

    def agent_service(self, llm: LLMClient) -> AgentService:
        """Get AgentService with dependencies injected."""
        storage_service = self._storage_service_factory() if self._storage_service_factory else None
        sequence_service = (
            self._sequence_service_factory() if self._sequence_service_factory else None
        )

        return AgentService(
            conversation_repository=self.conversation_repository(),
            execution_repository=self.agent_execution_repository(),
            llm=llm,
            execute_step_use_case=self.execute_step_use_case(llm),
            synthesize_results_use_case=self.synthesize_results_use_case(llm),
            workflow_learner=self.workflow_learner(),
            skill_repository=self.skill_repository(),
            skill_service=self.skill_service(),
            subagent_repository=self.subagent_repository(),
            redis_client=self._redis_client,
            tool_execution_record_repository=self.tool_execution_record_repository(),
            agent_execution_event_repository=self.agent_execution_event_repository(),
            execution_checkpoint_repository=self.execution_checkpoint_repository(),
            storage_service=storage_service,
            db_session=self._db,
            sequence_service=sequence_service,
            context_loader=self.context_loader(),
        )

    def _conversation_agent_service(self, llm: LLMClient) -> AgentService:
        """Get AgentService for conversation-only operations.

        Conversation CRUD endpoints are hot paths in the UI and e2e suite. They
        should not configure execution tools or sandbox adapters, which are only
        required once a chat run starts.
        """
        return AgentService(
            conversation_repository=self.conversation_repository(),
            execution_repository=self.agent_execution_repository(),
            llm=llm,
            redis_client=self._redis_client,
        )

    # === Agent Orchestrators ===

    def event_converter(self) -> Any:
        """Get EventConverter for domain event to SSE conversion."""
        from src.infrastructure.agent.events.converter import get_event_converter

        return get_event_converter()

    def attachment_processor(self) -> Any:
        """Get AttachmentProcessor for handling chat attachments."""
        from src.infrastructure.agent.attachment.processor import get_attachment_processor

        return get_attachment_processor()

    # === Context Management ===

    def message_builder(self) -> Any:
        """Get MessageBuilder for converting messages to LLM format."""
        from src.infrastructure.agent.context.builder import MessageBuilder

        return MessageBuilder()

    def attachment_injector(self) -> Any:
        """Get AttachmentInjector for injecting attachment context."""
        from src.infrastructure.agent.context.builder import AttachmentInjector

        return AttachmentInjector()

    def span_service(self) -> Any:
        if self._span_service_instance is not None:
            return self._span_service_instance
        from src.infrastructure.agent.subagent.span_service import SubAgentSpanService

        self._span_service_instance = SubAgentSpanService()
        return self._span_service_instance

    def fork_merge_service(self) -> Any:
        if self._fork_merge_service_instance is not None:
            return self._fork_merge_service_instance
        from src.infrastructure.agent.subagent.session_fork_merge_service import (
            SessionForkMergeService,
        )

        self._fork_merge_service_instance = SessionForkMergeService()
        return self._fork_merge_service_instance

    def layered_tool_policy_service(self) -> Any:
        if self._layered_tool_policy_service_instance is not None:
            return self._layered_tool_policy_service_instance
        from src.application.services.layered_tool_policy_service import (
            LayeredToolPolicyService,
        )

        self._layered_tool_policy_service_instance = LayeredToolPolicyService()
        return self._layered_tool_policy_service_instance

    def default_message_router(self) -> Any:
        from src.infrastructure.agent.routing.default_message_router import (
            DefaultMessageRouter,
        )

        return DefaultMessageRouter(binding_repo=self.message_binding_repository())

    def message_binding_repository(self) -> Any:
        from src.infrastructure.adapters.secondary.persistence.sql_message_binding_repository import (
            SqlMessageBindingRepository,
        )

        assert self._db is not None
        return SqlMessageBindingRepository(self._db)

    def agent_router_service(self) -> Any:
        from src.application.services.agent_router_service import AgentRouterService

        return AgentRouterService(
            binding_repository=self.agent_binding_repository(),
            agent_registry=self.agent_registry(),
        )

    def redis_agent_namespace(self) -> Any:
        if self._redis_agent_namespace_instance is not None:
            return self._redis_agent_namespace_instance
        from src.infrastructure.adapters.secondary.cache.redis_agent_namespace import (
            RedisAgentNamespaceAdapter,
        )

        assert self._redis_client is not None
        self._redis_agent_namespace_instance = RedisAgentNamespaceAdapter(
            redis=self._redis_client,
        )
        return self._redis_agent_namespace_instance

    def redis_agent_credential_scope(self) -> Any:
        if self._redis_agent_credential_scope_instance is not None:
            return self._redis_agent_credential_scope_instance
        from src.infrastructure.adapters.secondary.cache.redis_agent_credential_scope import (
            RedisAgentCredentialScopeAdapter,
        )
        from src.infrastructure.security.encryption_service import EncryptionService

        assert self._redis_client is not None
        encryption_key = self._settings.llm_encryption_key if self._settings else ""
        encryption_service = EncryptionService(encryption_key)
        self._redis_agent_credential_scope_instance = RedisAgentCredentialScopeAdapter(
            redis=self._redis_client,
            encryption_service=encryption_service,
        )
        return self._redis_agent_credential_scope_instance

    def context_facade(self, window_manager: ContextWindowManager | None = None) -> Any:
        """Get ContextFacade for unified context management."""
        from src.infrastructure.agent.context import ContextFacade

        return ContextFacade(
            message_builder=self.message_builder(),
            attachment_injector=self.attachment_injector(),
            window_manager=window_manager,
        )

    def default_context_engine(self, window_manager: ContextWindowManager | None = None) -> Any:
        from src.infrastructure.agent.context.default_context_engine import (
            DefaultContextEngine,
        )

        return DefaultContextEngine(
            context_facade=self.context_facade(window_manager),
        )

    # === Agent Use Cases ===

    def create_conversation_use_case(self, llm: LLMClient) -> CreateConversationUseCase:
        """Get CreateConversationUseCase with dependencies injected."""
        return CreateConversationUseCase(self._conversation_agent_service(llm))

    def list_conversations_use_case(self, llm: LLMClient) -> ListConversationsUseCase:
        """Get ListConversationsUseCase with dependencies injected."""
        return ListConversationsUseCase(self._conversation_agent_service(llm))

    def get_conversation_use_case(self, llm: LLMClient) -> GetConversationUseCase:
        """Get GetConversationUseCase with dependencies injected."""
        return GetConversationUseCase(self._conversation_agent_service(llm))

    # === Multi-Level Thinking Use Cases ===

    def execute_step_use_case(self, llm: LLMClient) -> ExecuteStepUseCase:
        """Get ExecuteStepUseCase with dependencies injected.

        This legacy surface has no explicit tools and therefore performs only
        free-form LLM steps. Agent tools belong to the pinned V2 generation;
        constructing this use case must not mutate their process-wide state.
        """
        return ExecuteStepUseCase(
            llm=llm,
            tools={},
        )

    def synthesize_results_use_case(self, llm: LLMClient) -> SynthesizeResultsUseCase:
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
        return WorkflowLearner(
            learn_pattern=self.learn_pattern_use_case(),
            find_similar_pattern=self.find_similar_pattern_use_case(),
            repository=self.workflow_pattern_repository(),
        )
