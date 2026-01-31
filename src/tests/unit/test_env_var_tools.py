"""Unit tests for Environment Variable Tools.

Tests the GetEnvVarTool, RequestEnvVarTool, and CheckEnvVarsTool
for managing agent tool environment variables.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.tool_environment_variable import (
    EnvVarScope,
    ToolEnvironmentVariable,
)
from src.infrastructure.agent.tools.env_var_tools import (
    CheckEnvVarsTool,
    EnvVarField,
    EnvVarInputType,
    EnvVarManager,
    EnvVarRequest,
    GetEnvVarTool,
    RequestEnvVarTool,
)


class TestEnvVarField:
    """Tests for EnvVarField data class."""

    def test_basic_field_creation(self):
        """Test creating a basic env var field."""
        field = EnvVarField(
            variable_name="API_KEY",
            display_name="API Key",
        )
        assert field.variable_name == "API_KEY"
        assert field.display_name == "API Key"
        assert field.is_required is True
        assert field.is_secret is True
        assert field.input_type == EnvVarInputType.TEXT

    def test_field_to_dict(self):
        """Test converting field to dict for SSE."""
        field = EnvVarField(
            variable_name="SECRET_TOKEN",
            display_name="Secret Token",
            description="Your secret API token",
            input_type=EnvVarInputType.PASSWORD,
            is_required=True,
            is_secret=True,
        )
        result = field.to_dict()

        assert result["variable_name"] == "SECRET_TOKEN"
        assert result["display_name"] == "Secret Token"
        assert result["description"] == "Your secret API token"
        assert result["input_type"] == "password"
        assert result["is_required"] is True
        assert result["is_secret"] is True


class TestEnvVarManager:
    """Tests for EnvVarManager."""

    @pytest.fixture
    def manager(self):
        """Create a fresh EnvVarManager instance."""
        return EnvVarManager()

    @pytest.mark.asyncio
    async def test_respond_to_request(self, manager):
        """Test responding to an env var request."""
        # Create a request
        request_id = "test-123"
        request = EnvVarRequest(
            request_id=request_id,
            tool_name="web_search",
            fields=[EnvVarField("API_KEY", "API Key")],
        )

        async with manager._lock:
            manager._pending_requests[request_id] = request

        # Respond
        values = {"API_KEY": "secret-value"}
        success = await manager.respond(request_id, values)

        assert success is True
        assert request.future.done()
        assert await request.future == values

    @pytest.mark.asyncio
    async def test_respond_to_nonexistent_request(self, manager):
        """Test responding to a request that doesn't exist."""
        success = await manager.respond("nonexistent", {"KEY": "value"})
        assert success is False

    @pytest.mark.asyncio
    async def test_cancel_request(self, manager):
        """Test cancelling a request."""
        request_id = "test-cancel"
        request = EnvVarRequest(
            request_id=request_id,
            tool_name="test_tool",
            fields=[],
        )

        async with manager._lock:
            manager._pending_requests[request_id] = request

        success = await manager.cancel_request(request_id)

        assert success is True
        assert request_id not in manager._pending_requests
        assert request.future.cancelled()

    def test_get_pending_requests(self, manager):
        """Test getting all pending requests."""
        request1 = EnvVarRequest("r1", "tool1", [])
        request2 = EnvVarRequest("r2", "tool2", [])

        manager._pending_requests = {"r1": request1, "r2": request2}

        pending = manager.get_pending_requests()

        assert len(pending) == 2


class TestGetEnvVarTool:
    """Tests for GetEnvVarTool."""

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

    @pytest.fixture
    def get_env_tool(self, mock_repository, mock_encryption_service):
        """Create GetEnvVarTool with mocked dependencies."""
        tool = GetEnvVarTool(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )
        return tool

    def test_tool_initialization(self, get_env_tool):
        """Test tool is initialized with correct name and description."""
        assert get_env_tool.name == "get_env_var"
        assert "environment variable" in get_env_tool.description.lower()

    def test_validate_args_missing_tenant(self, mock_repository, mock_encryption_service):
        """Test validation fails without tenant_id."""
        tool = GetEnvVarTool(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
        )
        assert tool.validate_args(tool_name="test", variable_name="VAR") is False

    def test_validate_args_missing_tool_name(self, get_env_tool):
        """Test validation fails without tool_name."""
        assert get_env_tool.validate_args(variable_name="VAR") is False

    def test_validate_args_valid(self, get_env_tool):
        """Test validation passes with all required args."""
        assert (
            get_env_tool.validate_args(
                tool_name="web_search",
                variable_name="API_KEY",
            )
            is True
        )

    @pytest.mark.asyncio
    async def test_execute_found(self, get_env_tool, mock_repository, mock_encryption_service):
        """Test getting an existing env var."""
        # Setup mock
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

        result = await get_env_tool.execute(
            tool_name="web_search",
            variable_name="API_KEY",
        )

        result_data = json.loads(result)
        assert result_data["status"] == "found"
        assert result_data["value"] == "decrypted-value"
        assert result_data["is_secret"] is True
        mock_encryption_service.decrypt.assert_called_once_with("encrypted-value")

    @pytest.mark.asyncio
    async def test_execute_not_found(self, get_env_tool, mock_repository):
        """Test getting a non-existent env var."""
        mock_repository.get.return_value = None

        result = await get_env_tool.execute(
            tool_name="web_search",
            variable_name="MISSING_KEY",
        )

        result_data = json.loads(result)
        assert result_data["status"] == "not_found"
        assert "MISSING_KEY" in result_data["message"]

    @pytest.mark.asyncio
    async def test_get_all_for_tool(self, get_env_tool, mock_repository, mock_encryption_service):
        """Test getting all env vars for a tool."""
        env_vars = [
            ToolEnvironmentVariable(
                id="ev-1",
                tenant_id="tenant-123",
                tool_name="web_search",
                variable_name="API_KEY",
                encrypted_value="enc-key",
            ),
            ToolEnvironmentVariable(
                id="ev-2",
                tenant_id="tenant-123",
                tool_name="web_search",
                variable_name="ENDPOINT",
                encrypted_value="enc-endpoint",
            ),
        ]
        mock_repository.get_for_tool.return_value = env_vars

        result = await get_env_tool.get_all_for_tool("web_search")

        assert len(result) == 2
        assert "API_KEY" in result
        assert "ENDPOINT" in result


