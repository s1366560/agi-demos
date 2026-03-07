"""Unit tests for built-in tool registration into agent context."""

from types import SimpleNamespace

import pytest


@pytest.mark.unit
class TestToolContextRegistration:
    """Verify tool setup helpers actually expose configured tools to context."""

    def test_add_todo_tools_adds_todoread_and_todowrite(self, monkeypatch: pytest.MonkeyPatch):
        """Todo helper should configure and inject todoread/todowrite into tools dict."""
        from src.infrastructure.agent.state import agent_worker_state as worker_state

        fake_session_factory = object()
        registry = {
            "todoread": SimpleNamespace(name="todoread"),
            "todowrite": SimpleNamespace(name="todowrite"),
        }
        configured: dict[str, object] = {}

        def _fake_configure_todoread(*, session_factory: object) -> None:
            configured["todoread_session_factory"] = session_factory

        def _fake_configure_todowrite(*, session_factory: object) -> None:
            configured["todowrite_session_factory"] = session_factory

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            fake_session_factory,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.todo_tools.configure_todoread",
            _fake_configure_todoread,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.todo_tools.configure_todowrite",
            _fake_configure_todowrite,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.define.get_registered_tools",
            lambda: registry,
        )

        tools: dict[str, object] = {}
        worker_state._add_todo_tools(tools, project_id="project-1")

        assert configured["todoread_session_factory"] is fake_session_factory
        assert configured["todowrite_session_factory"] is fake_session_factory
        assert tools["todoread"] is registry["todoread"]
        assert tools["todowrite"] is registry["todowrite"]

    def test_add_register_mcp_server_tool_adds_tool_to_context(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """register_mcp_server helper should configure and inject tool into tools dict."""
        from src.infrastructure.agent.state import agent_worker_state as worker_state

        fake_session_factory = object()
        fake_sandbox_adapter = object()
        registry = {"register_mcp_server": SimpleNamespace(name="register_mcp_server")}
        configured: dict[str, object] = {}

        def _fake_configure_register_mcp_server_tool(
            *,
            session_factory: object,
            tenant_id: str,
            project_id: str,
            sandbox_adapter: object,
            sandbox_id: str | None,
        ) -> None:
            configured["session_factory"] = session_factory
            configured["tenant_id"] = tenant_id
            configured["project_id"] = project_id
            configured["sandbox_adapter"] = sandbox_adapter
            configured["sandbox_id"] = sandbox_id

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            fake_session_factory,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.register_mcp_server.configure_register_mcp_server_tool",
            _fake_configure_register_mcp_server_tool,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.define.get_registered_tools",
            lambda: registry,
        )
        monkeypatch.setattr(worker_state, "_mcp_sandbox_adapter", fake_sandbox_adapter)

        tools: dict[str, object] = {}
        worker_state._add_register_mcp_server_tool(
            tools,
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert configured["session_factory"] is fake_session_factory
        assert configured["tenant_id"] == "tenant-1"
        assert configured["project_id"] == "project-1"
        assert configured["sandbox_adapter"] is fake_sandbox_adapter
        assert configured["sandbox_id"] is None
        assert tools["register_mcp_server"] is registry["register_mcp_server"]

    def test_add_register_mcp_server_tool_uses_private_sandbox_id_attr(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """register_mcp_server helper should detect sandbox id from `_sandbox_id` tool attr."""
        from src.infrastructure.agent.state import agent_worker_state as worker_state

        fake_session_factory = object()
        fake_sandbox_adapter = object()
        registry = {"register_mcp_server": SimpleNamespace(name="register_mcp_server")}
        configured: dict[str, object] = {}

        def _fake_configure_register_mcp_server_tool(
            *,
            session_factory: object,
            tenant_id: str,
            project_id: str,
            sandbox_adapter: object,
            sandbox_id: str | None,
        ) -> None:
            configured["session_factory"] = session_factory
            configured["tenant_id"] = tenant_id
            configured["project_id"] = project_id
            configured["sandbox_adapter"] = sandbox_adapter
            configured["sandbox_id"] = sandbox_id

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            fake_session_factory,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.register_mcp_server.configure_register_mcp_server_tool",
            _fake_configure_register_mcp_server_tool,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.define.get_registered_tools",
            lambda: registry,
        )
        monkeypatch.setattr(worker_state, "_mcp_sandbox_adapter", fake_sandbox_adapter)

        tools: dict[str, object] = {
            "bash": SimpleNamespace(_sandbox_id="sandbox-private-1"),
        }
        worker_state._add_register_mcp_server_tool(
            tools,
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert configured["sandbox_id"] == "sandbox-private-1"

    def test_add_register_mcp_server_tool_falls_back_to_active_sandbox_by_project(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """register_mcp_server helper should fallback to adapter active sandboxes by project."""
        from src.infrastructure.agent.state import agent_worker_state as worker_state

        fake_session_factory = object()
        registry = {"register_mcp_server": SimpleNamespace(name="register_mcp_server")}
        configured: dict[str, object] = {}

        def _fake_configure_register_mcp_server_tool(
            *,
            session_factory: object,
            tenant_id: str,
            project_id: str,
            sandbox_adapter: object,
            sandbox_id: str | None,
        ) -> None:
            configured["session_factory"] = session_factory
            configured["tenant_id"] = tenant_id
            configured["project_id"] = project_id
            configured["sandbox_adapter"] = sandbox_adapter
            configured["sandbox_id"] = sandbox_id

        fake_active_adapter = SimpleNamespace(
            _active_sandboxes={
                "sandbox-active-1": SimpleNamespace(project_id="project-1"),
            }
        )

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            fake_session_factory,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.register_mcp_server.configure_register_mcp_server_tool",
            _fake_configure_register_mcp_server_tool,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.define.get_registered_tools",
            lambda: registry,
        )
        monkeypatch.setattr(worker_state, "_mcp_sandbox_adapter", fake_active_adapter)

        tools: dict[str, object] = {}
        worker_state._add_register_mcp_server_tool(
            tools,
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert configured["sandbox_id"] == "sandbox-active-1"

    def test_add_register_mcp_server_tool_prefers_running_connected_sandbox(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Fallback sandbox selection should prefer running/connected instance."""
        from src.infrastructure.agent.state import agent_worker_state as worker_state

        fake_session_factory = object()
        registry = {"register_mcp_server": SimpleNamespace(name="register_mcp_server")}
        configured: dict[str, object] = {}

        def _fake_configure_register_mcp_server_tool(
            *,
            session_factory: object,
            tenant_id: str,
            project_id: str,
            sandbox_adapter: object,
            sandbox_id: str | None,
        ) -> None:
            configured["session_factory"] = session_factory
            configured["tenant_id"] = tenant_id
            configured["project_id"] = project_id
            configured["sandbox_adapter"] = sandbox_adapter
            configured["sandbox_id"] = sandbox_id

        fake_active_adapter = SimpleNamespace(
            _active_sandboxes={
                "sandbox-stopped": SimpleNamespace(
                    project_id="project-1",
                    status=SimpleNamespace(value="stopped"),
                    mcp_client=None,
                ),
                "sandbox-running": SimpleNamespace(
                    project_id="project-1",
                    status=SimpleNamespace(value="running"),
                    mcp_client=object(),
                ),
            }
        )

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            fake_session_factory,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.register_mcp_server.configure_register_mcp_server_tool",
            _fake_configure_register_mcp_server_tool,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.define.get_registered_tools",
            lambda: registry,
        )
        monkeypatch.setattr(worker_state, "_mcp_sandbox_adapter", fake_active_adapter)

        worker_state._add_register_mcp_server_tool(
            tools={},
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert configured["sandbox_id"] == "sandbox-running"
