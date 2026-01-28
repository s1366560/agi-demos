"""Tests for Security and Authentication.

TDD approach: Write tests first, expect failures, then implement.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.server.security import (
    TokenAuthenticator,
    SessionTimeoutManager,
    SecurityConfig,
    SecurityMiddleware,
)


class TestSecurityConfig:
    """Test suite for SecurityConfig dataclass."""

    def test_default_config(self):
        """Test default security configuration."""
        config = SecurityConfig()
        assert config.session_timeout == 1800
        assert config.token_expiry == 3600
        assert config.max_concurrent_sessions == 10
        assert config.allowed_origins == ["*"]
        assert config.require_token is False

    def test_custom_config(self):
        """Test custom security configuration."""
        config = SecurityConfig(
            session_timeout=600,
            token_expiry=1800,
            max_concurrent_sessions=5,
            allowed_origins=["http://localhost:3000"],
            require_token=True,
        )
        assert config.session_timeout == 600
        assert config.token_expiry == 1800
        assert config.max_concurrent_sessions == 5
        assert config.allowed_origins == ["http://localhost:3000"]
        assert config.require_token is True


class TestTokenAuthenticator:
    """Test suite for TokenAuthenticator."""

    @pytest.fixture
    def authenticator(self):
        """Provide a TokenAuthenticator with default config."""
        return TokenAuthenticator()

    @pytest.fixture
    def authenticator_with_secret(self):
        """Provide a TokenAuthenticator with custom secret."""
        return TokenAuthenticator(secret="test-secret-key")

    def test_generate_token(self, authenticator):
        """Test token generation."""
        token = authenticator.generate_token()
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 32  # Tokens should be substantial

    def test_generate_token_is_unique(self, authenticator):
        """Test that generated tokens are unique."""
        token1 = authenticator.generate_token()
        token2 = authenticator.generate_token()
        assert token1 != token2

    def test_validate_valid_token(self, authenticator):
        """Test validating a valid token."""
        token = authenticator.generate_token()
        assert authenticator.validate_token(token) is True

    def test_validate_invalid_token(self, authenticator):
        """Test validating an invalid token."""
        assert authenticator.validate_token("invalid-token") is False
        assert authenticator.validate_token("") is False
        assert authenticator.validate_token(None) is False

    def test_revoke_token(self, authenticator):
        """Test revoking a token."""
        token = authenticator.generate_token()
        assert authenticator.validate_token(token) is True

        authenticator.revoke_token(token)
        assert authenticator.validate_token(token) is False

    def test_revoke_nonexistent_token(self, authenticator):
        """Test revoking a token that doesn't exist."""
        # Should not raise an error
        authenticator.revoke_token("nonexistent-token")

    def test_revoke_all_tokens(self, authenticator):
        """Test revoking all tokens."""
        token1 = authenticator.generate_token()
        token2 = authenticator.generate_token()

        assert authenticator.validate_token(token1) is True
        assert authenticator.validate_token(token2) is True

        authenticator.revoke_all()
        assert authenticator.validate_token(token1) is False
        assert authenticator.validate_token(token2) is False

    def test_get_token_count(self, authenticator):
        """Test getting count of active tokens."""
        assert authenticator.get_token_count() == 0

        authenticator.generate_token()
        assert authenticator.get_token_count() == 1

        authenticator.generate_token()
        authenticator.generate_token()
        assert authenticator.get_token_count() == 3

    def test_token_expiry(self, authenticator_with_secret):
        """Test that tokens expire after configured time."""
        # Create authenticator with very short expiry
        auth = TokenAuthenticator(secret="test", token_expiry=1)  # 1 second
        token = auth.generate_token()
        assert auth.validate_token(token) is True

        # Wait for expiry
        time.sleep(1.1)
        assert auth.validate_token(token) is False