class TestRequestEnvVarTool:
    """Tests for RequestEnvVarTool."""

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository."""
        repo = AsyncMock()
        repo.upsert.return_value = MagicMock()
        return repo

    @pytest.fixture
    def mock_encryption_service(self):
        """Create a mock encryption service."""
        service = MagicMock()
        service.encrypt.return_value = "encrypted-value"
        return service

    @pytest.fixture
    def mock_event_publisher(self):
        """Create a mock event publisher."""
        return MagicMock()

    @pytest.fixture
    def request_env_tool(self, mock_repository, mock_encryption_service, mock_event_publisher):
        """Create RequestEnvVarTool with mocked dependencies."""
        manager = EnvVarManager()
        tool = RequestEnvVarTool(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            manager=manager,
            event_publisher=mock_event_publisher,
            tenant_id="tenant-123",
            project_id="project-456",
        )
        return tool

    def test_tool_initialization(self, request_env_tool):
        """Test tool is initialized with correct name and description."""
        assert request_env_tool.name == "request_env_var"
        assert "environment variable" in request_env_tool.description.lower()

    def test_validate_args_valid(self, request_env_tool):
        """Test validation passes with valid args."""
        assert (
            request_env_tool.validate_args(
                tool_name="web_search",
                fields=[{"variable_name": "API_KEY", "display_name": "API Key"}],
            )
            is True
        )

    def test_validate_args_empty_fields(self, request_env_tool):
        """Test validation fails with empty fields."""
        assert (
            request_env_tool.validate_args(
                tool_name="web_search",
                fields=[],
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_execute_emits_event(
        self,
        request_env_tool,
        mock_event_publisher,
        mock_repository,
        mock_encryption_service,
    ):
        """Test that executing the tool emits an SSE event."""

        # Create a background task that will respond after a short delay
        async def respond_later():
            await asyncio.sleep(0.05)
            for req_id in list(request_env_tool._manager._pending_requests.keys()):
                await request_env_tool._manager.respond(req_id, {"API_KEY": "user-provided-value"})

        asyncio.create_task(respond_later())

        result = await request_env_tool.execute(
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY", "display_name": "API Key"}],
            timeout=1.0,
        )

        # Verify events were published (first call is request, second is provided)
        assert mock_event_publisher.call_count >= 1
        first_call_args = mock_event_publisher.call_args_list[0][0][0]
        assert first_call_args["type"] == "env_var_requested"

        # Verify the value was encrypted and saved
        result_data = json.loads(result)
        assert result_data["status"] == "success"
        assert "API_KEY" in result_data["saved_variables"]
        mock_encryption_service.encrypt.assert_called_with("user-provided-value")

    @pytest.mark.asyncio
    async def test_execute_timeout(self, request_env_tool):
        """Test that execution times out when no response."""
        result = await request_env_tool.execute(
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY", "display_name": "API Key"}],
            timeout=0.1,  # Very short timeout
        )

        result_data = json.loads(result)
        assert result_data["status"] == "timeout"


class TestCheckEnvVarsTool:
    """Tests for CheckEnvVarsTool."""

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_encryption_service(self):
        """Create a mock encryption service."""
        return MagicMock()

    @pytest.fixture
    def check_env_tool(self, mock_repository, mock_encryption_service):
        """Create CheckEnvVarsTool with mocked dependencies."""
        tool = CheckEnvVarsTool(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )
        return tool

    def test_tool_initialization(self, check_env_tool):
        """Test tool is initialized with correct name and description."""
        assert check_env_tool.name == "check_env_vars"
        assert "environment variable" in check_env_tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_all_available(self, check_env_tool, mock_repository):
        """Test checking vars when all are available."""
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

        result = await check_env_tool.execute(
            tool_name="web_search",
            required_vars=["API_KEY", "ENDPOINT"],
        )

        result_data = json.loads(result)
        assert result_data["status"] == "checked"
        assert result_data["all_available"] is True
        assert len(result_data["available"]) == 2
        assert len(result_data["missing"]) == 0

    @pytest.mark.asyncio
    async def test_execute_some_missing(self, check_env_tool, mock_repository):
        """Test checking vars when some are missing."""
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

        result = await check_env_tool.execute(
            tool_name="web_search",
            required_vars=["API_KEY", "SECRET_KEY", "ENDPOINT"],
        )

        result_data = json.loads(result)
        assert result_data["status"] == "checked"
        assert result_data["all_available"] is False
        assert result_data["available"] == ["API_KEY"]
        assert set(result_data["missing"]) == {"SECRET_KEY", "ENDPOINT"}


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
