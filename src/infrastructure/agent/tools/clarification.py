"""
Clarification Tool for Human-in-the-Loop Interaction.

This tool allows the agent to ask clarifying questions during planning phase
when encountering ambiguous requirements or multiple valid approaches.

Cross-Process Communication:
- Uses Redis Pub/Sub for cross-process HITL responses
- Worker process subscribes to Redis channel for responses
- API process publishes responses to Redis channel

Database Persistence:
- Stores HITL requests in database for recovery after page refresh
- Enables frontend to query pending requests on reconnection
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from src.domain.model.agent.hitl_request import (
    HITLRequest as HITLRequestEntity,
)
from src.domain.model.agent.hitl_request import (
    HITLRequestType,
)
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class ClarificationType(str, Enum):
    """Type of clarification needed."""

    SCOPE = "scope"  # Clarify task scope or boundaries
    APPROACH = "approach"  # Choose between multiple approaches
    PREREQUISITE = "prerequisite"  # Clarify prerequisites or assumptions
    PRIORITY = "priority"  # Clarify priority or order
    CUSTOM = "custom"  # Custom clarification question


class ClarificationOption:
    """
    A clarification option the user can choose.

    Attributes:
        id: Unique identifier for this option
        label: Short label (e.g., "Use caching")
        description: Detailed explanation
        recommended: Whether this is the recommended option
    """

    def __init__(
        self, id: str, label: str, description: Optional[str] = None, recommended: bool = False
    ):
        self.id = id
        self.label = label
        self.description = description
        self.recommended = recommended

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "recommended": self.recommended,
        }


class ClarificationRequest:
    """
    A pending clarification request.

    Attributes:
        request_id: Unique ID for this clarification
        question: The clarification question
        clarification_type: Type of clarification
        options: List of predefined options
        allow_custom: Whether user can provide custom answer
        context: Additional context for the question
        future: Future that resolves when user answers
    """

    def __init__(
        self,
        request_id: str,
        question: str,
        clarification_type: ClarificationType,
        options: List[ClarificationOption],
        allow_custom: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.request_id = request_id
        self.question = question
        self.clarification_type = clarification_type
        self.options = options
        self.allow_custom = allow_custom
        self.context = context or {}
        self.future: asyncio.Future = asyncio.Future()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE event."""
        return {
            "request_id": self.request_id,
            "question": self.question,
            "clarification_type": self.clarification_type.value,
            "options": [opt.to_dict() for opt in self.options],
            "allow_custom": self.allow_custom,
            "context": self.context,
        }

    def resolve(self, answer: str):
        """Resolve the future with user's answer."""
        if not self.future.done():
            self.future.set_result(answer)

    def cancel(self):
        """Cancel the clarification request."""
        if not self.future.done():
            self.future.cancel()


