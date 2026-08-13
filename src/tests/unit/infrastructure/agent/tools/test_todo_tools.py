"""Contracts for conversation todos and retired Workspace todo authority."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.todo_tools import todoread_tool, todowrite_tool
from src.infrastructure.workspace_core.legacy_runtime import LegacyWorkspaceRuntimeRetiredError


def _make_ctx(**overrides: Any) -> ToolContext:
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


class _DummySession:
    async def __aenter__(self) -> _DummySession:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def commit(self) -> None:
        return None


class TestTodoReadTool:
    async def test_read_without_session_factory(self) -> None:
        result = await todoread_tool.execute(_make_ctx())

        assert result.is_error is True
        assert json.loads(result.output) == {
            "error": "Task storage not configured",
            "todos": [],
        }

    def test_schema_uses_context_scope_and_valid_statuses(self) -> None:
        schema = todoread_tool.parameters

        assert todoread_tool.name == "todoread"
        assert "session_id" not in schema["properties"]
        assert set(schema["properties"]["status"]["enum"]) >= {"pending", "in_progress"}

    async def test_read_uses_conversation_id_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        captured: dict[str, Any] = {}

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                del session

            async def find_by_conversation(
                self, conversation_id: str, status: str | None = None
            ) -> list[Any]:
                captured.update(conversation_id=conversation_id, status=status)
                return []

        monkeypatch.setattr(
            todo_tools_module,
            "_todoread_session_factory",
            lambda: _DummySession(),
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository."
            "SqlAgentTaskRepository",
            _FakeRepo,
        )

        result = await todoread_tool.execute(
            _make_ctx(session_id="session-ephemeral", conversation_id="conv-persisted")
        )

        assert result.is_error is False
        assert captured == {"conversation_id": "conv-persisted", "status": None}
        assert "exact todos[].id" in json.loads(result.output)["update_instruction"]

    async def test_workspace_read_fails_closed_without_legacy_repository(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        monkeypatch.setattr(
            todo_tools_module,
            "_todoread_session_factory",
            lambda: _DummySession(),
        )

        with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Avernet Workspace Core"):
            await todoread_tool.execute(
                _make_ctx(
                    runtime_context={
                        "task_authority": "workspace",
                        "workspace_id": "workspace-1",
                        "root_goal_task_id": "root-1",
                    }
                )
            )


class TestTodoWriteTool:
    async def test_write_without_session_factory(self) -> None:
        result = await todowrite_tool.execute(_make_ctx(), action="replace", todos=[])

        assert result.is_error is True
        assert json.loads(result.output) == {"error": "Task storage not configured"}

    def test_schema_uses_context_scope_and_exact_todo_ids(self) -> None:
        schema = todowrite_tool.parameters

        assert todowrite_tool.name == "todowrite"
        assert "session_id" not in schema["properties"]
        assert set(schema["properties"]["action"]["enum"]) == {"replace", "add", "update"}
        assert schema["properties"]["todo_id"]["pattern"] == "^(?!\\d+$).+"
        assert "never use list positions" in todowrite_tool.description

    def test_events_are_owned_by_tool_context(self) -> None:
        assert _make_ctx().consume_pending_events() == []

    async def test_write_uses_conversation_id_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        captured: dict[str, Any] = {}

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                del session

            async def save_all(self, conversation_id: str, tasks: list[Any]) -> None:
                captured.update(conversation_id=conversation_id, task_count=len(tasks))

        monkeypatch.setattr(
            todo_tools_module,
            "_todowrite_session_factory",
            lambda: _DummySession(),
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository."
            "SqlAgentTaskRepository",
            _FakeRepo,
        )

        result = await todowrite_tool.execute(
            _make_ctx(session_id="session-ephemeral", conversation_id="conv-persisted"),
            action="replace",
            todos=[{"content": "Task A", "status": "pending", "priority": "high"}],
        )

        assert result.is_error is False
        assert captured == {"conversation_id": "conv-persisted", "task_count": 1}

    async def test_numeric_list_position_is_rejected_before_lookup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                del session

            async def find_by_id(self, task_id: str) -> Any:
                raise AssertionError(f"numeric id {task_id} must not reach persistence")

        monkeypatch.setattr(
            todo_tools_module,
            "_todowrite_session_factory",
            lambda: _DummySession(),
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository."
            "SqlAgentTaskRepository",
            _FakeRepo,
        )

        result = await todowrite_tool.execute(
            _make_ctx(),
            action="update",
            todo_id="1",
            todos=[{"status": "completed"}],
        )

        payload = json.loads(result.output)
        assert payload["error_code"] == "TODO_ID_IS_LIST_POSITION"
        assert "Call todoread and retry" in payload["retry_instruction"]

    @pytest.mark.parametrize("action", ["replace", "add", "update"])
    async def test_workspace_write_fails_closed_without_legacy_repository(
        self,
        action: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        monkeypatch.setattr(
            todo_tools_module,
            "_todowrite_session_factory",
            lambda: _DummySession(),
        )

        with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Avernet Workspace Core"):
            await todowrite_tool.execute(
                _make_ctx(
                    runtime_context={
                        "task_authority": "workspace",
                        "workspace_id": "workspace-1",
                        "root_goal_task_id": "root-1",
                    }
                ),
                action=action,
                todo_id="workspace-task-1" if action == "update" else None,
                todos=[{"content": "Core-owned task"}],
            )

    @pytest.mark.parametrize("action", ["replace", "add"])
    async def test_worker_scope_blocks_structural_workspace_writes_before_storage(
        self,
        action: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        monkeypatch.setattr(
            todo_tools_module,
            "_todowrite_session_factory",
            lambda: _DummySession(),
        )

        result = await todowrite_tool.execute(
            _make_ctx(
                runtime_context={
                    "task_authority": "workspace",
                    "workspace_id": "workspace-1",
                    "root_goal_task_id": "root-1",
                    "workspace_task_id": "workspace-task-1",
                    "attempt_id": "attempt-1",
                    "workspace_session_role": "worker",
                }
            ),
            action=action,
            todos=[{"content": "Forbidden structural edit"}],
        )

        payload = json.loads(result.output)
        assert payload["success"] is False
        assert payload["workspace_scope"] == "worker"
        assert "workspace_report_progress/complete/blocked" in payload["blocked_reason"]
