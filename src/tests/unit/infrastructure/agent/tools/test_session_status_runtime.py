"""Generation-bound runtime coverage for the session status tool."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from src.domain.model.agent.agent_mode import AgentMode
from src.domain.model.agent.conversation.conversation import Conversation, ConversationStatus
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


def _conversation(label: str) -> Conversation:
    return Conversation(
        id=f"conversation-{label}",
        project_id=f"project-{label}",
        tenant_id=f"tenant-{label}",
        user_id=f"user-{label}",
        title=f"Generation {label}",
        status=ConversationStatus.ACTIVE,
        current_mode=AgentMode.BUILD,
    )


class _Session:
    def __init__(self, label: str) -> None:
        self.label = label
        self.exits = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        self.exits += 1
        return False


def _factory(session: _Session) -> Callable[[], _Session]:
    return lambda: session


@pytest.mark.unit
async def test_bound_session_status_runtimes_are_isolated_during_interleaved_awaits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.tools import session_status as session_status_module
    from src.infrastructure.agent.tools.session_status import (
        make_session_status_tool,
    )

    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    class _Repository:
        def __init__(self, label: str) -> None:
            self.label = label

        async def find_by_id(self, _conversation_id: str) -> Conversation:
            if self.label == "a":
                first_entered.set()
                await release_first.wait()
            else:
                await first_entered.wait()
                release_first.set()
                await asyncio.sleep(0)
            return _conversation(self.label)

    session_a = _Session("a")
    session_b = _Session("b")
    monkeypatch.setattr(
        session_status_module,
        "_build_conversation_repo",
        lambda session: _Repository(session.label),
        raising=False,
    )
    tool_a = make_session_status_tool(session_factory=_factory(session_a))
    tool_b = make_session_status_tool(session_factory=_factory(session_b))

    result_a, result_b = await asyncio.gather(
        tool_a.execute(_context("a")),
        tool_b.execute(_context("b")),
    )

    assert result_a.metadata["conversation_id"] == "conversation-a"
    assert result_b.metadata["conversation_id"] == "conversation-b"
    assert "Generation a" in result_a.output
    assert "Generation b" in result_b.output
    assert session_a.exits == 1
    assert session_b.exits == 1


@pytest.mark.unit
def test_unbound_session_status_template_rejects_legacy_runtime_fallback() -> None:
    from src.infrastructure.agent.tools import session_status as session_status_module

    with pytest.raises(RuntimeError, match="generation-bound runtime"):
        session_status_module._repo()


@pytest.mark.unit
def test_session_status_module_has_no_legacy_configure_seam() -> None:
    from src.infrastructure.agent.tools import session_status as session_status_module

    assert not hasattr(session_status_module, "configure_session_status")
