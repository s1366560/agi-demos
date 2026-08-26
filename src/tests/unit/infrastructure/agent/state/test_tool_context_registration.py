"""Unit tests for built-in tool registration into agent context."""

from types import SimpleNamespace

import pytest


@pytest.mark.unit
class TestToolContextRegistration:
    """Verify tool setup helpers actually expose configured tools to context."""

    def test_add_todo_tools_adds_todoread_and_todowrite(self, monkeypatch: pytest.MonkeyPatch):
        """Todo helper should inject operation-bound todoread/todowrite definitions."""
        from src.infrastructure.agent.state import agent_worker_state as worker_state

        fake_session_factory = object()
        bound_tools = {
            "todoread": SimpleNamespace(name="todoread"),
            "todowrite": SimpleNamespace(name="todowrite"),
        }
        captured: dict[str, object] = {}

        def _fake_make_todo_tools(*, session_factory: object) -> dict[str, object]:
            captured["session_factory"] = session_factory
            return bound_tools

        def _forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("worker todo tools must not use global configuration or registry")

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            fake_session_factory,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.todo_tools.make_todo_tools",
            _fake_make_todo_tools,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.todo_tools.configure_todoread",
            _forbidden,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.todo_tools.configure_todowrite",
            _forbidden,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.define.get_registered_tools",
            _forbidden,
        )

        tools: dict[str, object] = {}
        worker_state._add_todo_tools(tools, project_id="project-1")

        assert captured["session_factory"] is fake_session_factory
        assert tools == bound_tools

    def test_add_register_mcp_server_tool_adds_tool_to_context(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """register_mcp_server helper should bind and inject one generation's tool."""
        from src.infrastructure.agent.state import agent_worker_state as worker_state
        from src.infrastructure.agent.tools.register_mcp_server import register_mcp_server_tool

        fake_session_factory = object()
        fake_sandbox_adapter = object()
        bound_tool = SimpleNamespace(name="register_mcp_server")
        captured: dict[str, object] = {}

        def _fake_make_register_mcp_server_tool(
            *,
            template: object,
            session_factory: object,
            tenant_id: str,
            project_id: str,
            sandbox_adapter: object,
            sandbox_id: str | None,
        ) -> object:
            captured["template"] = template
            captured["session_factory"] = session_factory
            captured["tenant_id"] = tenant_id
            captured["project_id"] = project_id
            captured["sandbox_adapter"] = sandbox_adapter
            captured["sandbox_id"] = sandbox_id
            return bound_tool

        def _forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(
                "worker register_mcp_server must not use global configuration or registry"
            )

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            fake_session_factory,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.register_mcp_server_runtime.make_register_mcp_server_tool",
            _fake_make_register_mcp_server_tool,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.register_mcp_server.configure_register_mcp_server_tool",
            _forbidden,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.define.get_registered_tools",
            _forbidden,
        )
        monkeypatch.setattr(
            worker_state,
            "current_mcp_sandbox_adapter_v2",
            lambda: fake_sandbox_adapter,
        )

        tools: dict[str, object] = {}
        worker_state._add_register_mcp_server_tool(
            tools,
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert captured["session_factory"] is fake_session_factory
        assert captured["template"] is register_mcp_server_tool
        assert captured["tenant_id"] == "tenant-1"
        assert captured["project_id"] == "project-1"
        assert captured["sandbox_adapter"] is fake_sandbox_adapter
        assert captured["sandbox_id"] is None
        assert tools["register_mcp_server"] is bound_tool

    def test_add_register_mcp_server_tool_uses_private_sandbox_id_attr(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """register_mcp_server helper should detect sandbox id from `_sandbox_id` tool attr."""
        from src.infrastructure.agent.state import agent_worker_state as worker_state

        fake_session_factory = object()
        fake_sandbox_adapter = object()
        bound_tool = SimpleNamespace(name="register_mcp_server")
        captured: dict[str, object] = {}

        def _fake_make_register_mcp_server_tool(**kwargs: object) -> object:
            captured.update(kwargs)
            return bound_tool

        def _forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(
                "worker register_mcp_server must not use global configuration or registry"
            )

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            fake_session_factory,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.register_mcp_server_runtime.make_register_mcp_server_tool",
            _fake_make_register_mcp_server_tool,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.register_mcp_server.configure_register_mcp_server_tool",
            _forbidden,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.define.get_registered_tools",
            _forbidden,
        )
        monkeypatch.setattr(
            worker_state,
            "current_mcp_sandbox_adapter_v2",
            lambda: fake_sandbox_adapter,
        )

        tools: dict[str, object] = {
            "bash": SimpleNamespace(_sandbox_id="sandbox-private-1"),
        }
        worker_state._add_register_mcp_server_tool(
            tools,
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert captured["sandbox_id"] == "sandbox-private-1"
        assert tools["register_mcp_server"] is bound_tool

    def test_add_register_mcp_server_tool_falls_back_to_active_sandbox_by_project(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """register_mcp_server helper should fallback to adapter active sandboxes by project."""
        from src.infrastructure.agent.state import agent_worker_state as worker_state

        fake_session_factory = object()
        bound_tool = SimpleNamespace(name="register_mcp_server")
        captured: dict[str, object] = {}

        def _fake_make_register_mcp_server_tool(**kwargs: object) -> object:
            captured.update(kwargs)
            return bound_tool

        def _forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(
                "worker register_mcp_server must not use global configuration or registry"
            )

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
            "src.infrastructure.agent.tools.register_mcp_server_runtime.make_register_mcp_server_tool",
            _fake_make_register_mcp_server_tool,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.register_mcp_server.configure_register_mcp_server_tool",
            _forbidden,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.define.get_registered_tools",
            _forbidden,
        )
        monkeypatch.setattr(
            worker_state,
            "current_mcp_sandbox_adapter_v2",
            lambda: fake_active_adapter,
        )

        tools: dict[str, object] = {}
        worker_state._add_register_mcp_server_tool(
            tools,
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert captured["sandbox_id"] == "sandbox-active-1"
        assert tools["register_mcp_server"] is bound_tool

    def test_add_register_mcp_server_tool_prefers_running_connected_sandbox(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Fallback sandbox selection should prefer running/connected instance."""
        from src.infrastructure.agent.state import agent_worker_state as worker_state

        fake_session_factory = object()
        bound_tool = SimpleNamespace(name="register_mcp_server")
        captured: dict[str, object] = {}

        def _fake_make_register_mcp_server_tool(**kwargs: object) -> object:
            captured.update(kwargs)
            return bound_tool

        def _forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(
                "worker register_mcp_server must not use global configuration or registry"
            )

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
            "src.infrastructure.agent.tools.register_mcp_server_runtime.make_register_mcp_server_tool",
            _fake_make_register_mcp_server_tool,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.register_mcp_server.configure_register_mcp_server_tool",
            _forbidden,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.define.get_registered_tools",
            _forbidden,
        )
        monkeypatch.setattr(
            worker_state,
            "current_mcp_sandbox_adapter_v2",
            lambda: fake_active_adapter,
        )

        worker_state._add_register_mcp_server_tool(
            tools={},
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert captured["sandbox_id"] == "sandbox-running"
