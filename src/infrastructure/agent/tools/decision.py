"""
Decision Tool for Human-in-the-Loop Interaction.

This tool allows the agent to request user decisions at critical execution points
when multiple approaches exist or confirmation is needed for risky operations.

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


class DecisionType(str, Enum):
    """Type of decision needed."""

    BRANCH = "branch"  # Choose execution branch
    METHOD = "method"  # Choose implementation method
    CONFIRMATION = "confirmation"  # Confirm a risky operation
    RISK = "risk"  # Acknowledge and proceed with risk
    CUSTOM = "custom"  # Custom decision point


class DecisionOption:
    """
    A decision option the user can choose.

    Attributes:
        id: Unique identifier for this option
        label: Short label (e.g., "Proceed with deletion")
        description: Detailed explanation
        recommended: Whether this is the recommended option
        estimated_time: Optional estimated time for this option
        estimated_cost: Optional estimated cost/resources
        risks: Optional list of risks associated with this option
    """

    def __init__(
        self,
        id: str,
        label: str,
        description: Optional[str] = None,
        recommended: bool = False,
        estimated_time: Optional[str] = None,
        estimated_cost: Optional[str] = None,
        risks: Optional[List[str]] = None,
    ):
        self.id = id
        self.label = label
        self.description = description
        self.recommended = recommended
        self.estimated_time = estimated_time
        self.estimated_cost = estimated_cost
        self.risks = risks or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "recommended": self.recommended,
            "estimated_time": self.estimated_time,
            "estimated_cost": self.estimated_cost,
            "risks": self.risks,
        }


class DecisionRequest:
    """
    A pending decision request.

    Attributes:
        request_id: Unique ID for this decision
        question: The decision question
        decision_type: Type of decision
        options: List of decision options
        allow_custom: Whether user can provide custom response
        context: Additional context for the decision
        default_option: Default option if user doesn't respond
        future: Future that resolves when user decides
    """

    def __init__(
        self,
        request_id: str,
        question: str,
        decision_type: DecisionType,
        options: List[DecisionOption],
        allow_custom: bool = False,
        context: Optional[Dict[str, Any]] = None,
        default_option: Optional[str] = None,
    ):
        self.request_id = request_id
        self.question = question
        self.decision_type = decision_type
        self.options = options
        self.allow_custom = allow_custom
        self.context = context or {}
        self.default_option = default_option
        self.future: asyncio.Future = asyncio.Future()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE event."""
        return {
            "request_id": self.request_id,
            "question": self.question,
            "decision_type": self.decision_type.value,
            "options": [opt.to_dict() for opt in self.options],
            "allow_custom": self.allow_custom,
            "context": self.context,
            "default_option": self.default_option,
        }

    def resolve(self, decision: str):
        """Resolve the future with user's decision."""
        if not self.future.done():
            self.future.set_result(decision)

    def cancel(self):
        """Cancel the decision request."""
        if not self.future.done():
            self.future.cancel()


