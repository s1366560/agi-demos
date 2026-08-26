"""Unit tests for register_mcp_server_tool (@tool_define version)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.register_mcp_server import (
    register_mcp_server_tool,
)


def _make_ctx(**overrides: Any) -> ToolContext:
    """Create a minimal ToolContext for testing."""
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


_MOD = "src.infrastructure.agent.tools.register_mcp_server"


@pytest.mark.unit
class TestRegisterMCPServerTool:
    """Tests for register_mcp_server_tool @tool_define implementation."""

    def test_name_and_description(self) -> None:
        assert register_mcp_server_tool.name == "register_mcp_server"
        assert "MCP server" in register_mcp_server_tool.description

    def test_parameters_schema(self) -> None:
        schema = register_mcp_server_tool.parameters
        assert "server_name" in schema["properties"]
        assert "server_type" in schema["properties"]
        assert "command" in schema["properties"]
        assert "args" in schema["properties"]
        assert "url" in schema["properties"]
        assert "server_name" in schema["required"]
        assert "server_type" in schema["required"]

    async def test_execute_no_sandbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When sandbox adapter/id is not set, return error."""
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", None)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", None)
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="my-server", server_type="stdio", command="node"
        )
        assert result.is_error
        assert "Sandbox not available" in result.output

    async def test_execute_missing_server_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", AsyncMock())
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="", server_type="stdio", command="node"
        )
        assert result.is_error
        assert "server_name is required" in result.output

    async def test_execute_invalid_server_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", AsyncMock())
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="my-server", server_type="invalid", command="node"
        )
        assert result.is_error
        assert "Invalid server_type" in result.output

    async def test_execute_stdio_missing_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", AsyncMock())
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="my-server", server_type="stdio"
        )
        assert result.is_error
        assert "'command' is required" in result.output

    async def test_execute_sse_missing_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", AsyncMock())
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="my-server", server_type="sse"
        )
        assert result.is_error
        assert "'url' is required" in result.output

    async def test_execute_install_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [
                    {"type": "text", "text": '{"success": false, "error": "pkg not found"}'}
                ]
            }
        )
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="bad-server", server_type="stdio", command="node"
        )
        assert result.is_error
        assert "Failed to install" in result.output

    async def test_execute_start_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # install succeeds
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            # start fails
            return {
                "content": [{"type": "text", "text": '{"success": false, "error": "port busy"}'}]
            }

        mock_adapter.call_tool = mock_call_tool
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="fail-server", server_type="stdio", command="node"
        )
        assert result.is_error
        assert "Failed to start" in result.output

    async def test_execute_success_no_apps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # install + start succeed
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            # discover returns tools
            return {
                "content": [
                    {"type": "text", "text": '[{"name": "query_db", "description": "Run SQL"}]'}
                ]
            }

        mock_adapter.call_tool = mock_call_tool
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_session_factory", None)
        # Stub out persist/lifecycle helpers to avoid DB calls
        monkeypatch.setattr(f"{_MOD}._register_mcp_persist_server", AsyncMock(return_value=None))
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_emit_events",
            AsyncMock(return_value={"probe": {"status": "ok"}}),
        )

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx,
            server_name="my-server",
            server_type="stdio",
            command="node",
            args=["server.js"],
        )
        assert not result.is_error
        assert "registered and started successfully" in result.output
        assert "query_db" in result.output
        assert "MCP App" not in result.output

    async def test_execute_success_with_apps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            tools = [
                {
                    "name": "render_dashboard",
                    "_meta": {
                        "ui": {
                            "resourceUri": "ui://dashboard/index.html",
                            "title": "Dashboard",
                        }
                    },
                },
                {"name": "query_data", "description": "Query backend"},
            ]
            return {"content": [{"type": "text", "text": json.dumps(tools)}]}

        mock_adapter.call_tool = mock_call_tool
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_session_factory", AsyncMock())
        monkeypatch.setattr(f"{_MOD}._register_mcp_persist_server", AsyncMock(return_value=None))
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_persist_app", AsyncMock(return_value="test-app-id-123")
        )
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_emit_events",
            AsyncMock(return_value={"probe": {"status": "ok"}}),
        )

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx,
            server_name="dashboard-server",
            server_type="stdio",
            command="node",
            args=["server.js"],
        )
        assert not result.is_error
        assert "registered and started successfully" in result.output
        assert "2 tool(s)" in result.output
        assert "1 MCP App(s)" in result.output
        assert "render_dashboard" in result.output

    async def test_execute_exception_handling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(side_effect=Exception("Connection lost"))
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="broken", server_type="stdio", command="node"
        )
        assert result.is_error
        assert "Connection lost" in result.output

    async def test_execute_normalizes_transport_config_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_adapter = AsyncMock()
        mock_adapter.normalize_mcp_transport_config_for_sandbox = lambda **_: {
            "command": "python",
            "args": ["/workspace/pdf/server.py"],
        }

        call_count = 0

        async def mock_call_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            return {
                "content": [
                    {"type": "text", "text": '[{"name": "extract_text", "description": "Extract"}]'}
                ]
            }

        mock_adapter.call_tool = AsyncMock(side_effect=mock_call_tool)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_session_factory", None)
        persist_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(f"{_MOD}._register_mcp_persist_server", persist_mock)
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_emit_events",
            AsyncMock(return_value={"probe": {"status": "ok"}}),
        )

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx,
            server_name="pdf-server",
            server_type="stdio",
            command="python",
            args=["./pdf/server.py"],
        )

        assert not result.is_error
        install_transport = json.loads(
            mock_adapter.call_tool.await_args_list[0].kwargs["arguments"]["transport_config"]
        )
        assert install_transport["args"] == ["/workspace/pdf/server.py"]
        assert persist_mock.await_args.kwargs["transport_config"]["args"] == [
            "/workspace/pdf/server.py"
        ]

    async def test_execute_persists_runtime_normalized_transport_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_adapter = AsyncMock()
        mock_adapter.normalize_mcp_transport_config_for_sandbox = lambda **_: {
            "command": "python",
            "args": ["/Users/test/pdf/server.py"],
        }
        mock_adapter.get_stored_mcp_server_config = lambda **_: {
            "server_type": "stdio",
            "transport_config": json.dumps(
                {
                    "command": "python",
                    "args": ["/workspace/pdf/server.py"],
                }
            ),
        }

        call_count = 0

        async def mock_call_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            return {"content": [{"type": "text", "text": '[{"name": "extract_text"}]'}]}

        mock_adapter.call_tool = AsyncMock(side_effect=mock_call_tool)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_session_factory", None)
        persist_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(f"{_MOD}._register_mcp_persist_server", persist_mock)
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_emit_events",
            AsyncMock(return_value={"probe": {"status": "ok"}}),
        )

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx,
            server_name="pdf-server",
            server_type="stdio",
            command="python",
            args=["/Users/test/pdf/server.py"],
        )

        assert not result.is_error
        assert persist_mock.await_args.kwargs["transport_config"]["args"] == [
            "/workspace/pdf/server.py"
        ]

    async def test_execute_returns_path_normalization_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_adapter = AsyncMock()
        mock_adapter.normalize_mcp_transport_config_for_sandbox = lambda **_: (_ for _ in ()).throw(
            ValueError("Path '/Users/test/report.pdf' is not mounted in the sandbox")
        )
        mock_adapter.call_tool = AsyncMock()
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx,
            server_name="pdf-server",
            server_type="stdio",
            command="python",
            args=["/Users/test/report.pdf"],
        )

        assert result.is_error
        assert "not mounted in the sandbox" in result.output
        mock_adapter.call_tool.assert_not_called()

    def test_consume_pending_events_empty(self) -> None:
        """New API uses ToolContext for events; fresh ctx has no events."""
        ctx = _make_ctx()
        assert ctx.consume_pending_events() == []


