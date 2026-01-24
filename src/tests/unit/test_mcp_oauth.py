"""
Unit tests for MCP OAuth implementation.

Tests the OAuth authentication support for MCP servers,
including auth storage, OAuth provider, and callback server.
"""

import asyncio
import time

import pytest

from src.infrastructure.agent.mcp.oauth import (
    MCPAuthEntry,
    MCPAuthStorage,
    MCPOAuthProvider,
    OAuthClientInfo,
    OAuthTokens,
    base64_url_encode,
)
from src.infrastructure.agent.mcp.oauth_callback import (
    MCPOAuthCallbackServer,
)


@pytest.mark.unit
class TestBase64UrlEncode:
    """Test base64 URL-safe encoding."""

    def test_basic_encoding(self):
        """Test basic encoding."""
        data = b"test"
        result = base64_url_encode(data)
        assert result == "dGVzdA"

    def test_padding_removed(self):
        """Test that padding is removed."""
        data = b"hello"
        result = base64_url_encode(data)
        # URL-safe base64 without =
        assert "=" not in result


@pytest.mark.unit
class TestMCPAuthStorage:
    """Test MCP OAuth storage."""

    @pytest.fixture
    def temp_storage(self, tmp_path):
        """Create a temporary storage instance."""
        storage = MCPAuthStorage(data_dir=tmp_path)
        return storage

    @pytest.mark.asyncio
    async def test_save_and_get_entry(self, temp_storage):
        """Test saving and retrieving auth entry."""
        mcp_name = "test-server"
        tokens = OAuthTokens(
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            expires_at=time.time() + 3600,
            scope="read write",
        )
        entry = MCPAuthEntry(tokens=tokens, server_url="http://example.com")

        await temp_storage.set(mcp_name, entry)

        retrieved = await temp_storage.get(mcp_name)

        assert retrieved is not None
        assert retrieved.tokens is not None
        assert retrieved.tokens.access_token == "test_access_token"
        assert retrieved.tokens.refresh_token == "test_refresh_token"
        assert retrieved.tokens.expires_at is not None
        assert retrieved.tokens.scope == "read write"
        assert retrieved.server_url == "http://example.com"

    @pytest.mark.asyncio
    async def test_get_for_url_validates_url(self, temp_storage):
        """Test that get_for_url validates the server URL."""
        mcp_name = "test-server"

        # Save entry with URL
        entry = MCPAuthEntry(
            tokens=OAuthTokens(access_token="token"),
            server_url="http://example.com",
        )
        await temp_storage.set(mcp_name, entry)

        # Matching URL should return entry
        retrieved = await temp_storage.get_for_url(mcp_name, "http://example.com")
        assert retrieved is not None

        # Different URL should return None
        retrieved = await temp_storage.get_for_url(mcp_name, "http://other.com")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_for_url_requires_server_url(self, temp_storage):
        """Test that get_for_url requires server_url in entry."""
        mcp_name = "test-server"

        # Save entry WITHOUT URL (old version)
        entry = MCPAuthEntry(tokens=OAuthTokens(access_token="token"))
        await temp_storage.set(mcp_name, entry)

        # Should return None for old entries without URL
        retrieved = await temp_storage.get_for_url(mcp_name, "http://example.com")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_update_tokens(self, temp_storage):
        """Test updating tokens."""
        mcp_name = "test-server"

        tokens = OAuthTokens(access_token="new_token", expires_at=time.time() + 3600)
        await temp_storage.update_tokens(mcp_name, tokens, "http://example.com")

        retrieved = await temp_storage.get(mcp_name)
        assert retrieved is not None
        assert retrieved.tokens.access_token == "new_token"

    @pytest.mark.asyncio
    async def test_update_client_info(self, temp_storage):
        """Test updating client info."""
        mcp_name = "test-server"

        client_info = OAuthClientInfo(
            client_id="test_client",
            client_secret="test_secret",
        )
        await temp_storage.update_client_info(mcp_name, client_info)

        retrieved = await temp_storage.get(mcp_name)
        assert retrieved is not None
        assert retrieved.client_info.client_id == "test_client"
        assert retrieved.client_info.client_secret == "test_secret"

    @pytest.mark.asyncio
    async def test_code_verifier(self, temp_storage):
        """Test code verifier storage."""
        mcp_name = "test-server"

        await temp_storage.update_code_verifier(mcp_name, "verifier123")

        retrieved = await temp_storage.get(mcp_name)
        assert retrieved is not None
        assert retrieved.code_verifier == "verifier123"

    @pytest.mark.asyncio
    async def test_clear_code_verifier(self, temp_storage):
        """Test clearing code verifier."""
        mcp_name = "test-server"

        # First create an entry with tokens
        await temp_storage.update_tokens(mcp_name, OAuthTokens(access_token="token"))
        await temp_storage.update_code_verifier(mcp_name, "verifier123")
        await temp_storage.clear_code_verifier(mcp_name)

        retrieved = await temp_storage.get(mcp_name)
        assert retrieved is not None
        assert retrieved.code_verifier is None
        # Entry still exists with tokens
        assert retrieved.tokens is not None

    @pytest.mark.asyncio
    async def test_oauth_state(self, temp_storage):
        """Test OAuth state storage."""
        mcp_name = "test-server"

        await temp_storage.update_oauth_state(mcp_name, "state456")

        retrieved = await temp_storage.get(mcp_name)
        assert retrieved is not None
        assert retrieved.oauth_state == "state456"

    @pytest.mark.asyncio
    async def test_clear_oauth_state(self, temp_storage):
        """Test clearing OAuth state."""
        mcp_name = "test-server"

        # First create an entry with tokens
        await temp_storage.update_tokens(mcp_name, OAuthTokens(access_token="token"))
        await temp_storage.update_oauth_state(mcp_name, "state456")
        await temp_storage.clear_oauth_state(mcp_name)

        retrieved = await temp_storage.get(mcp_name)
        assert retrieved is not None
        assert retrieved.oauth_state is None
        # Entry still exists with tokens
        assert retrieved.tokens is not None

    @pytest.mark.asyncio
    async def test_remove_entry(self, temp_storage):
        """Test removing auth entry."""
        mcp_name = "test-server"

        entry = MCPAuthEntry(tokens=OAuthTokens(access_token="token"))
        await temp_storage.set(mcp_name, entry)

        # Verify it exists
        retrieved = await temp_storage.get(mcp_name)
        assert retrieved is not None

        # Remove it
        await temp_storage.remove(mcp_name)

        # Verify it's gone
        retrieved = await temp_storage.get(mcp_name)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_is_token_expired(self, temp_storage):
        """Test token expiration checking."""
        mcp_name = "test-server"

        # No tokens
        result = await temp_storage.is_token_expired(mcp_name)
        assert result is None

        # Token without expiry
        tokens = OAuthTokens(access_token="token")
        await temp_storage.update_tokens(mcp_name, tokens)
        result = await temp_storage.is_token_expired(mcp_name)
        assert result is False

        # Expired token
        tokens = OAuthTokens(
            access_token="token",
            expires_at=time.time() - 100,  # Expired 100 seconds ago
        )
        await temp_storage.update_tokens(mcp_name, tokens)
        result = await temp_storage.is_token_expired(mcp_name)
        assert result is True

        # Valid token
        tokens = OAuthTokens(
            access_token="token",
            expires_at=time.time() + 3600,  # Expires in 1 hour
        )
        await temp_storage.update_tokens(mcp_name, tokens)
        result = await temp_storage.is_token_expired(mcp_name)
        assert result is False


