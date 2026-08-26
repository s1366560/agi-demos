"""Unit tests for Environment Variable Tools.

Tests the get_env_var_tool and check_env_vars_tool decorator-based tools
for managing agent tool environment variables.

NOTE: RequestEnvVarTool is now tested via HITL strategy tests.
See src/tests/unit/agent/test_temporal_hitl_handler.py for HITL-related tests.
"""

import asyncio
import json
import logging
from typing import Any
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
    make_env_var_tools,
    request_env_var_tool,
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
        tenant_id="tenant-123",
        project_id="project-456",
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

    async def test_bound_runtimes_are_isolated_during_interleaved_reads(
        self,
        tool_ctx: ToolContext,
    ) -> None:
        first_entered = asyncio.Event()
        release_first = asyncio.Event()

        class _Repository:
            def __init__(self, marker: str, *, wait: bool) -> None:
                self._marker = marker
                self._wait = wait

            async def get(self, **kwargs: object) -> ToolEnvironmentVariable:
                if self._wait:
                    first_entered.set()
                    await release_first.wait()
                else:
                    await first_entered.wait()
                    release_first.set()
                return ToolEnvironmentVariable(
                    tenant_id=str(kwargs["tenant_id"]),
                    project_id=str(kwargs["project_id"]),
                    tool_name=str(kwargs["tool_name"]),
                    variable_name=str(kwargs["variable_name"]),
                    encrypted_value=self._marker,
                    is_secret=True,
                    scope=EnvVarScope.PROJECT,
                )

        class _EncryptionService:
            @staticmethod
            def decrypt(value: str) -> str:
                return f"value-{value}"

        first_tools = make_env_var_tools(
            repository=_Repository("generation-a", wait=True),
            encryption_service=_EncryptionService(),
        )
        second_tools = make_env_var_tools(
            repository=_Repository("generation-b", wait=False),
            encryption_service=_EncryptionService(),
        )
        first_task = asyncio.create_task(
            first_tools["get_env_var"].execute(
                tool_ctx,
                tool_name="runtime_test",
                variable_name="RUNTIME_VALUE",
            )
        )
        await first_entered.wait()
        second_result = await second_tools["get_env_var"].execute(
            tool_ctx,
            tool_name="runtime_test",
            variable_name="RUNTIME_VALUE",
        )
        first_result = await first_task

        assert json.loads(first_result.output)["value"] == "value-generation-a"
        assert json.loads(second_result.output)["value"] == "value-generation-b"

    async def test_missing_tenant_returns_error(
        self, tool_ctx, mock_repository, mock_encryption_service
    ):
        """Test that calling without tenant_id returns an error ToolResult."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-global",
            project_id="project-global",
        )
        tool_ctx.tenant_id = ""
        tool_ctx.project_id = ""

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

    async def test_execute_found_does_not_log_decrypted_value(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        caplog,
    ):
        """Retrieved env-var logs must never include decrypted values."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )

        env_var = ToolEnvironmentVariable(
            id="ev-124",
            tenant_id="tenant-123",
            tool_name="web_search",
            variable_name="PUBLIC_ENDPOINT",
            encrypted_value="encrypted-endpoint",
            is_secret=False,
            scope=EnvVarScope.TENANT,
        )
        mock_repository.get.return_value = env_var
        mock_encryption_service.decrypt.return_value = "https://visible.example.com/token"

        with caplog.at_level(logging.INFO):
            result = await get_env_var_tool.execute(
                tool_ctx,
                tool_name="web_search",
                variable_name="PUBLIC_ENDPOINT",
            )

        assert isinstance(result, ToolResult)
        assert "https://visible.example.com/token" not in caplog.text
        assert "Retrieved env var web_search/PUBLIC_ENDPOINT" in caplog.text

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

    async def test_invalid_variable_name_returns_error(
        self, tool_ctx, mock_repository, mock_encryption_service
    ):
        """Secret-like or malformed variable names should be rejected."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )

        result = await get_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            variable_name="AKIAIOSFODNN7EXAMPLE",
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "invalid" in result_data["message"].lower()

    @pytest.mark.parametrize(
        "variable_name",
        ["AKIA_CONFIG", "SK_TEST_KEY", "GHP_TOKEN", "GITHUB_PAT_TOKEN"],
    )
    async def test_secret_like_prefix_variable_name_is_allowed(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        variable_name: str,
    ):
        """Normal env-var names must not be rejected only because of their prefixes."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )
        mock_repository.get.return_value = None

        result = await get_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            variable_name=variable_name,
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is False
        result_data = json.loads(result.output)
        assert result_data["status"] == "not_found"

    async def test_tool_context_identity_overrides_global_scope(
        self, tool_ctx, mock_repository, mock_encryption_service
    ):
        """Per-call ToolContext identity must win over later global reconfiguration."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-global",
            project_id="project-global",
        )
        tool_ctx.tenant_id = "tenant-ctx"
        tool_ctx.project_id = "project-ctx"
        mock_repository.get.return_value = None

        await get_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            variable_name="API_KEY",
        )

        assert mock_repository.get.await_args.kwargs["tenant_id"] == "tenant-ctx"
        assert mock_repository.get.await_args.kwargs["project_id"] == "project-ctx"


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
            tenant_id="tenant-global",
            project_id="project-global",
        )
        tool_ctx.tenant_id = ""
        tool_ctx.project_id = ""

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

    async def test_invalid_required_var_name_returns_error(
        self, tool_ctx, mock_repository, mock_encryption_service
    ):
        """Malformed required var names should be rejected before echoing them."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            tenant_id="tenant-123",
            project_id="project-456",
        )

        result = await check_env_vars_tool.execute(
            tool_ctx,
            tool_name="web_search",
            required_vars=["API_KEY", "AKIAIOSFODNN7EXAMPLE"],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "invalid" in result_data["message"].lower()


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


class TestRequestEnvVarTool:
    """Tests for request_env_var_tool."""

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository."""
        repo = AsyncMock()
        repo.upsert = AsyncMock()
        return repo

    @pytest.fixture
    def mock_encryption_service(self):
        """Create a mock encryption service."""
        service = MagicMock()
        service.encrypt.return_value = "encrypted-value"
        return service

    @pytest.fixture
    def mock_hitl_handler(self):
        """Create a mock HITL handler."""
        handler = AsyncMock()
        handler.request_env_vars = AsyncMock()
        return handler

    async def test_success_response_includes_scope_and_message(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Success responses should explain what was saved and where."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[
                {
                    "variable_name": "API_KEY",
                    "display_name": "API Key",
                    "description": "Credential for the search provider",
                }
            ],
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "success"
        assert result_data["scope"] == EnvVarScope.TENANT.value
        assert result_data["saved_variables"] == ["API_KEY"]
        assert "API_KEY" in result_data["message"]
        assert "tenant" in result_data["message"].lower()
        request_kwargs = mock_hitl_handler.request_env_vars.await_args.kwargs
        assert request_kwargs["context"]["save_scope"] == "tenant"
        assert "API_KEY" not in request_kwargs["context"]

    async def test_missing_tenant_returns_error_without_global_scope_fallback(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Env-var requests must not inherit tenant/project scope from global config."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-global",
            project_id="project-global",
        )
        tool_ctx.tenant_id = ""
        tool_ctx.project_id = ""

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        mock_hitl_handler.request_env_vars.assert_not_awaited()

    async def test_cancelled_response_mentions_requested_variables(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Cancelled requests should mention which variables are still needed."""
        mock_hitl_handler.request_env_vars.return_value = {"cancelled": True}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "cancelled"
        assert "API_KEY" in result_data["message"]

    async def test_empty_values_response_is_allowed_when_all_fields_optional(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """An explicit empty values payload is valid when no env-var field is required."""
        mock_hitl_handler.request_env_vars.return_value = {"values": {}}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "OPTIONAL_TOKEN", "is_required": False}],
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "success"
        assert result_data["saved_variables"] == []

    async def test_duplicate_variable_names_are_rejected(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Duplicate field names should fail before invoking HITL or persistence."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[
                {"variable_name": "API_KEY"},
                {"variable_name": "API_KEY", "display_name": "API key duplicate"},
            ],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "duplicate" in result.output.lower()
        mock_hitl_handler.request_env_vars.assert_not_awaited()

    async def test_missing_persistence_backend_is_rejected(
        self,
        tool_ctx,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Saving env vars requires a configured repository or session factory."""
        configure_env_var_tools(
            repository=None,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            session_factory=None,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "persistence is not configured" in result.output.lower()
        mock_hitl_handler.request_env_vars.assert_not_awaited()

    async def test_save_to_project_requires_project_context(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Project-scoped saves should fail fast without a project context."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )
        tool_ctx.project_id = ""

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
            save_to_project=True,
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "project" in result_data["message"].lower()

    async def test_request_context_drops_secret_like_values(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Only safe context keys should be forwarded to HITL storage/events."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
            context={
                "message": "Need credentials",
                "reason": "Authenticate with provider",
                "workflow": ["open settings", "paste API key"],
                "api_key": "should-not-leak",
            },
        )

        request_kwargs = mock_hitl_handler.request_env_vars.await_args.kwargs
        assert request_kwargs["message"] == "Need credentials"
        assert request_kwargs["context"]["reason"] == "Authenticate with provider"
        assert request_kwargs["context"]["workflow"] == ["open settings", "paste API key"]
        assert "api_key" not in request_kwargs["context"]

    async def test_request_context_overwrites_reserved_metadata_keys(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Caller-provided context must not spoof reserved HITL metadata."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )
        tool_ctx.project_id = "project-ctx"

        await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY", "display_name": "API & Key"}],
            context={
                "tool_name": "fake_tool",
                "requested_variables": ["WRONG"],
                "save_scope": "project",
                "project_id": "fake-project",
            },
        )

        request_kwargs = mock_hitl_handler.request_env_vars.await_args.kwargs
        assert request_kwargs["context"]["tool_name"] == "web_search"
        assert request_kwargs["context"]["requested_variables"] == ["API &amp; Key"]
        assert request_kwargs["context"]["save_scope"] == "tenant"
        assert "project_id" not in request_kwargs["context"]

    async def test_request_id_changes_with_effective_message(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Stable request ids should track the final message sent to HITL."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
            context={"message": "First prompt"},
        )
        first_request_id = mock_hitl_handler.request_env_vars.await_args.kwargs["request_id"]

        await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
            context={"message": "Second prompt"},
        )
        second_request_id = mock_hitl_handler.request_env_vars.await_args.kwargs["request_id"]

        assert first_request_id != second_request_id

    async def test_request_context_redacts_secret_like_string_values(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Freeform context/message text should not be forwarded into HITL persistence."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
            context={
                "message": "Use token sk-1234567890abcdefghijklmnop to authenticate",
                "reason": "Bearer sk-1234567890abcdefghijklmnop is required for provider auth",
                "workflow": [
                    "step-1",
                    "github_pat_1234567890abcdefghijklmnopqrstu",
                ],
            },
        )

        request_kwargs = mock_hitl_handler.request_env_vars.await_args.kwargs
        assert "sk-1234567890abcdefghijklmnop" not in request_kwargs["message"]
        assert "API_KEY" in request_kwargs["message"]
        assert "reason" not in request_kwargs["context"]
        assert "workflow" not in request_kwargs["context"]

    async def test_request_context_redacts_modern_secret_formats(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Newer provider token formats must also be stripped from HITL metadata."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
            context={
                "message": "Use sk-proj-abcdefghijklmnopqrstuvwxyz123456",
                "reason": "GitHub token ghs_abcdefghijklmnopqrstuvwxyz123456 is required",
                "workflow": ["open settings", "xoxc-12345-67890-abcdefghijk"],
            },
        )

        request_kwargs = mock_hitl_handler.request_env_vars.await_args.kwargs
        assert "sk-proj-" not in request_kwargs["message"]
        assert "reason" not in request_kwargs["context"]
        assert "workflow" not in request_kwargs["context"]

    async def test_blank_required_env_value_is_rejected(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Whitespace-only env values must not satisfy required fields."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "   "}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY", "is_required": True}],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "missing required" in result_data["message"].lower()

    async def test_project_scope_save_uses_captured_context_after_hitl_wait(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Long HITL waits must not reuse tenant/project globals from a later request."""
        from src.infrastructure.agent.tools import env_var_tools as mod

        async def mutate_context_during_wait(**_: object) -> dict[str, str]:
            configure_env_var_tools(
                repository=mock_repository,
                encryption_service=mock_encryption_service,
                hitl_handler=mock_hitl_handler,
                tenant_id="tenant-overwrite",
                project_id="project-overwrite",
            )
            return {"API_KEY": "secret"}

        mock_hitl_handler.request_env_vars.side_effect = mutate_context_during_wait
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
            project_id="project-456",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
            save_to_project=True,
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "success"
        assert result_data["scope"] == EnvVarScope.PROJECT.value
        saved_env_var = mock_repository.upsert.await_args.args[0]
        assert saved_env_var.tenant_id == "tenant-123"
        assert saved_env_var.project_id == "project-456"
        assert mod._tenant_id_ref == "tenant-overwrite"
        assert mod._project_id_ref == "project-overwrite"

    async def test_request_fields_redact_secret_like_metadata(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Field metadata forwarded to HITL must not leak secret-like values."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[
                {
                    "variable_name": "API_KEY",
                    "display_name": "sk-1234567890abcdefghijklmnop",
                    "description": "Use bearer sk-1234567890abcdefghijklmnop",
                    "placeholder": "Paste sk-1234567890abcdefghijklmnop here",
                    "default_value": "sk-1234567890abcdefghijklmnop",
                }
            ],
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "success"
        request_kwargs = mock_hitl_handler.request_env_vars.await_args.kwargs
        forwarded_field = request_kwargs["fields"][0]
        assert forwarded_field["label"] == "API_KEY"
        assert forwarded_field["description"] is None
        assert forwarded_field["placeholder"] is None
        assert forwarded_field["default_value"] is None
        saved_env_var = mock_repository.upsert.await_args.args[0]
        assert saved_env_var.description is None

    async def test_request_fields_preserve_safe_ui_metadata(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Safe HITL field metadata should remain available to the user-facing form."""
        mock_hitl_handler.request_env_vars.return_value = {"SEARCH_REGION": "eu-west-1"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[
                {
                    "variable_name": "SEARCH_REGION",
                    "display_name": "Search & Region",
                    "description": "Region used by the search provider",
                    "placeholder": "https://api.example.com?x=1&y=2",
                    "default_value": "A&B",
                    "is_secret": False,
                    "input_type": "text",
                }
            ],
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "success"
        request_kwargs = mock_hitl_handler.request_env_vars.await_args.kwargs
        assert "Search & Region" in request_kwargs["message"]
        forwarded_field = request_kwargs["fields"][0]
        assert forwarded_field["label"] == "Search &amp; Region"
        assert forwarded_field["description"] == "Region used by the search provider"
        assert forwarded_field["placeholder"] == "https://api.example.com?x=1&amp;y=2"
        assert forwarded_field["default_value"] == "A&amp;B"

    async def test_request_fields_drop_defaults_for_secret_inputs(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Secret HITL fields must never prefill or suggest values back to the user."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[
                {
                    "variable_name": "API_KEY",
                    "display_name": "Search API key",
                    "placeholder": "paste key here",
                    "default_value": "hunter2",
                    "is_secret": True,
                }
            ],
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "success"
        request_kwargs = mock_hitl_handler.request_env_vars.await_args.kwargs
        forwarded_field = request_kwargs["fields"][0]
        assert forwarded_field["label"] == "Search API key"
        assert forwarded_field["placeholder"] is None
        assert forwarded_field["default_value"] is None

    async def test_request_fields_redact_entity_encoded_secret_metadata(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Double-encoded secrets must be dropped before they reach HITL payloads."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[
                {
                    "variable_name": "API_KEY",
                    "display_name": "sk&amp;#45;1234567890abcdefghijklmnop",
                    "description": "Bearer&amp;#32;sk&amp;#45;1234567890abcdefghijklmnop",
                    "placeholder": "Paste&amp;#32;sk&amp;#45;1234567890abcdefghijklmnop&amp;#32;here",
                    "default_value": "sk&amp;#45;1234567890abcdefghijklmnop",
                }
            ],
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "success"
        request_kwargs = mock_hitl_handler.request_env_vars.await_args.kwargs
        forwarded_field = request_kwargs["fields"][0]
        assert forwarded_field["label"] == "API_KEY"
        assert forwarded_field["description"] is None
        assert forwarded_field["placeholder"] is None
        assert forwarded_field["default_value"] is None

    async def test_request_persists_safe_field_description(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Safe descriptions may be stored after HITL completes."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[
                {
                    "variable_name": "API_KEY",
                    "description": "Credential for the search provider",
                    "is_secret": False,
                }
            ],
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "success"
        request_kwargs = mock_hitl_handler.request_env_vars.await_args.kwargs
        assert request_kwargs["fields"][0]["description"] == "Credential for the search provider"
        saved_env_var = mock_repository.upsert.await_args.args[0]
        assert saved_env_var.description == "Credential for the search provider"

    async def test_request_invalid_variable_name_returns_error(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Malformed variable names should be rejected before HITL/SSE emission."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "AKIAIOSFODNN7EXAMPLE"}],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "invalid" in result_data["message"].lower()

    async def test_request_invalid_tool_name_returns_error(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Secret-like or malformed tool names should not flow into HITL."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="tool with spaces",
            fields=[{"variable_name": "API_KEY"}],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "invalid tool name" in result_data["message"].lower()

    async def test_request_secret_like_tool_name_returns_error(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Secret-looking tool names must be rejected before HITL/UI emission."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="AKIAIOSFODNN7EXAMPLE",
            fields=[{"variable_name": "API_KEY"}],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "invalid tool name" in result_data["message"].lower()

    async def test_request_invalid_context_returns_error(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Non-mapping context values should fail fast with a ToolResult error."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
            context=["not", "a", "dict"],  # type: ignore[arg-type]
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "invalid context" in result_data["message"].lower()

    async def test_request_invalid_field_payload_returns_error(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Non-dict field payloads should fail fast with a ToolResult error."""
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=["API_KEY"],  # type: ignore[list-item]
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "invalid field" in result_data["message"].lower()

    async def test_request_rejects_unexpected_hitl_response_keys(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """HITL responses must not be able to inject extra variable names."""
        mock_hitl_handler.request_env_vars.return_value = {
            "API_KEY": "secret",
            "AKIAIOSFODNN7EXAMPLE": "malicious",
        }
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "invalid" in result_data["message"].lower()

    async def test_request_requires_all_required_values(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Responses missing required requested values should fail closed."""
        mock_hitl_handler.request_env_vars.return_value = {"ORG_ID": "org-1"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[
                {"variable_name": "API_KEY", "is_required": True},
                {"variable_name": "ORG_ID", "is_required": False},
            ],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "missing required" in result_data["message"].lower()

    async def test_request_rejects_non_string_hitl_values(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """HITL responses must provide string values before persistence/encryption."""
        mock_hitl_handler.request_env_vars.return_value = {"API_KEY": ["secret"]}  # type: ignore[dict-item]
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        result_data = json.loads(result.output)
        assert result_data["status"] == "error"
        assert "invalid environment variable values" in result_data["message"].lower()

    async def test_request_variable_name_length_boundary(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        mock_hitl_handler,
    ):
        """Variable names should respect the DB-backed 100 character limit."""
        valid_name = "A" + ("B" * 99)
        invalid_name = "A" + ("B" * 100)
        mock_hitl_handler.request_env_vars.return_value = {valid_name: "secret"}
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=mock_hitl_handler,
            tenant_id="tenant-123",
        )

        valid_result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": valid_name}],
        )
        invalid_result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": invalid_name}],
        )

        assert isinstance(valid_result, ToolResult)
        assert valid_result.is_error is False
        invalid_data = json.loads(invalid_result.output)
        assert invalid_result.is_error is True
        assert invalid_data["status"] == "error"
        assert "invalid" in invalid_data["message"].lower()

    def test_scope_hitl_handler_rebinds_tenant_project(self):
        """Scoped handlers should publish HITL requests under the current ctx scope."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler
        from src.infrastructure.agent.tools import env_var_tools as mod

        handler = RayHITLHandler(
            conversation_id="conv-1",
            tenant_id="tenant-global",
            project_id="project-global",
        )

        scoped = mod._scope_hitl_handler(
            handler,
            tenant_id="tenant-ctx",
            project_id="project-ctx",
            conversation_id="conv-ctx",
            message_id="msg-ctx",
        )

        assert scoped is not handler
        assert scoped.conversation_id == "conv-ctx"
        assert scoped.tenant_id == "tenant-ctx"
        assert scoped.message_id == "msg-ctx"
        assert scoped.project_id == "project-ctx"

    @pytest.mark.unit
    async def test_scope_hitl_handler_preserves_preinjected_response(self):
        """Scoped handlers must preserve and consume preinjected HITL responses once."""
        from src.domain.model.agent.hitl_types import HITLType
        from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler
        from src.infrastructure.agent.tools import env_var_tools as mod

        handler = RayHITLHandler(
            conversation_id="conv-1",
            tenant_id="tenant-global",
            project_id="project-global",
            preinjected_response={
                "request_id": "env_req_1",
                "hitl_type": "env_var",
                "conversation_id": "conv-ctx",
                "tenant_id": "tenant-ctx",
                "project_id": "project-ctx",
                "message_id": "msg-ctx",
                "response_data": {"values": {"API_KEY": "secret"}},
            },
        )

        first_scoped = mod._scope_hitl_handler(
            handler,
            tenant_id="tenant-ctx",
            project_id="project-ctx",
            conversation_id="conv-ctx",
            message_id="msg-ctx",
        )
        second_scoped = mod._scope_hitl_handler(
            handler,
            tenant_id="tenant-ctx-2",
            project_id="project-ctx-2",
            conversation_id="conv-ctx-2",
            message_id="msg-ctx-2",
        )
        response = await first_scoped.request_env_vars(
            tool_name="web_search",
            fields=[{"name": "API_KEY", "label": "API_KEY"}],
            request_id="env_req_1",
        )

        assert response == {"values": {"API_KEY": "secret"}}
        assert handler._preinjected_response is None
        assert first_scoped._preinjected_response is None
        assert second_scoped._preinjected_response is None
        assert second_scoped.peek_preinjected_response(HITLType.ENV_VAR) is None

    @pytest.mark.unit
    async def test_tenant_scope_request_keeps_active_project_for_hitl(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        monkeypatch,
    ):
        """Tenant-scoped saves should still emit HITL requests in the active project context."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler

        captured_scope: dict[str, str] = {}

        async def fake_request_env_vars(
            self: RayHITLHandler,
            *,
            tool_name: str,
            fields: list[dict[str, str]],
            message: str | None = None,
            context: dict[str, str] | None = None,
            timeout_seconds: float | None = None,
            allow_save: bool = True,
            save_project_id: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, str]:
            captured_scope["conversation_id"] = self.conversation_id
            captured_scope["tenant_id"] = self.tenant_id
            captured_scope["project_id"] = self.project_id
            captured_scope["message_id"] = self.message_id or ""
            captured_scope["save_project_id"] = save_project_id or ""
            return {"API_KEY": "secret"}

        monkeypatch.setattr(RayHITLHandler, "request_env_vars", fake_request_env_vars)

        tool_ctx.tenant_id = "tenant-ctx"
        tool_ctx.project_id = "project-ctx"
        handler = RayHITLHandler(
            conversation_id="conv-1",
            tenant_id="tenant-global",
            project_id="project-global",
        )
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=handler,
            tenant_id="tenant-global",
            project_id="project-global",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
            save_to_project=False,
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "success"
        assert captured_scope == {
            "conversation_id": "conv-1",
            "tenant_id": "tenant-ctx",
            "project_id": "project-ctx",
            "message_id": "msg-1",
            "save_project_id": "",
        }
        saved_env_var = mock_repository.upsert.await_args.args[0]
        assert saved_env_var.project_id is None

    async def test_request_handler_scope_does_not_inherit_global_project(
        self,
        tool_ctx,
        mock_repository,
        mock_encryption_service,
        monkeypatch,
    ):
        """Projectless ToolContext must not inherit project scope from the base handler."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler

        captured_scope: dict[str, Any] = {}

        async def fake_request_env_vars(
            self: RayHITLHandler,
            *,
            tool_name: str,
            fields: list[dict[str, str]],
            message: str | None = None,
            context: dict[str, str] | None = None,
            timeout_seconds: float | None = None,
            allow_save: bool = True,
            save_project_id: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, str]:
            captured_scope["tenant_id"] = self.tenant_id
            captured_scope["project_id"] = self.project_id
            captured_scope["save_project_id"] = save_project_id
            return {"API_KEY": "secret"}

        monkeypatch.setattr(RayHITLHandler, "request_env_vars", fake_request_env_vars)

        tool_ctx.tenant_id = "tenant-ctx"
        tool_ctx.project_id = ""
        handler = RayHITLHandler(
            conversation_id="conv-1",
            tenant_id="tenant-global",
            project_id="project-global",
        )
        configure_env_var_tools(
            repository=mock_repository,
            encryption_service=mock_encryption_service,
            hitl_handler=handler,
            tenant_id="tenant-global",
            project_id="project-global",
        )

        result = await request_env_var_tool.execute(
            tool_ctx,
            tool_name="web_search",
            fields=[{"variable_name": "API_KEY"}],
            save_to_project=False,
        )

        assert isinstance(result, ToolResult)
        result_data = json.loads(result.output)
        assert result_data["status"] == "success"
        assert captured_scope == {
            "tenant_id": "tenant-ctx",
            "project_id": "",
            "save_project_id": None,
        }

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
