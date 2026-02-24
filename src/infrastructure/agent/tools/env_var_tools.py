"""
Environment Variable Tools for Agent Tools Configuration.

These tools allow the agent to:
1. GetEnvVarTool: Load environment variables from the database
2. RequestEnvVarTool: Request missing environment variables from the user
3. CheckEnvVarsTool: Check if required environment variables are configured

Architecture (Ray-based for HITL):
- RequestEnvVarTool uses RayHITLHandler for unified HITL handling
- Redis Streams for response delivery
- SSE events for real-time frontend updates

GetEnvVarTool and CheckEnvVarsTool do NOT use HITL, they just read from database.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

from src.domain.model.agent.tool_environment_variable import (
    EnvVarScope,
    ToolEnvironmentVariable,
)
from src.domain.ports.repositories.tool_environment_variable_repository import (
    ToolEnvironmentVariableRepositoryPort,
)
from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler
from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.security.encryption_service import (
    EncryptionService,
    get_encryption_service,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CheckEnvVarsTool",
    "GetEnvVarTool",
    "RequestEnvVarTool",
]


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
        repository: ToolEnvironmentVariableRepositoryPort | None = None,
        encryption_service: EncryptionService | None = None,
        tenant_id: str | None = None,
        project_id: str | None = None,
        session_factory: Any | None = None,
    ) -> None:
        """
        Initialize the get env var tool.

        Args:
            repository: Repository for env var persistence (optional if session_factory provided)
            encryption_service: Service for decryption (defaults to singleton)
            tenant_id: Current tenant ID (can be set later via context)
            project_id: Current project ID (can be set later via context)
            session_factory: Async session factory for creating database sessions
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
        self._session_factory = session_factory

    def set_context(self, tenant_id: str, project_id: str | None = None) -> None:
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

    async def execute(  # type: ignore[override]
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
        if not self.validate_args(tool_name=tool_name, variable_name=variable_name):
            return json.dumps(
                {
                    "status": "error",
                    "message": "Invalid arguments or missing tenant context",
                }
            )

        assert self._tenant_id is not None, "tenant_id is required"
        tenant_id: str = self._tenant_id
        try:
            # If we have a session_factory, create a new session for this operation
            if self._session_factory:
                from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
                    SqlToolEnvironmentVariableRepository,
                )

                async with self._session_factory() as db_session:
                    repository = SqlToolEnvironmentVariableRepository(db_session)
                    env_var = await repository.get(
                        tenant_id=tenant_id,
                        tool_name=tool_name,
                        variable_name=variable_name,
                        project_id=self._project_id,
                    )
            else:
                env_var = await self._repository.get(  # type: ignore[union-attr]
                    tenant_id=tenant_id,
                    tool_name=tool_name,
                    variable_name=variable_name,
                    project_id=self._project_id,
                )

            if env_var:
                # Decrypt the value
                decrypted_value = self._encryption_service.decrypt(env_var.encrypted_value)

                # Mask if secret for logging
                log_value = "***" if env_var.is_secret else decrypted_value[:20] + "..."
                logger.info(f"Retrieved env var {tool_name}/{variable_name}: {log_value}")

                return json.dumps(
                    {
                        "status": "found",
                        "variable_name": variable_name,
                        "value": decrypted_value,
                        "is_secret": env_var.is_secret,
                        "scope": env_var.scope.value,
                    }
                )
            else:
                logger.info(f"Env var not found: {tool_name}/{variable_name}")
                return json.dumps(
                    {
                        "status": "not_found",
                        "variable_name": variable_name,
                        "message": f"Environment variable '{variable_name}' not configured for tool '{tool_name}'",
                    }
                )

        except Exception as e:
            logger.error(f"Error getting env var {tool_name}/{variable_name}: {e}")
            return json.dumps(
                {
                    "status": "error",
                    "message": str(e),
                }
            )

    async def get_all_for_tool(self, tool_name: str) -> dict[str, str]:
        """
        Get all environment variables for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Dictionary of variable_name -> decrypted_value
        """
        if not self._tenant_id:
            raise ValueError("tenant_id not set")

        # If we have a session_factory, create a new session for this operation
        if self._session_factory:
            from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
                SqlToolEnvironmentVariableRepository,
            )

            async with self._session_factory() as db_session:
                repository = SqlToolEnvironmentVariableRepository(db_session)
                env_vars = await repository.get_for_tool(
                    tenant_id=self._tenant_id,
                    tool_name=tool_name,
                    project_id=self._project_id,
                )
        else:
            env_vars = await self._repository.get_for_tool(  # type: ignore[union-attr]
                tenant_id=self._tenant_id,
                tool_name=tool_name,
                project_id=self._project_id,
            )

        result = {}
        for env_var in env_vars:
            decrypted_value = self._encryption_service.decrypt(env_var.encrypted_value)
            result[env_var.variable_name] = decrypted_value

        return result

    def get_output_schema(self) -> dict[str, Any]:
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

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool that needs the environment variable",
                },
                "variable_name": {
                    "type": "string",
                    "description": "Name of the environment variable to retrieve",
                },
            },
            "required": ["tool_name", "variable_name"],
        }


