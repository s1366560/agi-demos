"""Generation-bound runtime coverage for peer session communication tools."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest

from src.infrastructure.agent.tools.context import ToolContext


def _context(label: str) -> ToolContext:
    return ToolContext(
        session_id=f"session-{label}",
        message_id=f"message-{label}",
        call_id=f"call-{label}",
        agent_name=f"agent-{label}",
        conversation_id=f"conversation-{label}",
        project_id=f"project-{label}",
    )


class _Session:
    def __init__(self, label: str) -> None:
        self.label = label
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _factory(session: _Session) -> Callable[[], _Session]:
    return lambda: session


@pytest.mark.unit
async def test_bound_session_comm_runtimes_are_isolated_during_interleaved_awaits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.tools import session_comm_tools as session_comm_module
    from src.infrastructure.agent.tools.session_comm_tools import (
        configure_session_comm,
        make_session_comm_tools,
    )

    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    class _Service:
        def __init__(self, label: str) -> None:
            self.label = label

        async def list_sessions(self, project_id: str, **_kwargs: Any) -> list[dict[str, str]]:
            if self.label == "generation-a":
                first_entered.set()
                await release_first.wait()
            else:
                await first_entered.wait()
                release_first.set()
                await asyncio.sleep(0)
            return [{"runtime": self.label, "project_id": project_id}]

    session_a = _Session("generation-a")
    session_b = _Session("generation-b")
    monkeypatch.setattr(
        session_comm_module,
        "_build_session_comm_service",
        lambda session: _Service(session.label),
        raising=False,
    )
    tool_a = make_session_comm_tools(session_factory=_factory(session_a))["peer_sessions_list"]
    tool_b = make_session_comm_tools(session_factory=_factory(session_b))["peer_sessions_list"]
    configure_session_comm(_Service("legacy"))  # type: ignore[arg-type]

    result_a, result_b = await asyncio.gather(
        tool_a.execute(_context("a")),
        tool_b.execute(_context("b")),
    )

    assert json.loads(result_a.output)["sessions"] == [
        {"runtime": "generation-a", "project_id": "project-a"}
    ]
    assert json.loads(result_b.output)["sessions"] == [
        {"runtime": "generation-b", "project_id": "project-b"}
    ]
    assert session_a.commits == 1
    assert session_b.commits == 1
    assert session_a.rollbacks == 0
    assert session_b.rollbacks == 0


@pytest.mark.unit
async def test_bound_session_comm_commits_success_and_rolls_back_tool_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.tools import session_comm_tools as session_comm_module
    from src.infrastructure.agent.tools.session_comm_tools import make_session_comm_tools

    class _Service:
        def __init__(self, *, fail: bool) -> None:
            self.fail = fail

        async def send_to_session(self, *_args: object, **_kwargs: object) -> dict[str, str]:
            if self.fail:
                raise RuntimeError("write failed")
            return {"status": "sent"}

    success_session = _Session("success")
    failure_session = _Session("failure")
    monkeypatch.setattr(
        session_comm_module,
        "_build_session_comm_service",
        lambda session: _Service(fail=session.label == "failure"),
        raising=False,
    )
    success_tool = make_session_comm_tools(session_factory=_factory(success_session))[
        "peer_sessions_send"
    ]
    failure_tool = make_session_comm_tools(session_factory=_factory(failure_session))[
        "peer_sessions_send"
    ]

    success = await success_tool.execute(
        _context("success"),
        conversation_id="target",
        content="hello",
    )
    failure = await failure_tool.execute(
        _context("failure"),
        conversation_id="target",
        content="hello",
    )

    assert success.is_error is False
    assert failure.is_error is True
    assert success_session.commits == 1
    assert success_session.rollbacks == 0
    assert failure_session.commits == 0
    assert failure_session.rollbacks == 1
