"""
Environment Variable Manager - Refactored HITL manager for env var requests.

This module provides the EnvVarManager that inherits from BaseHITLManager
and implements environment variable request-specific behavior.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

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
from src.infrastructure.agent.hitl.base_manager import (
    BaseHITLManager,
    BaseHITLRequest,
    HITLManagerConfig,
)

logger = logging.getLogger(__name__)


class EnvVarInputType(str, Enum):
    """Type of input field for environment variable."""

    TEXT = "text"  # Plain text input
    PASSWORD = "password"  # Masked password input
    TEXTAREA = "textarea"  # Multi-line text input
    SELECT = "select"  # Dropdown selection


@dataclass
class EnvVarField:
    """
    Specification for an environment variable input field.

    Attributes:
        variable_name: Name of the environment variable
        display_name: Human-readable label for the field
        description: Help text for the user
        input_type: Type of input field (text, password, etc.)
        is_required: Whether the field is required
        is_secret: Whether to mask the value in logs/outputs
        default_value: Optional default value
        options: For select type, list of valid options
    """

    variable_name: str
    display_name: str
    description: Optional[str] = None
    input_type: EnvVarInputType = EnvVarInputType.TEXT
    is_required: bool = True
    is_secret: bool = True
    default_value: Optional[str] = None
    options: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE event.

        Field mapping to match frontend EnvVarField interface:
        - variable_name -> name (used as form field key)
        - display_name -> label (shown to user)
        - is_required -> required
        """
        return {
            "name": self.variable_name,  # Frontend uses 'name' as form field key
            "label": self.display_name,  # Frontend uses 'label' for display
            "description": self.description,
            "input_type": self.input_type.value,
            "required": self.is_required,  # Frontend uses 'required'
            "is_secret": self.is_secret,
            "default_value": self.default_value,
            "placeholder": f"请输入 {self.display_name}",  # Frontend expects placeholder
        }


@dataclass
class EnvVarRequest(BaseHITLRequest[Dict[str, str]]):
    """
    A pending environment variable request.

    Extends BaseHITLRequest with env var-specific fields.

    Attributes:
        tool_name: Name of the tool requesting the variables
        fields: List of variable fields to request
    """

    tool_name: str = ""
    fields: List[EnvVarField] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE event."""
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "fields": [f.to_dict() for f in self.fields],
            "context": self.context,
        }


class EnvVarManager(BaseHITLManager[Dict[str, str]]):
    """
    Manager for pending environment variable requests.

    Inherits from BaseHITLManager and implements env var-specific behavior.
    Uses Redis Streams for reliable cross-process communication.
    Uses database persistence for recovery after page refresh.

    Architecture:
    - Worker process: Creates request, persists to DB, subscribes to Redis Stream, waits for response
    - API process: Receives WebSocket message, updates DB, publishes to Redis Stream
    - Worker process: Receives Redis message, resolves the future
    """

    # HITL type configuration
    request_type = HITLRequestType.ENV_VAR
    response_key = "values"

    def __init__(
        self,
        message_bus: Optional[HITLMessageBusPort] = None,
        config: Optional[HITLManagerConfig] = None,
    ):
        """
        Initialize the env var manager.

        Args:
            message_bus: Optional message bus for cross-process communication
            config: Optional configuration (default timeout is 600 seconds for env vars)
        """
        # Use a longer default timeout for env var requests (10 minutes)
        if config is None:
            config = HITLManagerConfig(default_timeout=600.0)
        super().__init__(message_bus=message_bus, config=config)

    def _create_domain_entity(
        self,
        request: BaseHITLRequest[Dict[str, str]],
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        message_id: Optional[str],
        timeout: float,
    ) -> HITLRequestEntity:
        """Create the domain entity for database persistence."""
        env_var_request = request  # Type hint: EnvVarRequest
        tool_name = getattr(env_var_request, "tool_name", "unknown")
        fields = getattr(env_var_request, "fields", [])

        return HITLRequestEntity(
            id=request.request_id,
            request_type=HITLRequestType.ENV_VAR,
            conversation_id=conversation_id,
            message_id=message_id,
            tenant_id=tenant_id,
            project_id=project_id,
            question=f"Environment variables needed for {tool_name}",
            options=[f.to_dict() if hasattr(f, "to_dict") else f for f in fields],
            context=request.context,
            metadata={
                "tool_name": tool_name,
            },
            expires_at=datetime.utcnow() + timedelta(seconds=timeout),
        )

    def _parse_response(self, message: HITLMessage) -> Dict[str, str]:
        """Parse the env var response from a message bus message."""
        values = message.payload.get(self.response_key, {})
        if isinstance(values, str):
            # Handle JSON-encoded values
            try:
                values = json.loads(values)
            except json.JSONDecodeError:
                values = {}
        return values

    def _get_response_for_db(self, response: Dict[str, str]) -> str:
        """Convert response to string for database storage."""
        return json.dumps(response)

    # =========================================================================
    # Convenience methods for creating env var requests
    # =========================================================================

    async def create_request(
        self,
        tool_name: str,
        fields: List[EnvVarField],
        context: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, str]:
        """
        Create a new env var request and wait for user response.

        Args:
            tool_name: Name of the tool requesting variables
            fields: List of variable fields to request
            context: Additional context
            timeout: Maximum time to wait for response (seconds)

        Returns:
            Dictionary of variable_name -> value

        Raises:
            asyncio.TimeoutError: If user doesn't respond within timeout
            asyncio.CancelledError: If request is cancelled
        """
        import uuid

        timeout = timeout or self._config.default_timeout
        request_id = str(uuid.uuid4())

        request = EnvVarRequest(
            request_id=request_id,
            tool_name=tool_name,
            fields=fields,
            context=context or {},
        )

        async with self._lock:
            self._pending_requests[request_id] = request

        logger.info(
            f"Created env var request {request_id} for tool={tool_name}, "
            f"fields={[f.variable_name for f in fields]}"
        )

        try:
            values = await self.wait_for_response(
                request_id=request_id,
                timeout=timeout,
            )
            logger.info(f"Received values for {request_id}")
            return values
        except asyncio.TimeoutError:
            logger.warning(f"Env var request {request_id} timed out")
            raise
        except asyncio.CancelledError:
            logger.warning(f"Env var request {request_id} was cancelled")
            raise
        finally:
            await self.unregister_request(request_id)


# Global env var manager instance
_env_var_manager: Optional[EnvVarManager] = None


def get_env_var_manager() -> EnvVarManager:
    """Get the global env var manager instance."""
    global _env_var_manager
    if _env_var_manager is None:
        _env_var_manager = EnvVarManager()
    return _env_var_manager


def set_env_var_manager(manager: EnvVarManager) -> None:
    """Set the global env var manager instance (for DI)."""
    global _env_var_manager
    _env_var_manager = manager
