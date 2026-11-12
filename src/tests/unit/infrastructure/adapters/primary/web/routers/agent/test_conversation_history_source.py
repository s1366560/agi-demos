"""Parent conversation history is the execution event stream."""

import inspect

import pytest

from src.infrastructure.adapters.primary.web.routers.agent.messages import (
    get_conversation_messages,
)

pytestmark = pytest.mark.unit


def test_message_route_reads_execution_events_not_the_messages_table() -> None:
    source = inspect.getsource(get_conversation_messages)
    assert "get_events" in source
    assert "agent execution event stream" in inspect.getdoc(get_conversation_messages)
    assert "public.messages" in inspect.getdoc(get_conversation_messages)
