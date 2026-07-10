import pytest

from scripts.verify_e2e_agent import (
    E2E_AGENT_RESPONSE,
    verify_agent_events,
    verify_agent_history,
)


def test_verify_agent_events_requires_text_and_terminal_completion() -> None:
    verify_agent_events(
        [
            {"type": "text_delta", "data": {"delta": E2E_AGENT_RESPONSE}},
            {"type": "complete", "data": {}},
        ]
    )


@pytest.mark.parametrize(
    "events,match",
    [
        ([{"type": "complete", "data": {}}], "deterministic assistant text"),
        (
            [{"type": "text_delta", "data": {"delta": E2E_AGENT_RESPONSE}}],
            "terminal complete event",
        ),
        (
            [{"type": "error", "data": {"message": "provider failed"}}],
            "provider failed",
        ),
    ],
)
def test_verify_agent_events_rejects_incomplete_or_error_streams(
    events: list[dict[str, object]],
    match: str,
) -> None:
    with pytest.raises(RuntimeError, match=match):
        verify_agent_events(events)


def test_verify_agent_history_requires_persisted_assistant_text() -> None:
    verify_agent_history(
        {
            "timeline": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": E2E_AGENT_RESPONSE},
            ]
        }
    )


def test_verify_agent_history_rejects_missing_assistant_text() -> None:
    with pytest.raises(RuntimeError, match="persisted assistant text"):
        verify_agent_history({"timeline": [{"role": "user", "content": "hello"}]})