class DecisionManager:
    """
    Manager for pending decision requests.

    Thread-safe manager for handling multiple decision requests.
    Uses Redis Pub/Sub for cross-process communication.
    Uses database persistence for recovery after page refresh.

    Architecture:
    - Worker process: Creates request, persists to DB, subscribes to Redis channel, waits for response
    - API process: Receives WebSocket message, updates DB, publishes to Redis channel
    - Worker process: Receives Redis message, resolves the future
    """

    # Redis channel prefix for HITL responses
    REDIS_CHANNEL_PREFIX = "hitl:decision:"

    def __init__(self):
        self._pending_requests: Dict[str, DecisionRequest] = {}
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
        request: DecisionRequest,
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
                request_type=HITLRequestType.DECISION,
                conversation_id=conversation_id,
                message_id=message_id,
                tenant_id=tenant_id,
                project_id=project_id,
                question=request.question,
                options=[opt.to_dict() for opt in request.options],
                context=request.context,
                metadata={
                    "decision_type": request.decision_type.value,
                    "allow_custom": request.allow_custom,
                    "default_option": request.default_option,
                },
                expires_at=datetime.utcnow() + timedelta(seconds=timeout),
            )

            await repo.create(entity)
            await session.commit()
            logger.info(f"Persisted decision request {request.request_id} to database")
            return True
        except Exception as e:
            logger.error(f"Failed to persist decision request: {e}")
            await session.rollback()
            return False
        finally:
            await session.close()

    async def _update_db_response(self, request_id: str, decision: str) -> bool:
        """Update database with response."""
        session = await self._get_db_session()
        if not session:
            return False

        try:
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SQLHITLRequestRepository,
            )

            repo = SQLHITLRequestRepository(session)
            result = await repo.update_response(request_id, decision)
            await session.commit()
            return result is not None
        except Exception as e:
            logger.error(f"Failed to update DB response: {e}")
            await session.rollback()
            return False
        finally:
            await session.close()

    async def _mark_db_timeout(
        self, request_id: str, default_response: Optional[str] = None
    ) -> bool:
        """Mark request as timed out in database."""
        session = await self._get_db_session()
        if not session:
            return False

        try:
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SQLHITLRequestRepository,
            )

            repo = SQLHITLRequestRepository(session)
            result = await repo.mark_timeout(request_id, default_response)
            await session.commit()
            return result is not None
        except Exception as e:
            logger.error(f"Failed to mark DB timeout: {e}")
            await session.rollback()
            return False
        finally:
            await session.close()

    async def _listen_for_response(self, request_id: str, request: DecisionRequest):
        """Listen for response on Redis channel."""
        redis_client = await self._get_redis_client()
        if not redis_client:
            logger.warning(f"No Redis client available for decision request {request_id}")
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
                        decision = data.get("decision", "")
                        logger.info(f"Received Redis decision for {request_id}: {decision}")
                        request.resolve(decision)
                        break
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in Redis message for {request_id}")
                    except Exception as e:
                        logger.error(f"Error processing Redis message for {request_id}: {e}")
        except asyncio.CancelledError:
            logger.info(f"Redis listener cancelled for decision {request_id}")
        except Exception as e:
            logger.error(f"Redis listener error for decision {request_id}: {e}")
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    async def create_request(
        self,
        question: str,
        decision_type: DecisionType,
        options: List[DecisionOption],
        allow_custom: bool = False,
        context: Optional[Dict[str, Any]] = None,
        default_option: Optional[str] = None,
        timeout: float = 300.0,  # 5 minutes default
    ) -> str:
        """
        Create a new decision request and wait for user response.

        Args:
            question: The decision question
            decision_type: Type of decision
            options: List of decision options
            allow_custom: Whether user can provide custom response
            context: Additional context
            default_option: Default option if timeout (option ID)
            timeout: Maximum time to wait for response (seconds)

        Returns:
            User's decision (option ID or custom text)

        Raises:
            asyncio.TimeoutError: If user doesn't respond within timeout and no default
            asyncio.CancelledError: If request is cancelled
        """
        request_id = str(uuid.uuid4())

        async with self._lock:
            request = DecisionRequest(
                request_id=request_id,
                question=question,
                decision_type=decision_type,
                options=options,
                allow_custom=allow_custom,
                context=context,
                default_option=default_option,
            )
            self._pending_requests[request_id] = request

            # Start Redis listener for cross-process responses
            listener_task = asyncio.create_task(self._listen_for_response(request_id, request))
            self._redis_listeners[request_id] = listener_task

        logger.info(f"Created decision request {request_id}: {question}")

        try:
            # Wait for user response with timeout
            decision = await asyncio.wait_for(request.future, timeout=timeout)
            logger.info(f"Received decision for {request_id}: {decision}")
            return decision
        except asyncio.TimeoutError:
            # Use default if provided
            if default_option:
                logger.warning(
                    f"Decision request {request_id} timed out, using default: {default_option}"
                )
                return default_option
            else:
                logger.warning(f"Decision request {request_id} timed out with no default")
                raise
        except asyncio.CancelledError:
            logger.warning(f"Decision request {request_id} was cancelled")
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
        request: "DecisionRequest",
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
            request: The DecisionRequest to register
            tenant_id: Optional tenant ID for persistence
            project_id: Optional project ID for persistence
            conversation_id: Optional conversation ID for persistence
            message_id: Optional message ID for persistence
            timeout: Timeout for the request (used for expiration)
        """
        async with self._lock:
            self._pending_requests[request.request_id] = request

        logger.info(f"Registered decision request {request.request_id}")

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

    async def wait_for_response(
        self, request_id: str, timeout: float = 300.0, default_option: Optional[str] = None
    ) -> str:
        """
        Wait for user response with Redis cross-process support.

        This method waits for either:
        1. Local response via future (same process)
        2. Redis pub/sub response (cross-process)

        Args:
            request_id: The request ID to wait for
            timeout: Maximum time to wait (seconds)
            default_option: Default option to use on timeout

        Returns:
            User's decision

        Raises:
            asyncio.TimeoutError: If no response within timeout and no default
            ValueError: If request not found
        """
        async with self._lock:
            request = self._pending_requests.get(request_id)

        if not request:
            raise ValueError(f"Decision request {request_id} not found")

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
                            decision = data.get("decision", "")
                            logger.info(f"Received Redis response for {request_id}: {decision}")
                            request.resolve(decision)
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
            decision = await asyncio.wait_for(request.future, timeout=timeout)
            return decision
        except asyncio.TimeoutError:
            # Mark as timed out in database
            await self._mark_db_timeout(request_id, default_option)
            if default_option:
                logger.warning(f"Decision {request_id} timed out, using default: {default_option}")
                return default_option
            raise
        finally:
            redis_task.cancel()
            try:
                await redis_task
            except asyncio.CancelledError:
                pass

    async def unregister_request(self, request_id: str) -> None:
        """
        Unregister a request.

        Args:
            request_id: ID of the request to unregister
        """
        async with self._lock:
            self._pending_requests.pop(request_id, None)

        logger.info(f"Unregistered decision request {request_id}")

    async def respond(self, request_id: str, decision: str) -> bool:
        """
        Respond to a decision request.

        This method first tries to resolve locally, then publishes to Redis
        for cross-process communication. Also updates the database.

        Args:
            request_id: ID of the decision request
            decision: User's decision

        Returns:
            True if request was found and resolved, False otherwise
        """
        # Update database first - this returns False if already answered
        db_updated = await self._update_db_response(request_id, decision)
        if not db_updated:
            logger.warning(f"Decision request {request_id} not found or already answered in DB")
            return False

        # First try local resolution (same process)
        async with self._lock:
            request = self._pending_requests.get(request_id)
            if request:
                request.resolve(decision)
                logger.info(f"Responded to decision {request_id} (local)")
                return True

        # If not found locally, publish to Redis (cross-process)
        redis_client = await self._get_redis_client()
        if redis_client:
            channel = f"{self.REDIS_CHANNEL_PREFIX}{request_id}"
            message = json.dumps({"request_id": request_id, "decision": decision})
            subscribers = await redis_client.publish(channel, message)
            if subscribers > 0:
                logger.info(
                    f"Published decision response to Redis: {request_id}, subscribers={subscribers}"
                )
                return True
            else:
                # DB was updated but no Redis subscriber - agent may have timed out
                logger.warning(
                    f"No subscribers for decision {request_id} on Redis channel, but DB was updated"
                )
                return True
        else:
            # No Redis available but DB was updated
            logger.warning(f"No Redis client, but DB was updated for {request_id}")
            return True

    async def cancel_request(self, request_id: str) -> bool:
        """
        Cancel a decision request.

        Args:
            request_id: ID of the decision request

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
                logger.info(f"Cancelled decision {request_id}")
                return True
            else:
                logger.warning(f"Decision request {request_id} not found")
                return False

    def get_request(self, request_id: str) -> Optional[DecisionRequest]:
        """Get a decision request by ID."""
        return self._pending_requests.get(request_id)

    def get_pending_requests(self) -> List[DecisionRequest]:
        """Get all pending decision requests."""
        return list(self._pending_requests.values())


