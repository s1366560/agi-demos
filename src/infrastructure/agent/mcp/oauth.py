"""MCP OAuth Authentication Support.

This module provides OAuth 2.0 authentication support for MCP servers,
implementing RFC 7591 dynamic client registration and authorization code flow.

Components:
- MCPOAuthProvider: OAuth client provider implementation
- MCPAuthStorage: Token and credential storage
- MCPOAuthCallback: OAuth callback HTTP server

Based on vendor/opencode/packages/opencode/src/mcp/ implementation.
"""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Constants
OAUTH_CALLBACK_PORT = 19876
OAUTH_CALLBACK_PATH = "/mcp/oauth/callback"
CALLBACK_TIMEOUT_MS = 5 * 60 * 1000  # 5 minutes


# ============================================
# Data Models
# ============================================


@dataclass
class OAuthTokens:
    """OAuth tokens from authorization server."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None
    scope: Optional[str] = None


@dataclass
class OAuthClientInfo:
    """OAuth client registration information."""

    client_id: str
    client_secret: Optional[str] = None
    client_id_issued_at: Optional[float] = None
    client_secret_expires_at: Optional[float] = None


@dataclass
class MCPAuthEntry:
    """Stored authentication data for an MCP server."""

    tokens: Optional[OAuthTokens] = None
    client_info: Optional[OAuthClientInfo] = None
    code_verifier: Optional[str] = None
    oauth_state: Optional[str] = None
    server_url: Optional[str] = None  # Track URL these credentials are for


# ============================================
# Auth Storage
# ============================================


class MCPAuthStorage:
    """Storage for MCP OAuth credentials and tokens.

    Stores data in ~/.memstack/mcp-auth.json with restricted permissions.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize auth storage.

        Args:
            data_dir: Directory for storing auth data (default: ~/.memstack)
        """
        if data_dir is None:
            home = Path.home()
            data_dir = home / ".memstack"

        self._data_dir = data_dir
        self._filepath = data_dir / "mcp-auth.json"
        self._lock = asyncio.Lock()

    async def _ensure_dir(self) -> None:
        """Ensure data directory exists."""
        self._data_dir.mkdir(parents=True, exist_ok=True)

    async def _read_all(self) -> Dict[str, Dict[str, Any]]:
        """Read all auth entries from storage.

        Returns:
            Dictionary mapping MCP server names to auth data
        """
        await self._ensure_dir()

        if not self._filepath.exists():
            return {}

        try:
            content = self._filepath.read_text()
            return json.loads(content)
        except (json.JSONDecodeError, IOError):
            return {}

    def _entry_to_dict(self, entry: MCPAuthEntry) -> Dict[str, Any]:
        """Convert MCPAuthEntry to dictionary for storage.

        Args:
            entry: Auth entry to convert

        Returns:
            Dictionary representation
        """
        result: Dict[str, Any] = {}

        if entry.tokens:
            result["tokens"] = {
                "accessToken": entry.tokens.access_token,
            }
            if entry.tokens.refresh_token:
                result["tokens"]["refreshToken"] = entry.tokens.refresh_token
            if entry.tokens.expires_at:
                result["tokens"]["expiresAt"] = entry.tokens.expires_at
            if entry.tokens.scope:
                result["tokens"]["scope"] = entry.tokens.scope

        if entry.client_info:
            result["clientInfo"] = {
                "clientId": entry.client_info.client_id,
            }
            if entry.client_info.client_secret:
                result["clientInfo"]["clientSecret"] = entry.client_info.client_secret
            if entry.client_info.client_id_issued_at:
                result["clientInfo"]["clientIdIssuedAt"] = entry.client_info.client_id_issued_at
            if entry.client_info.client_secret_expires_at:
                result["clientInfo"]["clientSecretExpiresAt"] = (
                    entry.client_info.client_secret_expires_at
                )

        if entry.code_verifier:
            result["codeVerifier"] = entry.code_verifier

        if entry.oauth_state:
            result["oauthState"] = entry.oauth_state

        if entry.server_url:
            result["serverUrl"] = entry.server_url

        return result

    def _dict_to_entry(self, data: Dict[str, Any]) -> MCPAuthEntry:
        """Convert dictionary to MCPAuthEntry.

        Args:
            data: Dictionary from storage

        Returns:
            MCPAuthEntry instance
        """
        entry = MCPAuthEntry()

        if "tokens" in data:
            tokens_data = data["tokens"]
            entry.tokens = OAuthTokens(
                access_token=tokens_data["accessToken"],
                refresh_token=tokens_data.get("refreshToken"),
                expires_at=tokens_data.get("expiresAt"),
                scope=tokens_data.get("scope"),
            )

        if "clientInfo" in data:
            client_data = data["clientInfo"]
            entry.client_info = OAuthClientInfo(
                client_id=client_data["clientId"],
                client_secret=client_data.get("clientSecret"),
                client_id_issued_at=client_data.get("clientIdIssuedAt"),
                client_secret_expires_at=client_data.get("clientSecretExpiresAt"),
            )

        if "codeVerifier" in data:
            entry.code_verifier = data["codeVerifier"]

        if "oauthState" in data:
            entry.oauth_state = data["oauthState"]

        if "serverUrl" in data:
            entry.server_url = data["serverUrl"]

        return entry

    async def get(self, mcp_name: str) -> Optional[MCPAuthEntry]:
        """Get auth entry for MCP server.

        Args:
            mcp_name: Name of the MCP server

        Returns:
            Auth entry or None if not found
        """
        async with self._lock:
            all_data = await self._read_all()
            data = all_data.get(mcp_name)
            if data:
                return self._dict_to_entry(data)
            return None

    async def get_for_url(self, mcp_name: str, server_url: str) -> Optional[MCPAuthEntry]:
        """Get auth entry and validate it's for the correct URL.

        Args:
            mcp_name: Name of the MCP server
            server_url: Server URL to validate against

        Returns:
            Auth entry if valid, None otherwise
        """
        entry = await self.get(mcp_name)
        if not entry:
            return None

        # If no serverUrl is stored, this is from an old version - consider it invalid
        if not entry.server_url:
            return None

        # If URL has changed, credentials are invalid
        if entry.server_url != server_url:
            return None

        return entry

    async def set(
        self, mcp_name: str, entry: MCPAuthEntry, server_url: Optional[str] = None
    ) -> None:
        """Save auth entry for MCP server.

        Args:
            mcp_name: Name of the MCP server
            entry: Auth entry to save
            server_url: Optional server URL to associate with entry
        """
        async with self._lock:
            await self._ensure_dir()

            all_data = await self._read_all()

            # Always update serverUrl if provided
            if server_url:
                entry.server_url = server_url

            all_data[mcp_name] = self._entry_to_dict(entry)

            # Write with restricted permissions
            self._filepath.write_text(json.dumps(all_data, indent=2))
            os.chmod(self._filepath, 0o600)

            logger.info(f"Saved auth entry for MCP server: {mcp_name}")

    async def remove(self, mcp_name: str) -> None:
        """Remove auth entry for MCP server.

        Args:
            mcp_name: Name of the MCP server
        """
        async with self._lock:
            all_data = await self._read_all()

            if mcp_name in all_data:
                del all_data[mcp_name]
                await self._ensure_dir()
                self._filepath.write_text(json.dumps(all_data, indent=2))
                os.chmod(self._filepath, 0o600)
                logger.info(f"Removed auth entry for MCP server: {mcp_name}")

    async def update_tokens(
        self, mcp_name: str, tokens: OAuthTokens, server_url: Optional[str] = None
    ) -> None:
        """Update tokens for MCP server.

        Args:
            mcp_name: Name of the MCP server
            tokens: New OAuth tokens
            server_url: Optional server URL to associate with tokens
        """
        entry = await self.get(mcp_name) or MCPAuthEntry()
        entry.tokens = tokens
        await self.set(mcp_name, entry, server_url)

    async def update_client_info(
        self, mcp_name: str, client_info: OAuthClientInfo, server_url: Optional[str] = None
    ) -> None:
        """Update client info for MCP server.

        Args:
            mcp_name: Name of the MCP server
            client_info: OAuth client registration info
            server_url: Optional server URL to associate with client info
        """
        entry = await self.get(mcp_name) or MCPAuthEntry()
        entry.client_info = client_info
        await self.set(mcp_name, entry, server_url)

    async def update_code_verifier(self, mcp_name: str, code_verifier: str) -> None:
        """Update PKCE code verifier for MCP server.

        Args:
            mcp_name: Name of the MCP server
            code_verifier: PKCE code verifier
        """
        entry = await self.get(mcp_name) or MCPAuthEntry()
        entry.code_verifier = code_verifier
        await self.set(mcp_name, entry)

    async def clear_code_verifier(self, mcp_name: str) -> None:
        """Clear PKCE code verifier for MCP server.

        Args:
            mcp_name: Name of the MCP server
        """
        entry = await self.get(mcp_name)
        if entry and entry.code_verifier:
            entry.code_verifier = None
            await self.set(mcp_name, entry)

    async def update_oauth_state(self, mcp_name: str, oauth_state: str) -> None:
        """Update OAuth state for MCP server.

        Args:
            mcp_name: Name of the MCP server
            oauth_state: OAuth state parameter
        """
        entry = await self.get(mcp_name) or MCPAuthEntry()
        entry.oauth_state = oauth_state
        await self.set(mcp_name, entry)

    async def clear_oauth_state(self, mcp_name: str) -> None:
        """Clear OAuth state for MCP server.

        Args:
            mcp_name: Name of the MCP server
        """
        entry = await self.get(mcp_name)
        if entry and entry.oauth_state:
            entry.oauth_state = None
            await self.set(mcp_name, entry)

    async def is_token_expired(self, mcp_name: str) -> Optional[bool]:
        """Check if stored tokens are expired.

        Args:
            mcp_name: Name of the MCP server

        Returns:
            None if no tokens exist, False if no expiry or not expired, True if expired
        """
        entry = await self.get(mcp_name)
        if not entry or not entry.tokens:
            return None
        if not entry.tokens.expires_at:
            return False
        return entry.tokens.expires_at < time.time()


# ============================================
# OAuth Provider
# ============================================


class MCPOAuthProvider:
    """OAuth client provider for MCP servers.

    Implements OAuth 2.0 authorization code flow with PKCE,
    supporting both pre-registered and dynamically registered clients.

    Based on vendor/opencode/packages/opencode/src/mcp/oauth-provider.ts
    """

    def __init__(
        self,
        mcp_name: str,
        server_url: str,
        storage: MCPAuthStorage,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
    ):
        """Initialize OAuth provider.

        Args:
            mcp_name: Name of the MCP server
            server_url: URL of the MCP server
            storage: Auth storage instance
            client_id: Optional pre-registered client ID
            client_secret: Optional pre-registered client secret
            scope: Optional OAuth scope
        """
        self._mcp_name = mcp_name
        self._server_url = server_url
        self._storage = storage
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope

    @property
    def redirect_url(self) -> str:
        """Get OAuth redirect URL."""
        return f"http://127.0.0.1:{OAUTH_CALLBACK_PORT}{OAUTH_CALLBACK_PATH}"

    @property
    def client_metadata(self) -> Dict[str, Any]:
        """Get OAuth client metadata for dynamic registration."""
        return {
            "redirect_uris": [self.redirect_url],
            "client_name": "MemStack",
            "client_uri": "https://memstack.ai",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post" if self._client_secret else "none",
        }

    async def client_information(self) -> Optional[OAuthClientInfo]:
        """Get OAuth client information.

        Checks in order:
        1. Pre-configured client_id/client_secret
        2. Stored client info from dynamic registration
        3. Returns None if no client info (triggers dynamic registration)

        Returns:
            OAuth client info or None
        """
        # Check pre-configured client
        if self._client_id:
            return OAuthClientInfo(
                client_id=self._client_id,
                client_secret=self._client_secret,
            )

        # Check stored client info (validate URL matches)
        entry = await self._storage.get_for_url(self._mcp_name, self._server_url)
        if entry and entry.client_info:
            # Check if client secret has expired
            if (
                entry.client_info.client_secret_expires_at
                and entry.client_info.client_secret_expires_at < time.time()
            ):
                logger.info(f"Client secret expired for {self._mcp_name}")
                return None
            return entry.client_info

        # No client info - will trigger dynamic registration
        return None

    async def save_client_information(
        self,
        client_id: str,
        client_secret: Optional[str] = None,
        client_id_issued_at: Optional[float] = None,
        client_secret_expires_at: Optional[float] = None,
    ) -> None:
        """Save dynamically registered client information.

        Args:
            client_id: Client ID from registration response
            client_secret: Optional client secret from registration response
            client_id_issued_at: Optional timestamp when client ID was issued
            client_secret_expires_at: Optional timestamp when client secret expires
        """
        client_info = OAuthClientInfo(
            client_id=client_id,
            client_secret=client_secret,
            client_id_issued_at=client_id_issued_at,
            client_secret_expires_at=client_secret_expires_at,
        )
        await self._storage.update_client_info(self._mcp_name, client_info, self._server_url)
        logger.info(f"Saved dynamically registered client for {self._mcp_name}: {client_id}")

    async def get_tokens(self) -> Optional[OAuthTokens]:
        """Get stored OAuth tokens.

        Returns:
            OAuth tokens or None if not found/expired
        """
        entry = await self._storage.get_for_url(self._mcp_name, self._server_url)
        if not entry or not entry.tokens:
            return None

        return entry.tokens

    async def save_tokens(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
        scope: Optional[str] = None,
    ) -> None:
        """Save OAuth tokens.

        Args:
            access_token: Access token from authorization response
            refresh_token: Optional refresh token
            expires_in: Optional lifetime in seconds
            scope: Optional scope granted
        """
        expires_at = None
        if expires_in:
            expires_at = time.time() + expires_in

        tokens = OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
        )
        await self._storage.update_tokens(self._mcp_name, tokens, self._server_url)
        logger.info(f"Saved OAuth tokens for {self._mcp_name}")

    async def generate_code_verifier(self) -> str:
        """Generate PKCE code verifier and challenge.

        Returns:
            Code challenge to send in authorization request
        """
        # Generate code verifier (43-128 characters)
        code_verifier = secrets.token_urlsafe(32)

        # Save verifier for later token exchange
        await self._storage.update_code_verifier(self._mcp_name, code_verifier)

        # Generate code challenge (S256 method)
        challenge_bytes = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64_url_encode(challenge_bytes)

        return code_challenge

    async def get_code_verifier(self) -> str:
        """Get stored PKCE code verifier.

        Returns:
            Code verifier for token exchange

        Raises:
            ValueError: If no code verifier was saved
        """
        entry = await self._storage.get(self._mcp_name)
        if not entry or not entry.code_verifier:
            raise ValueError(f"No code verifier saved for MCP server: {self._mcp_name}")
        return entry.code_verifier

    async def save_oauth_state(self) -> str:
        """Generate and save OAuth state parameter.

        Returns:
            State parameter for authorization request
        """
        oauth_state = secrets.token_urlsafe(16)
        await self._storage.update_oauth_state(self._mcp_name, oauth_state)
        return oauth_state

    async def get_oauth_state(self) -> str:
        """Get stored OAuth state parameter.

        Returns:
            OAuth state parameter

        Raises:
            ValueError: If no state was saved
        """
        entry = await self._storage.get(self._mcp_name)
        if not entry or not entry.oauth_state:
            raise ValueError(f"No OAuth state saved for MCP server: {self._mcp_name}")
        return entry.oauth_state


def base64_url_encode(data: bytes) -> str:
    """Base64 URL-safe encode without padding.

    Args:
        data: Bytes to encode

    Returns:
        URL-safe base64 string without padding
    """
    import base64

    return base64.urlsafe_b64encode(data).decode().rstrip("=")
