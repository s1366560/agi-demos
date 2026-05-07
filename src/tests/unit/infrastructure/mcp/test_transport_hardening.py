"""Tests for MCP transport hardening (P1-14).

Covers:
- TLS verify default + MCP_TLS_VERIFY override + one-shot warn log.
- Global limiter zero-locked-fast-path correctness.
- Subprocess client termination on CancelledError.
"""

from __future__ import annotations

import asyncio
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


class TestSubprocessCancelLadder:
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