class TestSessionTimeoutManager:
    """Test suite for SessionTimeoutManager."""

    @pytest.fixture
    def timeout_manager(self):
        """Provide a SessionTimeoutManager with short timeout."""
        return SessionTimeoutManager(timeout=2)  # 2 second timeout

    @pytest.mark.asyncio
    async def test_register_session(self, timeout_manager):
        """Test registering a new session."""
        session_id = "test-session-1"
        timeout_manager.register_session(session_id)

        assert timeout_manager.is_active(session_id) is True

    @pytest.mark.asyncio
    async def test_unregister_session(self, timeout_manager):
        """Test unregistering a session."""
        session_id = "test-session-1"
        timeout_manager.register_session(session_id)
        assert timeout_manager.is_active(session_id) is True

        timeout_manager.unregister_session(session_id)
        assert timeout_manager.is_active(session_id) is False

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_session(self, timeout_manager):
        """Test unregistering a session that doesn't exist."""
        # Should not raise an error
        timeout_manager.unregister_session("nonexistent")

    @pytest.mark.asyncio
    async def test_update_activity(self, timeout_manager):
        """Test updating session activity."""
        session_id = "test-session-1"
        timeout_manager.register_session(session_id)

        # Wait a bit
        await asyncio.sleep(1)

        # Update activity (resets timeout)
        timeout_manager.update_activity(session_id)
        assert timeout_manager.is_active(session_id) is True

        # Wait more than timeout after activity update
        await asyncio.sleep(2.5)
        assert timeout_manager.is_active(session_id) is False

    @pytest.mark.asyncio
    async def test_session_timeout(self, timeout_manager):
        """Test that sessions timeout after inactivity."""
        session_id = "test-session-1"
        timeout_manager.register_session(session_id)

        assert timeout_manager.is_active(session_id) is True

        # Wait for timeout
        await asyncio.sleep(2.5)
        assert timeout_manager.is_active(session_id) is False

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, timeout_manager):
        """Test cleanup of expired sessions."""
        session_id1 = "test-session-1"
        session_id2 = "test-session-2"

        timeout_manager.register_session(session_id1)
        await asyncio.sleep(1)
        timeout_manager.register_session(session_id2)

        assert timeout_manager.get_active_count() == 2

        # Wait for first session to expire
        await asyncio.sleep(1.5)

        # Cleanup should remove expired sessions
        timeout_manager.cleanup_expired()
        assert timeout_manager.get_active_count() == 1

    @pytest.mark.asyncio
    async def test_get_active_count(self, timeout_manager):
        """Test getting count of active sessions."""
        assert timeout_manager.get_active_count() == 0

        timeout_manager.register_session("session-1")
        assert timeout_manager.get_active_count() == 1

        timeout_manager.register_session("session-2")
        timeout_manager.register_session("session-3")
        assert timeout_manager.get_active_count() == 3

    @pytest.mark.asyncio
    async def test_get_all_active_sessions(self, timeout_manager):
        """Test getting all active session IDs."""
        timeout_manager.register_session("session-1")
        timeout_manager.register_session("session-2")

        sessions = timeout_manager.get_all_active()
        assert set(sessions) == {"session-1", "session-2"}

    @pytest.mark.asyncio
    async def test_autocleanup_task(self, timeout_manager):
        """Test that autocleanup task removes expired sessions."""
        # Manager with autocleanup enabled
        manager = SessionTimeoutManager(timeout=1, autocleanup_interval=0.5)

        session_id = "test-session"
        manager.register_session(session_id)
        assert manager.is_active(session_id) is True

        # Wait for cleanup to run
        await asyncio.sleep(1.5)
        assert manager.is_active(session_id) is False

        # Stop autocleanup
        manager.stop_autocleanup()

    @pytest.mark.asyncio
    async def test_max_sessions_limit(self):
        """Test maximum sessions limit."""
        manager = SessionTimeoutManager(timeout=60, max_sessions=2)

        manager.register_session("session-1")
        manager.register_session("session-2")

        # Third session should exceed limit
        with pytest.raises(RuntimeError, match="Maximum sessions"):
            manager.register_session("session-3")

    @pytest.mark.asyncio
    async def test_extend_session(self, timeout_manager):
        """Test extending a session's timeout."""
        session_id = "test-session"
        timeout_manager.register_session(session_id)

        await asyncio.sleep(1)
        assert timeout_manager.is_active(session_id) is True

        # Extend the session
        timeout_manager.update_activity(session_id)
        await asyncio.sleep(1)
        # Should still be active because we extended
        assert timeout_manager.is_active(session_id) is True

        await asyncio.sleep(1.5)
        # Now should be expired
        assert timeout_manager.is_active(session_id) is False


class TestSecurityMiddleware:
    """Test suite for SecurityMiddleware."""

    @pytest.fixture
    def middleware(self):
        """Provide a SecurityMiddleware with default config."""
        return SecurityMiddleware()

    @pytest.fixture
    def middleware_with_auth(self):
        """Provide a SecurityMiddleware with auth required."""
        config = SecurityConfig(require_token=True, session_timeout=2)
        return SecurityMiddleware(config)

    def test_create_session(self, middleware):
        """Test creating a new session."""
        token = middleware.create_session("client-1")
        assert token is not None
        assert isinstance(token, str)
        assert middleware.timeout_mgr.get_active_count() == 1

    def test_check_access_without_token(self, middleware):
        """Test access check when token is not required."""
        # Register session
        middleware.timeout_mgr.register_session("client-1")

        # Check access without token (should succeed when token not required)
        assert middleware.check_access("client-1", None) is True
        assert middleware.check_access("client-1", "any-token") is True

    def test_check_access_with_token_required(self, middleware_with_auth):
        """Test access check when token is required."""
        # Create session
        token = middleware_with_auth.create_session("client-1")

        # Valid token should work
        assert middleware_with_auth.check_access("client-1", token) is True

        # Invalid token should fail
        assert middleware_with_auth.check_access("client-1", "invalid") is False

        # No token should fail
        assert middleware_with_auth.check_access("client-1", None) is False

    def test_check_access_expired_session(self, middleware_with_auth):
        """Test access check with expired session."""
        import time

        config = SecurityConfig(require_token=True, session_timeout=1)
        middleware = SecurityMiddleware(config)

        token = middleware.create_session("client-1")

        # Wait for session timeout
        time.sleep(1.5)

        # Session should be expired
        assert middleware.check_access("client-1", token) is False

    def test_revoke_session(self, middleware):
        """Test revoking a session."""
        middleware.create_session("client-1")

        # Session should be active
        assert middleware.timeout_mgr.is_active("client-1") is True

        # Revoke
        middleware.revoke_session("client-1")

        # Session should be gone
        assert middleware.timeout_mgr.is_active("client-1") is False

    def test_get_status(self, middleware):
        """Test getting security status."""
        middleware.create_session("client-1")
        middleware.create_session("client-2")

        status = middleware.get_status()
        assert status["active_sessions"] == 2
        assert status["active_tokens"] == 2
        assert status["max_sessions"] == 10
        assert status["session_timeout"] == 1800
        assert status["require_token"] is False
