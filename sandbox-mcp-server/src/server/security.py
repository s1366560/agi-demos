"""Security and Authentication for sandbox sessions.

Provides token-based authentication and session timeout management.
"""

import hashlib
import secrets
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import logging

logger = logging.getLogger(__name__)


@dataclass
class SecurityConfig:
    """Security configuration settings."""

    session_timeout: int = 1800  # 30 minutes in seconds
    token_expiry: int = 3600  # 1 hour in seconds
    max_concurrent_sessions: int = 10
    allowed_origins: List[str] = field(default_factory=lambda: ["*"])
    require_token: bool = False


class TokenAuthenticator:
    """
    Token-based authentication for session access.

    Generates and validates access tokens for terminal and desktop sessions.
    Tokens can be revoked individually or all at once.

    Usage:
        auth = TokenAuthenticator()
        token = auth.generate_token()
        if auth.validate_token(token):
            # Access granted
            pass
    """

    def __init__(
        self,
        secret: Optional[str] = None,
        token_expiry: int = 3600,
    ):
        """
        Initialize the token authenticator.

        Args:
            secret: Secret key for token signing (auto-generated if None)
            token_expiry: Token validity duration in seconds
        """
        self.secret = secret or secrets.token_hex(32)
        self.token_expiry = token_expiry
        self._tokens: Dict[str, float] = {}  # token -> expiry timestamp

    def generate_token(self) -> str:
        """
        Generate a new access token.

        Returns:
            Access token string
        """
        # Generate random token
        token = secrets.token_urlsafe(32)

        # Set expiry
        expiry = time.time() + self.token_expiry
        self._tokens[token] = expiry

        logger.debug(f"Generated token (expires at {expiry})")
        return token

    def validate_token(self, token: Optional[str]) -> bool:
        """
        Validate an access token.

        Args:
            token: Token to validate

        Returns:
            True if token is valid and not expired
        """
        if not token:
            return False

        expiry = self._tokens.get(token)
        if expiry is None:
            return False

        # Check expiry
        if time.time() > expiry:
            # Remove expired token
            del self._tokens[token]
            return False

        return True

    def revoke_token(self, token: str) -> None:
        """
        Revoke a specific token.

        Args:
            token: Token to revoke
        """
        self._tokens.pop(token, None)

    def revoke_all(self) -> None:
        """Revoke all active tokens."""
        self._tokens.clear()
        logger.info("All tokens revoked")

    def get_token_count(self) -> int:
        """
        Get count of active tokens.

        Returns:
            Number of active tokens
        """
        # Clean expired tokens first
        self._cleanup_expired()
        return len(self._tokens)

    def _cleanup_expired(self) -> None:
        """Remove expired tokens from storage."""
        now = time.time()
        expired = [t for t, exp in self._tokens.items() if exp <= now]
        for token in expired:
            del self._tokens[token]


