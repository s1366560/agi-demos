"""Instance channel configuration service."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from websockets.asyncio.client import connect as websocket_connect

from src.domain.model.instance.instance_channel import InstanceChannelConfig
from src.domain.ports.repositories.instance_channel_repository import (
    InstanceChannelRepository,
)

logger = logging.getLogger(__name__)


class ChannelConnectionError(RuntimeError):
    """Raised when an instance channel connection check cannot complete."""


class InstanceChannelService:
    """Service for managing instance-scoped channel configurations."""

    def __init__(self, channel_repo: InstanceChannelRepository) -> None:
        self._channel_repo = channel_repo

    async def list_channels(self, instance_id: str) -> list[InstanceChannelConfig]:
        """List all channel configs for an instance."""
        return await self._channel_repo.find_by_instance_id(instance_id)

    async def create_channel(
        self,
        instance_id: str,
        channel_type: str,
        name: str,
        config: dict[str, object],
    ) -> InstanceChannelConfig:
        """Create a new channel config for an instance."""
        entity = InstanceChannelConfig(
            instance_id=instance_id,
            channel_type=channel_type,
            name=name,
            config=config,
        )
        return await self._channel_repo.save(entity)

    async def update_channel(
        self,
        channel_id: str,
        name: str | None = None,
        config: dict[str, object] | None = None,
    ) -> InstanceChannelConfig:
        """Update an existing channel config."""
        entity = await self._channel_repo.find_by_id(channel_id)
        if not entity:
            msg = f"Channel not found: {channel_id}"
            raise ValueError(msg)
        if name is not None:
            entity.name = name
        if config is not None:
            entity.config = config
        entity.updated_at = datetime.now(UTC)
        return await self._channel_repo.update(entity)

    async def delete_channel(self, channel_id: str) -> None:
        """Soft-delete a channel config."""
        entity = await self._channel_repo.find_by_id(channel_id)
        if not entity:
            msg = f"Channel not found: {channel_id}"
            raise ValueError(msg)
        await self._channel_repo.delete(channel_id)

    async def test_connection(self, channel_id: str) -> dict[str, str]:
        """Test a channel connection and persist the observed status."""
        entity = await self._channel_repo.find_by_id(channel_id)
        if not entity:
            msg = f"Channel not found: {channel_id}"
            raise ValueError(msg)

        try:
            message = await self._run_connection_test(entity)
        except ChannelConnectionError as exc:
            entity.status = "error"
            entity.updated_at = datetime.now(UTC)
            await self._channel_repo.update(entity)
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            entity.status = "error"
            entity.updated_at = datetime.now(UTC)
            await self._channel_repo.update(entity)
            logger.warning("Instance channel connection test failed: %s", exc)
            return {"status": "error", "message": "Connection test failed"}

        now = datetime.now(UTC)
        entity.last_connected_at = now
        entity.status = "connected"
        entity.updated_at = now
        await self._channel_repo.update(entity)
        return {"status": "ok", "message": message}

    async def _run_connection_test(self, entity: InstanceChannelConfig) -> str:
        handlers: dict[
            str,
            Callable[[InstanceChannelConfig], Awaitable[str]],
        ] = {
            "api": self._test_api_channel,
            "email": self._test_email_channel,
            "mcp": self._test_mcp_channel,
            "webhook": self._test_webhook_channel,
            "websocket": self._test_websocket_channel,
        }
        channel_type = entity.channel_type.strip().lower()
        handler = handlers.get(channel_type)
        if handler is None:
            msg = f"Connection testing is not supported for {entity.channel_type} channels"
            raise ChannelConnectionError(msg)
        return await handler(entity)

    async def _test_mcp_channel(self, entity: InstanceChannelConfig) -> str:
        url = self._required_config_str(entity.config, "server_url")
        timeout = self._connection_timeout(entity.config)
        return await self._test_websocket_url(url, label="MCP server", timeout=timeout)

    async def _test_websocket_channel(self, entity: InstanceChannelConfig) -> str:
        url = self._required_config_str(entity.config, "url", "server_url")
        timeout = self._connection_timeout(entity.config)
        return await self._test_websocket_url(url, label="WebSocket endpoint", timeout=timeout)

    async def _test_webhook_channel(self, entity: InstanceChannelConfig) -> str:
        url = self._required_config_str(entity.config, "url")
        timeout = self._connection_timeout(entity.config)
        return await self._test_http_endpoint(url, label="Webhook endpoint", timeout=timeout)

    async def _test_api_channel(self, entity: InstanceChannelConfig) -> str:
        url = self._required_config_str(entity.config, "base_url", "url")
        timeout = self._connection_timeout(entity.config)
        headers = self._api_headers(entity.config)
        return await self._test_http_endpoint(
            url,
            label="API endpoint",
            timeout=timeout,
            headers=headers,
        )

    async def _test_email_channel(self, entity: InstanceChannelConfig) -> str:
        host = self._required_config_str(entity.config, "host", "smtp_host")
        port = self._connection_port(entity.config, default=587)
        timeout = self._connection_timeout(entity.config)
        use_tls = self._config_bool(entity.config, "start_tls", default=True)
        username = self._optional_config_str(entity.config, "username", "user")
        password = self._optional_config_str(entity.config, "password")

        try:
            await asyncio.to_thread(
                self._test_smtp_endpoint,
                host,
                port,
                timeout,
                use_tls,
                username,
                password,
            )
        except (OSError, smtplib.SMTPException) as exc:
            msg = f"SMTP endpoint is unreachable: {exc.__class__.__name__}"
            raise ChannelConnectionError(msg) from exc
        return "SMTP endpoint reachable"

    async def _test_websocket_url(self, url: str, *, label: str, timeout: float) -> str:
        self._validate_url(url, allowed_schemes={"ws", "wss"})
        try:
            async with websocket_connect(url, open_timeout=timeout):
                return f"{label} handshake successful"
        except Exception as exc:
            msg = f"{label} handshake failed: {exc.__class__.__name__}"
            raise ChannelConnectionError(msg) from exc

    async def _test_http_endpoint(
        self,
        url: str,
        *,
        label: str,
        timeout: float,
        headers: dict[str, str] | None = None,
    ) -> str:
        self._validate_url(url, allowed_schemes={"http", "https"})
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.head(url, headers=headers)
        except httpx.HTTPError as exc:
            msg = f"{label} is unreachable: {exc.__class__.__name__}"
            raise ChannelConnectionError(msg) from exc

        if response.status_code >= 500:
            msg = f"{label} returned HTTP {response.status_code}"
            raise ChannelConnectionError(msg)
        return f"{label} reachable (HTTP {response.status_code})"

    @staticmethod
    def _test_smtp_endpoint(
        host: str,
        port: int,
        timeout: float,
        use_tls: bool,
        username: str | None,
        password: str | None,
    ) -> None:
        with smtplib.SMTP(host=host, port=port, timeout=timeout) as client:
            client.ehlo()
            if use_tls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if username or password:
                if not username or not password:
                    msg = "SMTP username and password must be provided together"
                    raise smtplib.SMTPException(msg)
                client.login(username, password)
            client.noop()

    @staticmethod
    def _required_config_str(config: dict[str, object], *keys: str) -> str:
        value = InstanceChannelService._optional_config_str(config, *keys)
        if value is None:
            msg = f"Missing required config field: {keys[0]}"
            raise ChannelConnectionError(msg)
        return value

    @staticmethod
    def _optional_config_str(config: dict[str, object], *keys: str) -> str | None:
        for key in keys:
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _connection_timeout(config: dict[str, object]) -> float:
        value = config.get("timeout")
        if isinstance(value, bool):
            return 10.0
        if isinstance(value, (int, float)):
            return min(max(float(value), 1.0), 300.0)
        return 10.0

    @staticmethod
    def _connection_port(config: dict[str, object], *, default: int) -> int:
        value = config.get("port")
        if isinstance(value, bool):
            return default
        if isinstance(value, int) and 0 < value <= 65535:
            return value
        return default

    @staticmethod
    def _config_bool(config: dict[str, object], key: str, *, default: bool) -> bool:
        value = config.get(key)
        if isinstance(value, bool):
            return value
        return default

    @staticmethod
    def _api_headers(config: dict[str, object]) -> dict[str, str]:
        api_key = InstanceChannelService._optional_config_str(config, "api_key", "token")
        if api_key is None:
            return {}
        scheme = InstanceChannelService._optional_config_str(config, "auth_scheme") or "Bearer"
        return {"Authorization": f"{scheme} {api_key}"}

    @staticmethod
    def _validate_url(url: str, *, allowed_schemes: set[str]) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in allowed_schemes or not parsed.netloc:
            allowed = ", ".join(sorted(allowed_schemes))
            msg = f"Invalid endpoint URL; expected one of: {allowed}"
            raise ChannelConnectionError(msg)