class RequestEnvVarTool(AgentTool):
    """
    Tool for requesting missing environment variables from the user.

    This tool triggers a human-in-the-loop interaction where the agent
    asks the user to provide missing environment variable values. The
    values are then encrypted and stored in the database.

    Usage:
        request_env = RequestEnvVarTool(hitl_handler, repository, encryption_service, ...)
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
        hitl_handler: RayHITLHandler | None = None,
        repository: ToolEnvironmentVariableRepositoryPort | None = None,
        encryption_service: EncryptionService | None = None,
        event_publisher: Callable[[dict[str, Any]], None] | None = None,
        tenant_id: str | None = None,
        project_id: str | None = None,
        session_factory: Any | None = None,
    ) -> None:
        """
        Initialize the request env var tool.

        Args:
            hitl_handler: RayHITLHandler instance (required for execution)
            repository: Repository for env var persistence (optional if session_factory provided)
            encryption_service: Service for encryption (defaults to singleton)
            event_publisher: Function to publish SSE events (optional, handler emits SSE)
            tenant_id: Current tenant ID (can be set later via context)
            project_id: Current project ID (can be set later via context)
            session_factory: Async session factory for creating database sessions
        """
        super().__init__(
            name="request_env_var",
            description=(
                "Request environment variables from the user when they are missing. "
                "This will prompt the user to input the required values which will "
                "be securely stored for future use."
            ),
        )
        self._hitl_handler = hitl_handler
        self._repository = repository
        self._encryption_service = encryption_service or get_encryption_service()
        self._event_publisher = event_publisher
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._session_factory = session_factory

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool that needs the environment variables",
                },
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "variable_name": {
                                "type": "string",
                                "description": "Name of the environment variable (e.g., API_KEY)",
                            },
                            "display_name": {
                                "type": "string",
                                "description": "Human-readable name to display to the user",
                            },
                            "description": {
                                "type": "string",
                                "description": "Description of what this variable is for",
                            },
                            "input_type": {
                                "type": "string",
                                "enum": ["text", "password", "textarea"],
                                "description": "Type of input field",
                                "default": "text",
                            },
                            "is_required": {
                                "type": "boolean",
                                "description": "Whether this variable is required",
                                "default": True,
                            },
                            "is_secret": {
                                "type": "boolean",
                                "description": "Whether this is a secret value that should be encrypted",
                                "default": True,
                            },
                        },
                        "required": ["variable_name"],
                    },
                    "description": "List of environment variable fields to request from the user",
                },
                "context": {
                    "type": "object",
                    "description": "Additional context information to show the user",
                },
                "save_to_project": {
                    "type": "boolean",
                    "description": "If true, save variables at project level; otherwise tenant level",
                    "default": False,
                },
            },
            "required": ["tool_name", "fields"],
        }

    def set_context(
        self,
        tenant_id: str,
        project_id: str | None = None,
        event_publisher: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Set the tenant, project, and event publisher context."""
        self._tenant_id = tenant_id
        self._project_id = project_id
        if event_publisher:
            self._event_publisher = event_publisher

    def set_hitl_handler(self, handler: RayHITLHandler) -> None:
        """Set the HITL handler (for late binding)."""
        self._hitl_handler = handler

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

    async def execute(  # type: ignore[override]
        self,
        tool_name: str,
        fields: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
        save_to_project: bool = False,
        timeout: float = 600.0,
    ) -> str:
        """
        Request environment variables from the user.

        Args:
            tool_name: Name of the tool that needs the variables
            fields: List of field specifications
            context: Additional context to display to the user
            save_to_project: If True, save to project level; else tenant level
            timeout: Maximum wait time in seconds

        Returns:
            JSON string with status and saved variables

        Raises:
            RuntimeError: If HITL handler not set
        """
        if not self.validate_args(tool_name=tool_name, fields=fields):
            return json.dumps(
                {
                    "status": "error",
                    "message": "Invalid arguments or missing tenant context",
                }
            )

        if self._hitl_handler is None:
            raise RuntimeError("HITL handler not set. Call set_hitl_handler() first.")

        # Convert fields to format expected by RayHITLHandler
        hitl_fields = []
        field_specs = {}  # Track original specs for saving
        for f in fields:
            # Map old field format to new format
            input_type = f.get("input_type", "text")
            is_secret = f.get("is_secret", True)
            if input_type == "password" or is_secret:
                input_type = "password"

            hitl_field = {
                "name": f["variable_name"],
                "label": f.get("display_name", f["variable_name"]),
                "description": f.get("description"),
                "required": f.get("is_required", True),
                "secret": is_secret,
                "input_type": input_type,
                "default_value": f.get("default_value"),
                "placeholder": f.get("placeholder"),
            }
            hitl_fields.append(hitl_field)

            # Store original spec for later use
            field_specs[f["variable_name"]] = {
                "description": f.get("description"),
                "is_required": f.get("is_required", True),
                "is_secret": is_secret,
            }

        logger.info(f"Requesting env vars for tool={tool_name}: {[f['name'] for f in hitl_fields]}")

        try:
            # Use RayHITLHandler to request env vars
            values = await self._hitl_handler.request_env_vars(
                tool_name=tool_name,
                fields=hitl_fields,
                message=context.get("message") if context else None,
                timeout_seconds=timeout,
                allow_save=True,
            )

            # If empty or cancelled, return appropriate response
            if not values:
                return json.dumps(
                    {
                        "status": "cancelled",
                        "message": "User did not provide the requested environment variables",
                    }
                )

            # Encrypt and save each value
            saved_vars = []
            scope = (
                EnvVarScope.PROJECT if save_to_project and self._project_id else EnvVarScope.TENANT
            )
            project_id = self._project_id if save_to_project else None

            # Save env vars to database
            saved_vars = await self._save_env_vars(
                tool_name=tool_name,
                values=values,
                field_specs=field_specs,
                scope=scope,
                project_id=project_id,
            )

            return json.dumps(
                {
                    "status": "success",
                    "saved_variables": saved_vars,
                    "scope": scope.value,
                }
            )

        except TimeoutError:
            logger.warning(f"Env var request for {tool_name} timed out")
            return json.dumps(
                {
                    "status": "timeout",
                    "message": "User did not provide the requested environment variables in time",
                }
            )

        except Exception as e:
            logger.error(f"Error in env var request for {tool_name}: {e}")
            return json.dumps(
                {
                    "status": "error",
                    "message": str(e),
                }
            )

    async def _save_env_vars(
        self,
        tool_name: str,
        values: dict[str, str],
        field_specs: dict[str, dict[str, Any]],
        scope: EnvVarScope,
        project_id: str | None,
    ) -> list[str]:
        """Encrypt and persist env var values, returning saved variable names."""
        saved_vars: list[str] = []

        if self._session_factory:
            from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
                SqlToolEnvironmentVariableRepository,
            )

            async with self._session_factory() as db_session:
                repository = SqlToolEnvironmentVariableRepository(db_session)
                await self._upsert_env_vars(
                    repository, tool_name, values, field_specs, scope, project_id, saved_vars
                )
                await db_session.commit()
        elif self._repository:
            await self._upsert_env_vars(
                self._repository, tool_name, values, field_specs, scope, project_id, saved_vars
            )

        return saved_vars

    async def _upsert_env_vars(
        self,
        repository: Any,
        tool_name: str,
        values: dict[str, str],
        field_specs: dict[str, dict[str, Any]],
        scope: EnvVarScope,
        project_id: str | None,
        saved_vars: list[str],
    ) -> None:
        """Encrypt and upsert each env var value to the given repository."""
        assert self._tenant_id is not None, "tenant_id is required"
        for var_name, var_value in values.items():
            if not var_value:
                continue
            spec = field_specs.get(var_name, {})
            encrypted_value = self._encryption_service.encrypt(var_value)
            env_var = ToolEnvironmentVariable(
                tenant_id=self._tenant_id,
                project_id=project_id,
                tool_name=tool_name,
                variable_name=var_name,
                encrypted_value=encrypted_value,
                description=spec.get("description"),
                is_required=spec.get("is_required", True),
                is_secret=spec.get("is_secret", True),
                scope=scope,
            )
            await repository.upsert(env_var)
            saved_vars.append(var_name)
            logger.info(f"Saved env var: {tool_name}/{var_name}")

    def get_output_schema(self) -> dict[str, Any]:
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
        repository: ToolEnvironmentVariableRepositoryPort | None = None,
        encryption_service: EncryptionService | None = None,
        tenant_id: str | None = None,
        project_id: str | None = None,
        session_factory: Any | None = None,
    ) -> None:
        """
        Initialize the check env vars tool.

        Args:
            repository: Repository for env var persistence (optional if session_factory provided)
            encryption_service: Service for decryption (defaults to singleton)
            tenant_id: Current tenant ID (can be set later via context)
            project_id: Current project ID (can be set later via context)
            session_factory: Async session factory for creating database sessions
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
        self._session_factory = session_factory

    def set_context(self, tenant_id: str, project_id: str | None = None) -> None:
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

    async def execute(  # type: ignore[override]
        self,
        tool_name: str,
        required_vars: list[str],
    ) -> str:
        """
        Check if required environment variables are available.

        Args:
            tool_name: Name of the tool
            required_vars: List of required variable names

        Returns:
            JSON string with available and missing variables
        """
        if not self.validate_args(tool_name=tool_name, required_vars=required_vars):
            return json.dumps(
                {
                    "status": "error",
                    "message": "Invalid arguments or missing tenant context",
                }
            )

        assert self._tenant_id is not None
        tenant_id: str = self._tenant_id
        try:
            # If we have a session_factory, create a new session for this operation
            # This is needed when running in worker context where sessions aren't managed externally
            if self._session_factory:
                from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
                    SqlToolEnvironmentVariableRepository,
                )

                async with self._session_factory() as db_session:
                    repository = SqlToolEnvironmentVariableRepository(db_session)
                    env_vars = await repository.get_for_tool(
                        tenant_id=tenant_id,
                        tool_name=tool_name,
                        project_id=self._project_id,
                    )
            else:
                # Use injected repository (for API context with managed sessions)
                env_vars = await self._repository.get_for_tool(  # type: ignore[union-attr]
                    tenant_id=tenant_id,
                    tool_name=tool_name,
                    project_id=self._project_id,
                )

            configured_vars = {ev.variable_name for ev in env_vars}
            available = [v for v in required_vars if v in configured_vars]
            missing = [v for v in required_vars if v not in configured_vars]

            return json.dumps(
                {
                    "status": "checked",
                    "tool_name": tool_name,
                    "available": available,
                    "missing": missing,
                    "all_available": len(missing) == 0,
                }
            )

        except Exception as e:
            logger.error(f"Error checking env vars for {tool_name}: {e}")
            return json.dumps(
                {
                    "status": "error",
                    "message": str(e),
                }
            )

    def get_output_schema(self) -> dict[str, Any]:
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

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool to check environment variables for",
                },
                "required_vars": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of required variable names to check",
                },
            },
            "required": ["tool_name", "required_vars"],
        }
