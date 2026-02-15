"""Unit tests for MCP API schemas and router logic.

Tests server_type validation, transport_config validation,
tool call error propagation, and server deletion app cleanup.
"""

import pytest
from pydantic import ValidationError

from src.domain.exceptions.mcp import (
    MCPConnectionError,
    MCPError,
    MCPServerAlreadyExistsError,
    MCPServerNotConnectedError,
    MCPServerNotFoundError,
    MCPToolExecutionError,
    MCPToolNotFoundError,
)
from src.infrastructure.adapters.primary.web.routers.mcp.schemas import (
    MCPServerCreate,
    MCPServerUpdate,
    MCPToolCallResponse,
)


@pytest.mark.unit
class TestMCPServerCreateSchema:
    """Tests for MCPServerCreate schema validation."""

    def test_valid_stdio_server(self):
        server = MCPServerCreate(
            name="test-server",
            server_type="stdio",
            transport_config={"command": "npx", "args": ["-y", "@test/mcp"]},
            project_id="proj-1",
        )
        assert server.server_type == "stdio"
        assert server.transport_config["command"] == "npx"

    def test_valid_sse_server(self):
        server = MCPServerCreate(
            name="test-sse",
            server_type="sse",
            transport_config={"url": "http://localhost:3001/sse"},
            project_id="proj-1",
        )
        assert server.server_type == "sse"

    def test_valid_http_server(self):
        server = MCPServerCreate(
            name="test-http",
            server_type="http",
            transport_config={"url": "http://localhost:3001/mcp"},
            project_id="proj-1",
        )
        assert server.server_type == "http"

    def test_valid_websocket_server(self):
        server = MCPServerCreate(
            name="test-ws",
            server_type="websocket",
            transport_config={"url": "ws://localhost:18765"},
            project_id="proj-1",
        )
        assert server.server_type == "websocket"

    def test_invalid_server_type_rejected(self):
        with pytest.raises(ValidationError, match="Input should be"):
            MCPServerCreate(
                name="test",
                server_type="invalid",
                transport_config={"url": "http://example.com"},
                project_id="proj-1",
            )

    def test_stdio_without_command_rejected(self):
        with pytest.raises(ValidationError, match="stdio transport requires 'command'"):
            MCPServerCreate(
                name="test",
                server_type="stdio",
                transport_config={"args": ["--verbose"]},
                project_id="proj-1",
            )

    def test_sse_without_url_rejected(self):
        with pytest.raises(ValidationError, match="sse transport requires 'url'"):
            MCPServerCreate(
                name="test",
                server_type="sse",
                transport_config={"headers": {"Authorization": "Bearer x"}},
                project_id="proj-1",
            )

    def test_http_without_url_rejected(self):
        with pytest.raises(ValidationError, match="http transport requires 'url'"):
            MCPServerCreate(
                name="test",
                server_type="http",
                transport_config={},
                project_id="proj-1",
            )

    def test_websocket_without_url_rejected(self):
        with pytest.raises(ValidationError, match="websocket transport requires 'url'"):
            MCPServerCreate(
                name="test",
                server_type="websocket",
                transport_config={"headers": {}},
                project_id="proj-1",
            )

    def test_name_too_long_rejected(self):
        with pytest.raises(ValidationError):
            MCPServerCreate(
                name="x" * 201,
                server_type="stdio",
                transport_config={"command": "test"},
                project_id="proj-1",
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            MCPServerCreate(
                name="",
                server_type="stdio",
                transport_config={"command": "test"},
                project_id="proj-1",
            )


@pytest.mark.unit
class TestMCPServerUpdateSchema:
    """Tests for MCPServerUpdate schema validation."""

    def test_partial_update_name_only(self):
        update = MCPServerUpdate(name="new-name")
        assert update.name == "new-name"
        assert update.server_type is None
        assert update.transport_config is None

    def test_invalid_server_type_rejected(self):
        with pytest.raises(ValidationError, match="Input should be"):
            MCPServerUpdate(server_type="ftp")

    def test_valid_type_with_config(self):
        update = MCPServerUpdate(
            server_type="sse",
            transport_config={"url": "http://localhost:3001"},
        )
        assert update.server_type == "sse"

    def test_type_and_config_mismatch_rejected(self):
        with pytest.raises(ValidationError, match="sse transport requires 'url'"):
            MCPServerUpdate(
                server_type="sse",
                transport_config={"command": "test"},
            )

    def test_config_without_type_allowed(self):
        """Config-only update is allowed (type comes from DB)."""
        update = MCPServerUpdate(transport_config={"url": "http://new-host"})
        assert update.transport_config == {"url": "http://new-host"}


@pytest.mark.unit
class TestMCPToolCallResponse:
    """Tests for MCPToolCallResponse model."""

    def test_successful_response(self):
        resp = MCPToolCallResponse(
            result={"content": [{"type": "text", "text": "Hello"}]},
            execution_time_ms=150.5,
        )
        assert resp.is_error is False
        assert resp.error_message is None

    def test_error_response(self):
        resp = MCPToolCallResponse(
            result={"content": [{"type": "text", "text": "Error occurred"}], "isError": True},
            is_error=True,
            error_message="Error occurred",
            execution_time_ms=50.0,
        )
        assert resp.is_error is True
        assert resp.error_message == "Error occurred"


@pytest.mark.unit
class TestMCPDomainExceptions:
    """Tests for MCP domain exception hierarchy."""

    def test_mcp_error_base(self):
        err = MCPError("base error")
        assert str(err) == "base error"
        assert err.details == {}

    def test_mcp_error_with_cause(self):
        cause = RuntimeError("underlying")
        err = MCPError("wrapped", original_error=cause)
        assert "caused by: underlying" in str(err)
        assert err.original_error is cause

    def test_server_not_found_by_id(self):
        err = MCPServerNotFoundError(server_id="srv-123")
        assert "srv-123" in str(err)
        assert err.server_id == "srv-123"

    def test_server_not_found_by_name(self):
        err = MCPServerNotFoundError(server_name="my-server")
        assert "my-server" in str(err)
        assert err.server_name == "my-server"

    def test_server_already_exists(self):
        err = MCPServerAlreadyExistsError("my-server")
        assert "my-server" in str(err)
        assert "already exists" in str(err)

    def test_server_not_connected(self):
        err = MCPServerNotConnectedError("my-server")
        assert "not connected" in str(err)

    def test_tool_not_found(self):
        err = MCPToolNotFoundError("my_tool", server_name="my-server")
        assert "my_tool" in str(err)
        assert "my-server" in str(err)

    def test_tool_not_found_no_server(self):
        err = MCPToolNotFoundError("my_tool")
        assert "my_tool" in str(err)
        assert err.server_name is None

    def test_tool_execution_error(self):
        cause = TimeoutError("timed out")
        err = MCPToolExecutionError("my_tool", original_error=cause)
        assert "my_tool" in str(err)
        assert err.original_error is cause

    def test_connection_error(self):
        err = MCPConnectionError(endpoint="ws://localhost:18765")
        assert "ws://localhost:18765" in str(err)

    def test_exception_hierarchy(self):
        """Verify exception hierarchy for catch patterns."""
        assert issubclass(MCPServerNotFoundError, MCPError)
        assert issubclass(MCPServerAlreadyExistsError, MCPError)
        assert issubclass(MCPServerNotConnectedError, MCPError)
        assert issubclass(MCPToolNotFoundError, MCPError)
        assert issubclass(MCPToolExecutionError, MCPError)
        assert issubclass(MCPConnectionError, MCPError)


# =====================================================
# Health Check Schema Tests
# =====================================================


@pytest.mark.unit
class TestMCPHealthSchemas:
    """Tests for MCP health check schemas."""

    def test_health_status_healthy(self):
        from src.infrastructure.adapters.primary.web.routers.mcp.schemas import (
            MCPServerHealthStatus,
        )

        h = MCPServerHealthStatus(
            id="s1", name="test", status="healthy", enabled=True, tools_count=3
        )
        assert h.status == "healthy"
        assert h.tools_count == 3

    def test_health_status_disabled(self):
        from src.infrastructure.adapters.primary.web.routers.mcp.schemas import (
            MCPServerHealthStatus,
        )

        h = MCPServerHealthStatus(id="s1", name="test", status="disabled", enabled=False)
        assert h.status == "disabled"
        assert h.tools_count == 0

    def test_health_summary(self):
        from src.infrastructure.adapters.primary.web.routers.mcp.schemas import (
            MCPHealthSummary,
            MCPServerHealthStatus,
        )

        statuses = [
            MCPServerHealthStatus(id="1", name="a", status="healthy", enabled=True, tools_count=2),
            MCPServerHealthStatus(id="2", name="b", status="error", enabled=True, sync_error="x"),
            MCPServerHealthStatus(id="3", name="c", status="disabled", enabled=False),
        ]
        summary = MCPHealthSummary(
            total=3, healthy=1, degraded=0, error=1, disabled=1, servers=statuses
        )
        assert summary.total == 3
        assert summary.healthy == 1
        assert summary.error == 1

    def test_compute_server_health_statuses(self):
        from types import SimpleNamespace

        from src.infrastructure.adapters.primary.web.routers.mcp.servers import (
            _compute_server_health,
        )

        _s = SimpleNamespace

        # Disabled
        h = _compute_server_health(
            _s(
                id="1",
                name="s",
                enabled=False,
                sync_error=None,
                last_sync_at=None,
                discovered_tools=None,
            )
        )
        assert h.status == "disabled"

        # Error
        h = _compute_server_health(
            _s(
                id="2",
                name="s",
                enabled=True,
                sync_error="fail",
                last_sync_at=None,
                discovered_tools=None,
            )
        )
        assert h.status == "error"

        # Unknown (never synced)
        h = _compute_server_health(
            _s(
                id="3",
                name="s",
                enabled=True,
                sync_error=None,
                last_sync_at=None,
                discovered_tools=None,
            )
        )
        assert h.status == "unknown"

        # Healthy
        h = _compute_server_health(
            _s(
                id="4",
                name="s",
                enabled=True,
                sync_error=None,
                last_sync_at="2024-01-01",
                discovered_tools=[{"name": "t"}],
            )
        )
        assert h.status == "healthy"
        assert h.tools_count == 1

        # Degraded (synced but no tools)
        h = _compute_server_health(
            _s(
                id="5",
                name="s",
                enabled=True,
                sync_error=None,
                last_sync_at="2024-01-01",
                discovered_tools=None,
            )
        )
        assert h.status == "degraded"


# =====================================================
# OAuth Encryption Tests
# =====================================================


@pytest.mark.unit
class TestMCPAuthStorageEncryption:
    """Tests for MCPAuthStorage encryption support."""

    def test_encrypt_decrypt_roundtrip(self):
        from src.infrastructure.security.encryption_service import EncryptionService

        svc = EncryptionService(encryption_key=("ab" * 32))
        encrypted = svc.encrypt("my-secret-token")
        assert encrypted != "my-secret-token"
        assert svc.decrypt(encrypted) == "my-secret-token"

    def test_storage_encrypt_value(self, tmp_path):
        from src.infrastructure.agent.mcp.oauth import MCPAuthStorage
        from src.infrastructure.security.encryption_service import EncryptionService

        enc = EncryptionService(encryption_key=("cd" * 32))
        storage = MCPAuthStorage(data_dir=tmp_path, encryption_service=enc)

        result = storage._encrypt_value("secret123")
        assert result.startswith("enc:")
        assert storage._decrypt_value(result) == "secret123"

    def test_storage_decrypt_legacy_plaintext(self, tmp_path):
        from src.infrastructure.agent.mcp.oauth import MCPAuthStorage

        storage = MCPAuthStorage(data_dir=tmp_path, encryption_service=None)
        # Legacy plaintext should pass through unchanged
        assert storage._decrypt_value("plain-token") == "plain-token"

    async def test_entry_roundtrip_with_encryption(self, tmp_path):
        from src.infrastructure.agent.mcp.oauth import (
            MCPAuthEntry,
            MCPAuthStorage,
            OAuthClientInfo,
            OAuthTokens,
        )
        from src.infrastructure.security.encryption_service import EncryptionService

        enc = EncryptionService(encryption_key=("ef" * 32))
        storage = MCPAuthStorage(data_dir=tmp_path, encryption_service=enc)

        entry = MCPAuthEntry(
            tokens=OAuthTokens(
                access_token="at_secret",
                refresh_token="rt_secret",
                expires_at=9999999999.0,
            ),
            client_info=OAuthClientInfo(
                client_id="cid",
                client_secret="cs_secret",
            ),
            server_url="https://example.com",
        )

        await storage.set("test-server", entry)

        # Read raw file and verify tokens are encrypted
        import json

        raw = json.loads((tmp_path / "mcp-auth.json").read_text())
        raw_entry = raw["test-server"]
        assert raw_entry["tokens"]["accessToken"].startswith("enc:")
        assert raw_entry["tokens"]["refreshToken"].startswith("enc:")
        assert raw_entry["clientInfo"]["clientSecret"].startswith("enc:")
        # Client ID should NOT be encrypted
        assert raw_entry["clientInfo"]["clientId"] == "cid"

        # Round-trip: read back and verify decrypted values
        loaded = await storage.get("test-server")
        assert loaded is not None
        assert loaded.tokens.access_token == "at_secret"
        assert loaded.tokens.refresh_token == "rt_secret"
        assert loaded.client_info.client_secret == "cs_secret"
        assert loaded.client_info.client_id == "cid"

    async def test_revoke_removes_entry(self, tmp_path):
        from src.infrastructure.agent.mcp.oauth import MCPAuthEntry, MCPAuthStorage, OAuthTokens

        storage = MCPAuthStorage(data_dir=tmp_path, encryption_service=None)

        entry = MCPAuthEntry(tokens=OAuthTokens(access_token="token"))
        await storage.set("server-a", entry)
        assert await storage.get("server-a") is not None

        result = await storage.revoke("server-a")
        assert result is True
        assert await storage.get("server-a") is None

        # Revoking non-existent returns False
        result = await storage.revoke("server-a")
        assert result is False
