"""Tests for todo tools (@tool_define version).

Tests for todoread and todowrite tools. Without a real DB session factory,
the tools return graceful errors. We test metadata, parameter schemas, and
error handling.

Note: session_id comes from ToolContext, not as a kwarg.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.todo_tools import (
    todoread_tool,
    todowrite_tool,
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


class TestTodoReadTool:
    """Test suite for todoread tool (@tool_define)."""

    @pytest.mark.asyncio
    async def test_read_without_session_factory(self) -> None:
        """Without session_factory, returns error."""
        ctx = _make_ctx()
        result = await todoread_tool.execute(ctx)
        data = json.loads(result.output)
        assert "error" in data
        assert data["todos"] == []
        assert result.is_error is True

    def test_tool_name(self) -> None:
        assert todoread_tool.name == "todoread"

    def test_parameters_schema_no_session_id(self) -> None:
        """session_id is injected by processor via ToolContext, not exposed in LLM schema."""
        schema = todoread_tool.parameters
        assert "session_id" not in schema["properties"]
        assert "status" in schema["properties"]

    def test_valid_status_enum_in_schema(self) -> None:
        """Status parameter should list valid enum values."""
        schema = todoread_tool.parameters
        status_prop = schema["properties"]["status"]
        assert "enum" in status_prop
        assert "pending" in status_prop["enum"]
        assert "in_progress" in status_prop["enum"]

    @pytest.mark.asyncio
    async def test_read_uses_conversation_id_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Read path should query tasks by conversation scope, not ephemeral session scope."""
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        captured: dict[str, Any] = {}

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_conversation(
                self, conversation_id: str, status: str | None = None
            ) -> list[Any]:
                captured["conversation_id"] = conversation_id
                captured["status"] = status
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

        ctx = _make_ctx(session_id="session-ephemeral", conversation_id="conv-persisted")
        result = await todoread_tool.execute(ctx)

        assert result.is_error is False
        assert captured["conversation_id"] == "conv-persisted"

    @pytest.mark.asyncio
    async def test_read_uses_workspace_authority_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                assert workspace_id == "ws-1"
                assert root_goal_task_id == "root-1"
                return [
                    WorkspaceTask(
                        id="wt-1",
                        workspace_id="ws-1",
                        title="Execution task",
                        created_by="user-1",
                        status=WorkspaceTaskStatus.IN_PROGRESS,
                        priority=WorkspaceTaskPriority.P3,
                        metadata={
                            "task_role": "execution_task",
                            "root_goal_task_id": "root-1",
                            "workspace_agent_binding_id": "binding-1",
                            "pending_leader_adjudication": True,
                            "current_attempt_id": "attempt-1",
                            "current_attempt_worker_agent_id": "worker-1",
                            "last_attempt_id": "attempt-1",
                            "current_attempt_number": 1,
                            "current_attempt_worker_binding_id": "binding-1",
                            "last_attempt_status": "awaiting_leader_adjudication",
                            "last_worker_report_type": "completed",
                            "last_worker_report_summary": "Checklist drafted",
                            "last_worker_report_artifacts": ["artifact:checklist"],
                            "last_worker_report_verifications": ["worker_report:completed"],
                            "last_worker_report_id": "run-1",
                            "last_worker_report_fingerprint": "fp-1",
                        },
                    )
                ]

        monkeypatch.setattr(todo_tools_module, "_todoread_session_factory", lambda: _DummySession())
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        result = await todoread_tool.execute(ctx)
        payload = json.loads(result.output)

        assert payload["todos"] == [
            {
                "id": "wt-1",
                "workspace_task_id": "wt-1",
                "content": "Execution task",
                "status": "in_progress",
                "priority": "medium",
                "workspace_agent_id": "binding-1",
                "pending_leader_adjudication": True,
                "current_attempt_id": "attempt-1",
                "current_attempt_worker_agent_id": "worker-1",
                "last_attempt_id": "attempt-1",
                "current_attempt_number": 1,
                "current_attempt_worker_binding_id": "binding-1",
                "last_attempt_status": "awaiting_leader_adjudication",
                "last_worker_report_type": "completed",
                "last_worker_report_summary": "Checklist drafted",
                "last_worker_report_artifacts": ["artifact:checklist"],
                "last_worker_report_verifications": ["worker_report:completed"],
                "last_worker_report_id": "run-1",
                "last_worker_report_fingerprint": "fp-1",
            }
        ]