@pytest.mark.unit
async def test_bound_tools_isolate_runtime_during_interleaved_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each bound tool must retain its generation dependencies across awaits."""
    from src.infrastructure.agent.tools import register_mcp_server as register_module
    from src.infrastructure.agent.tools.register_mcp_server_runtime import (
        make_register_mcp_server_tool,
    )
    from src.infrastructure.agent.tools.result import ToolResult

    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    observed: dict[str, list[tuple[object, str, str, object, str]]] = {}

    def _snapshot() -> tuple[object, str, str, object, str]:
        runtime = register_module._current_register_mcp_server_runtime()
        assert runtime.sandbox_adapter is not None
        assert runtime.sandbox_id is not None
        return (
            runtime.session_factory,
            runtime.tenant_id,
            runtime.project_id,
            runtime.sandbox_adapter,
            runtime.sandbox_id,
        )

    async def _fake_execute_core(
        _ctx: ToolContext,
        server_name: str,
        _server_type: str,
        _config_json: str,
        _transport_config: dict[str, Any],
    ) -> ToolResult:
        observed.setdefault(server_name, []).append(_snapshot())
        if server_name == "generation-a":
            first_entered.set()
            await release_first.wait()
        else:
            await first_entered.wait()
            release_first.set()
            await asyncio.sleep(0)
        observed[server_name].append(_snapshot())
        return ToolResult(output=server_name)

    monkeypatch.setattr(register_module, "_register_mcp_execute_core", _fake_execute_core)

    session_factory_a = object()
    session_factory_b = object()
    adapter_a = SimpleNamespace()
    adapter_b = SimpleNamespace()
    tool_a = make_register_mcp_server_tool(
        template=register_module.register_mcp_server_tool,
        session_factory=session_factory_a,
        tenant_id="tenant-a",
        project_id="project-a",
        sandbox_adapter=adapter_a,
        sandbox_id="sandbox-a",
    )
    tool_b = make_register_mcp_server_tool(
        template=register_module.register_mcp_server_tool,
        session_factory=session_factory_b,
        tenant_id="tenant-b",
        project_id="project-b",
        sandbox_adapter=adapter_b,
        sandbox_id="sandbox-b",
    )

    await asyncio.gather(
        tool_a.execute(
            _make_ctx(),
            server_name="generation-a",
            server_type="stdio",
            command="python",
        ),
        tool_b.execute(
            _make_ctx(),
            server_name="generation-b",
            server_type="stdio",
            command="python",
        ),
    )

    expected_a = (
        session_factory_a,
        "tenant-a",
        "project-a",
        adapter_a,
        "sandbox-a",
    )
    expected_b = (
        session_factory_b,
        "tenant-b",
        "project-b",
        adapter_b,
        "sandbox-b",
    )
    assert observed == {
        "generation-a": [expected_a, expected_a],
        "generation-b": [expected_b, expected_b],
    }
