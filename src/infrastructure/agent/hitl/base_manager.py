"""
Base HITL Manager - Abstract base class for Human-in-the-Loop managers.

This module provides the common infrastructure for all HITL tools:
- DecisionManager
- ClarificationManager
- EnvVarManager

Key Features:
- Redis Streams for reliable cross-process communication
- Database persistence for recovery after page refresh
- Automatic cleanup and timeout handling
- Template method pattern for type-specific customization

Cross-Process Communication Architecture:
- Worker process: Creates request → persists to DB → subscribes to Redis Stream → waits for response
- API process: Receives WebSocket message → updates DB → publishes to Redis Stream
- Worker process: Receives Redis message → resolves the future → cleans up
"""

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

from src.domain.model.agent.hitl_request import (
    HITLRequest as HITLRequestEntity,
)
from src.domain.model.agent.hitl_request import (
    HITLRequestType,
)
from src.domain.ports.services.hitl_message_bus_port import (
    HITLMessage,
    HITLMessageBusPort,
)

logger = logging.getLogger(__name__)

# Type variable for the response type
T = TypeVar("T")


@dataclass
class HITLManagerConfig:
    """
    Configuration for HITL managers.

    Attributes:
        default_timeout: Default timeout in seconds for waiting on responses
        consumer_group_prefix: Prefix for consumer group names
        stream_cleanup_on_complete: Whether to cleanup stream after completion
        db_persistence_enabled: Whether to persist requests to database
        fallback_to_pubsub: Whether to fallback to pub/sub if streams fail
    """

    default_timeout: float = 300.0  # 5 minutes
    consumer_group_prefix: str = "hitl"
    stream_cleanup_on_complete: bool = True
    db_persistence_enabled: bool = True
    fallback_to_pubsub: bool = True