class TestTodoWriteTool:
    """Test suite for todowrite tool (@tool_define)."""

    @pytest.mark.asyncio
    async def test_write_without_session_factory(self) -> None:
        """Without session_factory, returns error."""
        ctx = _make_ctx()
        result = await todowrite_tool.execute(ctx, action="replace", todos=[])
        data = json.loads(result.output)
        assert "error" in data
        assert result.is_error is True

    def test_tool_name(self) -> None:
        assert todowrite_tool.name == "todowrite"

    def test_parameters_schema_no_session_id(self) -> None:
        """session_id is injected by processor via ToolContext, not exposed in LLM schema."""
        schema = todowrite_tool.parameters
        assert "session_id" not in schema["properties"]
        assert "action" in schema["properties"]
        assert "todos" in schema["properties"]

    def test_action_enum_in_schema(self) -> None:
        """Action parameter should list valid enum values."""
        schema = todowrite_tool.parameters
        action_prop = schema["properties"]["action"]
        assert "enum" in action_prop
        assert "replace" in action_prop["enum"]
        assert "add" in action_prop["enum"]
        assert "update" in action_prop["enum"]

    def test_consume_pending_events_via_context(self) -> None:
        """Events are consumed from ToolContext, not from the tool itself."""
        ctx = _make_ctx()
        events = ctx.consume_pending_events()
        assert events == []

    @pytest.mark.asyncio
    async def test_write_uses_conversation_id_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Write path should persist tasks under conversation scope, not ephemeral session scope."""
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        captured: dict[str, Any] = {}

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def save_all(self, conversation_id: str, tasks: list[Any]) -> None:
                captured["conversation_id"] = conversation_id
                captured["task_count"] = len(tasks)

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

        ctx = _make_ctx(session_id="session-ephemeral", conversation_id="conv-persisted")
        result = await todowrite_tool.execute(
            ctx,
            action="replace",
            todos=[{"content": "Task A", "status": "pending", "priority": "high"}],
        )

        assert result.is_error is False
        assert captured["task_count"] == 1
        assert captured["conversation_id"] == "conv-persisted"

    @pytest.mark.asyncio
    async def test_update_rejects_task_from_other_conversation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Update should not modify a task outside current conversation scope."""
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        captured: dict[str, Any] = {"update_called": False}

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        class _FakeRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_id(self, task_id: str) -> Any:
                _ = task_id
                return type("Task", (), {"conversation_id": "another-conversation"})()

            async def update(self, task_id: str, **updates: Any) -> Any:
                _ = task_id
                _ = updates
                captured["update_called"] = True
                return None

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

        ctx = _make_ctx(session_id="session-ephemeral", conversation_id="conv-persisted")
        result = await todowrite_tool.execute(
            ctx,
            action="update",
            todo_id="task-1",
            todos=[{"status": "completed"}],
        )
        data = json.loads(result.output)

        assert data["success"] is False
        assert "not found" in data["message"].lower()
        assert captured["update_called"] is False

    @pytest.mark.asyncio
    async def test_add_writes_workspace_execution_tasks_when_workspace_authority_active(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        created: list[dict[str, Any]] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def create_task(self, **kwargs: Any) -> WorkspaceTask:
                created.append(kwargs)
                return WorkspaceTask(
                    id=f"wt-{len(created)}",
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"],
                    created_by=kwargs["actor_user_id"],
                    status=WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"],
                    metadata=kwargs["metadata"],
                )

            def consume_pending_events(self) -> list[Any]:
                return []

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                if not created:
                    return []
                return [
                    WorkspaceTask(
                        id=f"wt-{i + 1}",
                        workspace_id=workspace_id,
                        title=kwargs["title"],
                        created_by=kwargs["actor_user_id"],
                        status=WorkspaceTaskStatus.TODO,
                        priority=kwargs["priority"],
                        metadata={**kwargs["metadata"], "root_goal_task_id": root_goal_task_id},
                    )
                    for i, kwargs in enumerate(created)
                ]

        dispatch_calls: list[dict[str, Any]] = []

        async def _fake_dispatch(**kwargs: Any) -> dict[str, Any]:
            dispatch_calls.append(kwargs)
            return {"dispatched": True}

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            todo_tools_module, "_dispatch_created_workspace_tasks", _fake_dispatch
        )
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
                "selected_agent_id": "leader-agent-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="add",
            todos=[{"content": "Task A", "status": "pending", "priority": "high"}],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert payload["added_count"] == 1
        assert payload["skipped_count"] == 0
        assert payload["dispatched"] is True
        assert created[0]["workspace_id"] == "ws-1"
        assert created[0]["metadata"]["root_goal_task_id"] == "root-1"
        assert len(dispatch_calls) == 1
        assert dispatch_calls[0]["leader_agent_id"] == "leader-agent-1"
        assert [t.title for t in dispatch_calls[0]["created_tasks"]] == ["Task A"]
        pending = ctx.consume_pending_events()
        assert any(event["type"] == "task_list_updated" for event in pending)

    @pytest.mark.asyncio
    async def test_add_skips_terminal_workspace_todos_when_workspace_authority_active(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        created: list[dict[str, Any]] = []
        dispatch_calls: list[dict[str, Any]] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def create_task(self, **kwargs: Any) -> WorkspaceTask:
                created.append(kwargs)
                raise AssertionError("terminal add should not create execution tasks")

            def consume_pending_events(self) -> list[Any]:
                return []

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                assert workspace_id == "ws-1"
                assert root_goal_task_id == "root-1"
                return []

        async def _fake_dispatch(**kwargs: Any) -> dict[str, Any]:
            dispatch_calls.append(kwargs)
            return {"dispatched": False, "dispatch_skipped_reason": "no_created_tasks"}

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            todo_tools_module, "_dispatch_created_workspace_tasks", _fake_dispatch
        )
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
                "selected_agent_id": "leader-agent-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="add",
            todos=[
                {"content": "Cancel stale blocked tasks", "status": "cancelled"},
                {"content": "Already complete", "status": "completed"},
                {"content": "Known failed work", "status": "failed"},
            ],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert payload["added_count"] == 0
        assert payload["skipped_count"] == 3
        assert payload["dispatch_skipped_reason"] == "no_created_tasks"
        assert created == []
        assert dispatch_calls[0]["created_tasks"] == []

    @pytest.mark.asyncio
    async def test_replace_reconciles_workspace_execution_tasks_when_workspace_authority_active(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        created: list[dict[str, Any]] = []
        deleted: list[str] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def create_task(self, **kwargs: Any) -> WorkspaceTask:
                created.append(kwargs)
                return WorkspaceTask(
                    id=f"wt-new-{len(created)}",
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"],
                    created_by=kwargs["actor_user_id"],
                    status=WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                    metadata=kwargs["metadata"],
                )

            async def delete_task(self, **kwargs: Any) -> bool:
                deleted.append(kwargs["task_id"])
                return True

            async def update_task(self, **kwargs: Any) -> WorkspaceTask:
                raise AssertionError("update_task should not be called for replace")

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                if created:
                    return [
                        WorkspaceTask(
                            id="wt-new-1",
                            workspace_id=workspace_id,
                            title="Task B",
                            created_by="user-1",
                            status=WorkspaceTaskStatus.TODO,
                            priority=WorkspaceTaskPriority.P1,
                            metadata={
                                "task_role": "execution_task",
                                "root_goal_task_id": root_goal_task_id,
                            },
                        )
                    ]
                return [
                    WorkspaceTask(
                        id="wt-old-1",
                        workspace_id=workspace_id,
                        title="Old Task",
                        created_by="user-1",
                        status=WorkspaceTaskStatus.TODO,
                        priority=WorkspaceTaskPriority.P4,
                        metadata={
                            "task_role": "execution_task",
                            "root_goal_task_id": root_goal_task_id,
                        },
                    )
                ]

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="replace",
            todos=[{"content": "Task B", "status": "pending", "priority": "high"}],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert deleted == ["wt-old-1"]
        assert created[0]["title"] == "Task B"

    @pytest.mark.asyncio
    async def test_replace_created_completed_workspace_tasks_are_not_dispatched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        created: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def create_task(self, **kwargs: Any) -> WorkspaceTask:
                created.append(kwargs)
                return WorkspaceTask(
                    id=f"wt-new-{len(created)}",
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"],
                    created_by=kwargs["actor_user_id"],
                    status=WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                    metadata=kwargs["metadata"],
                )

            async def delete_task(self, **kwargs: Any) -> bool:
                return True

            async def update_task(self, **kwargs: Any) -> WorkspaceTask:
                updated.append(kwargs)
                return WorkspaceTask(
                    id=kwargs["task_id"],
                    workspace_id=kwargs["workspace_id"],
                    title="Already Done",
                    created_by=kwargs["actor_user_id"],
                    status=kwargs["status"],
                    priority=WorkspaceTaskPriority.P1,
                    metadata={},
                )

            def consume_pending_events(self) -> list[Any]:
                return []

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                return []

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
                "selected_agent_id": "leader-agent-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="replace",
            todos=[{"content": "Already Done", "status": "completed", "priority": "high"}],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert updated[0]["status"] == WorkspaceTaskStatus.DONE
        assert payload["dispatched"] is False
        assert payload["dispatch_skipped_reason"] == "no_dispatchable_created_tasks"

    @pytest.mark.asyncio
    async def test_dispatch_created_workspace_tasks_starts_todo_tasks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        assign_calls: list[dict[str, Any]] = []
        started: list[dict[str, Any]] = []

        async def _fake_assign(**kwargs: Any) -> None:
            assign_calls.append(kwargs)

        class _FakeCommandService:
            async def start_task(self, **kwargs: Any) -> WorkspaceTask:
                started.append(kwargs)
                return WorkspaceTask(
                    id=kwargs["task_id"],
                    workspace_id=kwargs["workspace_id"],
                    title="Started task",
                    created_by=kwargs["actor_user_id"],
                    status=WorkspaceTaskStatus.IN_PROGRESS,
                    priority=WorkspaceTaskPriority.P1,
                    metadata={
                        "task_role": "execution_task",
                        "root_goal_task_id": "root-1",
                    },
                )

        monkeypatch.setattr(
            "src.infrastructure.agent.workspace.workspace_goal_runtime."
            "_assign_execution_tasks_to_workers",
            _fake_assign,
        )

        result = await todo_tools_module._dispatch_created_workspace_tasks(
            session=object(),
            command_service=_FakeCommandService(),
            workspace_id="ws-1",
            created_tasks=[
                WorkspaceTask(
                    id="wt-todo",
                    workspace_id="ws-1",
                    title="Todo task",
                    created_by="user-1",
                    status=WorkspaceTaskStatus.TODO,
                    priority=WorkspaceTaskPriority.P1,
                    metadata={
                        "task_role": "execution_task",
                        "root_goal_task_id": "root-1",
                    },
                ),
                WorkspaceTask(
                    id="wt-running",
                    workspace_id="ws-1",
                    title="Running task",
                    created_by="user-1",
                    status=WorkspaceTaskStatus.IN_PROGRESS,
                    priority=WorkspaceTaskPriority.P1,
                    metadata={
                        "task_role": "execution_task",
                        "root_goal_task_id": "root-1",
                    },
                ),
            ],
            leader_agent_id="leader-agent-1",
            actor_user_id="user-1",
            reason="unit.dispatch",
        )

        assert result["dispatched"] is True
        assert result["started_count"] == 1
        assert result["start_failed_count"] == 0
        assert len(assign_calls) == 1
        assert [call["task_id"] for call in started] == ["wt-todo"]
        assert started[0]["authority"].role == "leader"
        assert started[0]["actor_agent_id"] == "leader-agent-1"

    @pytest.mark.asyncio
    async def test_replace_preserves_matching_workspace_execution_task_by_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        created: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        deleted: list[str] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def create_task(self, **kwargs: Any) -> WorkspaceTask:
                created.append(kwargs)
                return WorkspaceTask(
                    id="wt-new",
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"],
                    created_by=kwargs["actor_user_id"],
                    status=WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                    metadata=kwargs["metadata"],
                )

            async def delete_task(self, **kwargs: Any) -> bool:
                deleted.append(kwargs["task_id"])
                return True

            async def update_task(self, **kwargs: Any) -> WorkspaceTask:
                updated.append(kwargs)
                return WorkspaceTask(
                    id=kwargs["task_id"],
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"] or "Task A",
                    created_by=kwargs["actor_user_id"],
                    status=kwargs["status"] or WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                    metadata={
                        "task_role": "execution_task",
                        "root_goal_task_id": "root-1",
                    },
                )

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                return [
                    WorkspaceTask(
                        id="wt-old-1",
                        workspace_id=workspace_id,
                        title="Task A",
                        created_by="user-1",
                        status=WorkspaceTaskStatus.TODO,
                        priority=WorkspaceTaskPriority.P4,
                        metadata={
                            "task_role": "execution_task",
                            "root_goal_task_id": root_goal_task_id,
                        },
                    )
                ]

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="replace",
            todos=[{"content": "Task A", "status": "in_progress", "priority": "high"}],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert created == []
        assert deleted == []
        assert updated[0]["task_id"] == "wt-old-1"

    @pytest.mark.asyncio
    async def test_replace_preserves_unchanged_completed_workspace_task_without_finalize(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        created: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        deleted: list[str] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def create_task(self, **kwargs: Any) -> WorkspaceTask:
                created.append(kwargs)
                return WorkspaceTask(
                    id="wt-new",
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"],
                    created_by=kwargs["actor_user_id"],
                    status=WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                    metadata=kwargs["metadata"],
                )

            async def delete_task(self, **kwargs: Any) -> bool:
                deleted.append(kwargs["task_id"])
                return True

            async def update_task(self, **kwargs: Any) -> WorkspaceTask:
                updated.append(kwargs)
                raise AssertionError("unchanged completed task should not be finalized again")

            def consume_pending_events(self) -> list[Any]:
                return []

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                return [
                    WorkspaceTask(
                        id="wt-done-1",
                        workspace_id=workspace_id,
                        title="Already complete",
                        created_by="user-1",
                        status=WorkspaceTaskStatus.DONE,
                        priority=WorkspaceTaskPriority.P1,
                        metadata={
                            "task_role": "execution_task",
                            "root_goal_task_id": root_goal_task_id,
                            "current_attempt_id": "attempt-blocked",
                            "last_attempt_status": "blocked",
                        },
                    )
                ]

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="replace",
            todos=[
                {
                    "id": "wt-done-1",
                    "content": "Already complete",
                    "status": "completed",
                    "priority": "high",
                }
            ],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert created == []
        assert updated == []
        assert deleted == []

    @pytest.mark.asyncio
    async def test_replace_replaces_blocked_workspace_task_with_fresh_pending_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        created: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        deleted: list[str] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def create_task(self, **kwargs: Any) -> WorkspaceTask:
                created.append(kwargs)
                return WorkspaceTask(
                    id="wt-fresh-1",
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"],
                    created_by=kwargs["actor_user_id"],
                    status=WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                    metadata=kwargs["metadata"],
                )

            async def delete_task(self, **kwargs: Any) -> bool:
                deleted.append(kwargs["task_id"])
                return True

            async def update_task(self, **kwargs: Any) -> WorkspaceTask:
                updated.append(kwargs)
                raise AssertionError("blocked replacement should not downgrade the old task")

            def consume_pending_events(self) -> list[Any]:
                return []

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                if created:
                    return [
                        WorkspaceTask(
                            id="wt-fresh-1",
                            workspace_id=workspace_id,
                            title="Fresh task",
                            created_by="user-1",
                            status=WorkspaceTaskStatus.TODO,
                            priority=WorkspaceTaskPriority.P1,
                            metadata={
                                "task_role": "execution_task",
                                "root_goal_task_id": root_goal_task_id,
                                "derived_from_internal_plan_step": "wt-blocked-1",
                            },
                        )
                    ]
                return [
                    WorkspaceTask(
                        id="wt-blocked-1",
                        workspace_id=workspace_id,
                        title="Old blocked task",
                        created_by="user-1",
                        status=WorkspaceTaskStatus.BLOCKED,
                        priority=WorkspaceTaskPriority.P1,
                        metadata={
                            "task_role": "execution_task",
                            "root_goal_task_id": root_goal_task_id,
                        },
                    )
                ]

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="replace",
            todos=[
                {
                    "id": "wt-blocked-1",
                    "content": "Fresh task",
                    "status": "pending",
                    "priority": "high",
                }
            ],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert created[0]["title"] == "Fresh task"
        assert created[0]["metadata"]["derived_from_internal_plan_step"] == "wt-blocked-1"
        assert updated == []
        assert deleted == ["wt-blocked-1"]

    @pytest.mark.asyncio
    async def test_update_resolves_workspace_step_id_to_real_task_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        updated: list[dict[str, Any]] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def update_task(self, **kwargs: Any) -> WorkspaceTask:
                updated.append(kwargs)
                return WorkspaceTask(
                    id="wt-real-1",
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"] or "Task A",
                    created_by=kwargs["actor_user_id"],
                    status=kwargs["status"] or WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                    metadata={
                        "task_role": "execution_task",
                        "root_goal_task_id": "root-1",
                        "derived_from_internal_plan_step": "step-1",
                    },
                )

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_id(self, task_id: str) -> Any:
                assert task_id == "step-1"
                return None

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                return [
                    WorkspaceTask(
                        id="wt-real-1",
                        workspace_id=workspace_id,
                        title="Task A",
                        created_by="user-1",
                        status=WorkspaceTaskStatus.TODO,
                        priority=WorkspaceTaskPriority.P3,
                        metadata={
                            "task_role": "execution_task",
                            "root_goal_task_id": root_goal_task_id,
                            "derived_from_internal_plan_step": "step-1",
                        },
                    )
                ]

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="update",
            todo_id="step-1",
            todos=[{"content": "Task A", "status": "in_progress", "priority": "high"}],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert updated[0]["task_id"] == "wt-real-1"

    @pytest.mark.asyncio
    async def test_update_cancelled_archives_workspace_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        deleted: list[dict[str, Any]] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def delete_task(self, **kwargs: Any) -> bool:
                deleted.append(kwargs)
                return True

            def consume_pending_events(self) -> list[Any]:
                return []

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_id(self, task_id: str) -> WorkspaceTask:
                assert task_id == "wt-old-1"
                return WorkspaceTask(
                    id=task_id,
                    workspace_id="ws-1",
                    title="Old blocked task",
                    created_by="user-1",
                    status=WorkspaceTaskStatus.BLOCKED,
                    priority=WorkspaceTaskPriority.P1,
                    metadata={
                        "task_role": "execution_task",
                        "root_goal_task_id": "root-1",
                        "current_attempt_id": "attempt-1",
                    },
                )

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                assert workspace_id == "ws-1"
                assert root_goal_task_id == "root-1"
                return []

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="update",
            todo_id="wt-old-1",
            todos=[{"content": "Old blocked task", "status": "cancelled"}],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert payload["archived"] is True
        assert deleted[0]["task_id"] == "wt-old-1"
        assert ctx.consume_pending_events() == [
            {
                "type": "task_list_updated",
                "conversation_id": "conv-persisted",
                "tasks": [],
            }
        ]

    @pytest.mark.asyncio
    async def test_update_completed_root_synthesizes_goal_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        updated: list[dict[str, Any]] = []

        root_task = WorkspaceTask(
            id="root-1",
            workspace_id="ws-1",
            title="Build my-evo",
            created_by="user-1",
            status=WorkspaceTaskStatus.IN_PROGRESS,
            priority=WorkspaceTaskPriority.P1,
            metadata={"task_role": "goal_root"},
        )
        child_task = WorkspaceTask(
            id="child-1",
            workspace_id="ws-1",
            title="Verify build",
            created_by="user-1",
            status=WorkspaceTaskStatus.DONE,
            priority=WorkspaceTaskPriority.P1,
            metadata={
                "task_role": "execution_task",
                "root_goal_task_id": "root-1",
                "last_attempt_status": "accepted",
                "last_worker_report_type": "completed",
                "last_worker_report_summary": "npm run build passed",
                "evidence_refs": ["sandbox:/workspace/my-evo"],
                "verification_refs": ["cmd:npm run build"],
            },
        )

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def update_task(self, **kwargs: Any) -> WorkspaceTask:
                updated.append(kwargs)
                root_task.status = kwargs["status"]
                root_task.metadata = {**root_task.metadata, **(kwargs.get("metadata") or {})}
                return root_task

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_id(self, task_id: str) -> WorkspaceTask:
                assert task_id == "root-1"
                return root_task

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                assert workspace_id == "ws-1"
                assert root_goal_task_id == "root-1"
                return [child_task]

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
                "selected_agent_id": "leader-agent-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="update",
            todo_id="root-1",
            todos=[{"content": "Build my-evo", "status": "completed"}],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        evidence = updated[0]["metadata"]["goal_evidence"]
        assert evidence["goal_task_id"] == "root-1"
        assert evidence["goal_text_snapshot"] == "Build my-evo"
        assert evidence["generated_by_agent_id"] == "leader-agent-1"

    @pytest.mark.asyncio
    async def test_update_uses_leader_adjudication_path_for_pending_worker_report(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        adjudicated: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def update_task(self, **kwargs: Any) -> WorkspaceTask:
                updated.append(kwargs)
                return WorkspaceTask(
                    id="wt-real-1",
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"] or "Task A",
                    created_by=kwargs["actor_user_id"],
                    status=kwargs["status"] or WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                    metadata={
                        "task_role": "execution_task",
                        "root_goal_task_id": "root-1",
                        "derived_from_internal_plan_step": "step-1",
                    },
                )

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_id(self, task_id: str) -> Any:
                return WorkspaceTask(
                    id=task_id,
                    workspace_id="ws-1",
                    title="Task A",
                    created_by="user-1",
                    status=WorkspaceTaskStatus.IN_PROGRESS,
                    priority=WorkspaceTaskPriority.P3,
                    metadata={
                        "task_role": "execution_task",
                        "root_goal_task_id": "root-1",
                        "derived_from_internal_plan_step": "step-1",
                        "pending_leader_adjudication": True,
                        "current_attempt_id": "attempt-7",
                    },
                )

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                _ = workspace_id
                _ = root_goal_task_id
                return []

        async def _fake_adjudicate(**kwargs: Any) -> WorkspaceTask:
            adjudicated.append(kwargs)
            return WorkspaceTask(
                id=kwargs["task_id"],
                workspace_id=kwargs["workspace_id"],
                title=kwargs["title"] or "Task A",
                created_by=kwargs["actor_user_id"],
                status=kwargs["status"],
                priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                metadata={
                    "task_role": "execution_task",
                    "root_goal_task_id": "root-1",
                    "derived_from_internal_plan_step": "step-1",
                    "pending_leader_adjudication": False,
                },
            )

        monkeypatch.setattr(todo_tools_module, "_todowrite_session_factory", lambda: _DummySession())
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.workspace.workspace_goal_runtime."
            "adjudicate_workspace_worker_report",
            _fake_adjudicate,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="update",
            todo_id="wt-real-1",
            todos=[{"content": "Task A", "status": "completed", "priority": "high"}],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert adjudicated[0]["task_id"] == "wt-real-1"
        assert adjudicated[0]["attempt_id"] == "attempt-7"
        assert adjudicated[0]["status"] == WorkspaceTaskStatus.DONE
        assert updated == []

    @pytest.mark.asyncio
    async def test_add_skips_duplicate_by_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dedup: adding a todo whose title matches an existing task should skip."""
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        created: list[dict[str, Any]] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def create_task(self, **kwargs: Any) -> WorkspaceTask:
                created.append(kwargs)
                return WorkspaceTask(
                    id=f"wt-{len(created)}",
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"],
                    created_by=kwargs["actor_user_id"],
                    status=WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"],
                    metadata=kwargs["metadata"],
                )

            def consume_pending_events(self) -> list[Any]:
                return []

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                return [
                    WorkspaceTask(
                        id="wt-existing",
                        workspace_id=workspace_id,
                        title="Existing Task",
                        created_by="user-1",
                        status=WorkspaceTaskStatus.TODO,
                        priority=WorkspaceTaskPriority.P3,
                        metadata={
                            "task_role": "execution_task",
                            "root_goal_task_id": root_goal_task_id,
                        },
                    )
                ]

        dispatch_calls: list[dict[str, Any]] = []

        async def _fake_dispatch(**kwargs: Any) -> dict[str, Any]:
            dispatch_calls.append(kwargs)
            return {"dispatched": False, "dispatch_skipped_reason": "no_created_tasks"}

        monkeypatch.setattr(
            todo_tools_module, "_todowrite_session_factory", lambda: _DummySession()
        )
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            todo_tools_module, "_dispatch_created_workspace_tasks", _fake_dispatch
        )
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
                "selected_agent_id": "leader-1",
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="add",
            todos=[{"content": "Existing Task"}, {"content": "New Task"}],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert payload["added_count"] == 1
        assert payload["skipped_count"] == 1
        assert payload["skipped_titles"] == ["Existing Task"]
        # Only the non-duplicate was passed to create_task
        assert [c["title"] for c in created] == ["New Task"]
        # Dispatch invoked exactly once for the single new task
        assert len(dispatch_calls) == 1
        assert [t.title for t in dispatch_calls[0]["created_tasks"]] == ["New Task"]

    @pytest.mark.asyncio
    async def test_add_without_selected_agent_id_skips_dispatch_with_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """selected_agent_id missing → create succeeds, dispatch cleanly skipped with reason."""
        import src.infrastructure.agent.tools.todo_tools as todo_tools_module

        class _DummySession:
            async def __aenter__(self) -> _DummySession:
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

            async def commit(self) -> None:
                return None

        created: list[dict[str, Any]] = []

        class _FakeCommandService:
            def __init__(self, task_service: Any) -> None:
                _ = task_service

            async def create_task(self, **kwargs: Any) -> WorkspaceTask:
                created.append(kwargs)
                return WorkspaceTask(
                    id=f"wt-{len(created)}",
                    workspace_id=kwargs["workspace_id"],
                    title=kwargs["title"],
                    created_by=kwargs["actor_user_id"],
                    status=WorkspaceTaskStatus.TODO,
                    priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                    metadata=kwargs["metadata"],
                )

            def consume_pending_events(self) -> list[Any]:
                return []

        class _FakeWorkspaceRepo:
            def __init__(self, session: Any) -> None:
                _ = session

            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_goal_task_id: str
            ) -> list[Any]:
                return [
                    WorkspaceTask(
                        id=f"wt-{i + 1}",
                        workspace_id=workspace_id,
                        title=kwargs["title"],
                        created_by=kwargs["actor_user_id"],
                        status=WorkspaceTaskStatus.TODO,
                        priority=kwargs["priority"] or WorkspaceTaskPriority.NONE,
                        metadata={**kwargs["metadata"], "root_goal_task_id": root_goal_task_id},
                    )
                    for i, kwargs in enumerate(created)
                ]

        # NOTE: intentionally do NOT monkeypatch _dispatch_created_workspace_tasks —
        # we want the real code path so the "leader_agent_id_missing" branch executes.
        monkeypatch.setattr(
            todo_tools_module, "_todowrite_session_factory", lambda: _DummySession()
        )
        monkeypatch.setattr(todo_tools_module, "WorkspaceTaskService", lambda **kwargs: object())
        monkeypatch.setattr(
            "src.application.services.workspace_task_command_service.WorkspaceTaskCommandService",
            _FakeCommandService,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository."
            "SqlWorkspaceTaskRepository",
            _FakeWorkspaceRepo,
        )

        ctx = _make_ctx(
            conversation_id="conv-persisted",
            user_id="user-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
                # selected_agent_id deliberately omitted
            },
        )
        result = await todowrite_tool.execute(
            ctx,
            action="add",
            todos=[{"content": "Lonely Task"}],
        )
        payload = json.loads(result.output)

        assert payload["success"] is True
        assert payload["added_count"] == 1
        assert payload["dispatched"] is False
        assert payload["dispatch_skipped_reason"] == "leader_agent_id_missing"
        # Task still created despite dispatch skip
        assert len(created) == 1
