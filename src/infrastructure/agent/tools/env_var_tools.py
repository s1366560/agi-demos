"""
Environment Variable Tools for Agent Tools Configuration.

These tools allow the agent to:
1. GetEnvVarTool: Load environment variables from the database
2. RequestEnvVarTool: Request missing environment variables from the user

Follows the human-in-the-loop pattern from ClarificationTool for user input.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from src.domain.model.agent.tool_environment_variable import (
    EnvVarScope,
    ToolEnvironmentVariable,
)
from src.domain.ports.repositories.tool_environment_variable_repository import (
    ToolEnvironmentVariableRepositoryPort,
)
from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.security.encryption_service import (
    EncryptionService,
    get_encryption_service,
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
        """Convert to dictionary for SSE event."""
        return {
            "variable_name": self.variable_name,
            "display_name": self.display_name,
            "description": self.description,
            "input_type": self.input_type.value,
            "is_required": self.is_required,
            "is_secret": self.is_secret,
            "default_value": self.default_value,
            "options": self.options,
        }


@dataclass
class EnvVarRequest:
    """
    A pending environment variable request.

    Attributes:
        request_id: Unique ID for this request
        tool_name: Name of the tool requesting the variables
        fields: List of variable fields to request
        context: Additional context for the request
        future: Future that resolves when user provides values
    """

    request_id: str
    tool_name: str
    fields: List[EnvVarField]
    context: Dict[str, Any] = field(default_factory=dict)
    future: asyncio.Future = field(default_factory=asyncio.Future)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE event."""
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "fields": [f.to_dict() for f in self.fields],
            "context": self.context,
        }

    def resolve(self, values: Dict[str, str]):
        """Resolve the future with user's provided values."""
        if not self.future.done():
            self.future.set_result(values)

    def cancel(self):
        """Cancel the request."""
        if not self.future.done():
            self.future.cancel()


