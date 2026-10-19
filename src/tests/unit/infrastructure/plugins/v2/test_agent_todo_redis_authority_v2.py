"""Retired Workspace Todo paths stay closed while pinned generations reload."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.todo_tools import make_todo_tools
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    current_agent_worker_redis_client_v2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.workspace_core.legacy_runtime import LegacyWorkspaceRuntimeRetiredError

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedRedisClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.close_calls = 0

    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str | bytes]:
        for key in ():
            yield key

    async def xadd(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("Redis stream publication is outside this authority fixture")

    async def delete(self, *keys: str | bytes) -> int:
        return 0

    async def aclose(self) -> None:
        self.close_calls += 1


@pytest.mark.parametrize("tool_name", ["todoread", "todowrite"])
async def test_retired_workspace_todos_cannot_publish_during_reload(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    clients = iter((first_client, second_client))

    async def redis_factory() -> _TrackedRedisClient:
        return next(clients)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=701,
        version=701,
    )
    assert first.accepted is True

    session = AsyncMock()

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncMock]:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=702,
            version=702,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0
        assert current_agent_worker_redis_client_v2() is first_client
        yield session

    publisher = MagicMock(side_effect=AssertionError("retired Todo paths cannot publish"))
    monkeypatch.setattr(
        "src.application.services.workspace_task_event_publisher.WorkspaceTaskEventPublisher",
        publisher,
    )
    tool = make_todo_tools(session_factory=session_factory)[tool_name]
    ctx = ToolContext(
        session_id="todo-session",
        conversation_id="todo-session",
        message_id="message-1",
        call_id="call-1",
        agent_name="test-agent",
        tenant_id="todo-tenant",
        project_id="todo-project",
        runtime_context={
            "task_authority": "workspace",
            "workspace_id": "workspace-1",
            "root_goal_task_id": "root-1",
        },
    )

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="retired-workspace-todo",
            scope=ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id="todo-tenant",
                project_id="todo-project",
                session_id="todo-session",
            ),
        ):
            with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Workspace authority"):
                if tool_name == "todoread":
                    await tool.execute(ctx)
                else:
                    await tool.execute(ctx, action="replace", todos=[{"content": "retired"}])

        publisher.assert_not_called()
        assert session.mock_calls == []
        assert ctx.consume_pending_events() == []
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        await host.close()

    assert second_client.close_calls == 1


def test_todo_tools_do_not_read_the_process_global_redis_pool() -> None:
    source = (_ROOT / "src/infrastructure/agent/tools/todo_tools.py").read_text(encoding="utf-8")
    assert "agent_worker_state import" not in source
    assert "get_redis_client" not in source