class SessionTimeoutManager:
    """
    Manages session timeouts and activity tracking.

    Tracks session activity and automatically expires inactive sessions
    after a configured timeout period.

    Usage:
        manager = SessionTimeoutManager(timeout=1800)  # 30 minutes
        manager.register_session("session-id")

        # Update activity on user action
        manager.update_activity("session-id")

        # Check if session is still active
        if manager.is_active("session-id"):
            # Session is valid
            pass

        # Clean up expired sessions
        manager.cleanup_expired()
    """

    def __init__(
        self,
        timeout: int = 1800,
        max_sessions: int = 10,
        autocleanup_interval: float = 60,
    ):
        """
        Initialize the session timeout manager.

        Args:
            timeout: Session inactivity timeout in seconds
            max_sessions: Maximum number of concurrent sessions
            autocleanup_interval: Interval between automatic cleanups (seconds)
        """
        self.timeout = timeout
        self.max_sessions = max_sessions
        self._sessions: Dict[str, float] = {}  # session_id -> last activity
        self._lock = threading.Lock()
        self._autocleanup_task: Optional[threading.Thread] = None
        self._autocleanup_running = False
        self._autocleanup_interval = autocleanup_interval

    def register_session(self, session_id: str) -> None:
        """
        Register a new session.

        Args:
            session_id: Unique session identifier

        Raises:
            RuntimeError: If maximum sessions limit reached
        """
        with self._lock:
            # Clean expired first
            self._cleanup_expired_unlocked()

            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError(
                    f"Maximum sessions limit ({self.max_sessions}) reached"
                )

            self._sessions[session_id] = time.time()
            logger.debug(f"Registered session: {session_id}")

    def unregister_session(self, session_id: str) -> None:
        """
        Unregister a session.

        Args:
            session_id: Session identifier to remove
        """
        with self._lock:
            self._sessions.pop(session_id, None)
            logger.debug(f"Unregistered session: {session_id}")

    def update_activity(self, session_id: str) -> None:
        """
        Update session activity timestamp.

        Call this when the session is active to prevent timeout.

        Args:
            session_id: Session identifier
        """
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id] = time.time()

    def is_active(self, session_id: str) -> bool:
        """
        Check if a session is still active.

        Args:
            session_id: Session identifier

        Returns:
            True if session exists and has not timed out
        """
        with self._lock:
            last_activity = self._sessions.get(session_id)
            if last_activity is None:
                return False

            # Check timeout
            if time.time() - last_activity > self.timeout:
                # Remove expired session
                del self._sessions[session_id]
                return False

            return True

    def cleanup_expired(self) -> int:
        """
        Remove expired sessions.

        Returns:
            Number of sessions removed
        """
        with self._lock:
            return self._cleanup_expired_unlocked()

    def _cleanup_expired_unlocked(self) -> int:
        """Remove expired sessions (assumes lock is held)."""
        now = time.time()
        expired = [
            sid
            for sid, last_activity in self._sessions.items()
            if now - last_activity > self.timeout
        ]
        for sid in expired:
            del self._sessions[sid]
            logger.debug(f"Expired session removed: {sid}")

        return len(expired)

    def get_active_count(self) -> int:
        """
        Get count of active sessions.

        Returns:
            Number of active sessions
        """
        with self._lock:
            self._cleanup_expired_unlocked()
            return len(self._sessions)

    def get_all_active(self) -> List[str]:
        """
        Get all active session IDs.

        Returns:
            List of active session IDs
        """
        with self._lock:
            self._cleanup_expired_unlocked()
            return list(self._sessions.keys())

    def start_autocleanup(self) -> None:
        """Start automatic cleanup of expired sessions in background thread."""
        if self._autocleanup_running:
            return

        self._autocleanup_running = True

        def cleanup_loop():
            while self._autocleanup_running:
                time.sleep(self._autocleanup_interval)
                if self._autocleanup_running:
                    self.cleanup_expired()

        self._autocleanup_task = threading.Thread(
            target=cleanup_loop, daemon=True, name="SessionAutocleanup"
        )
        self._autocleanup_task.start()
        logger.info("Started session autocleanup")

    def stop_autocleanup(self) -> None:
        """Stop automatic cleanup background task."""
        self._autocleanup_running = False
        if self._autocleanup_task:
            self._autocleanup_task.join(timeout=2)
            self._autocleanup_task = None
            logger.info("Stopped session autocleanup")


class SecurityMiddleware:
    """
    Security middleware for session access.

    Combines token authentication and session timeout management
    to provide secure access to terminal and desktop sessions.

    Usage:
        middleware = SecurityMiddleware()
        token = middleware.create_session("client-id")

        # On subsequent access
        if middleware.check_access("client-id", token):
            # Access granted
            pass
    """

    def __init__(self, config: Optional[SecurityConfig] = None):
        """
        Initialize security middleware.

        Args:
            config: Security configuration (uses defaults if None)
        """
        self.config = config or SecurityConfig()
        self.auth = TokenAuthenticator(token_expiry=self.config.token_expiry)
        self.timeout_mgr = SessionTimeoutManager(
            timeout=self.config.session_timeout,
            max_sessions=self.config.max_concurrent_sessions,
        )

    def create_session(self, client_id: str) -> str:
        """
        Create a new authenticated session.

        Args:
            client_id: Client identifier

        Returns:
            Access token
        """
        self.timeout_mgr.register_session(client_id)
        token = self.auth.generate_token()
        logger.info(f"Created session for client: {client_id}")
        return token

    def check_access(self, client_id: str, token: Optional[str]) -> bool:
        """
        Check if client has valid access.

        Args:
            client_id: Client identifier
            token: Access token

        Returns:
            True if access is granted
        """
        # Skip token check if not required
        if not self.config.require_token:
            return self.timeout_mgr.is_active(client_id)

        # Validate token
        if not self.auth.validate_token(token):
            return False

        # Check session timeout
        if not self.timeout_mgr.is_active(client_id):
            return False

        return True

    def revoke_session(self, client_id: str) -> None:
        """
        Revoke a client's session.

        Args:
            client_id: Client identifier
        """
        self.timeout_mgr.unregister_session(client_id)
        logger.info(f"Revoked session for client: {client_id}")

    def get_status(self) -> dict:
        """
        Get security status.

        Returns:
            Dictionary with security status
        """
        return {
            "active_sessions": self.timeout_mgr.get_active_count(),
            "active_tokens": self.auth.get_token_count(),
            "max_sessions": self.config.max_concurrent_sessions,
            "session_timeout": self.config.session_timeout,
            "require_token": self.config.require_token,
        }