@pytest.mark.unit
class TestMCPOAuthProvider:
    """Test MCP OAuth provider."""

    @pytest.fixture
    def provider(self, tmp_path):
        """Create OAuth provider with temp storage."""
        storage = MCPAuthStorage(data_dir=tmp_path)
        provider = MCPOAuthProvider(
            mcp_name="test-server",
            server_url="http://example.com",
            storage=storage,
        )
        return provider

    def test_redirect_url(self, provider):
        """Test redirect URL generation."""
        assert "127.0.0.1:19876" in provider.redirect_url
        assert "/mcp/oauth/callback" in provider.redirect_url

    def test_client_metadata(self, provider):
        """Test client metadata for dynamic registration."""
        metadata = provider.client_metadata

        assert metadata["redirect_uris"] == [provider.redirect_url]
        assert metadata["client_name"] == "MemStack"
        assert metadata["grant_types"] == ["authorization_code", "refresh_token"]
        assert metadata["token_endpoint_auth_method"] == "none"

    def test_client_metadata_with_secret(self, tmp_path):
        """Test client metadata with pre-configured secret."""
        storage = MCPAuthStorage(data_dir=tmp_path)
        provider = MCPOAuthProvider(
            mcp_name="test-server",
            server_url="http://example.com",
            storage=storage,
            client_secret="secret",
        )

        metadata = provider.client_metadata
        assert metadata["token_endpoint_auth_method"] == "client_secret_post"

    @pytest.mark.asyncio
    async def test_client_information_pre_configured(self, tmp_path):
        """Test getting pre-configured client information."""
        storage = MCPAuthStorage(data_dir=tmp_path)
        provider = MCPOAuthProvider(
            mcp_name="test-server",
            server_url="http://example.com",
            storage=storage,
            client_id="pre_client",
            client_secret="pre_secret",
        )

        info = await provider.client_information()

        assert info is not None
        assert info.client_id == "pre_client"
        assert info.client_secret == "pre_secret"

    @pytest.mark.asyncio
    async def test_client_information_from_storage(self, provider):
        """Test getting client info from storage."""
        # Save client info to storage
        client_info = OAuthClientInfo(
            client_id="stored_client",
            client_secret="stored_secret",
        )
        await provider._storage.update_client_info(
            provider._mcp_name,
            client_info,
            provider._server_url,
        )

        info = await provider.client_information()

        assert info is not None
        assert info.client_id == "stored_client"

    @pytest.mark.asyncio
    async def test_client_information_expired_secret(self, provider):
        """Test that expired client secret is rejected."""
        # Save expired client info
        client_info = OAuthClientInfo(
            client_id="stored_client",
            client_secret="stored_secret",
            client_secret_expires_at=time.time() - 100,  # Expired
        )
        await provider._storage.update_client_info(
            provider._mcp_name,
            client_info,
            provider._server_url,
        )

        info = await provider.client_information()

        # Should return None to trigger re-registration
        assert info is None

    @pytest.mark.asyncio
    async def test_client_information_url_mismatch(self, provider):
        """Test that URL mismatch returns None."""
        # Save client info for different URL
        client_info = OAuthClientInfo(client_id="stored_client")
        await provider._storage.update_client_info(
            provider._mcp_name,
            client_info,
            "http://different.com",  # Different URL
        )

        info = await provider.client_information()

        # Should return None
        assert info is None

    @pytest.mark.asyncio
    async def test_save_and_get_tokens(self, provider):
        """Test saving and retrieving tokens."""
        await provider.save_tokens(
            access_token="access123",
            refresh_token="refresh123",
            expires_in=3600,
            scope="read write",
        )

        tokens = await provider.get_tokens()

        assert tokens is not None
        assert tokens.access_token == "access123"
        assert tokens.refresh_token == "refresh123"
        assert tokens.scope == "read write"
        assert tokens.expires_at is not None
        assert tokens.expires_at > time.time()

    @pytest.mark.asyncio
    async def test_save_client_information(self, provider):
        """Test saving dynamically registered client information."""
        await provider.save_client_information(
            client_id="dynamic_client",
            client_secret="dynamic_secret",
            client_id_issued_at=time.time(),
            client_secret_expires_at=time.time() + 86400,
        )

        # Verify it was saved
        entry = await provider._storage.get(provider._mcp_name)
        assert entry is not None
        assert entry.client_info is not None
        assert entry.client_info.client_id == "dynamic_client"
        assert entry.client_info.client_secret == "dynamic_secret"

    @pytest.mark.asyncio
    async def test_generate_code_verifier(self, provider):
        """Test PKCE code verifier generation."""
        challenge = await provider.generate_code_verifier()

        # Challenge should be URL-safe base64
        assert "=" not in challenge
        assert "+" not in challenge
        assert "/" not in challenge
        assert len(challenge) > 20

        # Verifier should be stored
        verifier = await provider.get_code_verifier()
        assert verifier is not None
        assert len(verifier) >= 32

    @pytest.mark.asyncio
    async def test_save_and_get_oauth_state(self, provider):
        """Test OAuth state management."""
        state = await provider.save_oauth_state()

        retrieved_state = await provider.get_oauth_state()

        assert state == retrieved_state

    @pytest.mark.asyncio
    async def test_get_code_verifier_raises_without_save(self, provider):
        """Test that getting code verifier without saving raises error."""
        with pytest.raises(ValueError, match="No code verifier saved"):
            await provider.get_code_verifier()

    @pytest.mark.asyncio
    async def test_get_oauth_state_raises_without_save(self, provider):
        """Test that getting OAuth state without saving raises error."""
        with pytest.raises(ValueError, match="No OAuth state saved"):
            await provider.get_oauth_state()