class EnvVarManager:
    """
    Manager for pending environment variable requests.

    Thread-safe manager for handling multiple env var requests.
    """

    def __init__(self):
        self._pending_requests: Dict[str, EnvVarRequest] = {}
        self._lock = asyncio.Lock()

    async def create_request(
        self,
        tool_name: str,
        fields: List[EnvVarField],
        context: Optional[Dict[str, Any]] = None,
        timeout: float = 600.0,  # 10 minutes default
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
        request_id = str(uuid.uuid4())

        async with self._lock:
            request = EnvVarRequest(
                request_id=request_id,
                tool_name=tool_name,
                fields=fields,
                context=context or {},
            )
            self._pending_requests[request_id] = request

        logger.info(
            f"Created env var request {request_id} for tool={tool_name}, "
            f"fields={[f.variable_name for f in fields]}"
        )

        try:
            # Wait for user response with timeout
            values = await asyncio.wait_for(request.future, timeout=timeout)
            logger.info(f"Received values for {request_id}")
            return values
        except asyncio.TimeoutError:
            logger.warning(f"Env var request {request_id} timed out")
            raise
        except asyncio.CancelledError:
            logger.warning(f"Env var request {request_id} was cancelled")
            raise
        finally:
            # Clean up
            async with self._lock:
                self._pending_requests.pop(request_id, None)

    async def respond(self, request_id: str, values: Dict[str, str]) -> bool:
        """
        Respond to an env var request.

        Args:
            request_id: ID of the request
            values: Dictionary of variable_name -> value

        Returns:
            True if request was found and resolved, False otherwise
        """
        async with self._lock:
            request = self._pending_requests.get(request_id)
            if request:
                request.resolve(values)
                logger.info(f"Responded to env var request {request_id}")
                return True
            else:
                logger.warning(f"Env var request {request_id} not found")
                return False

    async def cancel_request(self, request_id: str) -> bool:
        """
        Cancel an env var request.

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
                logger.info(f"Cancelled env var request {request_id}")
                return True
            else:
                logger.warning(f"Env var request {request_id} not found")
                return False

    def get_request(self, request_id: str) -> Optional[EnvVarRequest]:
        """Get an env var request by ID."""
        return self._pending_requests.get(request_id)

    def get_pending_requests(self) -> List[EnvVarRequest]:
        """Get all pending env var requests."""
        return list(self._pending_requests.values())


# Global env var manager instance
_env_var_manager = EnvVarManager()


def get_env_var_manager() -> EnvVarManager:
    """Get the global env var manager instance."""
    return _env_var_manager


class GetEnvVarTool(AgentTool):
    """
    Tool for loading environment variables from the database.

    This tool retrieves encrypted environment variables stored for a specific
    tool, decrypts them, and returns the values to the agent.

    Usage:
        get_env = GetEnvVarTool(repository, encryption_service, tenant_id, project_id)
        value = await get_env.execute(
            tool_name="web_search",
            variable_name="SERPER_API_KEY"
        )
    """

    def __init__(
        self,
        repository: ToolEnvironmentVariableRepositoryPort,
        encryption_service: Optional[EncryptionService] = None,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ):
        """
        Initialize the get env var tool.

        Args:
            repository: Repository for env var persistence
            encryption_service: Service for decryption (defaults to singleton)
            tenant_id: Current tenant ID (can be set later via context)
            project_id: Current project ID (can be set later via context)
        """
        super().__init__(
            name="get_env_var",
            description=(
                "Load an environment variable needed by a tool. "
                "Returns the decrypted value if found, or indicates if missing."
            ),
        )
        self._repository = repository
        self._encryption_service = encryption_service or get_encryption_service()
        self._tenant_id = tenant_id
        self._project_id = project_id

    def set_context(self, tenant_id: str, project_id: Optional[str] = None):
        """Set the tenant and project context."""
        self._tenant_id = tenant_id
        self._project_id = project_id

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate arguments."""
        if not self._tenant_id:
            logger.error("tenant_id not set")
            return False
        if "tool_name" not in kwargs:
            logger.error("Missing required argument: tool_name")
            return False
        if "variable_name" not in kwargs:
            logger.error("Missing required argument: variable_name")
            return False
        return True

    async def execute(
        self,
        tool_name: str,
        variable_name: str,
    ) -> str:
        """
        Get an environment variable value.

        Args:
            tool_name: Name of the tool that needs the variable
            variable_name: Name of the environment variable

        Returns:
            JSON string with status and value (if found)
        """
        import json

        if not self.validate_args(tool_name=tool_name, variable_name=variable_name):
            return json.dumps({
                "status": "error",
                "message": "Invalid arguments or missing tenant context",
            })

        try:
            env_var = await self._repository.get(
                tenant_id=self._tenant_id,
                tool_name=tool_name,
                variable_name=variable_name,
                project_id=self._project_id,
            )

            if env_var:
                # Decrypt the value
                decrypted_value = self._encryption_service.decrypt(env_var.encrypted_value)

                # Mask if secret for logging
                log_value = "***" if env_var.is_secret else decrypted_value[:20] + "..."
                logger.info(
                    f"Retrieved env var {tool_name}/{variable_name}: {log_value}"
                )

                return json.dumps({
                    "status": "found",
                    "variable_name": variable_name,
                    "value": decrypted_value,
                    "is_secret": env_var.is_secret,
                    "scope": env_var.scope.value,
                })
            else:
                logger.info(f"Env var not found: {tool_name}/{variable_name}")
                return json.dumps({
                    "status": "not_found",
                    "variable_name": variable_name,
                    "message": f"Environment variable '{variable_name}' not configured for tool '{tool_name}'",
                })

        except Exception as e:
            logger.error(f"Error getting env var {tool_name}/{variable_name}: {e}")
            return json.dumps({
                "status": "error",
                "message": str(e),
            })

    async def get_all_for_tool(self, tool_name: str) -> Dict[str, str]:
        """
        Get all environment variables for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Dictionary of variable_name -> decrypted_value
        """
        if not self._tenant_id:
            raise ValueError("tenant_id not set")

        env_vars = await self._repository.get_for_tool(
            tenant_id=self._tenant_id,
            tool_name=tool_name,
            project_id=self._project_id,
        )

        result = {}
        for env_var in env_vars:
            decrypted_value = self._encryption_service.decrypt(env_var.encrypted_value)
            result[env_var.variable_name] = decrypted_value

        return result

    def get_output_schema(self) -> Dict[str, Any]:
        """Get output schema for tool composition."""
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["found", "not_found", "error"]},
                "variable_name": {"type": "string"},
                "value": {"type": "string"},
                "is_secret": {"type": "boolean"},
                "scope": {"type": "string"},
                "message": {"type": "string"},
            },
        }


