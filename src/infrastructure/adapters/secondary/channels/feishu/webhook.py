"""Feishu Webhook handler for receiving events via HTTP."""

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


class FeishuWebhookHandler:
    """Handler for Feishu webhook events."""

    def __init__(
        self, verification_token: str | None = None, encrypt_key: str | None = None
    ) -> None:
        self._verification_token = verification_token
        self._encrypt_key = encrypt_key
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register_handler(self, event_type: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Register a handler for a specific event type.

        Args:
            event_type: Event type (e.g., "im.message.receive_v1")
            handler: Handler function
        """
        self._handlers[event_type] = handler
        logger.debug(f"Registered handler for event: {event_type}")

    async def handle_request(self, request: Request) -> dict[str, Any]:
        """Handle incoming webhook request.

        Args:
            request: FastAPI request object

        Returns:
            Response dict
        """
        body = await request.body()

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook request: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON") from e

        # Handle URL verification challenge
        if data.get("type") == "url_verification":
            return await self._handle_verification(data)

        # Verify token if configured
        if self._verification_token:
            token = data.get("token")
            if token != self._verification_token:
                logger.warning("Webhook verification token mismatch")
                raise HTTPException(status_code=401, detail="Invalid token")

        # Process event
        event_data = data.get("event", {})
        event_type = data.get("header", {}).get("event_type") or data.get("type")

        if not event_type:
            logger.warning("No event type in webhook data")
            return {"code": 0}

        # Find and call handler
        handler = self._handlers.get(event_type)
        if handler:
            try:
                result = handler(event_data)
                if hasattr(result, "__await__"):
                    result = await result
                return {"code": 0, "data": result}
            except Exception as e:
                logger.error(f"Error handling event {event_type}: {e}")
                return {"code": 0}  # Still return success to Feishu
        else:
            logger.debug(f"No handler for event type: {event_type}")

        return {"code": 0}

    async def _handle_verification(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle URL verification challenge.

        Feishu sends this when configuring the webhook URL.
        """
        challenge = data.get("challenge")
        if not challenge:
            raise HTTPException(status_code=400, detail="No challenge in request")

        logger.info("Received Feishu URL verification challenge")

        return {
            "challenge": challenge,
        }

    def verify_signature(self, timestamp: str, nonce: str, body: str, signature: str) -> bool:
        """Verify request signature.

        Args:
            timestamp: Request timestamp
            nonce: Request nonce
            body: Request body
            signature: Provided signature

        Returns:
            True if signature is valid
        """
        if not self._encrypt_key:
            return True  # No encryption key configured, skip verification

        # Build signature string
        sign_str = f"{timestamp}{nonce}{self._encrypt_key}{body}"
        expected = hashlib.sha256(sign_str.encode()).hexdigest()

        return signature == expected


class FeishuEventDispatcher:
    """Dispatcher for Feishu events with filtering and middleware."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = {}
        self._middleware: list[Callable[..., Any]] = []
        self._filters: list[Callable[[dict[str, Any]], bool]] = []

    def on(self, event_type: str, *filters: Callable[[dict[str, Any]], bool]) -> Callable[..., Any]:
        """Decorator to register an event handler.

        Args:
            event_type: Event type to handle
            *filters: Optional filter functions

        Example:
            @dispatcher.on("im.message.receive_v1")
            async def handle_message(event):
                print(event)
        """

        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            if event_type not in self._handlers:
                self._handlers[event_type] = []

            self._handlers[event_type].append(
                {
                    "handler": handler,
                    "filters": list(filters),
                }
            )
            return handler

        return decorator

    def use(self, middleware: Callable[..., Any]) -> Callable[..., Any]:
        """Register middleware.

        Middleware is called before handlers and can modify the event.
        """
        self._middleware.append(middleware)
        return middleware

    def add_filter(self, filter_fn: Callable[[dict[str, Any]], bool]) -> None:
        """Add a global filter.

        Events must pass all global filters to be processed.
        """
        self._filters.append(filter_fn)

    async def dispatch(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Dispatch an event to handlers.

        Args:
            event_type: Type of event
            event_data: Event data
        """
        # Apply global filters
        for filter_fn in self._filters:
            if not filter_fn(event_data):
                logger.debug("Event filtered out by global filter")
                return

        # Apply middleware
        for middleware in self._middleware:
            try:
                result = middleware(event_data)
                if hasattr(result, "__await__"):
                    result = await result
            except Exception as e:
                logger.error(f"Middleware error: {e}")
                return

        # Find handlers
        handlers = self._handlers.get(event_type, [])

        for handler_info in handlers:
            handler = handler_info["handler"]
            filters = handler_info["filters"]

            # Apply per-handler filters
            passed = True
            for filter_fn in filters:
                if not filter_fn(event_data):
                    passed = False
                    break

            if not passed:
                continue

            # Call handler
            try:
                result = handler(event_data)
                if hasattr(result, "__await__"):
                    result = await result
            except Exception as e:
                logger.error(f"Handler error for {event_type}: {e}")


# Common event types
EVENT_MESSAGE_RECEIVE = "im.message.receive_v1"
EVENT_MESSAGE_UPDATED = "im.message.updated_v1"
EVENT_MESSAGE_DELETED = "im.message.deleted_v1"
EVENT_BOT_ADDED = "im.chat.member.bot.added_v1"
EVENT_BOT_DELETED = "im.chat.member.bot.deleted_v1"
EVENT_CHAT_DISBANDED = "im.chat.disbanded_v1"
EVENT_CHAT_UPDATED = "im.chat.updated_v1"
