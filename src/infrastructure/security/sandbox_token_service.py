"""Sandbox Token Service - Token generation and validation for sandbox connections.

Provides secure token-based authentication for sandbox WebSocket connections,
supporting both cloud sandboxes and local sandboxes (via tunnel).

Features:
- Project-scoped short-lived tokens (5-15 minutes)
- Token validation with project/user context
- Support for local sandbox connection authentication
"""

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default token TTL in seconds (5 minutes)
DEFAULT_TOKEN_TTL = 300


@dataclass(frozen=True)
class SandboxAccessToken:
    """Sandbox access token with metadata."""

    token: str
    project_id: str
    user_id: str
    tenant_id: str
    sandbox_type: str  # "cloud" or "local"
    expires_at: datetime
    created_at: datetime

    def is_expired(self) -> bool:
        """Check if token has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "token": self.token,
            "project_id": self.project_id,
            "sandbox_type": self.sandbox_type,
            "expires_at": self.expires_at.isoformat(),
            "expires_in": max(0, int((self.expires_at - datetime.now(timezone.utc)).total_seconds())),
        }


@dataclass
class TokenValidationResult:
    """Result of token validation."""

    valid: bool
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    sandbox_type: Optional[str] = None
    error: Optional[str] = None


class SandboxTokenService:
    """Service for generating and validating sandbox access tokens.

    Tokens are used for authenticating WebSocket connections to sandboxes,
    especially important for local sandboxes accessed via tunnel.

    The token format is: {random_part}.{signature}
    where signature = HMAC(secret_key, random_part + project_id + user_id + expires_at)
    """

    def __init__(
        self,
        secret_key: str,
        token_ttl: int = DEFAULT_TOKEN_TTL,
        token_store: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """Initialize token service.

        Args:
            secret_key: Secret key for token signing (should be from settings)
            token_ttl: Token time-to-live in seconds
            token_store: Optional external token store (for distributed deployments)
        """
        self._secret_key = secret_key.encode() if isinstance(secret_key, str) else secret_key
        self._token_ttl = token_ttl
        # In-memory store for simple deployments; use Redis for production
        self._tokens: Dict[str, Dict[str, Any]] = token_store if token_store is not None else {}

    def generate_token(
        self,
        project_id: str,
        user_id: str,
        tenant_id: str,
        sandbox_type: str = "cloud",
        ttl_override: Optional[int] = None,
    ) -> SandboxAccessToken:
        """Generate a new sandbox access token.

        Args:
            project_id: Project ID the token is scoped to
            user_id: User ID requesting the token
            tenant_id: Tenant ID for multi-tenant isolation
            sandbox_type: Type of sandbox ("cloud" or "local")
            ttl_override: Override default TTL (in seconds)

        Returns:
            SandboxAccessToken with token string and metadata
        """
        now = datetime.now(timezone.utc)
        ttl = ttl_override if ttl_override is not None else self._token_ttl
        expires_at = now + timedelta(seconds=ttl)

        # Generate random token part
        random_part = secrets.token_urlsafe(32)

        # Create signature
        expires_ts = str(int(expires_at.timestamp()))
        data_to_sign = f"{random_part}:{project_id}:{user_id}:{expires_ts}"
        signature = self._create_signature(data_to_sign)

        # Full token: random_part.signature
        token = f"{random_part}.{signature}"

        # Store token metadata (for validation and revocation)
        self._tokens[token] = {
            "project_id": project_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "sandbox_type": sandbox_type,
            "expires_at": expires_at.isoformat(),
            "created_at": now.isoformat(),
        }

        logger.info(
            f"Generated sandbox token for project={project_id}, user={user_id}, "
            f"type={sandbox_type}, expires_in={ttl}s"
        )

        return SandboxAccessToken(
            token=token,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            sandbox_type=sandbox_type,
            expires_at=expires_at,
            created_at=now,
        )

    def validate_token(
        self,
        token: str,
        project_id: Optional[str] = None,
    ) -> TokenValidationResult:
        """Validate a sandbox access token.

        Args:
            token: Token string to validate
            project_id: Optional project ID to verify against

        Returns:
            TokenValidationResult with validation status and metadata
        """
        if not token:
            return TokenValidationResult(valid=False, error="Token is required")

        # Check if token exists in store
        token_data = self._tokens.get(token)
        if not token_data:
            logger.warning(f"Token not found in store: {token[:20]}...")
            return TokenValidationResult(valid=False, error="Invalid or expired token")

        # Check expiration
        try:
            expires_at = datetime.fromisoformat(token_data["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                # Clean up expired token
                del self._tokens[token]
                logger.info(f"Token expired for project={token_data.get('project_id')}")
                return TokenValidationResult(valid=False, error="Token has expired")
        except (KeyError, ValueError) as e:
            logger.error(f"Invalid token data: {e}")
            return TokenValidationResult(valid=False, error="Invalid token format")

        # Verify project_id if provided
        stored_project_id = token_data.get("project_id")
        if project_id and stored_project_id != project_id:
            logger.warning(
                f"Token project mismatch: expected={project_id}, got={stored_project_id}"
            )
            return TokenValidationResult(valid=False, error="Token does not match project")

        return TokenValidationResult(
            valid=True,
            project_id=stored_project_id,
            user_id=token_data.get("user_id"),
            tenant_id=token_data.get("tenant_id"),
            sandbox_type=token_data.get("sandbox_type"),
        )

    def revoke_token(self, token: str) -> bool:
        """Revoke a token (delete from store).

        Args:
            token: Token to revoke

        Returns:
            True if token was revoked, False if not found
        """
        if token in self._tokens:
            del self._tokens[token]
            logger.info(f"Revoked sandbox token: {token[:20]}...")
            return True
        return False

    def revoke_all_for_project(self, project_id: str) -> int:
        """Revoke all tokens for a project.

        Args:
            project_id: Project ID to revoke tokens for

        Returns:
            Number of tokens revoked
        """
        tokens_to_revoke = [
            token for token, data in self._tokens.items() if data.get("project_id") == project_id
        ]

        for token in tokens_to_revoke:
            del self._tokens[token]

        if tokens_to_revoke:
            logger.info(f"Revoked {len(tokens_to_revoke)} tokens for project={project_id}")

        return len(tokens_to_revoke)

    def cleanup_expired(self) -> int:
        """Clean up expired tokens from store.

        Returns:
            Number of tokens cleaned up
        """
        now = datetime.now(timezone.utc)
        expired = [
            token
            for token, data in self._tokens.items()
            if datetime.fromisoformat(data.get("expires_at", "1970-01-01")) < now
        ]

        for token in expired:
            del self._tokens[token]

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired tokens")

        return len(expired)

    def _create_signature(self, data: str) -> str:
        """Create HMAC signature for data.

        Args:
            data: Data string to sign

        Returns:
            Hex-encoded signature
        """
        return hmac.new(
            self._secret_key,
            data.encode(),
            hashlib.sha256,
        ).hexdigest()[:32]  # Use first 32 chars for shorter tokens

    def get_active_token_count(self, project_id: Optional[str] = None) -> int:
        """Get count of active (non-expired) tokens.

        Args:
            project_id: Optional filter by project

        Returns:
            Count of active tokens
        """
        now = datetime.now(timezone.utc)
        count = 0
        for token, data in self._tokens.items():
            try:
                expires_at = datetime.fromisoformat(data.get("expires_at", "1970-01-01"))
                if expires_at > now:
                    if project_id is None or data.get("project_id") == project_id:
                        count += 1
            except ValueError:
                pass
        return count