class ClarificationManager:
    """
    Manager for pending clarification requests.

    Thread-safe manager for handling multiple clarification requests.
    Uses Redis Pub/Sub for cross-process communication.
    Uses database persistence for recovery after page refresh.

    Architecture:
    - Worker process: Creates request, persists to DB, subscribes to Redis channel, waits for response
    - API process: Receives WebSocket message, updates DB, publishes to Redis channel
    - Worker process: Receives Redis message, resolves the future
    """

    # Redis channel prefix for HITL responses
    REDIS_CHANNEL_PREFIX = "hitl:clarification:"

    def __init__(self):
        self._pending_requests: Dict[str, ClarificationRequest] = {}
        self._lock = asyncio.Lock()
        self._redis_listeners: Dict[str, asyncio.Task] = {}

    async def _get_redis_client(self):
        """Get Redis client for Pub/Sub.

        Tries multiple sources:
        1. Agent Worker process: via get_redis_client from agent_worker_state
        2. Direct connection using settings (for API process)
        """
        # Try Agent Worker's Redis client first (Worker process)
        try:
            from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
                get_redis_client,
            )

            return await get_redis_client()
        except Exception:
            pass

        # Direct connection as fallback (API process)
        try:
            import redis.asyncio as redis_lib

            from src.configuration.config import get_settings

            settings = get_settings()
            return redis_lib.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception as e:
            logger.warning(f"Failed to get Redis client: {e}")
            return None

    async def _get_db_session(self):
        """Get database session for persistence."""
        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            return async_session_factory()
        except Exception as e:
            logger.warning(f"Failed to get DB session: {e}")
            return None

    async def _persist_request(
        self,
        request: ClarificationRequest,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        message_id: Optional[str] = None,
        timeout: float = 300.0,
    ) -> bool:
        """Persist request to database."""
        session = await self._get_db_session()
        if not session:
            return False

        try:
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SQLHITLRequestRepository,
            )

            repo = SQLHITLRequestRepository(session)

            entity = HITLRequestEntity(
                id=request.request_id,
                request_type=HITLRequestType.CLARIFICATION,
                conversation_id=conversation_id,
                message_id=message_id,
                tenant_id=tenant_id,
                project_id=project_id,
                question=request.question,
                options=[opt.to_dict() for opt in request.options],
                context=request.context,
                metadata={
                    "clarification_type": request.clarification_type.value,
                    "allow_custom": request.allow_custom,
                },
                expires_at=datetime.utcnow() + timedelta(seconds=timeout),
            )

            await repo.create(entity)
            await session.commit()
            logger.info(f"Persisted clarification request {request.request_id} to database")
            return True
        except Exception as e:
            logger.error(f"Failed to persist clarification request: {e}")
            await session.rollback()
            return False
        finally:
            await session.close()

    async def _update_db_response(self, request_id: str, answer: str) -> bool:
        """Update database with response."""
        session = await self._get_db_session()
        if not session:
            return False

        try:
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SQLHITLRequestRepository,
            )

            repo = SQLHITLRequestRepository(session)
            result = await repo.update_response(request_id, answer)
            await session.commit()
            return result is not None
        except Exception as e:
            logger.error(f"Failed to update DB response: {e}")
            await session.rollback()
            return False
        finally:
            await session.close()

    async def _mark_db_timeout(self, request_id: str) -> bool:
        """Mark request as timed out in database."""
        session = await self._get_db_session()
        if not session:
            return False

        try:
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SQLHITLRequestRepository,
            )

            repo = SQLHITLRequestRepository(session)
            result = await repo.mark_timeout(request_id)
            await session.commit()
            return result is not None
        except Exception as e:
            logger.error(f"Failed to mark DB timeout: {e}")
            await session.rollback()
            return False
        finally:
            await session.close()

    async def _listen_for_response(self, request_id: str, request: ClarificationRequest):
        """Listen for response on Redis channel."""
        redis_client = await self._get_redis_client()
        if not redis_client:
            logger.warning(f"No Redis client available for request {request_id}")
            return

        channel = f"{self.REDIS_CHANNEL_PREFIX}{request_id}"
        pubsub = redis_client.pubsub()

        try:
            await pubsub.subscribe(channel)
            logger.info(f"Subscribed to Redis channel: {channel}")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        answer = data.get("answer", "")
                        logger.info(f"Received Redis response for {request_id}: {answer}")
                        request.resolve(answer)
                        break
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in Redis message for {request_id}")
                    except Exception as e:
                        logger.error(f"Error processing Redis message for {request_id}: {e}")
        except asyncio.CancelledError:
            logger.info(f"Redis listener cancelled for {request_id}")
        except Exception as e:
            logger.error(f"Redis listener error for {request_id}: {e}")
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    async def create_request(
        self,
        question: str,
        clarification_type: ClarificationType,
        options: List[ClarificationOption],
        allow_custom: bool = True,
        context: Optional[Dict[str, Any]] = None,
        timeout: float = 300.0,  # 5 minutes default
    ) -> str:
        """
        Create a new clarification request and wait for user response.

        Args:
            question: The clarification question
            clarification_type: Type of clarification
            options: List of predefined options
            allow_custom: Whether user can provide custom answer
            context: Additional context
            timeout: Maximum time to wait for response (seconds)

        Returns:
            User's answer (option ID or custom text)

        Raises:
            asyncio.TimeoutError: If user doesn't respond within timeout
            asyncio.CancelledError: If request is cancelled
        """
        request_id = str(uuid.uuid4())

        async with self._lock:
            request = ClarificationRequest(
                request_id=request_id,
                question=question,
                clarification_type=clarification_type,
                options=options,
                allow_custom=allow_custom,
                context=context,
            )
            self._pending_requests[request_id] = request

            # Start Redis listener for cross-process responses
            listener_task = asyncio.create_task(self._listen_for_response(request_id, request))
            self._redis_listeners[request_id] = listener_task

        logger.info(f"Created clarification request {request_id}: {question}")

        try:
            # Wait for user response with timeout
            answer = await asyncio.wait_for(request.future, timeout=timeout)
            logger.info(f"Received answer for {request_id}: {answer}")
            return answer
        except asyncio.TimeoutError:
            logger.warning(f"Clarification request {request_id} timed out")
            raise
        except asyncio.CancelledError:
            logger.warning(f"Clarification request {request_id} was cancelled")
            raise
        finally:
            # Clean up
            async with self._lock:
                self._pending_requests.pop(request_id, None)
                listener_task = self._redis_listeners.pop(request_id, None)
                if listener_task and not listener_task.done():
                    listener_task.cancel()

    async def register_request(
        self,
        request: "ClarificationRequest",
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
        timeout: float = 300.0,
    ) -> None:
        """
        Register an existing request with optional database persistence.

        This is used by processor.py which creates the request object directly
        instead of using create_request().

        Args:
            request: The ClarificationRequest to register
            tenant_id: Optional tenant ID for persistence
            project_id: Optional project ID for persistence
            conversation_id: Optional conversation ID for persistence
            message_id: Optional message ID for persistence
            timeout: Timeout for the request (used for expiration)
        """
        async with self._lock:
            self._pending_requests[request.request_id] = request

        logger.info(f"Registered clarification request {request.request_id}")

        # Persist to database if context is provided
        if tenant_id and project_id and conversation_id:
            await self._persist_request(
                request=request,
                tenant_id=tenant_id,
                project_id=project_id,
                conversation_id=conversation_id,
                message_id=message_id,
                timeout=timeout,
            )

    async def wait_for_response(self, request_id: str, timeout: float = 300.0) -> str:
        """
        Wait for user response with Redis cross-process support.

        This method waits for either:
        1. Local response via future (same process)
        2. Redis pub/sub response (cross-process)

        Args:
            request_id: The request ID to wait for
            timeout: Maximum time to wait (seconds)

        Returns:
            User's answer

        Raises:
            asyncio.TimeoutError: If no response within timeout
            ValueError: If request not found
        """
        async with self._lock:
            request = self._pending_requests.get(request_id)

        if not request:
            raise ValueError(f"Clarification request {request_id} not found")

        # Start Redis listener task
        async def listen_redis():
            redis_client = await self._get_redis_client()
            if not redis_client:
                return

            channel = f"{self.REDIS_CHANNEL_PREFIX}{request_id}"
            pubsub = redis_client.pubsub()

            try:
                await pubsub.subscribe(channel)
                logger.info(f"Subscribed to Redis channel: {channel}")

                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            answer = data.get("answer", "")
                            logger.info(f"Received Redis response for {request_id}: {answer}")
                            request.resolve(answer)
                            break
                        except Exception as e:
                            logger.error(f"Error processing Redis message: {e}")
            except asyncio.CancelledError:
                pass
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.close()

        # Run Redis listener concurrently with future wait
        redis_task = asyncio.create_task(listen_redis())

        try:
            answer = await asyncio.wait_for(request.future, timeout=timeout)
            return answer
        except asyncio.TimeoutError:
            # Mark request as timed out in database
            await self._mark_db_timeout(request_id)
            raise
        finally:
            redis_task.cancel()
            try:
                await redis_task
            except asyncio.CancelledError:
                pass

    async def unregister_request(self, request_id: str) -> None:
        """
        Unregister a request and stop its Redis listener.

        Args:
            request_id: ID of the request to unregister
        """
        async with self._lock:
            self._pending_requests.pop(request_id, None)
            listener_task = self._redis_listeners.pop(request_id, None)
            if listener_task and not listener_task.done():
                listener_task.cancel()

        logger.info(f"Unregistered clarification request {request_id}")

    async def respond(self, request_id: str, answer: str) -> bool:
        """
        Respond to a clarification request.

        This method first tries to resolve locally, then publishes to Redis
        for cross-process communication. Also updates the database.

        Args:
            request_id: ID of the clarification request
            answer: User's answer

        Returns:
            True if request was found and resolved, False otherwise
        """
        # Update database first - this returns False if already answered
        db_updated = await self._update_db_response(request_id, answer)
        if not db_updated:
            logger.warning(
                f"Clarification request {request_id} not found or already answered in DB"
            )
            return False

        # First try local resolution (same process)
        async with self._lock:
            request = self._pending_requests.get(request_id)
            if request:
                request.resolve(answer)
                logger.info(f"Responded to clarification {request_id} (local)")
                return True

        # If not found locally, publish to Redis (cross-process)
        redis_client = await self._get_redis_client()
        if redis_client:
            channel = f"{self.REDIS_CHANNEL_PREFIX}{request_id}"
            message = json.dumps({"request_id": request_id, "answer": answer})
            subscribers = await redis_client.publish(channel, message)
            if subscribers > 0:
                logger.info(
                    f"Published clarification response to Redis: {request_id}, "
                    f"subscribers={subscribers}"
                )
                return True
            else:
                # DB was updated but no Redis subscriber - agent may have timed out
                logger.warning(
                    f"No subscribers for clarification {request_id} on Redis channel, "
                    "but DB was updated"
                )
                return True
        else:
            # No Redis available but DB was updated
            logger.warning(f"No Redis client, but DB was updated for {request_id}")
            return True

    async def cancel_request(self, request_id: str) -> bool:
        """
        Cancel a clarification request.

        Args:
            request_id: ID of the clarification request

        Returns:
            True if request was found and cancelled, False otherwise
        """
        async with self._lock:
            request = self._pending_requests.get(request_id)
            if request:
                request.cancel()
                self._pending_requests.pop(request_id, None)
                listener_task = self._redis_listeners.pop(request_id, None)
                if listener_task and not listener_task.done():
                    listener_task.cancel()
                logger.info(f"Cancelled clarification {request_id}")
                return True
            else:
                logger.warning(f"Clarification request {request_id} not found")
                return False

    def get_request(self, request_id: str) -> Optional[ClarificationRequest]:
        """Get a clarification request by ID."""
        return self._pending_requests.get(request_id)

    def get_pending_requests(self) -> List[ClarificationRequest]:
        """Get all pending clarification requests."""
        return list(self._pending_requests.values())


