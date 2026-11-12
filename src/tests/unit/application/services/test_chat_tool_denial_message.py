"""Denial text names the tool and the current grant without widening it."""

import pytest

from src.application.services.chat_run_tool_permission_v2 import format_chat_tool_denial

pytestmark = pytest.mark.unit


def test_canvas_denial_names_the_read_only_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from src.application.services import chat_run_tool_permission_v2 as permission

    monkeypatch.setattr(
        permission,
        "current_chat_run_guard_v2",
        lambda: SimpleNamespace(mode="ask"),
    )
    message = format_chat_tool_denial("canvas_create")
    assert "tool=canvas_create" in message
    assert "permission_mode=ask" in message
    assert "permission_profile=read_only" in message
    assert "does not authorize this tool operation" in message


def test_unbound_denial_keeps_the_current_profile() -> None:
    message = format_chat_tool_denial("edit")
    assert message.startswith("tool_not_authorized tool=edit ")
    assert "permission_mode=unbound" in message
    assert "permission_profile=unbound" in message
    assert "keeps its current profile" in message
    assert "full_access" not in message
