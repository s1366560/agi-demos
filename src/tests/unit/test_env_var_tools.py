"""Unit tests for Environment Variable Tools.

Tests the get_env_var_tool and check_env_vars_tool decorator-based tools
for managing agent tool environment variables.

NOTE: RequestEnvVarTool is now tested via HITL strategy tests.
See src/tests/unit/agent/test_temporal_hitl_handler.py for HITL-related tests.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.tool_environment_variable import (
    EnvVarScope,
    ToolEnvironmentVariable,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.env_var_tools import (
    check_env_vars_tool,
    configure_env_var_tools,
    get_env_var_tool,
)
from src.infrastructure.agent.tools.result import ToolResult


@pytest.fixture
def tool_ctx():
    """Create a ToolContext for testing."""
    return ToolContext(
        session_id="sess-1",
        message_id="msg-1",
        call_id="call-1",
        agent_name="test-agent",
        conversation_id="conv-1",
    )


@pytest.fixture(autouse=True)
def _reset_env_var_state():
    """Reset all module-level globals between tests."""
    from src.infrastructure.agent.tools import env_var_tools as mod

    mod._env_var_repo = None
    mod._encryption_svc = None
    mod._hitl_handler_ref = None
    mod._session_factory_ref = None
    mod._tenant_id_ref = None
    mod._project_id_ref = None
    mod._event_publisher_ref = None
    yield
    mod._env_var_repo = None
    mod._encryption_svc = None
    mod._hitl_handler_ref = None
    mod._session_factory_ref = None
    mod._tenant_id_ref = None
    mod._project_id_ref = None
    mod._event_publisher_ref = None


class TestGetEnvVarTool:
    """Tests for get_env_var_tool."""

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_encryption_service(self):
        """Create a mock encryption service."""
        service = MagicMock()
        service.decrypt.return_value = "decrypted-value"
        return service

    def test_tool_initialization(self):
        """Test tool is initialized with correct name and description."""
        assert get_env_var_tool.name == "get_env_var"
        assert "environment variable" in get_env_var_tool.description.lower()

    async def test_missing_tenant_returns_error(
        self, tool_ctx, mock_repository, mock_encryption_service
    ):
        """Test that calling without tenant_id returns an error ToolResult."""
        # Configure WITHOUT tenant_id
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
        )

        result = await get_env_var_tool.execute(tool_ctx, tool_name="test", variable_name="VAR")

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert (
            "missing tenant" in result_data["message"].lower()
            or "invalid" in result_data["message"].lower()
        )

    async def test_execute_found(self, tool_ctx, mock_repository, mock_encryption_service):
        """Test getting an existing env var."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )

        env_var = ToolEnvironmentVariable(
            id="ev-123",
            tenant_id="tenant-123",
            tool_name="web_search",
            variable_name="API_KEY",
            encrypted_value="encrypted-value",
            is_secret=True,
            scope=EnvVarScope.TENANT,
        )
        mock_repository.get.return_value = env_var

        result = await get_env_var_tool.execute(
            tool_ctx, tool_name="web_search", variable_name="API_KEY"
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "found"
        assert result_data["value"] == "decrypted-value"
        assert result_data["is_secret"] is True
        mock_encryption_service.decrypt.assert_called_once_with("encrypted-value")

    async def test_execute_not_found(self, tool_ctx, mock_repository, mock_encryption_service):
        """Test getting a non-existent env var."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )
        mock_repository.get.return_value = None

        result = await get_env_var_tool.execute(
            tool_ctx, tool_name="web_search", variable_name="MISSING_KEY"
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "not_found"
        assert "MISSING_KEY" in result_data["message"]

    async def test_execute_error_returns_error_result(
        self, tool_ctx, mock_repository, mock_encryption_service
    ):
        """Test that a repository exception returns an error ToolResult."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )
        mock_repository.get.side_effect = RuntimeError("DB connection failed")

        result = await get_env_var_tool.execute(
            tool_ctx, tool_name="web_search", variable_name="API_KEY"
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "DB connection failed" in result_data["message"]


class TestCheckEnvVarsTool:
    """Tests for check_env_vars_tool."""

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_encryption_service(self):
        """Create a mock encryption service."""
        return MagicMock()

    def test_tool_initialization(self):
        """Test tool is initialized with correct name and description."""
        assert check_env_vars_tool.name == "check_env_vars"
        assert "environment variable" in check_env_vars_tool.description.lower()

    async def test_execute_all_available(self, tool_ctx, mock_repository, mock_encryption_service):
        """Test checking vars when all are available."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )

        env_vars = [
            ToolEnvironmentVariable(
                id="1",
                tenant_id="tenant-123",
                tool_name="web_search",
                variable_name="API_KEY",
                encrypted_value="enc",
            ),
            ToolEnvironmentVariable(
                id="2",
                tenant_id="tenant-123",
                tool_name="web_search",
                variable_name="ENDPOINT",
                encrypted_value="enc",
            ),
        ]
        mock_repository.get_for_tool.return_value = env_vars

        result = await check_env_vars_tool.execute(
            tool_ctx, tool_name="web_search", required_vars=["API_KEY", "ENDPOINT"]
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "checked"
        assert result_data["all_available"] is True
        assert len(result_data["available"]) == 2
        assert len(result_data["missing"]) == 0

    async def test_execute_some_missing(self, tool_ctx, mock_repository, mock_encryption_service):
        """Test checking vars when some are missing."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )

        env_vars = [
            ToolEnvironmentVariable(
                id="1",
                tenant_id="tenant-123",
                tool_name="web_search",
                variable_name="API_KEY",
                encrypted_value="enc",
            ),
        ]
        mock_repository.get_for_tool.return_value = env_vars

        result = await check_env_vars_tool.execute(
            tool_ctx,
            tool_name="web_search",
            required_vars=["API_KEY", "SECRET_KEY", "ENDPOINT"],
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "checked"
        assert result_data["all_available"] is False
        assert result_data["available"] == ["API_KEY"]
        assert set(result_data["missing"]) == {"SECRET_KEY", "ENDPOINT"}

    async def test_missing_tenant_returns_error(
        self, tool_ctx, mock_repository, mock_encryption_service
    ):
        """Test that calling without tenant_id returns an error ToolResult."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
        )

        result = await check_env_vars_tool.execute(
            tool_ctx, tool_name="web_search", required_vars=["API_KEY"]
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"

    async def test_execute_error_returns_error_result(
        self, tool_ctx, mock_repository, mock_encryption_service
    ):
        """Test that a repository exception returns an error ToolResult."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )
        mock_repository.get_for_tool.side_effect = RuntimeError("DB error")

        result = await check_env_vars_tool.execute(
            tool_ctx, tool_name="web_search", required_vars=["API_KEY"]
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "DB error" in result_data["message"]


class TestToolEnvironmentVariableDomainModel:
    """Tests for ToolEnvironmentVariable domain model."""

    def test_create_tenant_level_var(self):
        """Test creating a tenant-level env var."""
        env_var = ToolEnvironmentVariable(
            tenant_id="tenant-123",
            tool_name="web_search",
            variable_name="API_KEY",
            encrypted_value="encrypted-value",
        )

        assert env_var.tenant_id == "tenant-123"
        assert env_var.project_id is None
        assert env_var.scope == EnvVarScope.TENANT

    def test_create_project_level_var(self):
        """Test creating a project-level env var."""
        env_var = ToolEnvironmentVariable(
            tenant_id="tenant-123",
            project_id="project-456",
            tool_name="web_search",
            variable_name="API_KEY",
            encrypted_value="encrypted-value",
            scope=EnvVarScope.PROJECT,
        )

        assert env_var.project_id == "project-456"
        assert env_var.scope == EnvVarScope.PROJECT

    def test_project_id_sets_scope_automatically(self):
        """Test that setting project_id auto-sets scope to PROJECT."""
        env_var = ToolEnvironmentVariable(
            tenant_id="tenant-123",
            project_id="project-456",
            tool_name="web_search",
            variable_name="API_KEY",
            encrypted_value="encrypted-value",
            scope=EnvVarScope.TENANT,  # Wrong scope, should be corrected
        )

        assert env_var.scope == EnvVarScope.PROJECT

    def test_update_value(self):
        """Test updating the encrypted value."""
        env_var = ToolEnvironmentVariable(
            tenant_id="tenant-123",
            tool_name="web_search",
            variable_name="API_KEY",
            encrypted_value="old-value",
        )

        original_time = env_var.updated_at
        env_var.update_value("new-encrypted-value")

        assert env_var.encrypted_value == "new-encrypted-value"
        assert env_var.updated_at is not None
        assert env_var.updated_at != original_time

    def test_scoped_key_tenant_level(self):
        """Test scoped key for tenant-level var."""
        env_var = ToolEnvironmentVariable(
            tenant_id="tenant-123",
            tool_name="web_search",
            variable_name="API_KEY",
            encrypted_value="value",
        )

        assert env_var.scoped_key == "tenant-123::web_search:API_KEY"

    def test_scoped_key_project_level(self):
        """Test scoped key for project-level var."""
        env_var = ToolEnvironmentVariable(
            tenant_id="tenant-123",
            project_id="project-456",
            tool_name="web_search",
            variable_name="API_KEY",
            encrypted_value="value",
        )

        assert env_var.scoped_key == "tenant-123:project-456:web_search:API_KEY"

    def test_validation_errors(self):
        """Test that validation errors are raised for missing fields."""
        with pytest.raises(ValueError, match="tenant_id"):
            ToolEnvironmentVariable(
                tenant_id="",
                tool_name="test",
                variable_name="VAR",
                encrypted_value="val",
            )

        with pytest.raises(ValueError, match="tool_name"):
            ToolEnvironmentVariable(
                tenant_id="tenant",
                tool_name="",
                variable_name="VAR",
                encrypted_value="val",
            )
