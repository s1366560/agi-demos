"""DI sub-container for agent domain."""

from typing import Callable, Optional

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


class AgentContainer:
    """Sub-container for agent-related repositories, services, and use cases.

    Provides factory methods for all agent domain objects including
    repositories, orchestrators, use cases, plan mode, and context management.
    Cross-domain dependencies are injected via callbacks.
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        graph_service: Optional[GraphServicePort] = None,
        redis_client: Optional[redis.Redis] = None,
        settings=None,
        neo4j_client_factory: Optional[Callable] = None,
        storage_service_factory: Optional[Callable] = None,
        sandbox_orchestrator_factory: Optional[Callable] = None,
        sandbox_event_publisher_factory: Optional[Callable] = None,
        sequence_service_factory: Optional[Callable] = None,
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
        self._skill_service_instance: Optional[SkillService] = None

    # === Agent Repositories ===

    def conversation_repository(self) -> SqlConversationRepository:
        """Get SqlConversationRepository for conversation persistence."""
        return SqlConversationRepository(self._db)

    def agent_execution_repository(self) -> SqlAgentExecutionRepository:
        """Get SqlAgentExecutionRepository for agent execution persistence."""
        return SqlAgentExecutionRepository(self._db)

    def tool_execution_record_repository(self) -> SqlToolExecutionRecordRepository:
        """Get SqlToolExecutionRecordRepository for tool execution record persistence."""
        return SqlToolExecutionRecordRepository(self._db)

    def agent_execution_event_repository(self) -> SqlAgentExecutionEventRepository:
        """Get SqlAgentExecutionEventRepository for agent execution event persistence."""
        return SqlAgentExecutionEventRepository(self._db)

    def execution_checkpoint_repository(self) -> SqlExecutionCheckpointRepository:
        """Get SqlExecutionCheckpointRepository for execution checkpoint persistence."""
        return SqlExecutionCheckpointRepository(self._db)

    def workflow_pattern_repository(self) -> SqlWorkflowPatternRepository:
        """Get SqlWorkflowPatternRepository for workflow pattern persistence."""
        return SqlWorkflowPatternRepository(self._db)

    def context_summary_adapter(self) -> SqlContextSummaryAdapter:
        """Get SqlContextSummaryAdapter for context summary persistence."""
        return SqlContextSummaryAdapter(self._db)

    def context_loader(self):
        """Get ContextLoader for smart context loading with summary caching."""
        from src.application.services.agent.context_loader import ContextLoader

        return ContextLoader(
            event_repo=self.agent_execution_event_repository(),
            summary_adapter=self.context_summary_adapter(),
        )

    def tool_composition_repository(self) -> SqlToolCompositionRepository:
        """Get SqlToolCompositionRepository for tool composition persistence."""
        return SqlToolCompositionRepository(self._db)

    def tool_environment_variable_repository(self) -> SqlToolEnvironmentVariableRepository:
        """Get SqlToolEnvironmentVariableRepository for tool env var persistence."""
        return SqlToolEnvironmentVariableRepository(self._db)

    def hitl_request_repository(self) -> SqlHITLRequestRepository:
        """Get SqlHITLRequestRepository for HITL request persistence."""
        return SqlHITLRequestRepository(self._db)

    def tenant_agent_config_repository(self) -> SqlTenantAgentConfigRepository:
        """Get SqlTenantAgentConfigRepository for tenant agent config persistence."""
        return SqlTenantAgentConfigRepository(self._db)

    def skill_repository(self) -> SqlSkillRepository:
        """Get SqlSkillRepository for skill persistence."""
        return SqlSkillRepository(self._db)

    def skill_version_repository(self) -> SqlSkillVersionRepository:
        """Get SqlSkillVersionRepository for skill version persistence."""
        return SqlSkillVersionRepository(self._db)

    def tenant_skill_config_repository(self) -> SqlTenantSkillConfigRepository:
        """Get SqlTenantSkillConfigRepository for tenant skill config persistence."""
        return SqlTenantSkillConfigRepository(self._db)

    def subagent_repository(self) -> SqlSubAgentRepository:
        """Get SqlSubAgentRepository for subagent persistence."""
        return SqlSubAgentRepository(self._db)

    def subagent_template_repository(self) -> SqlSubAgentTemplateRepository:
        """Get SqlSubAgentTemplateRepository for template marketplace."""
        return SqlSubAgentTemplateRepository(self._db)

    # === Attachment & Artifact ===

    def attachment_repository(self):
        """Get AttachmentRepository for attachment persistence."""
        from src.infrastructure.adapters.secondary.persistence.sql_attachment_repository import (
            SqlAttachmentRepository,
        )

        return SqlAttachmentRepository(self._db)

    def attachment_service(self):
        """Get AttachmentService for file upload handling."""
        from src.application.services.attachment_service import AttachmentService

        storage_service = self._storage_service_factory() if self._storage_service_factory else None
        return AttachmentService(
            storage_service=storage_service,
            attachment_repository=self.attachment_repository(),
            upload_max_size_llm_mb=self._settings.upload_max_size_llm_mb,
            upload_max_size_sandbox_mb=self._settings.upload_max_size_sandbox_mb,
        )

    def artifact_service(self):
        """Get ArtifactService for managing tool output artifacts."""
        from src.application.services.artifact_service import ArtifactService

        storage_service = self._storage_service_factory() if self._storage_service_factory else None

        event_publisher = None
        try:
            if self._sandbox_event_publisher_factory:
                sandbox_event_pub = self._sandbox_event_publisher_factory()
                if sandbox_event_pub and sandbox_event_pub._event_bus:

                    async def publish_event(project_id: str, event):
                        await sandbox_event_pub._publish(project_id, event)

                    event_publisher = publish_event
        except Exception:
            pass

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

    # === Agent Service ===

    def agent_service(self, llm) -> AgentService:
        """Get AgentService with dependencies injected."""
        if not self._graph_service:
            raise ValueError("graph_service is required for AgentService")

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

    def event_converter(self):
        """Get EventConverter for domain event to SSE conversion."""
        from src.infrastructure.agent.events.converter import get_event_converter

        return get_event_converter()

    def skill_orchestrator(self):
        """Get SkillOrchestrator for skill matching and execution."""
        from src.infrastructure.agent.skill.orchestrator import create_skill_orchestrator

        return create_skill_orchestrator()

    def subagent_orchestrator(self):
        """Get SubAgentOrchestrator for sub-agent routing."""
        from src.infrastructure.agent.routing.subagent_orchestrator import (
            create_subagent_orchestrator,
        )

        return create_subagent_orchestrator()

    def attachment_processor(self):
        """Get AttachmentProcessor for handling chat attachments."""
        from src.infrastructure.agent.attachment.processor import get_attachment_processor

        return get_attachment_processor()

    def llm_invoker(self, llm):
        """Get LLMInvoker for LLM invocation with streaming."""
        from src.infrastructure.agent.llm.invoker import LLMInvoker

        return LLMInvoker(llm_client=llm)

    def tool_executor(self, tools: dict):
        """Get ToolExecutor for tool execution with permission checking."""
        from src.infrastructure.agent.tools.executor import ToolExecutor

        return ToolExecutor(tools=tools)

    def artifact_extractor(self):
        """Get ArtifactExtractor for extracting artifacts from tool results."""
        from src.infrastructure.agent.artifact.extractor import get_artifact_extractor

        return get_artifact_extractor()

    def react_loop(self, llm, tools: dict):
        """Get ReActLoop for core reasoning loop."""
        from src.infrastructure.agent.core.react_loop import ReActLoop

        return ReActLoop(
            llm_invoker=self.llm_invoker(llm),
            tool_executor=self.tool_executor(tools),
        )

    # === Context Management ===

    def message_builder(self):
        """Get MessageBuilder for converting messages to LLM format."""
        from src.infrastructure.agent.context.builder import MessageBuilder

        return MessageBuilder()

    def attachment_injector(self):
        """Get AttachmentInjector for injecting attachment context."""
        from src.infrastructure.agent.context.builder import AttachmentInjector

        return AttachmentInjector()

    def context_facade(self, window_manager=None):
        """Get ContextFacade for unified context management."""
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

    def execute_step_use_case(self, llm) -> ExecuteStepUseCase:
        """Get ExecuteStepUseCase with dependencies injected."""
        from src.infrastructure.agent.tools import (
            DesktopTool,
            TerminalTool,
            WebScrapeTool,
            WebSearchTool,
        )

        sandbox_orchestrator = (
            self._sandbox_orchestrator_factory() if self._sandbox_orchestrator_factory else None
        )

        tools = {
            "web_search": WebSearchTool(self._redis_client),
            "web_scrape": WebScrapeTool(),
            "desktop": DesktopTool(orchestrator=sandbox_orchestrator),
            "terminal": TerminalTool(orchestrator=sandbox_orchestrator),
        }

        return ExecuteStepUseCase(
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
        return WorkflowLearner(
            learn_pattern=self.learn_pattern_use_case(),
            find_similar_pattern=self.find_similar_pattern_use_case(),
            repository=self.workflow_pattern_repository(),
        )

    def compose_tools_use_case(self, llm) -> ComposeToolsUseCase:
        """Get ComposeToolsUseCase for tool composition."""
        return ComposeToolsUseCase(
            tool_composition_repository=self.tool_composition_repository(),
            llm=llm,
        )
