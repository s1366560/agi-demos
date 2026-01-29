"""VNC Token Authentication for secure remote desktop access.

Provides token-based authentication for VNC connections to prevent
unauthorized access to the remote desktop.
"""

import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class AuthToken:
    """Authentication token for VNC access.

    Attributes:
        token: The token string
        expires_at: Unix timestamp when token expires
        workspace_dir: Workspace directory for this session
    """
    token: str
    expires_at: float
    workspace_dir: str

    def is_valid(self) -> bool:
        """Check if token is still valid."""
        return time.time() < self.expires_at

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "token": self.token,
            "expires_at": self.expires_at,
            "workspace_dir": self.workspace_dir,
        }


class VNCTokenManager:
    """Manages VNC authentication tokens.

    Generates and validates tokens for VNC access using HMAC-SHA256.

    Usage:
        manager = VNCTokenManager(secret_key="my-secret")
        token = manager.generate_token("/workspace")
        is_valid = manager.validate_token(token.token, "/workspace")
    """

    def __init__(
        self,
        secret_key: Optional[str] = None,
        token_ttl_seconds: int = 3600,
    ):
        """Initialize the token manager.

        Args:
            secret_key: Secret key for HMAC signing. If None, reads from env.
            token_ttl_seconds: Time-to-live for tokens in seconds (default: 1 hour)
        """
        self._secret_key = secret_key or os.environ.get(
            "VNC_AUTH_SECRET",
            "default-secret-change-in-production",
        )
        self._token_ttl = token_ttl_seconds
        self._revoked_tokens: Set[str] = set()

    def generate_token(self, workspace_dir: str) -> AuthToken:
        """Generate a new authentication token.

        Args:
            workspace_dir: Workspace directory for this session

        Returns:
            AuthToken instance
        """
        expires_at = time.time() + self._token_ttl

        # Create HMAC signature: hmac(expires_at:workspace_dir)
        data = f"{expires_at}:{workspace_dir}"
        signature = self._create_hmac(data)

        # Format token
        token_str = self._format_token(signature, expires_at, workspace_dir)

        return AuthToken(
            token=token_str,
            expires_at=expires_at,
            workspace_dir=workspace_dir,
        )

    def validate_token(self, token: str, workspace_dir: str) -> bool:
        """Validate an authentication token.

        Args:
            token: Token string to validate
            workspace_dir: Workspace directory to match against

        Returns:
            True if token is valid and not expired
        """
        # Check if revoked
        if token in self._revoked_tokens:
            return False

        # Parse token
        parsed = self.parse_token(token)
        if parsed is None:
            return False

        # Check expiration
        if not parsed.is_valid():
            return False

        # Check workspace match
        if parsed.workspace_dir != workspace_dir:
            return False

        # Verify HMAC signature
        data = f"{parsed.expires_at}:{workspace_dir}"
        expected_signature = self._create_hmac(data)

        # Extract signature from token
        parts = token.split(":")
        if len(parts) != 3:
            return False

        actual_signature = parts[0]
        return hmac.compare_digest(actual_signature, expected_signature)

    def parse_token(self, token: str) -> Optional[AuthToken]:
        """Parse a token string without validation.

        Args:
            token: Token string to parse

        Returns:
            AuthToken instance or None if invalid format
        """
        parts = token.split(":")
        if len(parts) != 3:
            return None

        signature, expires_at_str, workspace_dir = parts

        try:
            expires_at = float(expires_at_str)
        except ValueError:
            return None

        return AuthToken(
            token=token,
            expires_at=expires_at,
            workspace_dir=workspace_dir,
        )

    def revoke_token(self, token: str) -> bool:
        """Revoke a token (mark as invalid).

        Args:
            token: Token to revoke

        Returns:
            True if successfully revoked
        """
        # Validate token format first
        parsed = self.parse_token(token)
        if parsed is None:
            return False

        self._revoked_tokens.add(token)
        return True

    def _create_hmac(self, data: str) -> str:
        """Create HMAC signature for data.

        Args:
            data: Data to sign

        Returns:
            Hexadecimal HMAC signature
        """
        return hmac.new(
            self._secret_key.encode(),
            data.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _format_token(self, signature: str, expires_at: float, workspace_dir: str) -> str:
        """Format token components into a token string.

        Args:
            signature: HMAC signature
            expires_at: Expiration timestamp
            workspace_dir: Workspace directory

        Returns:
            Formatted token string
        """
        # URL-safe base64 encoding would be better, but hex is simpler
        return f"{signature}:{expires_at}:{workspace_dir}"