# Global decision manager instance
_decision_manager = DecisionManager()


def get_decision_manager() -> DecisionManager:
    """Get the global decision manager instance."""
    return _decision_manager


class DecisionTool(AgentTool):
    """
    Tool for requesting user decisions at critical execution points.

    This tool triggers a human-in-the-loop interaction where the agent
    asks the user to make a decision at a critical point, such as choosing
    an execution branch, confirming a risky operation, or selecting a method.

    Usage:
        decision = DecisionTool()
        choice = await decision.execute(
            question="Delete all user data?",
            decision_type="confirmation",
            options=[
                {
                    "id": "proceed",
                    "label": "Proceed with deletion",
                    "risks": ["Data loss is irreversible"]
                },
                {
                    "id": "cancel",
                    "label": "Cancel operation",
                    "recommended": True
                }
            ]
        )
    """

    def __init__(self, manager: Optional[DecisionManager] = None):
        """
        Initialize the decision tool.

        Args:
            manager: Decision manager to use (defaults to global instance)
        """
        super().__init__(
            name="request_decision",
            description=(
                "Request a decision from the user at a critical execution point. "
                "Use when multiple approaches exist, confirmation is needed for risky "
                "operations, or a choice must be made between execution branches."
            ),
        )
        self.manager = manager or get_decision_manager()

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The decision question to ask the user",
                },
                "decision_type": {
                    "type": "string",
                    "enum": ["branch", "method", "confirmation", "risk", "custom"],
                    "description": "Type of decision: branch (choose execution path), method (choose approach), confirmation (approve/reject action), risk (accept/avoid risk), or custom",
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
                            "estimated_time": {
                                "type": "string",
                                "description": "Estimated time for this option",
                            },
                            "estimated_cost": {
                                "type": "string",
                                "description": "Estimated cost for this option",
                            },
                            "risks": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of potential risks with this option",
                            },
                        },
                        "required": ["id", "label"],
                    },
                    "description": "List of options for the user to choose from",
                },
                "allow_custom": {
                    "type": "boolean",
                    "description": "Whether the user can provide a custom decision instead of choosing an option",
                    "default": False,
                },
                "default_option": {
                    "type": "string",
                    "description": "Default option ID to use if user doesn't respond within timeout",
                },
                "context": {
                    "type": "object",
                    "description": "Additional context information to show the user",
                },
            },
            "required": ["question", "decision_type", "options"],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate decision arguments."""
        if "question" not in kwargs:
            logger.error("Missing required argument: question")
            return False

        if "decision_type" not in kwargs:
            logger.error("Missing required argument: decision_type")
            return False

        if "options" not in kwargs:
            logger.error("Missing required argument: options")
            return False

        # Validate decision type
        try:
            DecisionType(kwargs["decision_type"])
        except ValueError:
            logger.error(f"Invalid decision_type: {kwargs['decision_type']}")
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
        decision_type: str,
        options: List[Dict[str, Any]],
        allow_custom: bool = False,
        context: Optional[Dict[str, Any]] = None,
        default_option: Optional[str] = None,
        timeout: float = 300.0,
    ) -> str:
        """
        Execute decision request.

        Args:
            question: The decision question to ask
            decision_type: Type of decision (branch/method/confirmation/risk/custom)
            options: List of option dicts with id, label, description, recommended,
                    estimated_time, estimated_cost, risks
            allow_custom: Whether to allow custom user input
            context: Additional context information
            default_option: Default option ID if user doesn't respond
            timeout: Maximum wait time in seconds

        Returns:
            User's decision (option ID or custom text)

        Raises:
            ValueError: If arguments are invalid
            asyncio.TimeoutError: If user doesn't respond within timeout and no default
        """
        # Validate
        if not self.validate_args(question=question, decision_type=decision_type, options=options):
            raise ValueError("Invalid decision arguments")

        # Convert options to DecisionOption objects
        decision_options = [
            DecisionOption(
                id=opt["id"],
                label=opt["label"],
                description=opt.get("description"),
                recommended=opt.get("recommended", False),
                estimated_time=opt.get("estimated_time"),
                estimated_cost=opt.get("estimated_cost"),
                risks=opt.get("risks", []),
            )
            for opt in options
        ]

        # Create request
        dec_type = DecisionType(decision_type)
        decision = await self.manager.create_request(
            question=question,
            decision_type=dec_type,
            options=decision_options,
            allow_custom=allow_custom,
            context=context or {},
            default_option=default_option,
            timeout=timeout,
        )

        logger.info(f"Decision made: {decision}")
        return decision

    def get_output_schema(self) -> Dict[str, Any]:
        """Get output schema for tool composition."""
        return {"type": "string", "description": "User's decision (option ID or custom text)"}
