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
import json
import logging
import time as time_module
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

from src.domain.events.agent_events import AgentMessageEvent
from src.domain.llm_providers.llm_types import LLMClient
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

if TYPE_CHECKING:
    from src.application.services.skill_service import SkillService
    from src.application.services.workflow_learner import WorkflowLearner
    from src.application.use_cases.agent import (
        ExecuteStepUseCase,
        SynthesizeResultsUseCase,
    )

logger = logging.getLogger(__name__)


class AgentService(AgentServicePort):
    """
    Service for coordinating ReAct agent operations.

    This service manages conversations, messages, and agent execution
    while providing streaming responses via Server-Sent Events (SSE).

    Multi-Level Thinking:
    - Complex queries are broken down into work plans
    - Each step is executed with task-level thinking
    - Real-time SSE events for step_start, step_end
    """

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        execution_repository: AgentExecutionRepository,
        graph_service: GraphServicePort,
        llm: LLMClient,
        neo4j_client,
        execute_step_use_case: "ExecuteStepUseCase | None" = None,
        synthesize_results_use_case: "SynthesizeResultsUseCase | None" = None,
        workflow_learner: "WorkflowLearner | None" = None,
        skill_repository=None,
        skill_service: "SkillService | None" = None,
        subagent_repository=None,
        redis_client=None,
        tool_execution_record_repository: "ToolExecutionRecordRepository | None" = None,
        agent_execution_event_repository: "AgentExecutionEventRepository | None" = None,
        execution_checkpoint_repository: "ExecutionCheckpointRepository | None" = None,
        storage_service=None,
        db_session=None,
        sequence_service=None,
        context_loader=None,
    ):
        """
        Initialize the agent service.

        Args:
            conversation_repository: Repository for conversation data
            execution_repository: Repository for agent execution tracking
            graph_service: Graph service for knowledge graph operations
            llm: LangChain chat model for LLM calls
            neo4j_client: Neo4j client for direct graph database access
            execute_step_use_case: Optional use case for executing steps
            synthesize_results_use_case: Optional use case for synthesizing results
            workflow_learner: Optional service for learning workflow patterns
            skill_repository: Optional repository for skills (L2 layer)
            skill_service: Optional SkillService for progressive skill loading
            subagent_repository: Optional repository for subagents (L3 layer)
            redis_client: Optional Redis client for caching (used by WebSearchTool)
            tool_execution_record_repository: Optional repository for tool execution history
            agent_execution_event_repository: Optional repository for SSE event persistence
            execution_checkpoint_repository: Optional repository for execution checkpoints
            storage_service: Optional StorageServicePort for file storage (used by CodeExecutorTool)
            db_session: Optional database session (reserved for future use)
            sequence_service: Optional RedisSequenceService for atomic sequence generation
        """
        self._conversation_repo = conversation_repository
        self._execution_repo = execution_repository
        self._graph_service = graph_service
        self._llm = llm
        self._neo4j_client = neo4j_client
        self._execute_step_uc = execute_step_use_case
        self._synthesize_uc = synthesize_results_use_case
        self._workflow_learner = workflow_learner
        self._skill_repo = skill_repository
        self._skill_service = skill_service
        self._subagent_repo = subagent_repository
        self._redis_client = redis_client
        self._tool_execution_record_repo = tool_execution_record_repository
        self._agent_execution_event_repo = agent_execution_event_repository
        self._execution_checkpoint_repo = execution_checkpoint_repository
        self._storage_service = storage_service
        self._db_session = db_session
        self._sequence_service = sequence_service
        self._context_loader = context_loader

        # Initialize Redis Event Bus if client available
        self._event_bus = None
        if self._redis_client:
            from src.infrastructure.adapters.secondary.event.redis_event_bus import (
                RedisEventBusAdapter,
            )

            self._event_bus = RedisEventBusAdapter(self._redis_client)

        # Compose sub-services
        from src.application.services.agent.conversation_manager import ConversationManager
        from src.application.services.agent.runtime_bootstrapper import (
            AgentRuntimeBootstrapper,
        )
        from src.application.services.agent.tool_discovery import ToolDiscoveryService

        self._conversation_mgr = ConversationManager(
            conversation_repo=self._conversation_repo,
            execution_repo=self._execution_repo,
            agent_execution_event_repo=self._agent_execution_event_repo,
            tool_execution_record_repo=self._tool_execution_record_repo,
            execution_checkpoint_repo=self._execution_checkpoint_repo,
        )
        self._runtime = AgentRuntimeBootstrapper()
        self._tool_discovery = ToolDiscoveryService(
            redis_client=self._redis_client,
            skill_service=self._skill_service,
        )

    async def _build_react_agent_async(self, project_id: str, user_id: str, tenant_id: str):
        # Deprecated: Agent execution moved to Ray Actors
        pass

    async def stream_chat_v2(
        self,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        attachment_ids: Optional[List[str]] = None,
        file_metadata: Optional[List[Dict[str, Any]]] = None,
        forced_skill_name: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream agent response using Ray Actors.

        Args:
            conversation_id: Conversation ID
            user_message: User's message content
            project_id: Project ID
            user_id: User ID
            tenant_id: Tenant ID
            attachment_ids: Optional list of attachment IDs (legacy, deprecated)
            file_metadata: Optional list of file metadata dicts for sandbox-uploaded files
            forced_skill_name: Optional skill name to force direct execution

        Yields:
            Event dictionaries with type and data
        """
        logger.info("[AgentService] stream_chat_v2 invoked")
        try:
            # Get conversation and verify authorization
            conversation = await self._conversation_repo.find_by_id(conversation_id)
            if not conversation:
                yield {
                    "type": "error",
                    "data": {"message": f"Conversation {conversation_id} not found"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                return

            # Create user message event (unified event timeline - no messages table)
            user_msg_id = str(uuid.uuid4())

            # Generate correlation ID for this request (used to track all events from this request)
            correlation_id = f"req_{uuid.uuid4().hex[:12]}"

            # Use Domain Event - include attachment_ids/file_metadata at creation time (model is frozen)
            user_domain_event = AgentMessageEvent(
                role="user",
                content=user_message,
                attachment_ids=attachment_ids if attachment_ids else None,
                file_metadata=file_metadata if file_metadata else None,
                forced_skill_name=forced_skill_name if forced_skill_name else None,
            )

            # Get next event time
            # Use EventTimeGenerator for monotonic ordering
            from src.domain.model.agent.execution.event_time import EventTimeGenerator

            if self._agent_execution_event_repo:
                (
                    last_time_us,
                    last_counter,
                ) = await self._agent_execution_event_repo.get_last_event_time(conversation_id)
                time_gen = EventTimeGenerator(last_time_us=last_time_us, last_counter=last_counter)
            else:
                time_gen = EventTimeGenerator()
            next_time_us, next_counter = time_gen.next()

            # Convert to persistent entity
            user_msg_event = AgentExecutionEvent.from_domain_event(
                event=user_domain_event,
                conversation_id=conversation_id,
                message_id=user_msg_id,
                event_time_us=next_time_us,
                event_counter=next_counter,
            )

            # Set correlation_id on the event
            user_msg_event.correlation_id = correlation_id

            # Ensure ID is set (from_domain_event might not set it or might set None)
            if not user_msg_event.id:
                user_msg_event.id = str(uuid.uuid4())

            # Additional data fixup if needed for compatibility
            if not user_msg_event.event_data.get("message_id"):
                user_msg_event.event_data["message_id"] = user_msg_id

            await self._agent_execution_event_repo.save_and_commit(user_msg_event)

            # Yield user message event (using SSE adapter manually here or constructing dict)
            # Since we are returning a dict yield, we construct it to match the legacy format expected by frontend
            user_event_data = {
                "id": user_msg_id,
                "role": "user",
                "content": user_message,
                "created_at": user_msg_event.created_at.isoformat(),
            }
            if attachment_ids:
                user_event_data["attachment_ids"] = attachment_ids
            if file_metadata:
                user_event_data["file_metadata"] = file_metadata
            if forced_skill_name:
                user_event_data["forced_skill_name"] = forced_skill_name

            yield {
                "type": "message",
                "data": user_event_data,
                "correlation_id": correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Get conversation context with smart summary caching.
            # The user message was just saved above, so exclude it since
            # the Activity will add it again via build_context().
            context_summary = None
            if self._context_loader:
                load_result = await self._context_loader.load_context(
                    conversation_id=conversation.id,
                    exclude_event_id=user_msg_event.id,
                )
                conversation_context = load_result.messages
                context_summary = load_result.summary
            else:
                # Fallback: direct message loading (no summary caching)
                message_events = await self._agent_execution_event_repo.get_message_events(
                    conversation_id=conversation.id, limit=50
                )
                conversation_context = [
                    {
                        "role": event.event_data.get("role", "user"),
                        "content": event.event_data.get("content", ""),
                    }
                    for event in message_events
                    if event.id != user_msg_event.id
                ]

            # Start Ray Actor
            # Events will be published to Redis Stream by the Actor runtime
            actor_id = await self._start_chat_actor(
                conversation=conversation,
                message_id=user_msg_id,
                user_message=user_message,
                conversation_context=conversation_context,
                attachment_ids=attachment_ids,
                file_metadata=file_metadata,
                correlation_id=correlation_id,
                forced_skill_name=forced_skill_name,
                context_summary_data=(context_summary.to_dict() if context_summary else None),
            )
            logger.info(
                f"[AgentService] Started actor {actor_id} for conversation {conversation_id}"
            )

            # Connect to stream with message_id filtering
            async for event in self.connect_chat_stream(
                conversation_id,
                message_id=user_msg_id,
            ):
                # Add correlation_id to streamed events
                event["correlation_id"] = correlation_id
                yield event

        except Exception as e:
            logger.error(f"[AgentService] Error in stream_chat_v2: {e}", exc_info=True)
            yield {
                "type": "error",
                "data": {"message": str(e)},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def _start_chat_actor(
        self,
        conversation: Conversation,
        message_id: str,
        user_message: str,
        conversation_context: list[Dict[str, Any]],
        attachment_ids: Optional[List[str]] = None,
        file_metadata: Optional[List[Dict[str, Any]]] = None,
        correlation_id: Optional[str] = None,
        forced_skill_name: Optional[str] = None,
        context_summary_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start agent execution via Ray Actor, with local fallback."""
        return await self._runtime.start_chat_actor(
            conversation=conversation,
            message_id=message_id,
            user_message=user_message,
            conversation_context=conversation_context,
            attachment_ids=attachment_ids,
            file_metadata=file_metadata,
            correlation_id=correlation_id,
            forced_skill_name=forced_skill_name,
            context_summary_data=context_summary_data,
        )

    async def _get_stream_events(
        self, conversation_id: str, message_id: str, last_event_time_us: int
    ) -> list[Dict[str, Any]]:
        """
        Retrieve events from Redis Stream (for reliable replay).

        This provides persistent event storage that survives disconnects.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID for filtering
            last_event_time_us: Last event_time_us received

        Returns:
            List of events from stream
        """
        _ = last_event_time_us
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
            SSE event dictionaries with keys: type, data, event_time_us, event_counter, timestamp
        """

        if not self._agent_execution_event_repo or not self._event_bus:
            logger.error("Missing dependencies for chat stream")
            return

        logger.info(
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

            last_event_time_us = 0
            last_event_counter = 0
            saw_complete = False
            for event in events:
                # Reconstruct SSE event format
                yield {
                    "type": event.event_type,
                    "data": event.event_data,
                    "timestamp": event.created_at.isoformat(),
                    "event_time_us": event.event_time_us,
                    "event_counter": event.event_counter,
                }
                if event.event_time_us > last_event_time_us or (
                    event.event_time_us == last_event_time_us
                    and event.event_counter > last_event_counter
                ):
                    last_event_time_us = event.event_time_us
                    last_event_counter = event.event_counter
                if event.event_type in ("complete", "error"):
                    saw_complete = True

            logger.info(
                f"[AgentService] Replayed {len(events)} DB events for conversation {conversation_id}, "
                f"last_event_time_us={last_event_time_us}"
            )

        except Exception as e:
            logger.warning(f"[AgentService] Failed to replay events: {e}")

        # If completion already happened, replay text_delta from Redis Stream once
        if message_id and saw_complete:
            stream_events = await self._get_stream_events(
                conversation_id, message_id, last_event_time_us
            )
            stream_only = [e for e in stream_events]
            stream_only.sort(key=lambda e: (e.get("event_time_us", 0), e.get("event_counter", 0)))
            for event in stream_only:
                yield {
                    "type": event.get("type"),
                    "data": event.get("data"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event_time_us": event.get("event_time_us", 0),
                    "event_counter": event.get("event_counter", 0),
                }
            return

        # 4. Stream live events from Redis Stream (reliable real-time)
        # IMPORTANT: Use last_id="0" to read ALL messages from Redis Stream
        # This is necessary because events are published to Redis Stream BEFORE
        # being saved to DB. If we used "$", we might miss events published during DB replay.
        # We use last_event_time_us/counter filtering to skip duplicates from DB replay.
        #
        # When message_id is None: Read ALL new events for the conversation (HITL recovery mode)
        # When message_id is set: Filter events for that specific message
        stream_key = f"agent:events:{conversation_id}"
        logger.info(
            f"[AgentService] Streaming live from Redis Stream: {stream_key}, "
            f"message_id={message_id or 'ALL'}, "
            f"last_event_time_us={last_event_time_us}"
        )
        live_event_count = 0
        try:
            # Use "0" to read all messages (catch any missed during DB replay)
            # Filter by last_event_time_us/counter to avoid duplicates
            async for message in self._event_bus.stream_read(
                stream_key, last_id="0", count=1000, block_ms=1000
            ):
                event = message.get("data", {})
                event_type = event.get("type", "unknown")
                evt_time_us = event.get("event_time_us", 0)
                evt_counter = event.get("event_counter", 0)
                event_data = event.get("data", {})

                live_event_count += 1
                if live_event_count <= 10:
                    logger.debug(
                        f"[AgentService] Live stream event #{live_event_count}: "
                        f"type={event_type}, event_time_us={evt_time_us}, "
                        f"message_id={event_data.get('message_id')}"
                    )

                # Filter by message_id (only when message_id is specified)
                # When message_id is None (HITL recovery mode), accept all events
                if message_id and event_data.get("message_id") != message_id:
                    continue

                if event_type in ("task_list_updated", "task_updated"):
                    logger.info(
                        f"[AgentService] Task event from Redis: type={event_type}, "
                        f"conversation_id={conversation_id}"
                    )

                # CRITICAL: Use last_event_time_us/counter (from DB replay) for filtering
                # This prevents re-yielding events that were already replayed from DB
                if evt_time_us < last_event_time_us or (
                    evt_time_us == last_event_time_us and evt_counter <= last_event_counter
                ):
                    continue

                yield {
                    "type": event_type,
                    "data": event_data,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event_time_us": evt_time_us,
                    "event_counter": evt_counter,
                }
                if evt_time_us > last_event_time_us or (
                    evt_time_us == last_event_time_us and evt_counter > last_event_counter
                ):
                    last_event_time_us = evt_time_us
                    last_event_counter = evt_counter

                # Stop when completion is seen, but continue briefly for delayed events
                # (e.g., title_generated which is published after complete)
                if event_type in ("complete", "error"):
                    logger.info(
                        f"[AgentService] Stream completed from Redis Stream: type={event_type}, "
                        f"reading delayed events for 5 seconds"
                    )

                    # Launch background title generation (fire-and-forget)
                    if event_type == "complete":
                        try:
                            conv = await self._conversation_repo.find_by_id(conversation_id)
                            if conv and conv.title in ("New Conversation", "New Chat"):
                                # Extract first user message from the event data
                                first_user_msg = ""
                                if message_id:
                                    try:
                                        msg_events = await self._agent_execution_event_repo.get_events_by_message(
                                            message_id=message_id
                                        )
                                        for me in msg_events:
                                            if me.event_type == "user_message":
                                                first_user_msg = (
                                                    me.event_data.get("content", "")
                                                    if isinstance(me.event_data, dict)
                                                    else ""
                                                )
                                                break
                                    except Exception:
                                        pass
                                if first_user_msg:
                                    asyncio.create_task(
                                        self._trigger_title_generation(
                                            conversation_id=conversation_id,
                                            project_id=conv.project_id,
                                            user_message=first_user_msg,
                                        )
                                    )
                        except Exception as title_err:
                            logger.debug(f"Title generation check failed: {title_err}")

                    # Continue reading for a short time to catch delayed events like title_generated
                    # and artifact_ready (uploaded in background after agent completes)
                    delayed_start = time_module.time()
                    max_delay = 5.0  # Read for up to 5 more seconds
                    try:
                        async for delayed_message in self._event_bus.stream_read(
                            stream_key, last_id="0", count=100, block_ms=200
                        ):
                            delayed_event = delayed_message.get("data", {})
                            delayed_type = delayed_event.get("type", "unknown")
                            delayed_time_us = delayed_event.get("event_time_us", 0)
                            delayed_counter = delayed_event.get("event_counter", 0)
                            delayed_data = delayed_event.get("data", {})

                            # Skip already seen events
                            if delayed_time_us < last_event_time_us or (
                                delayed_time_us == last_event_time_us
                                and delayed_counter <= last_event_counter
                            ):
                                continue

                            # For conversation-level events (like title_generated), check conversation_id
                            # For message-level events, check message_id
                            event_message_id = delayed_data.get("message_id")
                            event_conversation_id = delayed_data.get("conversation_id")

                            # Skip events for different conversations
                            if event_conversation_id and event_conversation_id != conversation_id:
                                continue

                            # Skip message events for different messages (only when filtering by message_id)
                            if message_id and event_message_id and event_message_id != message_id:
                                continue

                            # Only process specific delayed events (conversation-level events)
                            # These events don't have message_id but are valid for this conversation
                            if delayed_type in ("title_generated",):
                                logger.info(
                                    f"[AgentService] Yielding delayed event: type={delayed_type}, "
                                    f"conversation_id={event_conversation_id}"
                                )
                                yield {
                                    "type": delayed_type,
                                    "data": delayed_data,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "event_time_us": delayed_time_us,
                                    "event_counter": delayed_counter,
                                }
                                if delayed_time_us > last_event_time_us or (
                                    delayed_time_us == last_event_time_us
                                    and delayed_counter > last_event_counter
                                ):
                                    last_event_time_us = delayed_time_us
                                    last_event_counter = delayed_counter

                            # Timeout check
                            if time_module.time() - delayed_start > max_delay:
                                break
                    except Exception as delay_err:
                        logger.warning(f"[AgentService] Error reading delayed events: {delay_err}")

                    logger.info("[AgentService] Stream ended (after delayed event window)")
                    return
        except Exception as e:
            logger.error(f"[AgentService] Error streaming from Redis Stream: {e}", exc_info=True)

    async def create_conversation(
        self,
        project_id: str,
        user_id: str,
        tenant_id: str,
        title: str | None = None,
        agent_config: Dict[str, Any] | None = None,
    ) -> Conversation:
        """Create a new conversation."""
        conversation = await self._conversation_mgr.create_conversation(
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            title=title,
            agent_config=agent_config,
        )
        await self._invalidate_conv_cache(project_id)
        return conversation

    async def get_conversation(
        self, conversation_id: str, project_id: str, user_id: str
    ) -> Conversation | None:
        """Get a conversation by ID."""
        return await self._conversation_mgr.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
        )

    # Cache TTL for conversation lists (30 seconds)
    _CONV_LIST_CACHE_TTL = 30

    def _conv_list_cache_key(
        self, project_id: str, offset: int, limit: int, status: ConversationStatus | None
    ) -> str:
        status_val = status.value if status else "all"
        return f"conv_list:{project_id}:{status_val}:{offset}:{limit}"

    def _conv_count_cache_key(self, project_id: str, status: ConversationStatus | None) -> str:
        status_val = status.value if status else "all"
        return f"conv_count:{project_id}:{status_val}"

    async def _invalidate_conv_cache(self, project_id: str) -> None:
        """Invalidate all conversation list caches for a project."""
        if not self._redis_client:
            return
        try:
            for prefix in ("conv_list:", "conv_count:"):
                keys = await self._redis_client.keys(f"{prefix}{project_id}:*")
                for key in keys:
                    await self._redis_client.delete(key)
        except Exception as e:
            logger.debug(f"Failed to invalidate conversation cache: {e}")

    async def list_conversations(
        self,
        project_id: str,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        status: ConversationStatus | None = None,
    ) -> list[Conversation]:
        """List conversations for a project with Redis caching."""
        # Try cache first
        if self._redis_client:
            cache_key = self._conv_list_cache_key(project_id, offset, limit, status)
            try:
                cached = await self._redis_client.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    return [Conversation.from_dict(d) for d in data]
            except Exception as e:
                logger.debug(f"Cache read failed for conversations: {e}")

        conversations = await self._conversation_mgr.list_conversations(
            project_id=project_id,
            user_id=user_id,
            limit=limit,
            offset=offset,
            status=status,
        )

        # Cache the result
        if self._redis_client:
            try:
                cache_key = self._conv_list_cache_key(project_id, offset, limit, status)
                data = json.dumps([c.to_dict() for c in conversations])
                await self._redis_client.set(cache_key, data, ex=self._CONV_LIST_CACHE_TTL)
            except Exception as e:
                logger.debug(f"Cache write failed for conversations: {e}")

        return conversations

    async def count_conversations(
        self,
        project_id: str,
        status: ConversationStatus | None = None,
    ) -> int:
        """Count conversations for a project with Redis caching."""
        if self._redis_client:
            cache_key = self._conv_count_cache_key(project_id, status)
            try:
                cached = await self._redis_client.get(cache_key)
                if cached:
                    return int(cached)
            except Exception as e:
                logger.debug(f"Cache read failed for conversation count: {e}")

        count = await self._conversation_mgr.count_conversations(
            project_id=project_id,
            status=status,
        )

        if self._redis_client:
            try:
                cache_key = self._conv_count_cache_key(project_id, status)
                await self._redis_client.set(cache_key, str(count), ex=self._CONV_LIST_CACHE_TTL)
            except Exception as e:
                logger.debug(f"Cache write failed for conversation count: {e}")

        return count

    async def delete_conversation(
        self, conversation_id: str, project_id: str, user_id: str
    ) -> bool:
        """Delete a conversation and all its messages."""
        result = await self._conversation_mgr.delete_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
        )
        if result:
            await self._invalidate_conv_cache(project_id)
        return result

    async def update_conversation_title(
        self, conversation_id: str, project_id: str, user_id: str, title: str
    ) -> Conversation | None:
        """Update conversation title."""
        conversation = await self._conversation_mgr.update_conversation_title(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
            title=title,
        )
        if conversation:
            await self._invalidate_conv_cache(project_id)
        return conversation

    async def generate_conversation_title(self, first_message: str, llm: LLMClient) -> str:
        """Generate a friendly, concise title for a conversation."""
        return await self._conversation_mgr.generate_conversation_title(
            first_message=first_message,
            llm=llm,
        )

    def _generate_fallback_title(self, first_message: str) -> str:
        """Generate a fallback title from the first message when LLM fails."""
        return self._conversation_mgr._generate_fallback_title(first_message)

    async def _trigger_title_generation(
        self,
        conversation_id: str,
        project_id: str,
        user_message: str,
    ) -> None:
        """
        Generate a title for a new conversation and publish title_generated event.

        Runs as a background task after the first assistant response completes.
        Fire-and-forget: errors are logged but don't affect the chat flow.

        Uses the same DB-configured LLM provider as the ReActAgent to ensure
        model name and API endpoint consistency.
        """
        try:
            conversation = await self._conversation_repo.find_by_id(conversation_id)
            if not conversation:
                return

            # Only generate if title is still the default
            if conversation.title not in ("New Conversation", "New Chat"):
                return

            # Only generate for early conversations (first few messages)
            if conversation.message_count > 4:
                return

            # Use DB-configured provider (same as ReActAgent) instead of self._llm
            llm = await self._get_title_llm()

            title = await self._conversation_mgr.generate_conversation_title(
                first_message=user_message, llm=llm
            )

            # Update the conversation title in DB
            conversation.update_title(title)
            await self._conversation_repo.save_and_commit(conversation)

            # Invalidate conversation list cache
            await self._invalidate_conv_cache(project_id)

            # Publish title_generated event to Redis stream
            if self._redis_client:
                now_us = int(time_module.time() * 1_000_000)
                stream_event = {
                    "type": "title_generated",
                    "event_time_us": now_us,
                    "event_counter": 0,
                    "data": {
                        "conversation_id": conversation_id,
                        "title": title,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "conversation_id": conversation_id,
                }
                stream_key = f"agent:events:{conversation_id}"
                await self._redis_client.xadd(
                    stream_key, {"data": json.dumps(stream_event)}, maxlen=1000
                )
                logger.info(
                    f"[AgentService] Published title_generated event: "
                    f"conversation={conversation_id}, title='{title}'"
                )
        except Exception as e:
            logger.warning(f"[AgentService] Title generation failed (non-fatal): {e}")

    async def _get_title_llm(self) -> "LLMClient":
        """Get LLM client for title generation using DB provider config.

        Uses the same provider configuration as the ReActAgent (from database)
        to ensure model name and API endpoint consistency. Falls back to
        the injected self._llm if DB provider is unavailable.
        """
        try:
            from src.infrastructure.agent.state.agent_worker_state import (
                get_or_create_llm_client,
                get_or_create_provider_config,
            )
            from src.infrastructure.llm.litellm.unified_llm_client import UnifiedLLMClient

            provider_config = await get_or_create_provider_config()
            litellm_client = await get_or_create_llm_client(provider_config)
            return UnifiedLLMClient(litellm_client=litellm_client)
        except Exception as e:
            logger.warning(
                f"[AgentService] Failed to get DB provider for title generation, "
                f"falling back to injected LLM: {e}"
            )
            return self._llm

    async def get_conversation_messages(
        self,
        conversation_id: str,
        project_id: str,
        user_id: str,
        limit: int = 100,
    ) -> list[AgentExecutionEvent]:
        """Get all message events in a conversation."""
        return await self._conversation_mgr.get_conversation_messages(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
            limit=limit,
        )

    async def get_execution_history(
        self,
        conversation_id: str,
        project_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[Dict[str, Any]]:
        """Get the execution history for a conversation."""
        return await self._conversation_mgr.get_execution_history(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
            limit=limit,
        )

    # -------------------------------------------------------------------------
    # Abstract Method Implementations for AgentServicePort
    # -------------------------------------------------------------------------

    async def get_available_tools(
        self, project_id: str, tenant_id: str, agent_mode: str = "default"
    ) -> list[Dict[str, Any]]:
        """Get list of available tools for the agent."""
        return await self._tool_discovery.get_available_tools(
            project_id=project_id,
            tenant_id=tenant_id,
            agent_mode=agent_mode,
        )

    async def get_conversation_context(
        self, conversation_id: str, max_messages: int = 50
    ) -> list[Dict[str, Any]]:
        """Get conversation context for agent processing."""
        return await self._conversation_mgr.get_conversation_context(
            conversation_id=conversation_id,
            max_messages=max_messages,
        )

    async def _trigger_pattern_learning(
        self,
        execution: AgentExecution,
        user_message: str,
        tenant_id: str,
    ) -> None:
        """Trigger workflow pattern learning after successful execution."""
        # Implementation preserved
        pass
