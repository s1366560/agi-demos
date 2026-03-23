"""DI sub-container for agent domain."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.ports.agent.agent_tool_port import AgentToolBase

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.agent_service import AgentService
from src.application.services.skill_service import SkillService
from src.application.services.workflow_learner import WorkflowLearner
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
from src.configuration.config import Settings
from src.domain.llm_providers.llm_types import LLMClient
from src.domain.ports.services.graph_service_port import GraphServicePort
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
from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
    SqlSkillVersionRepository,
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
from src.infrastructure.agent.orchestration import AgentSessionRegistry

logger = logging.getLogger(__name__)


async def _publish_to_agent_stream(
    event_bus: Any,
    conversation_id: str,
    event: Any,
) -> None:
    """Publish a domain event to the agent chat SSE stream.

    This allows events produced outside the ReAct actor loop
    (e.g. background artifact uploads) to reach the frontend
    via the same ``agent:events:{conversation_id}`` Redis stream
    that the SSE endpoint reads.
    """
    try:
        event_dict: dict[str, Any] = dict(event.to_event_dict())
        event_data = event_dict.get("data", {})
        if isinstance(event_data, dict):
            event_data["conversation_id"] = conversation_id

        stream_event_payload: dict[str, Any] = {
            "type": event_dict.get("type", "unknown"),
            "event_time_us": int(time.time() * 1_000_000),
            "event_counter": 0,
            "data": event_data,
            "timestamp": event_dict.get("timestamp", ""),
            "conversation_id": conversation_id,
            "message_id": "",
        }

        stream_key = f"agent:events:{conversation_id}"

        await event_bus.stream_add(stream_key, stream_event_payload, maxlen=1000)
        await event_bus.publish(stream_key, stream_event_payload)

        logger.info(
            "[AgentContainer] Published %s to %s",
            event_dict.get("type"),
            stream_key,
        )
    except Exception:
        logger.warning(
            "[AgentContainer] Failed to publish event to agent stream",
            exc_info=True,
        )


class AgentContainer:
    """Sub-container for agent-related repositories, services, and use cases.

    Provides factory methods for all agent domain objects including
    repositories, orchestrators, use cases, plan mode, and context management.
    Cross-domain dependencies are injected via callbacks.
    """

    def __init__(
        self,
        db: AsyncSession | None = None,
        graph_service: GraphServicePort | None = None,
        redis_client: redis.Redis | None = None,
        settings: Settings | None = None,
        neo4j_client_factory: Callable[..., Any] | None = None,
        storage_service_factory: Callable[..., Any] | None = None,
        sandbox_orchestrator_factory: Callable[..., Any] | None = None,
        sandbox_event_publisher_factory: Callable[..., Any] | None = None,
        sequence_service_factory: Callable[..., Any] | None = None,
        agent_message_bus_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._db = db
        self._graph_service = graph_service
        self._redis_client = redis_client
        self._settings = settings
        self._neo4j_client_factory = neo4j_client_factory
        self._storage_service_factory = storage_service_factory
        self._sandbox_orchestrator_factory = sandbox_orchestrator_factory
        self._sandbox_event_publisher_factory = sandbox_event_publisher_factory
        self._sequence_service_factory = sequence_service_factory
        self._agent_message_bus_factory = agent_message_bus_factory
        self._skill_service_instance: SkillService | None = None
        self._workspace_manager_instance: Any | None = None
        self._agent_session_registry_instance: AgentSessionRegistry | None = None
        self._spawn_manager_instance: Any | None = None
        self._agent_orchestrator_instance: Any | None = None
        self._subagent_run_registry_instance: Any | None = None
        self._spawn_validator_instance: Any | None = None
        self._announce_service_instance: Any | None = None
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

    def tool_composition_repository(self) -> SqlToolCompositionRepository:
        """Get SqlToolCompositionRepository for tool composition persistence."""
        assert self._db is not None
        return SqlToolCompositionRepository(self._db)

    def tool_environment_variable_repository(self) -> SqlToolEnvironmentVariableRepository:
        """Get SqlToolEnvironmentVariableRepository for tool env var persistence."""
        assert self._db is not None
        return SqlToolEnvironmentVariableRepository(self._db)

    def hitl_request_repository(self) -> SqlHITLRequestRepository:
        """Get SqlHITLRequestRepository for HITL request persistence."""
        assert self._db is not None
        return SqlHITLRequestRepository(self._db)

    def tenant_agent_config_repository(self) -> SqlTenantAgentConfigRepository:
        """Get SqlTenantAgentConfigRepository for tenant agent config persistence."""
        assert self._db is not None
        return SqlTenantAgentConfigRepository(self._db)

    def skill_repository(self) -> SqlSkillRepository:
        """Get SqlSkillRepository for skill persistence."""
        assert self._db is not None
        return SqlSkillRepository(self._db)

    def skill_version_repository(self) -> SqlSkillVersionRepository:
        """Get SqlSkillVersionRepository for skill version persistence."""
        assert self._db is not None
        return SqlSkillVersionRepository(self._db)

    def tenant_skill_config_repository(self) -> SqlTenantSkillConfigRepository:
        """Get SqlTenantSkillConfigRepository for tenant skill config persistence."""
        assert self._db is not None
        return SqlTenantSkillConfigRepository(self._db)

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

    # === Attachment & Artifact ===

    def attachment_repository(self) -> Any:
        """Get AttachmentRepository for attachment persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_attachment_repository import (
            SqlAttachmentRepository,
        )

        assert self._db is not None
        return SqlAttachmentRepository(self._db)

    def attachment_service(self) -> Any:
        """Get AttachmentService for file upload handling."""
        from src.application.services.attachment_service import AttachmentService

        storage_service = self._storage_service_factory() if self._storage_service_factory else None
        assert storage_service is not None
        assert self._settings is not None
        return AttachmentService(
            storage_service=storage_service,
            attachment_repository=self.attachment_repository(),
            upload_max_size_llm_mb=self._settings.upload_max_size_llm_mb,
            upload_max_size_sandbox_mb=self._settings.upload_max_size_sandbox_mb,
        )

    def artifact_service(self) -> Any:
        """Get ArtifactService for managing tool output artifacts."""
        from src.application.services.artifact_service import ArtifactService

        storage_service = self._storage_service_factory() if self._storage_service_factory else None

        event_publisher = None
        try:
            if self._sandbox_event_publisher_factory:
                sandbox_event_pub = self._sandbox_event_publisher_factory()
                if sandbox_event_pub and sandbox_event_pub._event_bus:

                    async def publish_event(
                        project_id: str,
                        event: Any,
                        *,
                        conversation_id: str | None = None,
                    ) -> None:
                        # Always publish to sandbox stream
                        await sandbox_event_pub._publish(project_id, event)
                        # Also publish to agent chat stream so the
                        # frontend SSE receives artifact_ready/error.
                        if conversation_id:
                            await _publish_to_agent_stream(
                                sandbox_event_pub._event_bus,
                                conversation_id,
                                event,
                            )

                    event_publisher = publish_event
        except Exception:
            pass

        assert storage_service is not None
        return ArtifactService(
            storage_service=storage_service,
            event_publisher=event_publisher,
            bucket_prefix="artifacts",
            url_expiration_seconds=7 * 24 * 3600,
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

    # === Workspace Manager ===

    def workspace_manager(self) -> Any:
        """Get WorkspaceManager for loading persona/soul workspace files (cached singleton)."""
        if self._workspace_manager_instance is not None:
            return self._workspace_manager_instance

        from pathlib import Path

        from src.infrastructure.agent.workspace.manager import WorkspaceManager

        settings = self._settings
        enabled = settings.workspace_enabled if settings else True
        workspace_dir = settings.workspace_dir if settings else "/workspace/.memstack/workspace"
        tenant_workspace_dir_str = settings.tenant_workspace_dir if settings else ""
        max_per_file = settings.workspace_max_chars_per_file if settings else 20000
        max_total = settings.workspace_max_chars_total if settings else 150000

        self._workspace_manager_instance = WorkspaceManager(
            workspace_dir=Path(workspace_dir),
            tenant_workspace_dir=Path(tenant_workspace_dir_str)
            if tenant_workspace_dir_str
            else None,
            max_chars_per_file=max_per_file,
            max_chars_total=max_total,
            enabled=enabled,
        )
        return self._workspace_manager_instance

    def agent_session_registry(self) -> AgentSessionRegistry:
        """Get AgentSessionRegistry singleton (in-memory, no DB dependency)."""
        if self._agent_session_registry_instance is not None:
            return self._agent_session_registry_instance
        self._agent_session_registry_instance = AgentSessionRegistry()
        return self._agent_session_registry_instance

    def spawn_manager(self) -> Any:
        """Get SpawnManager singleton (in-memory, no DB dependency)."""
        if self._spawn_manager_instance is not None:
            return self._spawn_manager_instance
        from src.infrastructure.agent.orchestration.spawn_manager import (
            SpawnManager,
        )

        self._spawn_manager_instance = SpawnManager(
            session_registry=self.agent_session_registry(),
        )
        return self._spawn_manager_instance

    def subagent_run_registry(self) -> Any:
        """Get SubAgentRunRegistry singleton (in-memory run tracking)."""
        if self._subagent_run_registry_instance is not None:
            return self._subagent_run_registry_instance
        from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

        self._subagent_run_registry_instance = SubAgentRunRegistry()
        return self._subagent_run_registry_instance

    def spawn_policy(self) -> Any:
        """Create SpawnPolicy from application settings."""
        from src.domain.model.agent.spawn_policy import SpawnPolicy

        return SpawnPolicy.from_settings(self._settings) if self._settings else SpawnPolicy()

    def spawn_validator(self) -> Any:
        """Get SpawnValidator singleton."""
        if self._spawn_validator_instance is not None:
            return self._spawn_validator_instance
        from src.infrastructure.agent.subagent.spawn_validator import SpawnValidator

        self._spawn_validator_instance = SpawnValidator(
            policy=self.spawn_policy(),
            run_registry=self.subagent_run_registry(),
        )
        return self._spawn_validator_instance

    def announce_service(self) -> Any:
        """Get AnnounceService singleton."""
        if self._announce_service_instance is not None:
            return self._announce_service_instance
        from src.domain.model.agent.announce_config import AnnounceConfig
        from src.infrastructure.agent.subagent.announce_service import AnnounceService

        assert self._redis_client is not None, "redis_client is required for AnnounceService"
        config = (
            AnnounceConfig.from_settings(self._settings) if self._settings else AnnounceConfig()
        )
        self._announce_service_instance = AnnounceService(
            redis_client=self._redis_client,
            config=config,
        )
        return self._announce_service_instance

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

    def orphan_sweeper(self, tracker: Any = None) -> Any:
        """Create OrphanSweeper for a given state tracker.

        Not a singleton -- each BackgroundExecutor may have its own tracker.
        """
        from src.infrastructure.agent.subagent.orphan_sweeper import OrphanSweeper

        timeout_seconds = (
            getattr(self._settings, "AGENT_SUBAGENT_TERMINAL_RETENTION_SECONDS", 300)
            if self._settings
            else 300
        )
        return OrphanSweeper(
            tracker=tracker,
            redis_client=self._redis_client,
            timeout_seconds=timeout_seconds,
        )

    def agent_orchestrator(self) -> Any:
        """Get AgentOrchestrator singleton for multi-agent coordination."""
        if self._agent_orchestrator_instance is not None:
            return self._agent_orchestrator_instance
        from src.infrastructure.agent.orchestration.orchestrator import (
            AgentOrchestrator,
        )

        message_bus = self._agent_message_bus_factory() if self._agent_message_bus_factory else None
        assert message_bus is not None, (
            "agent_message_bus_factory must be set for AgentOrchestrator"
        )
        self._agent_orchestrator_instance = AgentOrchestrator(
            agent_registry=self.agent_registry(),
            session_registry=self.agent_session_registry(),
            spawn_manager=self.spawn_manager(),
            message_bus=message_bus,
            spawn_validator=self.spawn_validator(),
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
        neo4j_client = self._neo4j_client_factory() if self._neo4j_client_factory else None
        storage_service = self._storage_service_factory() if self._storage_service_factory else None
        sequence_service = (
            self._sequence_service_factory() if self._sequence_service_factory else None
        )

        return AgentService(
            conversation_repository=self.conversation_repository(),
            execution_repository=self.agent_execution_repository(),
            graph_service=self._graph_service,
            llm=llm,
            neo4j_client=neo4j_client,
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

    # === Agent Orchestrators ===

    def event_converter(self) -> Any:
        """Get EventConverter for domain event to SSE conversion."""
        from src.infrastructure.agent.events.converter import get_event_converter

        return get_event_converter()

    def attachment_processor(self) -> Any:
        """Get AttachmentProcessor for handling chat attachments."""
        from src.infrastructure.agent.attachment.processor import get_attachment_processor

        return get_attachment_processor()

    def llm_invoker(self, llm: LLMClient) -> Any:
        """Get LLMInvoker for LLM invocation with streaming."""
        from src.infrastructure.agent.llm.invoker import get_llm_invoker

        return get_llm_invoker()

    def tool_executor(self, tools: dict[str, Any]) -> Any:
        """Get ToolExecutor for tool execution with permission checking."""
        from src.infrastructure.agent.tools.executor import get_tool_executor

        return get_tool_executor()

    def artifact_extractor(self) -> Any:
        """Get ArtifactExtractor for extracting artifacts from tool results."""
        from src.infrastructure.agent.artifact.extractor import get_artifact_extractor

        return get_artifact_extractor()

    def react_loop(self, llm: LLMClient, tools: dict[str, Any]) -> Any:
        """Get ReActLoop for core reasoning loop."""
        from src.infrastructure.agent.core.react_loop import ReActLoop

        return ReActLoop(
            llm_invoker=self.llm_invoker(llm),
            tool_executor=self.tool_executor(tools),
        )

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
        return CreateConversationUseCase(self.agent_service(llm))

    def list_conversations_use_case(self, llm: LLMClient) -> ListConversationsUseCase:
        """Get ListConversationsUseCase with dependencies injected."""
        return ListConversationsUseCase(self.agent_service(llm))

    def get_conversation_use_case(self, llm: LLMClient) -> GetConversationUseCase:
        """Get GetConversationUseCase with dependencies injected."""
        return GetConversationUseCase(self.agent_service(llm))

    def chat_use_case(self, llm: LLMClient) -> ChatUseCase:
        """Get ChatUseCase with dependencies injected."""
        return ChatUseCase(self.agent_service(llm))

    # === Multi-Level Thinking Use Cases ===

    def execute_step_use_case(self, llm: LLMClient) -> ExecuteStepUseCase:
        """Get ExecuteStepUseCase with dependencies injected.

        NOTE: ExecuteStepUseCase is a placeholder (raises NotImplementedError).
        Tools are configured via module-level configure_*() functions for the
        main ReAct agent system; this use case just needs valid DI wiring.
        """
        from src.infrastructure.agent.tools.desktop_tool import (
            configure_desktop,
        )
        from src.infrastructure.agent.tools.terminal_tool import (
            configure_terminal,
        )
        from src.infrastructure.agent.tools.web_scrape import (
            configure_web_scrape,
        )
        from src.infrastructure.agent.tools.web_search import (
            configure_web_search,
        )

        sandbox_orchestrator = (
            self._sandbox_orchestrator_factory() if self._sandbox_orchestrator_factory else None
        )

        # Configure decorator-based tool globals (used by the main agent system)
        configure_web_search(redis_client=self._redis_client)
        configure_web_scrape()
        configure_desktop(sandbox_orchestrator=sandbox_orchestrator)
        configure_terminal(sandbox_orchestrator=sandbox_orchestrator)

        from src.infrastructure.agent.tools.handoff_tool import configure_handoff

        configure_handoff(graph_orchestrator=self.graph_orchestrator())

        # Pass empty tools dict; ExecuteStepUseCase is a placeholder
        tools: dict[str, AgentToolBase] = {}

        return ExecuteStepUseCase(
            llm=llm,
            tools=tools,
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

    def compose_tools_use_case(self, llm: LLMClient) -> ComposeToolsUseCase:
        """Get ComposeToolsUseCase for tool composition."""
        return ComposeToolsUseCase(
            composition_repository=self.tool_composition_repository(),
            available_tools={},
        )