class RequestEnvVarTool(AgentTool):
    """
    Tool for requesting missing environment variables from the user.

    This tool triggers a human-in-the-loop interaction where the agent
    asks the user to provide missing environment variable values. The
    values are then encrypted and stored in the database.

    Usage:
        request_env = RequestEnvVarTool(repository, encryption_service, ...)
        result = await request_env.execute(
            tool_name="web_search",
            fields=[
                {
                    "variable_name": "SERPER_API_KEY",
                    "display_name": "Serper API Key",
                    "description": "API key for Serper web search service",
                    "input_type": "password",
                    "is_required": True,
                }
            ]
        )
    """

    def __init__(
        self,
        repository: ToolEnvironmentVariableRepositoryPort,
        encryption_service: Optional[EncryptionService] = None,
        manager: Optional[EnvVarManager] = None,
        event_publisher: Optional[Callable[[Dict[str, Any]], None]] = None,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ):
        """
        Initialize the request env var tool.

        Args:
            repository: Repository for env var persistence
            encryption_service: Service for encryption (defaults to singleton)
            manager: EnvVar manager (defaults to global instance)
            event_publisher: Function to publish SSE events
            tenant_id: Current tenant ID (can be set later via context)
            project_id: Current project ID (can be set later via context)
        """
        super().__init__(
            name="request_env_var",
            description=(
                "Request environment variables from the user when they are missing. "
                "This will prompt the user to input the required values which will "
                "be securely stored for future use."
            ),
        )
        self._repository = repository
        self._encryption_service = encryption_service or get_encryption_service()
        self._manager = manager or get_env_var_manager()
        self._event_publisher = event_publisher
        self._tenant_id = tenant_id
        self._project_id = project_id

    def set_context(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
        event_publisher: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        """Set the tenant, project, and event publisher context."""
        self._tenant_id = tenant_id
        self._project_id = project_id
        if event_publisher:
            self._event_publisher = event_publisher

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate arguments."""
        if not self._tenant_id:
            logger.error("tenant_id not set")
            return False
        if "tool_name" not in kwargs:
            logger.error("Missing required argument: tool_name")
            return False
        if "fields" not in kwargs:
            logger.error("Missing required argument: fields")
            return False
        if not isinstance(kwargs["fields"], list) or len(kwargs["fields"]) == 0:
            logger.error("fields must be a non-empty list")
            return False
        return True

    async def execute(
        self,
        tool_name: str,
        fields: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        save_to_project: bool = False,
        timeout: float = 600.0,
    ) -> str:
        """
        Request environment variables from the user.

        Args:
            tool_name: Name of the tool that needs the variables
            fields: List of field specifications (see EnvVarField)
            context: Additional context to display to the user
            save_to_project: If True, save to project level; else tenant level
            timeout: Maximum wait time in seconds

        Returns:
            JSON string with status and saved variables
        """
        import json

        if not self.validate_args(tool_name=tool_name, fields=fields):
            return json.dumps({
                "status": "error",
                "message": "Invalid arguments or missing tenant context",
            })

        # Convert field dicts to EnvVarField objects
        env_var_fields = []
        for f in fields:
            env_var_fields.append(EnvVarField(
                variable_name=f["variable_name"],
                display_name=f.get("display_name", f["variable_name"]),
                description=f.get("description"),
                input_type=EnvVarInputType(f.get("input_type", "text")),
                is_required=f.get("is_required", True),
                is_secret=f.get("is_secret", True),
                default_value=f.get("default_value"),
                options=f.get("options"),
            ))

        # Create the request
        request_id = str(uuid.uuid4())
        request = EnvVarRequest(
            request_id=request_id,
            tool_name=tool_name,
            fields=env_var_fields,
            context=context or {},
        )

        # Store in manager
        async with self._manager._lock:
            self._manager._pending_requests[request_id] = request

        # Publish SSE event for frontend
        if self._event_publisher:
            from src.domain.events.agent_events import AgentEventType

            self._event_publisher({
                "type": AgentEventType.ENV_VAR_REQUESTED.value,
                "data": request.to_dict(),
            })

        logger.info(
            f"Requesting env vars for tool={tool_name}: "
            f"{[f.variable_name for f in env_var_fields]}"
        )

        try:
            # Wait for user response
            values = await asyncio.wait_for(request.future, timeout=timeout)

            # Encrypt and save each value
            saved_vars = []
            scope = EnvVarScope.PROJECT if save_to_project and self._project_id else EnvVarScope.TENANT
            project_id = self._project_id if save_to_project else None

            for field_spec in env_var_fields:
                var_name = field_spec.variable_name
                if var_name in values and values[var_name]:
                    # Encrypt the value
                    encrypted_value = self._encryption_service.encrypt(values[var_name])

                    # Create domain entity
                    env_var = ToolEnvironmentVariable(
                        tenant_id=self._tenant_id,
                        project_id=project_id,
                        tool_name=tool_name,
                        variable_name=var_name,
                        encrypted_value=encrypted_value,
                        description=field_spec.description,
                        is_required=field_spec.is_required,
                        is_secret=field_spec.is_secret,
                        scope=scope,
                    )

                    # Upsert to database
                    await self._repository.upsert(env_var)
                    saved_vars.append(var_name)

                    logger.info(f"Saved env var: {tool_name}/{var_name}")

            # Publish success event
            if self._event_publisher:
                from src.domain.events.agent_events import AgentEventType

                self._event_publisher({
                    "type": AgentEventType.ENV_VAR_PROVIDED.value,
                    "data": {
                        "request_id": request_id,
                        "tool_name": tool_name,
                        "saved_variables": saved_vars,
                    },
                })

            return json.dumps({
                "status": "success",
                "saved_variables": saved_vars,
                "scope": scope.value,
            })

        except asyncio.TimeoutError:
            logger.warning(f"Env var request {request_id} timed out")
            return json.dumps({
                "status": "timeout",
                "message": "User did not provide the requested environment variables in time",
            })

        except asyncio.CancelledError:
            logger.warning(f"Env var request {request_id} was cancelled")
            return json.dumps({
                "status": "cancelled",
                "message": "Request was cancelled",
            })

        except Exception as e:
            logger.error(f"Error in env var request {request_id}: {e}")
            return json.dumps({
                "status": "error",
                "message": str(e),
            })

        finally:
            # Clean up
            async with self._manager._lock:
                self._manager._pending_requests.pop(request_id, None)

    def get_output_schema(self) -> Dict[str, Any]:
        """Get output schema for tool composition."""
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["success", "timeout", "cancelled", "error"],
                },
                "saved_variables": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "scope": {"type": "string"},
                "message": {"type": "string"},
            },
        }


class CheckEnvVarsTool(AgentTool):
    """
    Tool for checking if all required environment variables are available.

    This is a convenience tool that checks multiple variables at once
    and returns which ones are missing.

    Usage:
        check_env = CheckEnvVarsTool(repository, encryption_service, ...)
        result = await check_env.execute(
            tool_name="web_search",
            required_vars=["SERPER_API_KEY", "GOOGLE_API_KEY"]
        )
    """

    def __init__(
        self,
        repository: ToolEnvironmentVariableRepositoryPort,
        encryption_service: Optional[EncryptionService] = None,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ):
        """
        Initialize the check env vars tool.

        Args:
            repository: Repository for env var persistence
            encryption_service: Service for decryption (defaults to singleton)
            tenant_id: Current tenant ID (can be set later via context)
            project_id: Current project ID (can be set later via context)
        """
        super().__init__(
            name="check_env_vars",
            description=(
                "Check if required environment variables are configured for a tool. "
                "Returns which variables are available and which are missing."
            ),
        )
        self._repository = repository
        self._encryption_service = encryption_service or get_encryption_service()
        self._tenant_id = tenant_id
        self._project_id = project_id

    def set_context(self, tenant_id: str, project_id: Optional[str] = None):
        """Set the tenant and project context."""
        self._tenant_id = tenant_id
        self._project_id = project_id

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate arguments."""
        if not self._tenant_id:
            logger.error("tenant_id not set")
            return False
        if "tool_name" not in kwargs:
            logger.error("Missing required argument: tool_name")
            return False
        if "required_vars" not in kwargs:
            logger.error("Missing required argument: required_vars")
            return False
        return True

    async def execute(
        self,
        tool_name: str,
        required_vars: List[str],
    ) -> str:
        """
        Check if required environment variables are available.

        Args:
            tool_name: Name of the tool
            required_vars: List of required variable names

        Returns:
            JSON string with available and missing variables
        """
        import json

        if not self.validate_args(tool_name=tool_name, required_vars=required_vars):
            return json.dumps({
                "status": "error",
                "message": "Invalid arguments or missing tenant context",
            })

        try:
            # Get all configured vars for the tool
            env_vars = await self._repository.get_for_tool(
                tenant_id=self._tenant_id,
                tool_name=tool_name,
                project_id=self._project_id,
            )

            configured_vars = {ev.variable_name for ev in env_vars}
            available = [v for v in required_vars if v in configured_vars]
            missing = [v for v in required_vars if v not in configured_vars]

            return json.dumps({
                "status": "checked",
                "tool_name": tool_name,
                "available": available,
                "missing": missing,
                "all_available": len(missing) == 0,
            })

        except Exception as e:
            logger.error(f"Error checking env vars for {tool_name}: {e}")
            return json.dumps({
                "status": "error",
                "message": str(e),
            })

    def get_output_schema(self) -> Dict[str, Any]:
        """Get output schema for tool composition."""
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["checked", "error"]},
                "tool_name": {"type": "string"},
                "available": {"type": "array", "items": {"type": "string"}},
                "missing": {"type": "array", "items": {"type": "string"}},
                "all_available": {"type": "boolean"},
                "message": {"type": "string"},
            },
        }
