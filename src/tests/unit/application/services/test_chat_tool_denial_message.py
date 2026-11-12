"""Denial text names the tool and the current grant without widening it."""

import pytest

from src.application.services.chat_run_tool_permission_v2 import format_chat_tool_denial

pytestmark = pytest.mark.unit


def test_unbound_denial_keeps_the_current_profile() -> None:
    message = format_chat_tool_denial("edit")
    assert message.startswith("tool_not_authorized tool=edit ")
    assert "permission_mode=unbound" in message
    assert "permission_profile=unbound" in message
    assert "keeps its current profile" in message
    assert "full_access" not in message
