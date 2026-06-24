"""Tests for MCP transport hardening (P1-14).

Covers:
- TLS verify default + MCP_TLS_VERIFY override + one-shot warn log.
- Global limiter zero-locked-fast-path correctness.
- Subprocess client termination on CancelledError.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.mcp import _security
from src.infrastructure.mcp._security import (
    DEFAULT_WS_HEARTBEAT_SECONDS,
    DEFAULT_WS_MAX_MSG_SIZE,
    reset_tls_warning_state_for_tests,
    tls_verify_default,
)
from src.infrastructure.mcp.clients.global_connection_limiter import (
    GlobalConnectionLimiter,
)
from src.infrastructure.mcp.clients.subprocess_client import MCPSubprocessClient

pytestmark = pytest.mark.unit

SUBPROCESS_LOGGER_NAME = "src.infrastructure.mcp.clients.subprocess_client"


class TestTLSDefaults:
    def setup_method(self) -> None:
        reset_tls_warning_state_for_tests()

    def test_default_is_verify_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_TLS_VERIFY", raising=False)
        assert tls_verify_default() is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", "disabled"])
    def test_falsy_disables(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        value: str,
    ) -> None:
        monkeypatch.setenv("MCP_TLS_VERIFY", value)
        with caplog.at_level("WARNING", logger=_security.__name__):
            assert tls_verify_default() is False
        assert any("MCP_TLS_VERIFY is disabled" in rec.message for rec in caplog.records)

    def test_warning_emitted_only_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("MCP_TLS_VERIFY", "false")
        with caplog.at_level("WARNING", logger=_security.__name__):
            tls_verify_default()
            tls_verify_default()
            tls_verify_default()
        warns = [r for r in caplog.records if "MCP_TLS_VERIFY is disabled" in r.message]
        assert len(warns) == 1

    def test_truthy_keeps_verification_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TLS_VERIFY", "true")
        assert tls_verify_default() is True

    def test_constants_match_security_defaults(self) -> None:
        assert DEFAULT_WS_HEARTBEAT_SECONDS == 30.0
        assert DEFAULT_WS_MAX_MSG_SIZE == 16 * 1024 * 1024


class TestGlobalLimiterFastPath:
    async def test_default_max_connections_is_64(self) -> None:
        limiter = GlobalConnectionLimiter()
        assert limiter.max_connections == 64

    async def test_locked_fast_path_does_not_leak_when_full(self) -> None:
        # Saturate a tiny limiter then ensure ``acquire`` blocks rather than
        # racing through the (former) zero-timeout shortcut.
        limiter = GlobalConnectionLimiter(max_connections=1)
        limiter.register_pool("ws://a", AsyncMock(return_value=False))
        await limiter.acquire("ws://a")
        assert limiter.active_count == 1

        # Second acquire from a different pool must wait — verify by racing
        # it against a tiny timeout. Eviction returns False so it should
        # actually block.
        limiter.register_pool("ws://b", AsyncMock(return_value=False))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(limiter.acquire("ws://b"), timeout=0.05)

        # The first slot must still be accounted for — no leak.
        assert limiter.active_count == 1

    async def test_fast_path_acquires_when_slot_free(self) -> None:
        limiter = GlobalConnectionLimiter(max_connections=2)
        limiter.register_pool("ws://x", AsyncMock(return_value=False))
        await limiter.acquire("ws://x")
        await limiter.acquire("ws://x")
        assert limiter.active_count == 2
        await limiter.release("ws://x")
        await limiter.release("ws://x")
        assert limiter.active_count == 0

    async def test_lru_eviction_log_redacts_callback_error(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        limiter = GlobalConnectionLimiter(max_connections=2)
        secret_error = "lru-secret-token"
        callback = AsyncMock(side_effect=RuntimeError(secret_error))
        limiter.register_pool("ws://old", callback)
        await limiter.acquire("ws://old")

        with caplog.at_level(
            logging.WARNING,
            logger="src.infrastructure.mcp.clients.global_connection_limiter",
        ):
            evicted = await limiter.try_evict_lru()

        assert evicted is False
        assert "Error during LRU eviction" in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert secret_error not in caplog.text
        callback.assert_awaited_once()

    async def test_idle_eviction_log_redacts_callback_error(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        limiter = GlobalConnectionLimiter(max_connections=2, ttl=0)
        secret_error = "idle-secret-token"
        callback = AsyncMock(side_effect=RuntimeError(secret_error))
        limiter.register_pool("ws://idle", callback)
        await limiter.acquire("ws://idle")

        with caplog.at_level(
            logging.WARNING,
            logger="src.infrastructure.mcp.clients.global_connection_limiter",
        ):
            evicted_count = await limiter.evict_idle()

        assert evicted_count == 0
        assert "Error evicting idle connection" in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert secret_error not in caplog.text
        callback.assert_awaited_once()


class TestSubprocessCancelLadder:
    async def test_connect_initialize_failure_log_redacts_response_and_stderr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = MCPSubprocessClient(command="uvx", args=["server", "--token", "arg-secret"])
        response_secret = "response-secret-token"
        stderr_secret = "stderr-secret-token"
        fake_proc = MagicMock(returncode=None)

        async def fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
            return fake_proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
        client._send_request = AsyncMock(  # type: ignore[method-assign]
            return_value={"error": {"message": response_secret}, "id": 1}
        )
        client._read_stderr = AsyncMock(return_value=f"stderr: {stderr_secret}")  # type: ignore[method-assign]
        client.disconnect = AsyncMock()  # type: ignore[method-assign]

        with caplog.at_level(logging.ERROR, logger=SUBPROCESS_LOGGER_NAME):
            connected = await client.connect(timeout=0.01)

        assert connected is False
        assert "MCP initialize request failed" in caplog.text
        assert "response_keys=" in caplog.text
        assert "MCP subprocess stderr captured" in caplog.text
        assert "stderr_chars=" in caplog.text
        assert response_secret not in caplog.text
        assert stderr_secret not in caplog.text
        assert "arg-secret" not in caplog.text
        client.disconnect.assert_awaited_once()

    async def test_connect_timeout_log_redacts_command_args_and_stderr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = MCPSubprocessClient(command="uvx", args=["server", "--token", "arg-secret"])
        stderr_secret = "timeout-stderr-secret"
        fake_proc = MagicMock(returncode=None)

        async def fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
            return fake_proc

        async def raise_timeout(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise TimeoutError

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
        client._send_request = AsyncMock(side_effect=raise_timeout)  # type: ignore[method-assign]
        client._read_stderr = AsyncMock(return_value=f"stderr: {stderr_secret}")  # type: ignore[method-assign]
        client.disconnect = AsyncMock()  # type: ignore[method-assign]

        with caplog.at_level(logging.ERROR, logger=SUBPROCESS_LOGGER_NAME):
            connected = await client.connect(timeout=0.01)

        assert connected is False
        assert "MCP connection timeout" in caplog.text
        assert "args_count=3" in caplog.text
        assert "stderr_chars=" in caplog.text
        assert "uvx" not in caplog.text
        assert "arg-secret" not in caplog.text
        assert stderr_secret not in caplog.text
        client.disconnect.assert_awaited_once()

    async def test_connect_error_log_redacts_exception_and_stderr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = MCPSubprocessClient(command="uvx", args=["server", "--token", "arg-secret"])
        stderr_secret = "error-stderr-secret"
        exception_secret = "exception-secret-token"
        fake_proc = MagicMock(returncode=None)

        async def fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
            return fake_proc

        async def raise_error(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError(exception_secret)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
        client._send_request = AsyncMock(side_effect=raise_error)  # type: ignore[method-assign]
        client._read_stderr = AsyncMock(return_value=f"stderr: {stderr_secret}")  # type: ignore[method-assign]
        client.disconnect = AsyncMock()  # type: ignore[method-assign]

        with caplog.at_level(logging.ERROR, logger=SUBPROCESS_LOGGER_NAME):
            connected = await client.connect(timeout=0.01)

        assert connected is False
        assert "Error connecting to MCP subprocess" in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "stderr_chars=" in caplog.text
        assert exception_secret not in caplog.text
        assert stderr_secret not in caplog.text
        assert "arg-secret" not in caplog.text
        client.disconnect.assert_awaited_once()

    async def test_disconnect_force_kills_on_cancellation(self) -> None:
        client = MCPSubprocessClient(command="echo", args=["stub"])

        proc = MagicMock()
        proc.terminate = MagicMock()
        proc.kill = MagicMock()

        async def waiter() -> None:
            await asyncio.sleep(60)

        proc.wait = AsyncMock(side_effect=waiter)
        client._proc = proc  # type: ignore[assignment]

        task = asyncio.create_task(client.disconnect())
        await asyncio.sleep(0)  # let disconnect start
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        assert client._proc is None

    async def test_disconnect_kill_on_terminate_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = MCPSubprocessClient(command="echo", args=["stub"])
        proc = MagicMock()
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        client._proc = proc  # type: ignore[assignment]

        # Fake wait_for to raise TimeoutError on the first call (terminate
        # phase) and then succeed on the post-kill wait.
        original_wait_for = asyncio.wait_for
        call_count = {"n": 0}

        async def fake_wait_for(*args, **kwargs):  # type: ignore[no-untyped-def]
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TimeoutError
            return await original_wait_for(*args, **kwargs)

        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

        await client.disconnect()
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        assert client._proc is None

    async def test_disconnect_error_log_redacts_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = MCPSubprocessClient(command="echo", args=["stub"])
        secret_error = "disconnect-secret-token"
        proc = MagicMock()
        proc.terminate = MagicMock(side_effect=RuntimeError(secret_error))
        proc.kill = MagicMock()
        client._proc = proc  # type: ignore[assignment]

        with caplog.at_level(logging.ERROR, logger=SUBPROCESS_LOGGER_NAME):
            await client.disconnect()

        assert "Error disconnecting MCP subprocess" in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert secret_error not in caplog.text
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        assert client._proc is None

    async def test_ping_error_log_redacts_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = MCPSubprocessClient(command="echo", args=["stub"])
        secret_error = "ping-secret-token"
        client._send_request = AsyncMock(side_effect=RuntimeError(secret_error))  # type: ignore[method-assign]

        with caplog.at_level(logging.ERROR, logger=SUBPROCESS_LOGGER_NAME):
            pinged = await client.ping(timeout=0.01)

        assert pinged is False
        assert "Ping failed" in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert secret_error not in caplog.text
        client._send_request.assert_awaited_once_with("ping", {}, timeout=0.01)  # type: ignore[attr-defined]

    async def test_notification_error_log_redacts_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = MCPSubprocessClient(command="echo", args=["stub"])
        secret_error = "notification-secret-token"
        proc = MagicMock()
        proc.stdin.write = MagicMock(side_effect=RuntimeError(secret_error))
        proc.stdin.drain = AsyncMock()
        client._proc = proc  # type: ignore[assignment]

        with caplog.at_level(logging.ERROR, logger=SUBPROCESS_LOGGER_NAME):
            await client._send_notification("notifications/cancelled", {"token": "redacted"})

        assert "MCP notification error" in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert secret_error not in caplog.text
        proc.stdin.write.assert_called_once()
        proc.stdin.drain.assert_not_awaited()