@dataclass
class BaseHITLRequest(ABC, Generic[T]):
    """
    Base class for HITL requests.

    All HITL request types should inherit from this class.

    Attributes:
        request_id: Unique ID for this request
        context: Additional context for the request
        future: Future that resolves when user responds
        created_at: When the request was created
    """

    request_id: str
    context: Dict[str, Any] = field(default_factory=dict)
    future: asyncio.Future = field(default_factory=asyncio.Future)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE event."""
        pass

    def resolve(self, value: T):
        """Resolve the future with the response value."""
        if not self.future.done():
            self.future.set_result(value)

    def cancel(self):
        """Cancel the request."""
        if not self.future.done():
            self.future.cancel()

    @property
    def is_done(self) -> bool:
        """Check if the future is done."""
        return self.future.done()


class BaseHITLManager(ABC, Generic[T]):
    """
    Abstract base class for HITL managers.

    Provides common infrastructure for all HITL tools:
    - Request lifecycle management
    - Redis Streams for cross-process communication
    - Database persistence for recovery
    - Timeout handling

    Subclasses must implement:
    - request_type: The HITLRequestType for this manager
    - response_key: The key used in Redis messages (e.g., "decision", "answer")
    - _create_domain_entity: Create the domain entity for persistence
    - _parse_response: Parse the response from the message bus

    Type Parameters:
        T: The response type (str for decision/clarification, Dict[str, str] for env_var)
    """

    # To be defined by subclasses
    request_type: HITLRequestType
    response_key: str

    def __init__(
        self,
        message_bus: Optional[HITLMessageBusPort] = None,
        config: Optional[HITLManagerConfig] = None,
    ):
        """
        Initialize the HITL manager.

        Args:
            message_bus: The message bus for cross-process communication
            config: Configuration for the manager
        """
        self._message_bus = message_bus
        self._config = config or HITLManagerConfig()
        self._pending_requests: Dict[str, BaseHITLRequest[T]] = {}
        self._lock = asyncio.Lock()
        self._stream_tasks: Dict[str, asyncio.Task] = {}

    # =========================================================================
    # Abstract methods to be implemented by subclasses
    # =========================================================================

    @abstractmethod
    def _create_domain_entity(
        self,
        request: BaseHITLRequest[T],
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        message_id: Optional[str],
        timeout: float,
    ) -> HITLRequestEntity:
        """
        Create the domain entity for database persistence.

        Args:
            request: The request object
            tenant_id: Tenant ID
            project_id: Project ID
            conversation_id: Conversation ID
            message_id: Optional message ID
            timeout: Timeout in seconds

        Returns:
            HITLRequestEntity for persistence
        """
        pass

    @abstractmethod
    def _parse_response(self, message: HITLMessage) -> T:
        """
        Parse the response from a message bus message.

        Args:
            message: The message from the bus

        Returns:
            The parsed response value
        """
        pass

    @abstractmethod
    def _get_response_for_db(self, response: T) -> str:
        """
        Convert response to string for database storage.

        Args:
            response: The response value

        Returns:
            String representation for database
        """
        pass

    # =========================================================================
    # Resource acquisition (lazy initialization)
    # =========================================================================

    async def _get_message_bus(self) -> Optional[HITLMessageBusPort]:
        """Get the message bus, creating it if necessary."""
        if self._message_bus is not None:
            return self._message_bus

        # Try to create from Redis client
        try:
            from src.infrastructure.adapters.secondary.messaging.redis_hitl_message_bus import (
                RedisHITLMessageBusAdapter,
            )

            redis_client = await self._get_redis_client()
            if redis_client:
                self._message_bus = RedisHITLMessageBusAdapter(redis_client)
                return self._message_bus
        except Exception as e:
            logger.warning(f"Failed to create message bus: {e}")

        return None

    async def _get_redis_client(self):
        """Get Redis client for Pub/Sub fallback.

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

    # =========================================================================
    # Database operations
    # =========================================================================

    async def _persist_request(
        self,
        request: BaseHITLRequest[T],
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        message_id: Optional[str] = None,
        timeout: float = 300.0,
    ) -> bool:
        """Persist request to database."""
        if not self._config.db_persistence_enabled:
            return True

        session = await self._get_db_session()
        if not session:
            return False

        try:
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SqlHITLRequestRepository,
            )

            repo = SqlHITLRequestRepository(session)
            entity = self._create_domain_entity(
                request=request,
                tenant_id=tenant_id,
                project_id=project_id,
                conversation_id=conversation_id,
                message_id=message_id,
                timeout=timeout,
            )

            await repo.create(entity)
            await session.commit()
            logger.info(
                f"Persisted {self.request_type.value} request {request.request_id} to database"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to persist {self.request_type.value} request: {e}")
            await session.rollback()
            return False
        finally:
            await session.close()

    async def _update_db_response(
        self, request_id: str, response: T, metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Update database with response."""
        if not self._config.db_persistence_enabled:
            return True

        session = await self._get_db_session()
        if not session:
            return False

        try:
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SqlHITLRequestRepository,
            )

            repo = SqlHITLRequestRepository(session)
            response_str = self._get_response_for_db(response)
            result = await repo.update_response(request_id, response_str, metadata)
            await session.commit()
            return result is not None
        except Exception as e:
            logger.error(f"Failed to update DB response: {e}")
            await session.rollback()
            return False
        finally:
            await session.close()

    async def _mark_db_timeout(self, request_id: str, default_response: Optional[T] = None) -> bool:
        """Mark request as timed out in database."""
        if not self._config.db_persistence_enabled:
            return True

        session = await self._get_db_session()
        if not session:
            return False

        try:
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SqlHITLRequestRepository,
            )

            repo = SqlHITLRequestRepository(session)
            default_str = (
                self._get_response_for_db(default_response)
                if default_response is not None
                else None
            )
            result = await repo.mark_timeout(request_id, default_str)
            await session.commit()
            return result is not None
        except Exception as e:
            logger.error(f"Failed to mark DB timeout: {e}")
            await session.rollback()
            return False
        finally:
            await session.close()

    async def _mark_db_completed(self, request_id: str) -> bool:
        """Mark request as completed in database (Agent successfully processed)."""
        if not self._config.db_persistence_enabled:
            return True

        session = await self._get_db_session()
        if not session:
            return False

        try:
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SqlHITLRequestRepository,
            )

            repo = SqlHITLRequestRepository(session)
            result = await repo.mark_completed(request_id)
            await session.commit()
            if result:
                logger.debug(f"Marked HITL request {request_id} as completed")
            return result is not None
        except Exception as e:
            logger.error(f"Failed to mark DB completed: {e}")
            await session.rollback()
            return False
        finally:
            await session.close()

    # =========================================================================
    # Core HITL operations
    # =========================================================================

    async def register_request(
        self,
        request: BaseHITLRequest[T],
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
        timeout: float = 300.0,
    ) -> None:
        """
        Register a request with optional database persistence.

        Args:
            request: The request to register
            tenant_id: Optional tenant ID for persistence
            project_id: Optional project ID for persistence
            conversation_id: Optional conversation ID for persistence
            message_id: Optional message ID for persistence
            timeout: Timeout for the request
        """
        async with self._lock:
            self._pending_requests[request.request_id] = request

        logger.info(f"Registered {self.request_type.value} request {request.request_id}")

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
        self,
        request_id: str,
        timeout: Optional[float] = None,
        default_response: Optional[T] = None,
    ) -> T:
        """
        Wait for user response with Redis Streams cross-process support.

        This method waits for either:
        1. Local response via future (same process)
        2. Redis Streams response (cross-process) - primary
        3. Redis Pub/Sub response (cross-process) - fallback

        Args:
            request_id: The request ID to wait for
            timeout: Maximum time to wait (seconds)
            default_response: Default response to use on timeout

        Returns:
            User's response

        Raises:
            asyncio.TimeoutError: If no response within timeout and no default
            ValueError: If request not found
        """
        timeout = timeout or self._config.default_timeout

        async with self._lock:
            request = self._pending_requests.get(request_id)

        if not request:
            raise ValueError(f"{self.request_type.value} request {request_id} not found")

        # Get consumer info
        consumer_group = f"{self._config.consumer_group_prefix}-{self.request_type.value}-workers"
        consumer_name = f"worker-{uuid.uuid4().hex[:8]}"

        # Try Redis Streams first
        message_bus = await self._get_message_bus()
        stream_task = None
        pubsub_task = None

        if message_bus:
            # Listen via Redis Streams
            async def listen_stream():
                try:
                    async for message in message_bus.subscribe_for_response(
                        request_id=request_id,
                        consumer_group=consumer_group,
                        consumer_name=consumer_name,
                        timeout_ms=int(timeout * 1000),
                    ):
                        response = self._parse_response(message)
                        request.resolve(response)

                        # Acknowledge the message
                        await message_bus.acknowledge(
                            request_id=request_id,
                            consumer_group=consumer_group,
                            message_ids=[message.message_id],
                        )
                        break
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Stream listener error for {request_id}: {e}")

            stream_task = asyncio.create_task(listen_stream())
            self._stream_tasks[request_id] = stream_task

        # Also setup Pub/Sub fallback for backward compatibility
        if self._config.fallback_to_pubsub:
            pubsub_task = asyncio.create_task(self._listen_pubsub_fallback(request_id, request))

        try:
            response = await asyncio.wait_for(request.future, timeout=timeout)
            # Mark request as completed in database
            await self._mark_db_completed(request_id)
            return response
        except asyncio.TimeoutError:
            # Mark as timed out in database
            await self._mark_db_timeout(request_id, default_response)
            if default_response is not None:
                logger.warning(
                    f"{self.request_type.value} {request_id} timed out, "
                    f"using default: {default_response}"
                )
                return default_response
            raise
        finally:
            # Cleanup tasks
            if stream_task and not stream_task.done():
                stream_task.cancel()
                try:
                    await stream_task
                except asyncio.CancelledError:
                    pass
            self._stream_tasks.pop(request_id, None)

            if pubsub_task and not pubsub_task.done():
                pubsub_task.cancel()
                try:
                    await pubsub_task
                except asyncio.CancelledError:
                    pass

            # Cleanup stream if configured
            if self._config.stream_cleanup_on_complete and message_bus:
                try:
                    await message_bus.cleanup_stream(request_id)
                except Exception as e:
                    logger.warning(f"Failed to cleanup stream for {request_id}: {e}")

    async def _listen_pubsub_fallback(self, request_id: str, request: BaseHITLRequest[T]):
        """Fallback Pub/Sub listener for backward compatibility."""
        redis_client = await self._get_redis_client()
        if not redis_client:
            return

        channel = f"hitl:{self.request_type.value}:{request_id}"
        pubsub = redis_client.pubsub()

        try:
            await pubsub.subscribe(channel)
            logger.debug(f"Pub/Sub fallback subscribed to channel: {channel}")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        response_value = data.get(self.response_key)
                        if response_value is not None:
                            # Create a fake HITLMessage for parsing
                            fake_message = HITLMessage(
                                message_id="pubsub",
                                request_id=request_id,
                                message_type=self._get_message_type_from_response(),
                                payload={self.response_key: response_value},
                            )
                            response = self._parse_response(fake_message)
                            request.resolve(response)
                            break
                    except Exception as e:
                        logger.error(f"Error processing Pub/Sub message: {e}")
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    def _get_message_type_from_response(self):
        """Get the message type for response messages."""
        from src.domain.ports.services.hitl_message_bus_port import HITLMessageType

        return HITLMessageType.RESPONSE

    async def respond(self, request_id: str, response: T) -> Union[bool, str]:
        """
        Respond to a request.

        This method handles page refresh scenarios by finding the LATEST pending
        request for the same conversation when the original request is not found:

        1. Updates the database for the original request
        2. Tries local resolution (same process)
        3. If local not found, finds the LATEST PENDING request for same conversation
        4. Publishes to Redis Streams for the CORRECT target request (cross-process)
        5. Falls back to Pub/Sub if needed

        Args:
            request_id: ID of the request (may be stale after page refresh)
            response: User's response

        Returns:
            The target request_id if successful (may differ from input after page refresh),
            or False if request was not found
        """
        # First, determine the target request_id for cross-process messaging
        # This handles page refresh: user responds to old ID, but agent has new ID
        target_request_id = await self._find_target_request_id(request_id)

        if target_request_id != request_id:
            logger.info(
                f"[HITL] Redirecting response from {request_id} to {target_request_id} "
                f"(page refresh detected)"
            )

        # Update database - mark original request as answered
        db_updated = await self._update_db_response(request_id, response)
        if not db_updated:
            logger.warning(
                f"{self.request_type.value} request {request_id} not found or already answered in DB"
            )
            # Even if original not in DB, we might have found a target via conversation
            if target_request_id == request_id:
                return False

        # Try local resolution first (same process) - check both IDs
        async with self._lock:
            # Try original request_id
            request = self._pending_requests.get(request_id)
            if request:
                request.resolve(response)
                logger.info(f"Responded to {self.request_type.value} {request_id} (local)")
                return target_request_id  # Return target ID for stream bridge

            # Try target request_id if different
            if target_request_id != request_id:
                request = self._pending_requests.get(target_request_id)
                if request:
                    request.resolve(response)
                    logger.info(
                        f"Responded to {self.request_type.value} {target_request_id} "
                        f"(local, via conversation redirect)"
                    )
                    # Also update the target request in DB
                    await self._update_db_response(target_request_id, response)
                    return target_request_id  # Return target ID for stream bridge

        # Publish to Redis Streams (cross-process) - use TARGET request_id
        message_bus = await self._get_message_bus()
        if message_bus:
            try:
                await message_bus.publish_response(
                    request_id=target_request_id,
                    response_key=self.response_key,
                    response_value=response if not isinstance(response, dict) else response,
                )
                logger.info(
                    f"Published {self.request_type.value} response to stream: {target_request_id}"
                    + (
                        f" (redirected from {request_id})"
                        if target_request_id != request_id
                        else ""
                    )
                )

                # If we redirected, also update the target request in DB
                if target_request_id != request_id:
                    await self._update_db_response(target_request_id, response)

                return target_request_id  # Return target ID for stream bridge
            except Exception as e:
                logger.warning(f"Failed to publish to stream: {e}")

        # Fallback to Pub/Sub - use TARGET request_id
        if self._config.fallback_to_pubsub:
            redis_client = await self._get_redis_client()
            if redis_client:
                channel = f"hitl:{self.request_type.value}:{target_request_id}"
                message = json.dumps({"request_id": target_request_id, self.response_key: response})
                try:
                    subscribers = await redis_client.publish(channel, message)
                    if subscribers > 0:
                        logger.info(
                            f"Published {self.request_type.value} response to Pub/Sub: "
                            f"{target_request_id}, subscribers={subscribers}"
                        )
                        return target_request_id  # Return target ID for stream bridge
                    else:
                        logger.warning(
                            f"No subscribers for {target_request_id} on Pub/Sub channel, "
                            "but DB was updated"
                        )
                        return target_request_id  # Return target ID for stream bridge
                except Exception as e:
                    logger.warning(f"Failed to publish to Pub/Sub: {e}")

        # DB was updated even if messaging failed
        return target_request_id  # Return target ID for stream bridge

    async def _find_target_request_id(self, original_request_id: str) -> str:
        """
        Find the correct target request_id for cross-process messaging.

        After page refresh, user might respond to an OLD request_id, but the agent
        has since created a NEW request for the same conversation. This method:
        1. Looks up the original request to find its conversation_id
        2. Finds the LATEST PENDING request for that conversation of the same type
        3. Returns that request's ID as the target

        Args:
            original_request_id: The request_id user responded to

        Returns:
            The target request_id to publish to (may be different from original)
        """
        session = await self._get_db_session()
        if not session:
            return original_request_id

        try:
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SqlHITLRequestRepository,
            )

            repo = SqlHITLRequestRepository(session)

            # Get the original request to find conversation context
            original_request = await repo.get_by_id(original_request_id)
            if not original_request:
                logger.warning(f"Original request {original_request_id} not found in DB")
                return original_request_id

            # Find latest pending request for the same conversation
            # Note: Don't exclude expired - the Agent might still be waiting
            # (expires_at is for frontend display, actual timeout is handled by wait_for_response)
            pending_requests = await repo.get_pending_by_conversation(
                conversation_id=original_request.conversation_id,
                tenant_id=original_request.tenant_id,
                project_id=original_request.project_id,
                exclude_expired=False,  # Include expired because Agent might still wait
            )

            # Filter by request type and find the latest
            matching_pending = [r for r in pending_requests if r.request_type == self.request_type]

            if matching_pending:
                # Return the latest pending request (list is ordered by created_at desc)
                target = matching_pending[0]
                if target.id != original_request_id:
                    logger.info(
                        f"[HITL] Found newer pending request {target.id} for conversation "
                        f"{original_request.conversation_id} (original: {original_request_id})"
                    )
                    return target.id

            return original_request_id

        except Exception as e:
            logger.warning(f"Failed to find target request_id: {e}")
            return original_request_id
        finally:
            await session.close()

    async def unregister_request(self, request_id: str) -> None:
        """
        Unregister a request.

        Args:
            request_id: ID of the request to unregister
        """
        async with self._lock:
            self._pending_requests.pop(request_id, None)
            stream_task = self._stream_tasks.pop(request_id, None)
            if stream_task and not stream_task.done():
                stream_task.cancel()

        logger.info(f"Unregistered {self.request_type.value} request {request_id}")

    async def cancel_request(self, request_id: str) -> bool:
        """
        Cancel a request.

        Args:
            request_id: ID of the request

        Returns:
            True if request was found and cancelled, False otherwise
        """
        async with self._lock:
            request = self._pending_requests.get(request_id)
            if request:
                request.cancel()
                self._pending_requests.pop(request_id, None)
                stream_task = self._stream_tasks.pop(request_id, None)
                if stream_task and not stream_task.done():
                    stream_task.cancel()
                logger.info(f"Cancelled {self.request_type.value} {request_id}")
                return True
            else:
                logger.warning(f"{self.request_type.value} request {request_id} not found")
                return False

    def get_request(self, request_id: str) -> Optional[BaseHITLRequest[T]]:
        """Get a request by ID."""
        return self._pending_requests.get(request_id)

    def get_pending_requests(self) -> List[BaseHITLRequest[T]]:
        """Get all pending requests."""
        return list(self._pending_requests.values())

    # =========================================================================
    # Message bus injection (for DI)
    # =========================================================================

    def set_message_bus(self, message_bus: HITLMessageBusPort) -> None:
        """
        Set the message bus (for dependency injection).

        Args:
            message_bus: The message bus to use
        """
        self._message_bus = message_bus

    def set_config(self, config: HITLManagerConfig) -> None:
        """
        Set the configuration.

        Args:
            config: The configuration to use
        """
        self._config = config
