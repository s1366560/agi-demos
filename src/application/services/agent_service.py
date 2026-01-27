"""Agent service for coordinating ReAct agent operations.

This service provides the main interface for interacting with the ReAct agent,
including conversation management and streaming chat responses.

Multi-Level Thinking Support:
- Work-level planning for complex queries
- Task-level execution with detailed thinking
- SSE events for real-time observability

MCP (Model Context Protocol) Support:
- Dynamic tool loading from Temporal MCP servers
- Automatic tool namespace management
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Optional

from src.domain.events.agent_events import AgentMessageEvent, AgentEventType
from src.domain.llm_providers.llm_types import LLMClient
from src.domain.llm_providers.llm_types import Message as LLMMessage
from src.domain.model.agent import (
    AgentExecution,
    AgentExecutionEvent,
    Conversation,
    ConversationStatus,
)
from src.domain.ports.repositories.agent_repository import (
    AgentExecutionEventRepository,
    AgentExecutionRepository,
    ConversationRepository,
    ExecutionCheckpointRepository,
    ToolExecutionRecordRepository,
)
from src.domain.ports.services.agent_service_port import AgentServicePort
from src.domain.ports.services.graph_service_port import GraphServicePort
from src.infrastructure.agent.tools import (
    SkillLoaderTool,
    WebScrapeTool,
    WebSearchTool,
)

if TYPE_CHECKING:
    from src.application.services.skill_service import SkillService
    from src.application.services.workflow_learner import WorkflowLearner
    from src.application.use_cases.agent import (
        ExecuteStepUseCase,
        PlanWorkUseCase,
        SynthesizeResultsUseCase,
    )
    from src.domain.ports.repositories.agent_repository import WorkPlanRepository

logger = logging.getLogger(__name__)


class AgentService(AgentServicePort):
    """
    Service for coordinating ReAct agent operations.

    This service manages conversations, messages, and agent execution
    while providing streaming responses via Server-Sent Events (SSE).

    Multi-Level Thinking:
    - Complex queries are broken down into work plans
    - Each step is executed with task-level thinking
    - Real-time SSE events for work_plan, step_start, step_end
    """

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        execution_repository: AgentExecutionRepository,
        graph_service: GraphServicePort,
        llm: LLMClient,
        neo4j_client,
        plan_work_use_case: "PlanWorkUseCase | None" = None,
        execute_step_use_case: "ExecuteStepUseCase | None" = None,
        synthesize_results_use_case: "SynthesizeResultsUseCase | None" = None,
        workflow_learner: "WorkflowLearner | None" = None,
        work_plan_repository: "WorkPlanRepository | None" = None,
        skill_repository=None,
        skill_service: "SkillService | None" = None,
        subagent_repository=None,
        redis_client=None,
        tool_execution_record_repository: "ToolExecutionRecordRepository | None" = None,
        agent_execution_event_repository: "AgentExecutionEventRepository | None" = None,
        execution_checkpoint_repository: "ExecutionCheckpointRepository | None" = None,
        sandbox_service=None,
        storage_service=None,
        mcp_temporal_adapter: "Optional[Any]" = None,
        db_session=None,
    ):
        """
        Initialize the agent service.

        Args:
            conversation_repository: Repository for conversation data
            execution_repository: Repository for agent execution tracking
            graph_service: Graph service for knowledge graph operations
            llm: LangChain chat model for LLM calls
            neo4j_client: Neo4j client for direct graph database access
            plan_work_use_case: Optional use case for work-level planning
            execute_step_use_case: Optional use case for executing steps
            synthesize_results_use_case: Optional use case for synthesizing results
            workflow_learner: Optional service for learning workflow patterns
            work_plan_repository: Optional repository for work plan data
            skill_repository: Optional repository for skills (L2 layer)
            skill_service: Optional SkillService for progressive skill loading
            subagent_repository: Optional repository for subagents (L3 layer)
            redis_client: Optional Redis client for caching (used by WebSearchTool)
            tool_execution_record_repository: Optional repository for tool execution history
            agent_execution_event_repository: Optional repository for SSE event persistence
            execution_checkpoint_repository: Optional repository for execution checkpoints
            sandbox_service: Optional SandboxPort for code execution (used by CodeExecutorTool)
            storage_service: Optional StorageServicePort for file storage (used by CodeExecutorTool)
            mcp_temporal_adapter: Optional MCPTemporalAdapter for Temporal MCP integration
            db_session: Optional database session (reserved for future use)
        """
        self._conversation_repo = conversation_repository
        self._execution_repo = execution_repository
        self._graph_service = graph_service
        self._llm = llm
        self._neo4j_client = neo4j_client
        self._plan_work_uc = plan_work_use_case
        self._execute_step_uc = execute_step_use_case
        self._synthesize_uc = synthesize_results_use_case
        self._workflow_learner = workflow_learner
        self._work_plan_repo = work_plan_repository
        self._skill_repo = skill_repository
        self._skill_service = skill_service
        self._subagent_repo = subagent_repository
        self._redis_client = redis_client
        self._tool_execution_record_repo = tool_execution_record_repository
        self._agent_execution_event_repo = agent_execution_event_repository
        self._execution_checkpoint_repo = execution_checkpoint_repository
        self._sandbox_service = sandbox_service
        self._storage_service = storage_service
        self._mcp_temporal_adapter = mcp_temporal_adapter
        self._db_session = db_session

        # Tool definitions cache (static tool descriptions don't change)
        self._tool_definitions_cache: Dict[str, list[Dict[str, Any]]] | None = None

        # Initialize Redis Event Bus if client available
        self._event_bus = None
        if self._redis_client:
            from src.infrastructure.adapters.secondary.event.redis_event_bus import (
                RedisEventBusAdapter,
            )

            self._event_bus = RedisEventBusAdapter(self._redis_client)

    async def _build_react_agent_async(self, project_id: str, user_id: str, tenant_id: str):
        # Deprecated: Agent execution moved to Temporal
        pass

    async def stream_chat_v2(
        self,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream agent response using Temporal Workflow.

        Args:
            conversation_id: Conversation ID
            user_message: User's message content
            project_id: Project ID
            user_id: User ID
            tenant_id: Tenant ID

        Yields:
            Event dictionaries with type and data
        """
        logger.warning(f"[AgentService] stream_chat_v2 invoked (file={__file__})")
        try:
            # Get conversation and verify authorization
            conversation = await self._conversation_repo.find_by_id(conversation_id)
            if not conversation:
                yield {
                    "type": "error",
                    "data": {"message": f"Conversation {conversation_id} not found"},
                    "timestamp": datetime.utcnow().isoformat(),
                }
                return

            # Authorization check
            if conversation.project_id != project_id or conversation.user_id != user_id:
                logger.warning(
                    f"Unauthorized chat attempt on conversation {conversation_id} "
                    f"by user {user_id} in project {project_id}"
                )
                yield {
                    "type": "error",
                    "data": {"message": "You do not have permission to access this conversation"},
                    "timestamp": datetime.utcnow().isoformat(),
                }
                return

            # Create user message event (unified event timeline - no messages table)
            user_msg_id = str(uuid.uuid4())

            # Use Domain Event
            user_domain_event = AgentMessageEvent(
                role="user",
                content=user_message,
            )

            # Get next sequence number
            next_seq = await self._agent_execution_event_repo.get_last_sequence(conversation_id) + 1

            # Convert to persistent entity
            user_msg_event = AgentExecutionEvent.from_domain_event(
                event=user_domain_event,
                conversation_id=conversation_id,
                message_id=user_msg_id,
                sequence_number=next_seq,
            )

            # Ensure ID is set (from_domain_event might not set it or might set None)
            if not user_msg_event.id:
                user_msg_event.id = str(uuid.uuid4())

            # Additional data fixup if needed for compatibility
            if not user_msg_event.event_data.get("message_id"):
                user_msg_event.event_data["message_id"] = user_msg_id

            await self._agent_execution_event_repo.save_and_commit(user_msg_event)

            # Yield user message event (using SSE adapter manually here or constructing dict)
            # Since we are returning a dict yield, we construct it to match the legacy format expected by frontend
            yield {
                "type": "message",
                "data": {
                    "id": user_msg_id,
                    "role": "user",
                    "content": user_message,
                    "created_at": user_msg_event.created_at.isoformat(),
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Get conversation context BEFORE saving user message to avoid duplication
            # The user message was just saved above, but get_message_events will include it
            # We need to exclude it from conversation_context since Activity will add it again
            message_events = await self._agent_execution_event_repo.get_message_events(
                conversation_id=conversation.id, limit=50
            )
            # Exclude the user message we just saved (it will be added by the Activity)
            conversation_context = [
                {
                    "role": event.event_data.get("role", "user"),
                    "content": event.event_data.get("content", ""),
                }
                for event in message_events
                if event.id != user_msg_event.id  # Exclude current user message
            ]

            # Start Temporal Workflow
            # Events will be published to Redis Stream by the Activity
            workflow_id = await self._start_chat_workflow(
                conversation=conversation,
                message_id=user_msg_id,
                user_message=user_message,
                conversation_context=conversation_context,
            )
            logger.info(
                f"[AgentService] Started workflow {workflow_id} for conversation {conversation_id}"
            )

            # Connect to stream with message_id filtering
            async for event in self.connect_chat_stream(
                conversation_id,
                message_id=user_msg_id,
            ):
                yield event

        except Exception as e:
            logger.error(f"[AgentService] Error in stream_chat_v2: {e}", exc_info=True)
            yield {
                "type": "error",
                "data": {"message": str(e)},
                "timestamp": datetime.utcnow().isoformat(),
            }

    async def _start_chat_workflow(
        self,
        conversation: Conversation,
        message_id: str,
        user_message: str,
        conversation_context: list[Dict[str, Any]],
    ) -> str:
        """Start agent execution workflow in Temporal.

        This method supports two modes:
        1. Session Workflow (default): Long-running workflow that persists across requests
           - Uses AgentSessionWorkflow with wait_condition() for persistent agent instances
           - Sends chat via Temporal update mechanism
           - 95%+ latency reduction for subsequent requests

        2. Legacy Workflow: Per-request workflow that completes after each request
           - Uses AgentExecutionWorkflow
           - Each request creates a new workflow instance

        Args:
            conversation: The conversation entity (already loaded)
            message_id: The user message ID
            user_message: The user message content
            conversation_context: Pre-filtered conversation history (excludes current user message)

        Returns:
            The workflow ID
        """
        import os

        from src.configuration.config import get_settings
        from src.configuration.temporal_config import get_temporal_settings

        settings = get_settings()
        temporal_settings = get_temporal_settings()

        # Check if session workflow mode is enabled (default: True)
        use_session_workflow = os.getenv("USE_AGENT_SESSION_WORKFLOW", "true").lower() == "true"

        if use_session_workflow:
            return await self._start_or_get_session_workflow(
                conversation=conversation,
                message_id=message_id,
                user_message=user_message,
                conversation_context=conversation_context,
                settings=settings,
                temporal_settings=temporal_settings,
            )
        else:
            return await self._start_legacy_workflow(
                conversation=conversation,
                message_id=message_id,
                user_message=user_message,
                conversation_context=conversation_context,
                settings=settings,
                temporal_settings=temporal_settings,
            )

    async def _start_or_get_session_workflow(
        self,
        conversation: Conversation,
        message_id: str,
        user_message: str,
        conversation_context: list[Dict[str, Any]],
        settings,
        temporal_settings,
    ) -> str:
        """Start or get existing Agent Session Workflow and send chat via update.

        This implements the long-running workflow pattern similar to MCP Worker:
        - Workflow ID: agent_{tenant_id}_{project_id}_{agent_mode}
        - Workflow stays alive via wait_condition()
        - Chat requests sent via Temporal update mechanism
        - Agent instance persists across multiple requests

        Args:
            conversation: The conversation entity
            message_id: The user message ID
            user_message: The user message content
            conversation_context: Conversation history
            settings: Application settings
            temporal_settings: Temporal settings

        Returns:
            The session workflow ID
        """
        from temporalio.client import WorkflowExecutionStatus

        from src.infrastructure.adapters.secondary.temporal.client import TemporalClientFactory
        from src.infrastructure.adapters.secondary.temporal.workflows.agent_session import (
            AgentChatRequest,
            AgentSessionConfig,
            get_agent_session_workflow_id,
        )

        client = await TemporalClientFactory.get_client()

        # Generate session workflow ID (per project + mode)
        agent_mode = "default"  # Could be extracted from conversation settings
        workflow_id = get_agent_session_workflow_id(
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            agent_mode=agent_mode,
        )

        # Try to get existing workflow handle
        handle = client.get_workflow_handle(workflow_id)

        try:
            # Check if workflow exists and is running
            describe = await handle.describe()
            if describe.status != WorkflowExecutionStatus.RUNNING:
                # Workflow exists but not running, start a new one
                raise Exception("Workflow not running")

            logger.info(f"Using existing Agent Session Workflow: {workflow_id}")

        except Exception:
            # Workflow doesn't exist or not running, start a new one
            logger.info(f"Starting new Agent Session Workflow: {workflow_id}")

            config = AgentSessionConfig(
                tenant_id=conversation.tenant_id,
                project_id=conversation.project_id,
                agent_mode=agent_mode,
                model=self._get_model(settings),
                api_key=self._get_api_key(settings),
                base_url=self._get_base_url(settings),
                temperature=0.7,
                max_tokens=4096,
                max_steps=20,
                idle_timeout_seconds=1800,  # 30 minutes
                mcp_tools_ttl_seconds=300,  # 5 minutes
            )

            await client.start_workflow(
                "agent_session",  # Workflow name
                config,
                id=workflow_id,
                task_queue=temporal_settings.agent_temporal_task_queue,
            )

            # Get handle to the new workflow
            handle = client.get_workflow_handle(workflow_id)

            # Wait a moment for workflow to initialize
            import asyncio

            await asyncio.sleep(0.1)

        # Send chat request via Temporal update
        chat_request = AgentChatRequest(
            conversation_id=conversation.id,
            message_id=message_id,
            user_message=user_message,
            user_id=conversation.user_id,
            conversation_context=conversation_context,
        )

        # Execute update asynchronously to avoid blocking first token streaming
        # Note: Actual streaming happens via Redis pub/sub in the activity
        import asyncio

        asyncio.create_task(
            self._execute_chat_update_async(
                handle=handle,
                chat_request=chat_request,
                workflow_id=workflow_id,
                conversation_id=conversation.id,
            )
        )

        return workflow_id

    async def _execute_chat_update_async(
        self,
        handle,
        chat_request,
        workflow_id: str,
        conversation_id: str,
    ) -> None:
        """Execute Temporal chat update without blocking stream setup."""
        try:
            result = await handle.execute_update(
                "chat",
                chat_request,
            )
            is_error = (
                result.get("is_error", False)
                if isinstance(result, dict)
                else getattr(result, "is_error", False)
            )
            logger.info(
                f"Agent Session chat completed: workflow={workflow_id}, "
                f"conversation={conversation_id}, is_error={is_error}"
            )
        except Exception as e:
            logger.error(
                f"Agent Session chat failed: workflow={workflow_id}, conversation={conversation_id}, error={e}",
                exc_info=True,
            )

    async def _start_legacy_workflow(
        self,
        conversation: Conversation,
        message_id: str,
        user_message: str,
        conversation_context: list[Dict[str, Any]],
        settings,
        temporal_settings,
    ) -> str:
        """Start legacy per-request agent execution workflow.

        This is the original implementation where each chat creates a new workflow.

        Args:
            conversation: The conversation entity
            message_id: The user message ID
            user_message: The user message content
            conversation_context: Conversation history
            settings: Application settings
            temporal_settings: Temporal settings

        Returns:
            The workflow ID
        """
        from src.infrastructure.adapters.secondary.temporal.client import TemporalClientFactory
        from src.infrastructure.adapters.secondary.temporal.workflows.agent import AgentInput

        client = await TemporalClientFactory.get_client()

        # Get available tools (cached in _tool_definitions_cache)
        tools = await self.get_available_tools(conversation.project_id, conversation.tenant_id)

        # Prepare agent config (tools, model, etc.)
        agent_config = {
            "model": self._get_model(settings),
            "temperature": 0.7,
            "tools": tools,
            "api_key": self._get_api_key(settings),
            "base_url": self._get_base_url(settings),
        }

        input_data = AgentInput(
            conversation_id=conversation.id,
            message_id=message_id,
            user_message=user_message,
            project_id=conversation.project_id,
            user_id=conversation.user_id,
            tenant_id=conversation.tenant_id,
            agent_config=agent_config,
            conversation_context=conversation_context,
        )

        workflow_id = f"agent-execution-{conversation.id}-{message_id}"

        await client.start_workflow(
            "AgentExecutionWorkflow",
            input_data,
            id=workflow_id,
            task_queue=temporal_settings.agent_temporal_task_queue,
        )

        return workflow_id

    def _get_api_key(self, settings):
        provider = settings.llm_provider.strip().lower()
        if provider == "openai":
            return settings.openai_api_key
        if provider == "qwen":
            return settings.qwen_api_key
        if provider == "deepseek":
            return settings.deepseek_api_key
        if provider == "gemini":
            return settings.gemini_api_key
        return None

    def _get_base_url(self, settings):
        provider = settings.llm_provider.strip().lower()
        if provider == "openai":
            return settings.openai_base_url
        if provider == "qwen":
            return settings.qwen_base_url
        if provider == "deepseek":
            return settings.deepseek_base_url
        return None

    def _get_model(self, settings):
        """Get the LLM model name based on the configured provider."""
        provider = settings.llm_provider.strip().lower()
        if provider == "openai":
            return settings.openai_model
        if provider == "qwen":
            return settings.qwen_model
        if provider == "deepseek":
            return settings.deepseek_model
        if provider == "gemini":
            return settings.gemini_model
        if provider == "zai" or provider == "zhipu":
            return settings.zai_model
        return "qwen-plus"  # Default fallback

    async def _get_stream_events(
        self, conversation_id: str, message_id: str, last_seq: int
    ) -> list[Dict[str, Any]]:
        """
        Retrieve events from Redis Stream (for reliable replay).

        This provides persistent event storage that survives disconnects.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID for filtering
            last_seq: Last sequence number received

        Returns:
            List of events from stream
        """
        _ = last_seq
        if not self._event_bus:
            return []

        stream_key = f"agent:events:{conversation_id}"
        events = []

        try:
            # Read all events from stream
            async for message in self._event_bus.stream_read(
                stream_key, last_id="0", count=1000, block_ms=None
            ):
                event = message.get("data", {})

                # Filter by message_id
                event_data = event.get("data", {})
                if event_data.get("message_id") != message_id:
                    continue

                events.append(event)

            if events:
                logger.info(
                    f"[AgentService] Retrieved {len(events)} events from stream {stream_key}"
                )

        except Exception as e:
            logger.warning(f"[AgentService] Failed to read from stream: {e}")

        return events

    async def connect_chat_stream(
        self,
        conversation_id: str,
        message_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Connect to a chat stream, handling replay and real-time events.

        Simplified event flow:
        1. Database - for persisted events (except text_delta)
        2. Redis Stream - for all events including text_delta (persistent, replayable)

        Args:
            conversation_id: Conversation ID to connect to
            message_id: Optional message ID to filter events for a specific message

        Yields:
            SSE event dictionaries with keys: type, data, seq, timestamp
        """

        if not self._agent_execution_event_repo or not self._event_bus:
            logger.error("Missing dependencies for chat stream")
            return

        logger.warning(
            f"[AgentService] connect_chat_stream start: conversation_id={conversation_id}, "
            f"message_id={message_id}"
        )

        # 1. Replay from DB
        # Get events for this conversation, optionally filtered by message_id
        try:
            if message_id:
                # Filter events for specific message only
                events = await self._agent_execution_event_repo.get_events_by_message(
                    message_id=message_id
                )
            else:
                # Get all events for this conversation
                events = await self._agent_execution_event_repo.list_by_conversation(
                    conversation_id=conversation_id, limit=1000
                )

            last_sequence_id = 0
            saw_complete = False
            for event in events:
                # Reconstruct SSE event format
                yield {
                    "type": event.event_type,
                    "data": event.event_data,
                    "timestamp": event.created_at.isoformat(),
                    "id": event.sequence_number,
                }
                last_sequence_id = max(last_sequence_id, event.sequence_number)
                if event.event_type in ("complete", "error"):
                    saw_complete = True

            logger.info(
                f"[AgentService] Replayed {len(events)} DB events for conversation {conversation_id}, "
                f"last_seq={last_sequence_id}"
            )
            logger.warning(
                f"[AgentService] DB replay done: events={len(events)}, last_seq={last_sequence_id}"
            )

        except Exception as e:
            logger.warning(f"[AgentService] Failed to replay events: {e}")

        # If completion already happened, replay text_delta from Redis Stream once
        if message_id and saw_complete:
            stream_events = await self._get_stream_events(
                conversation_id, message_id, last_sequence_id
            )
            stream_only = [e for e in stream_events]
            stream_only.sort(key=lambda e: e.get("seq", 0))
            for event in stream_only:
                yield {
                    "type": event.get("type"),
                    "data": event.get("data"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "id": event.get("seq", 0),
                }
            return

        # 4. Stream live events from Redis Stream (reliable real-time)
        # IMPORTANT: Use last_id="0" to read ALL messages from Redis Stream
        # This is necessary because events are published to Redis Stream BEFORE
        # being saved to DB. If we used "$", we might miss events published during DB replay.
        # We use last_sequence_id filtering to skip duplicates from DB replay.
        if message_id:
            stream_key = f"agent:events:{conversation_id}"
            logger.warning(
                f"[AgentService] Streaming live from Redis Stream: {stream_key}, "
                f"message_id={message_id}, last_seq={last_sequence_id}"
            )
            live_event_count = 0
            try:
                # Use "0" to read all messages (catch any missed during DB replay)
                # Filter by last_sequence_id to avoid duplicates
                async for message in self._event_bus.stream_read(
                    stream_key, last_id="0", count=1000, block_ms=1000
                ):
                    event = message.get("data", {})
                    event_type = event.get("type", "unknown")
                    seq = event.get("seq", 0)
                    event_data = event.get("data", {})

                    live_event_count += 1
                    if live_event_count <= 10:
                        logger.warning(
                            f"[AgentService] Live stream event #{live_event_count}: "
                            f"type={event_type}, seq={seq}, message_id={event_data.get('message_id')}"
                        )

                    # Filter by message_id (only events for this specific message)
                    if event_data.get("message_id") != message_id:
                        continue

                    # CRITICAL: Use last_sequence_id (from DB replay) for filtering
                    # This prevents re-yielding events that were already replayed from DB
                    if seq <= last_sequence_id:
                        continue

                    yield {
                        "type": event_type,
                        "data": event_data,
                        "timestamp": datetime.utcnow().isoformat(),
                        "id": seq,
                    }
                    last_sequence_id = max(last_sequence_id, seq)

                    # Stop when completion is seen
                    if event_type in ("complete", "error"):
                        logger.info(
                            f"[AgentService] Stream completed from Redis Stream: type={event_type}"
                        )
                        return
            except Exception as e:
                logger.error(
                    f"[AgentService] Error streaming from Redis Stream: {e}", exc_info=True
                )

    async def create_conversation(
        self,
        project_id: str,
        user_id: str,
        tenant_id: str,
        title: str | None = None,
        agent_config: Dict[str, Any] | None = None,
    ) -> Conversation:
        """
        Create a new conversation.

        Args:
            project_id: Project ID for the conversation
            user_id: User ID who owns the conversation
            tenant_id: Tenant ID for multi-tenancy
            title: Optional title for the conversation
            agent_config: Optional agent configuration

        Returns:
            Created conversation entity
        """
        conversation = Conversation(
            id=str(uuid.uuid4()),
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title=title or "New Conversation",
            status=ConversationStatus.ACTIVE,
            agent_config=agent_config or {},
            metadata={"created_at": datetime.utcnow().isoformat()},
            message_count=0,
            created_at=datetime.utcnow(),
        )

        await self._conversation_repo.save(conversation)
        logger.info(f"Created conversation {conversation.id} for project {project_id}")
        return conversation

    async def get_conversation(
        self, conversation_id: str, project_id: str, user_id: str
    ) -> Conversation | None:
        """
        Get a conversation by ID.

        Args:
            conversation_id: Conversation ID
            project_id: Project ID for authorization
            user_id: User ID for authorization

        Returns:
            Conversation entity or None if not found or unauthorized
        """
        conversation = await self._conversation_repo.find_by_id(conversation_id)
        if not conversation:
            return None
        # Authorization check: verify conversation belongs to the project and user
        if conversation.project_id != project_id or conversation.user_id != user_id:
            logger.warning(
                f"Unauthorized access attempt to conversation {conversation_id} "
                f"by user {user_id} in project {project_id}"
            )
            return None
        return conversation

    async def list_conversations(
        self,
        project_id: str,
        user_id: str,
        limit: int = 50,
        status: ConversationStatus | None = None,
    ) -> list[Conversation]:
        """
        List conversations for a project.

        Args:
            project_id: Project ID to filter by
            user_id: User ID to filter by
            limit: Maximum number of conversations to return
            status: Optional status filter

        Returns:
            List of conversation entities
        """
        return await self._conversation_repo.list_by_project(
            project_id=project_id, limit=limit, status=status
        )

    async def delete_conversation(
        self, conversation_id: str, project_id: str, user_id: str
    ) -> bool:
        """
        Delete a conversation and all its messages.

        Args:
            conversation_id: Conversation ID to delete
            project_id: Project ID for authorization
            user_id: User ID for authorization

        Returns:
            True if deleted successfully, False if not found or unauthorized
        """
        # Verify conversation exists and belongs to user
        conversation = await self._conversation_repo.find_by_id(conversation_id)
        if not conversation:
            logger.warning(f"Attempted to delete non-existent conversation {conversation_id}")
            return False

        # Authorization check
        if conversation.project_id != project_id or conversation.user_id != user_id:
            logger.warning(
                f"Unauthorized delete attempt on conversation {conversation_id} "
                f"by user {user_id} in project {project_id}"
            )
            return False

        # Delete related records in order to avoid FK violations
        # 1. Delete tool execution records
        if self._tool_execution_record_repo:
            await self._tool_execution_record_repo.delete_by_conversation(conversation_id)

        # 2. Delete agent execution events
        if self._agent_execution_event_repo:
            await self._agent_execution_event_repo.delete_by_conversation(conversation_id)

        # 3. Delete execution checkpoints
        if self._execution_checkpoint_repo:
            await self._execution_checkpoint_repo.delete_by_conversation(conversation_id)

        # 4. Delete work plans
        if self._work_plan_repo:
            await self._work_plan_repo.delete_by_conversation(conversation_id)

        # 5. Delete executions (they reference conversations)
        await self._execution_repo.delete_by_conversation(conversation_id)

        # 6. Delete conversation
        await self._conversation_repo.delete(conversation_id)

        logger.info(f"Deleted conversation {conversation_id}")
        return True

    async def update_conversation_title(
        self, conversation_id: str, project_id: str, user_id: str, title: str
    ) -> Conversation | None:
        """
        Update conversation title.

        Args:
            conversation_id: Conversation ID to update
            project_id: Project ID for authorization
            user_id: User ID for authorization
            title: New title for the conversation

        Returns:
            Updated conversation if successful, None if not found or unauthorized
        """
        logger.info(f"[update_conversation_title] START: id={conversation_id}, title='{title}'")
        # Verify conversation exists and belongs to user
        conversation = await self._conversation_repo.find_by_id(conversation_id)
        if not conversation:
            logger.warning(f"Attempted to update non-existent conversation {conversation_id}")
            return None

        logger.info(
            f"[update_conversation_title] Found conversation: project_id={conversation.project_id}, user_id={conversation.user_id}, current_title='{conversation.title}'"
        )
        logger.info(
            f"[update_conversation_title] Authorization check: expected project_id={project_id}, user_id={user_id}"
        )

        # Authorization check
        if conversation.project_id != project_id or conversation.user_id != user_id:
            logger.warning(
                f"Unauthorized title update attempt on conversation {conversation_id} "
                f"by user {user_id} in project {project_id}"
            )
            return None

        # Update title
        logger.info(f"[update_conversation_title] Calling conversation.update_title('{title}')")
        conversation.update_title(title)
        logger.info("[update_conversation_title] Title updated in domain model, now saving...")
        await self._conversation_repo.save_and_commit(conversation)

        logger.info(f"Updated title for conversation {conversation_id} to: {title}")
        return conversation

    async def generate_conversation_title(self, first_message: str, llm: LLMClient) -> str:
        """
        Generate a friendly, concise title for a conversation based on the first user message.

        This method implements:
        - Retry mechanism (up to 3 attempts with exponential backoff)
        - Fallback to truncated first message on failure
        - Graceful degradation

        Args:
            first_message: The first user message content
            llm: The LLM to use for generation

        Returns:
            Generated title (max 50 characters)
        """
        prompt = f"""Generate a short, friendly title (max 50 characters) for a conversation that starts with this message:

"{first_message[:200]}"

Guidelines:
- Be concise and descriptive
- Use the user's language (English, Chinese, etc.)
- Focus on the main topic or question
- Maximum 50 characters
- Return ONLY the title, no explanation

Title:"""

        max_retries = 3
        base_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                response = await llm.ainvoke(
                    [
                        LLMMessage.system(
                            "You are a helpful assistant that generates concise conversation titles."
                        ),
                        LLMMessage.user(prompt),
                    ]
                )

                title = response.content.strip().strip('"').strip("'")

                # Limit length and add default if empty
                if len(title) > 50:
                    title = title[:47] + "..."
                if not title:
                    title = "New Conversation"

                logger.info(f"Generated conversation title: {title}")
                return title

            except Exception as e:
                logger.warning(
                    f"[generate_conversation_title] Attempt {attempt + 1}/{max_retries} failed: {e}"
                )

                # If not the last attempt, wait with exponential backoff
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    # All retries exhausted - use fallback
                    logger.error(f"All {max_retries} retries exhausted for title generation")
                    return self._generate_fallback_title(first_message)

        # Should not reach here, but return default as safety net
        return "New Conversation"

    def _generate_fallback_title(self, first_message: str) -> str:
        """
        Generate a fallback title from the first message when LLM fails.

        This ensures users always get a meaningful title even when LLM is unavailable.

        Args:
            first_message: The first user message content

        Returns:
            Fallback title (max 50 characters)
        """
        # Strip whitespace and get first line/segment
        content = first_message.strip()

        # Take first 40 characters + "..." to stay under 50
        if len(content) > 40:
            # Try to break at word boundary
            truncated = content[:40]
            last_space = truncated.rfind(" ")
            if last_space > 20:  # Only if we get a reasonable segment
                truncated = truncated[:last_space]
            content = truncated + "..."

        logger.info(f"Using fallback title: '{content}'")
        return content or "New Conversation"

    async def get_conversation_messages(
        self,
        conversation_id: str,
        project_id: str,
        user_id: str,
        limit: int = 100,
    ) -> list[AgentExecutionEvent]:
        """
        Get all message events in a conversation.

        Returns user_message and assistant_message events from the unified event timeline.

        Args:
            conversation_id: Conversation ID
            project_id: Project ID for authorization
            user_id: User ID for authorization
            limit: Maximum number of messages to return

        Returns:
            List of message events, or empty list if not found or unauthorized
        """
        # Verify conversation exists and belongs to user
        conversation = await self._conversation_repo.find_by_id(conversation_id)
        if not conversation:
            logger.warning(
                f"Attempted to get messages for non-existent conversation {conversation_id}"
            )
            return []

        # Authorization check
        if conversation.project_id != project_id or conversation.user_id != user_id:
            logger.warning(
                f"Unauthorized message access attempt on conversation {conversation_id} "
                f"by user {user_id} in project {project_id}"
            )
            return []

        return await self._agent_execution_event_repo.get_message_events(
            conversation_id=conversation_id, limit=limit
        )

    async def get_execution_history(
        self,
        conversation_id: str,
        project_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[Dict[str, Any]]:
        """
        Get the execution history for a conversation.

        Args:
            conversation_id: Conversation ID
            project_id: Project ID for authorization
            user_id: User ID for authorization
            limit: Maximum number of executions to return

        Returns:
            List of execution dictionaries with metadata

        Raises:
            ValueError: If conversation not found or unauthorized
        """
        # Verify conversation exists and belongs to user
        conversation = await self._conversation_repo.find_by_id(conversation_id)
        if not conversation:
            logger.warning(
                f"Attempted to get executions for non-existent conversation {conversation_id}"
            )
            raise ValueError(f"Conversation {conversation_id} not found")

        # Authorization check
        if conversation.project_id != project_id or conversation.user_id != user_id:
            logger.warning(
                f"Unauthorized execution history access attempt on conversation {conversation_id} "
                f"by user {user_id} in project {project_id}"
            )
            raise ValueError("You do not have permission to access this conversation")

        executions = await self._execution_repo.list_by_conversation(
            conversation_id=conversation_id, limit=limit
        )

        # Convert to dict for JSON response
        return [
            {
                "id": exec.id,
                "message_id": exec.message_id,
                "status": exec.status.value if exec.status else None,
                "started_at": exec.started_at.isoformat() if exec.started_at else None,
                "completed_at": exec.completed_at.isoformat() if exec.completed_at else None,
                "thought": exec.thought,
                "action": exec.action,
                "tool_name": exec.tool_name,
                "tool_input": exec.tool_input,
                "tool_output": exec.tool_output,
                "observation": exec.observation,
                "metadata": exec.metadata,
            }
            for exec in executions
        ]

    # -------------------------------------------------------------------------
    # Abstract Method Implementations for AgentServicePort
    # -------------------------------------------------------------------------

    async def get_available_tools(
        self, project_id: str, tenant_id: str, agent_mode: str = "default"
    ) -> list[Dict[str, Any]]:
        """
        Get list of available tools for the agent.

        Args:
            project_id: The project ID
            tenant_id: The tenant ID
            agent_mode: Agent mode for filtering skills (default: "default")

        Returns:
            List of tool definitions with name and description
        """
        # Use cached base tool definitions if available
        if self._tool_definitions_cache is None:
            self._tool_definitions_cache = self._build_base_tool_definitions()

        # Start with cached base tools (copy to avoid mutation)
        tools_list = list(self._tool_definitions_cache)

        # Add skill_loader if SkillService is available (tenant-specific, not cached)
        if self._skill_service:
            skill_loader = SkillLoaderTool(
                skill_service=self._skill_service,
                tenant_id=tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
            )
            await skill_loader.initialize()
            tools_list.append(
                {
                    "name": "skill_loader",
                    "description": skill_loader.description,
                }
            )

        return tools_list

    def _build_base_tool_definitions(self) -> list[Dict[str, Any]]:
        """Build and cache base tool definitions (static tools only)."""
        from src.infrastructure.agent.tools import ClarificationTool, DecisionTool

        return [
            {
                "name": "ask_clarification",
                "description": ClarificationTool().description,
            },
            {
                "name": "request_decision",
                "description": DecisionTool().description,
            },
            {
                "name": "web_search",
                "description": WebSearchTool(self._redis_client).description,
            },
            {
                "name": "web_scrape",
                "description": WebScrapeTool().description,
            },
        ]

    async def get_conversation_context(
        self, conversation_id: str, max_messages: int = 50
    ) -> list[Dict[str, Any]]:
        """
        Get conversation context for agent processing.

        Args:
            conversation_id: The conversation ID
            max_messages: Maximum number of messages to include

        Returns:
            List of message dictionaries for LLM context
        """
        message_events = await self._agent_execution_event_repo.get_message_events(
            conversation_id=conversation_id, limit=max_messages
        )

        return [
            {
                "role": event.event_data.get("role", "user"),
                "content": event.event_data.get("content", ""),
            }
            for event in message_events
        ]

    async def _trigger_pattern_learning(
        self,
        execution: AgentExecution,
        user_message: str,
        tenant_id: str,
    ) -> None:
        """Trigger workflow pattern learning after successful execution."""
        # Implementation preserved
        pass