@pytest.mark.unit
class TestMCPOAuthCallbackServer:
    """Test MCP OAuth callback server."""

    @pytest.fixture
    def server(self):
        """Create callback server instance."""
        return MCPOAuthCallbackServer(port=19876)

    def test_initially_not_running(self, server):
        """Test that server is initially not running."""
        assert not server.is_running

    @pytest.mark.asyncio
    async def test_start_and_stop(self, server):
        """Test starting and stopping server."""
        await server.start()
        assert server.is_running

        await server.stop()
        assert not server.is_running

    @pytest.mark.asyncio
    async def test_wait_for_callback_timeout(self, server):
        """Test callback timeout."""
        await server.start()

        state = "test_state_timeout"
        future = asyncio.ensure_future(server.wait_for_callback(state))

        # Cancel it quickly to simulate timeout (avoid 5 minute wait)
        await asyncio.sleep(0.1)
        server.cancel_pending(state)

        # Should raise exception
        with pytest.raises(Exception, match="Authorization cancelled"):
            await future

        await server.stop()

    @pytest.mark.asyncio
    async def test_cancel_pending(self, server):
        """Test canceling pending authorization."""
        state = "test_state"

        # Start waiting for callback
        future = asyncio.ensure_future(server.wait_for_callback(state))

        # Cancel it
        server.cancel_pending(state)

        # Should raise exception
        with pytest.raises(Exception, match="Authorization cancelled"):
            await future

    @pytest.mark.asyncio
    async def test_get_pending_states(self, server):
        """Test getting pending states."""
        state1 = "state1"
        state2 = "state2"

        # Start waiting for callbacks
        future1 = asyncio.ensure_future(server.wait_for_callback(state1))
        future2 = asyncio.ensure_future(server.wait_for_callback(state2))

        try:
            pending = server.get_pending_states()
            assert state1 in pending
            assert state2 in pending
        finally:
            server.cancel_pending(state1)
            server.cancel_pending(state2)
            try:
                await future1
            except Exception:
                pass
            try:
                await future2
            except Exception:
                pass


@pytest.mark.unit
class TestGlobalOAuthCallbackServer:
    """Test global OAuth callback server singleton."""

    @pytest.mark.asyncio
    async def test_global_singleton(self):
        """Test that global server is a singleton."""
        # Use custom port to avoid conflicts
        from src.infrastructure.agent.mcp.oauth_callback import (
            MCPOAuthCallbackServer,
        )

        # Create a new server with different port
        test_server = MCPOAuthCallbackServer(port=19877)
        await test_server.start()

        server1 = test_server
        server2 = test_server

        assert server1 is server2

        await test_server.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_singleton(self):
        """Test that stop clears the global singleton."""
        from src.infrastructure.agent.mcp.oauth_callback import (
            MCPOAuthCallbackServer,
        )

        # Use custom port to avoid conflicts
        test_server = MCPOAuthCallbackServer(port=19878)
        await test_server.start()
        assert test_server.is_running

        await test_server.stop()

        # Create new server to verify it's really stopped
        new_server = MCPOAuthCallbackServer(port=19878)
        await new_server.start()
        assert new_server is not test_server

        await new_server.stop()
