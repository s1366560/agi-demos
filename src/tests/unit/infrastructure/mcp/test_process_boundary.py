"""Unit tests for the R2 MCP process boundary hardening."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

import pytest

from src.infrastructure.mcp.process_boundary import (
    DEFAULT_MAX_OUTPUT_BYTES,
    MCP_STDIO_INHERIT_ENV,
    UNTRUSTED_MAX_OUTPUT_BYTES,
    MCPProcessBoundaryPolicy,
    MCPServerTrustTier,
    classify_trust_tier,
    emit_process_audit,
    sanitize_subprocess_env,
    spawn_mcp_server_process,
)

HOST_ENV = {
    "PATH": "/usr/bin",
    "HOME": "/home/test",
    "LANG": "en_US.UTF-8",
    "OPENAI_API_KEY": "sk-host-secret",
    "AWS_SECRET_ACCESS_KEY": "aws-secret",
    "DATABASE_URL": "postgres://secret",
}


@pytest.mark.unit
class TestSanitizeSubprocessEnv:
    def test_tenant_approved_strips_host_secrets(self) -> None:
        env = sanitize_subprocess_env(
            None,
            tier=MCPServerTrustTier.TENANT_APPROVED,
            environ=HOST_ENV,
        )
        assert env["PATH"] == "/usr/bin"
        assert env["HOME"] == "/home/test"
        assert "OPENAI_API_KEY" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "DATABASE_URL" not in env

    def test_explicit_env_always_passes_through(self) -> None:
        env = sanitize_subprocess_env(
            {"SERVER_TOKEN": "operator-provided"},
            tier=MCPServerTrustTier.UNTRUSTED,
            environ=HOST_ENV,
        )
        assert env["SERVER_TOKEN"] == "operator-provided"

    def test_untrusted_uses_minimal_allowlist(self) -> None:
        env = sanitize_subprocess_env(
            None,
            tier=MCPServerTrustTier.UNTRUSTED,
            environ=HOST_ENV,
        )
        assert env["PATH"] == "/usr/bin"
        assert "HOME" not in env
        assert "OPENAI_API_KEY" not in env

    def test_builtin_inherits_host_environment(self) -> None:
        env = sanitize_subprocess_env(
            None,
            tier=MCPServerTrustTier.BUILTIN,
            environ=HOST_ENV,
        )
        assert env["OPENAI_API_KEY"] == "sk-host-secret"

    def test_inherit_env_override_restores_legacy_behavior(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MCP_STDIO_INHERIT_ENV, "1")
        env = sanitize_subprocess_env(
            None,
            tier=MCPServerTrustTier.UNTRUSTED,
            environ=HOST_ENV,
        )
        assert env["AWS_SECRET_ACCESS_KEY"] == "aws-secret"

    def test_inherit_env_override_falsy_values_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MCP_STDIO_INHERIT_ENV, "off")
        env = sanitize_subprocess_env(
            None,
            tier=MCPServerTrustTier.UNTRUSTED,
            environ=HOST_ENV,
        )
        assert "AWS_SECRET_ACCESS_KEY" not in env


@pytest.mark.unit
class TestClassifyTrustTier:
    def test_builtin_command_basename_match(self) -> None:
        tier = classify_trust_tier(["/usr/bin/env", "python"], builtin_commands=frozenset({"env"}))
        assert tier is MCPServerTrustTier.BUILTIN

    def test_default_is_tenant_approved(self) -> None:
        assert (
            classify_trust_tier(["uvx", "mcp-server-fetch"]) is MCPServerTrustTier.TENANT_APPROVED
        )

    def test_empty_command_defaults_tenant_approved(self) -> None:
        assert classify_trust_tier([]) is MCPServerTrustTier.TENANT_APPROVED


@pytest.mark.unit
class TestBoundaryPolicy:
    def test_untrusted_policy_kills_on_timeout(self) -> None:
        policy = MCPProcessBoundaryPolicy.for_tier(MCPServerTrustTier.UNTRUSTED)
        assert policy.kill_on_timeout is True
        assert policy.max_output_bytes == UNTRUSTED_MAX_OUTPUT_BYTES

    def test_tenant_approved_policy_keeps_generous_budget(self) -> None:
        policy = MCPProcessBoundaryPolicy.for_tier(MCPServerTrustTier.TENANT_APPROVED)
        assert policy.kill_on_timeout is False
        assert policy.max_output_bytes == DEFAULT_MAX_OUTPUT_BYTES


@pytest.mark.unit
class TestSpawnAudit:
    async def test_spawn_emits_audit_event(self) -> None:
        events: list[dict[str, object]] = []
        proc = await spawn_mcp_server_process(
            [sys.executable, "-c", "pass"],
            env={"PATH": "/usr/bin"},
            server_name="test-server",
            audit=lambda event: events.append(dict(event)),
        )
        try:
            assert proc.pid is not None
        finally:
            proc.terminate()
            await proc.wait()
        assert len(events) == 1
        event = events[0]
        assert event["event"] == "mcp_server_spawn"
        assert event["server_name"] == "test-server"
        assert event["trust_tier"] == MCPServerTrustTier.TENANT_APPROVED.value
        # Args are counted, never logged (they may carry credentials).
        assert event["args_count"] == 2
        assert "-c" not in str(event)

    async def test_spawn_respects_explicit_policy(self) -> None:
        events: list[dict[str, object]] = []
        proc = await spawn_mcp_server_process(
            [sys.executable, "-c", "pass"],
            env=None,
            server_name="untrusted-server",
            policy=MCPProcessBoundaryPolicy.for_tier(MCPServerTrustTier.UNTRUSTED),
            audit=lambda event: events.append(dict(event)),
        )
        try:
            assert proc.pid is not None
        finally:
            proc.terminate()
            await proc.wait()
        assert events[0]["trust_tier"] == MCPServerTrustTier.UNTRUSTED.value
        assert events[0]["max_output_bytes"] == UNTRUSTED_MAX_OUTPUT_BYTES

    def test_emit_process_audit_defaults_to_plugin_audit_logger(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="plugin_audit"):
            emit_process_audit({"event": "mcp_server_spawn", "server_name": "x"})
        assert "mcp_server_spawn" in caplog.text


class _HangingStdout:
    async def readline(self) -> bytes:
        await asyncio.sleep(30)
        return b""


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = _HangingStdout()
        self.stderr = None
        self.returncode: int | None = None
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def _capture_audit_events(module: Any, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        module,
        "emit_process_audit",
        lambda event, sink=None: events.append(dict(event)),
    )
    return events


@pytest.mark.unit
class TestStdioTransportBoundary:
    async def test_start_uses_scrubbed_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.domain.model.mcp.transport import TransportConfig
        from src.infrastructure.mcp.transport import stdio as stdio_module
        from src.infrastructure.mcp.transport.base import MCPTransportError
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        captured: dict[str, Any] = {}

        async def fake_spawn(command: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            raise OSError("stop after capture")

        monkeypatch.setattr(stdio_module, "spawn_mcp_server_process", fake_spawn)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-host-secret")

        transport = StdioTransport()
        config = TransportConfig.local(command=["test-server"], environment={"A": "1"})

        with pytest.raises(MCPTransportError):
            await transport.start(config)

        env = captured["env"]
        assert env["A"] == "1"
        assert "OPENAI_API_KEY" not in env
        assert captured["server_name"] == "test-server"

    async def test_receive_timeout_kills_when_policy_requires(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.infrastructure.mcp.transport import stdio as stdio_module
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        events = _capture_audit_events(stdio_module, monkeypatch)
        process = _FakeProcess()
        transport = StdioTransport()
        transport._process = process  # type: ignore[assignment]
        transport._policy = MCPProcessBoundaryPolicy.for_tier(MCPServerTrustTier.UNTRUSTED)

        with pytest.raises(TimeoutError):
            await transport.receive(timeout=0.01)

        assert process.killed is True
        event_names = [event["event"] for event in events]
        assert "mcp_server_timeout" in event_names
        assert "mcp_server_kill" in event_names

    async def test_receive_timeout_keeps_alive_for_tenant_approved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.infrastructure.mcp.transport import stdio as stdio_module
        from src.infrastructure.mcp.transport.stdio import StdioTransport

        events = _capture_audit_events(stdio_module, monkeypatch)
        process = _FakeProcess()
        transport = StdioTransport()
        transport._process = process  # type: ignore[assignment]
        transport._policy = MCPProcessBoundaryPolicy.for_tier(MCPServerTrustTier.TENANT_APPROVED)

        with pytest.raises(TimeoutError):
            await transport.receive(timeout=0.01)

        assert process.killed is False
        event_names = [event["event"] for event in events]
        assert "mcp_server_timeout" in event_names
        assert "mcp_server_kill" not in event_names


@pytest.mark.unit
class TestSubprocessClientBoundary:
    async def test_connect_uses_scrubbed_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.infrastructure.mcp.clients import subprocess_client as client_module
        from src.infrastructure.mcp.clients.subprocess_client import MCPSubprocessClient

        captured: dict[str, Any] = {}

        async def fake_spawn(command: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            raise OSError("stop after capture")

        monkeypatch.setattr(client_module, "spawn_mcp_server_process", fake_spawn)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-host-secret")

        client = MCPSubprocessClient(command="test-server", env={"A": "1"})
        connected = await client.connect(timeout=1)

        assert connected is False
        env = captured["env"]
        assert env["A"] == "1"
        assert "OPENAI_API_KEY" not in env

    def test_client_audit_helper_includes_policy_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.infrastructure.mcp.clients import subprocess_client as client_module
        from src.infrastructure.mcp.clients.subprocess_client import MCPSubprocessClient

        events = _capture_audit_events(client_module, monkeypatch)
        client = MCPSubprocessClient(command="test-server")
        client._policy = MCPProcessBoundaryPolicy.for_tier(MCPServerTrustTier.UNTRUSTED)

        client._audit_process_event("mcp_server_timeout", method="tools/call")

        assert events[0]["event"] == "mcp_server_timeout"
        assert events[0]["server_name"] == "test-server"
        assert events[0]["trust_tier"] == MCPServerTrustTier.UNTRUSTED.value