# Global clarification manager instance
_clarification_manager = ClarificationManager()


def get_clarification_manager() -> ClarificationManager:
    """Get the global clarification manager instance."""
    return _clarification_manager


class ClarificationTool(AgentTool):
    """
    Tool for asking clarifying questions during planning.

    This tool triggers a human-in-the-loop interaction where the agent
    asks the user to clarify ambiguous requirements or choose between
    multiple valid approaches.

    Usage:
        clarification = ClarificationTool()
        answer = await clarification.execute(
            question="Should I use caching?",
            clarification_type="approach",
            options=[
                {"id": "cache", "label": "Use caching", "recommended": True},
                {"id": "no_cache", "label": "No caching"}
            ]
        )
    """

    def __init__(self, manager: Optional[ClarificationManager] = None):
        """
        Initialize the clarification tool.

        Args:
            manager: Clarification manager to use (defaults to global instance)
        """
        super().__init__(
            name="ask_clarification",
            description=(
                "Ask the user a clarifying question when requirements are ambiguous "
                "or multiple approaches are possible. Use during planning phase to "
                "ensure alignment before execution."
            ),
        )
        self.manager = manager or get_clarification_manager()

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The clarification question to ask the user",
                },
                "clarification_type": {
                    "type": "string",
                    "enum": ["scope", "approach", "prerequisite", "priority", "custom"],
                    "description": "Type of clarification: scope (what to include/exclude), approach (how to solve), prerequisite (what's needed first), priority (what's more important), or custom",
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique identifier for the option",
                            },
                            "label": {
                                "type": "string",
                                "description": "Display label for the option",
                            },
                            "description": {
                                "type": "string",
                                "description": "Optional detailed description",
                            },
                            "recommended": {
                                "type": "boolean",
                                "description": "Whether this is the recommended option",
                            },
                        },
                        "required": ["id", "label"],
                    },
                    "description": "List of options for the user to choose from",
                },
                "allow_custom": {
                    "type": "boolean",
                    "description": "Whether the user can provide a custom answer instead of choosing an option",
                    "default": True,
                },
                "context": {
                    "type": "object",
                    "description": "Additional context information to show the user",
                },
            },
            "required": ["question", "clarification_type", "options"],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate clarification arguments."""
        if "question" not in kwargs:
            logger.error("Missing required argument: question")
            return False

        if "clarification_type" not in kwargs:
            logger.error("Missing required argument: clarification_type")
            return False

        if "options" not in kwargs:
            logger.error("Missing required argument: options")
            return False

        # Validate clarification type
        try:
            ClarificationType(kwargs["clarification_type"])
        except ValueError:
            logger.error(f"Invalid clarification_type: {kwargs['clarification_type']}")
            return False

        # Validate options
        options = kwargs["options"]
        if not isinstance(options, list) or len(options) == 0:
            logger.error("options must be a non-empty list")
            return False

        return True

    async def execute(
        self,
        question: str,
        clarification_type: str,
        options: List[Dict[str, Any]],
        allow_custom: bool = True,
        context: Optional[Dict[str, Any]] = None,
        timeout: float = 300.0,
    ) -> str:
        """
        Execute clarification request.

        Args:
            question: The clarification question to ask
            clarification_type: Type of clarification (scope/approach/prerequisite/priority/custom)
            options: List of option dicts with id, label, description, recommended
            allow_custom: Whether to allow custom user input
            context: Additional context information
            timeout: Maximum wait time in seconds

        Returns:
            User's answer (option ID or custom text)

        Raises:
            ValueError: If arguments are invalid
            asyncio.TimeoutError: If user doesn't respond within timeout
        """
        # Validate
        if not self.validate_args(
            question=question, clarification_type=clarification_type, options=options
        ):
            raise ValueError("Invalid clarification arguments")

        # Convert options to ClarificationOption objects
        clarification_options = [
            ClarificationOption(
                id=opt["id"],
                label=opt["label"],
                description=opt.get("description"),
                recommended=opt.get("recommended", False),
            )
            for opt in options
        ]

        # Create request
        clarif_type = ClarificationType(clarification_type)
        answer = await self.manager.create_request(
            question=question,
            clarification_type=clarif_type,
            options=clarification_options,
            allow_custom=allow_custom,
            context=context or {},
            timeout=timeout,
        )

        logger.info(f"Clarification answered: {answer}")
        return answer

    def get_output_schema(self) -> Dict[str, Any]:
        """Get output schema for tool composition."""
        return {"type": "string", "description": "User's answer to the clarification question"}
