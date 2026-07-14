"""Unit tests for heartbeat content and acknowledgement token handling."""

import pytest

from src.infrastructure.agent.heartbeat.tokens import (
    HEARTBEAT_TOKEN,
    _strip_markup,
    _strip_token_at_edges,
    is_heartbeat_content_effectively_empty,
    strip_heartbeat_token,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (None, False),
        ("", True),
        ("  \n\t", True),
        ("# Heartbeat\n## Notes", True),
        ("-\n* [ ]\n+ [x]", True),
        ("<!-- nothing to do -->", True),
        ("#TODO", False),
        ("- [ ] refresh the index", False),
        ("Review the failed task", False),
    ],
)
def test_is_heartbeat_content_effectively_empty(
    content: str | None,
    expected: bool,
) -> None:
    assert is_heartbeat_content_effectively_empty(content) is expected


def test_multiline_html_comment_is_effectively_empty() -> None:
    content = """<!--
This comment documents the heartbeat file.
-->"""

    assert is_heartbeat_content_effectively_empty(content) is True


def test_strip_markup_normalizes_html_entities_and_wrappers() -> None:
    assert _strip_markup("**<b>&nbsp;HEARTBEAT_OK</b>**") == "  HEARTBEAT_OK "


@pytest.mark.parametrize("raw", ["", "   "])
def test_strip_token_at_edges_handles_empty_text(raw: str) -> None:
    assert _strip_token_at_edges(raw) == ("", False)


def test_strip_token_at_edges_leaves_text_without_token_unchanged() -> None:
    assert _strip_token_at_edges("  ordinary reply  ") == ("ordinary reply", False)


@pytest.mark.parametrize(
    "raw",
    [
        HEARTBEAT_TOKEN,
        f"{HEARTBEAT_TOKEN} {HEARTBEAT_TOKEN}",
    ],
)
def test_strip_token_at_edges_removes_ack_only_reply(raw: str) -> None:
    assert _strip_token_at_edges(raw) == ("", True)


def test_strip_token_at_edges_removes_ack_only_trailing_punctuation() -> None:
    assert _strip_token_at_edges(f"{HEARTBEAT_TOKEN}!!!") == ("", True)


def test_strip_token_at_edges_removes_repeated_leading_and_trailing_tokens() -> None:
    assert _strip_token_at_edges(f"{HEARTBEAT_TOKEN}   Work remains   {HEARTBEAT_TOKEN}.") == (
        "Work remains",
        True,
    )


@pytest.mark.parametrize("raw", [None, "", " \n "])
def test_strip_heartbeat_token_suppresses_empty_input(raw: str | None) -> None:
    assert strip_heartbeat_token(raw) == (True, "", False)


def test_strip_heartbeat_token_leaves_reply_without_token_unchanged() -> None:
    assert strip_heartbeat_token("  ordinary reply  ") == (False, "ordinary reply", False)


@pytest.mark.parametrize(
    "raw",
    [
        HEARTBEAT_TOKEN,
        f"<span>{HEARTBEAT_TOKEN}</span>",
        f"&nbsp;{HEARTBEAT_TOKEN}&nbsp;",
    ],
)
def test_strip_heartbeat_token_suppresses_wrapped_ack_only_reply(raw: str) -> None:
    assert strip_heartbeat_token(raw) == (True, "", True)


def test_strip_heartbeat_token_suppresses_markdown_wrapped_ack() -> None:
    assert strip_heartbeat_token(f"**{HEARTBEAT_TOKEN}**") == (True, "", True)


def test_strip_heartbeat_token_uses_markup_normalized_content() -> None:
    assert strip_heartbeat_token(f"<b>{HEARTBEAT_TOKEN}</b> details remain") == (
        False,
        "details remain",
        True,
    )


def test_strip_heartbeat_token_does_not_remove_token_from_middle() -> None:
    raw = f"before {HEARTBEAT_TOKEN} after"

    assert strip_heartbeat_token(raw) == (False, raw, False)


def test_strip_heartbeat_token_message_mode_keeps_remaining_text() -> None:
    assert strip_heartbeat_token(f"{HEARTBEAT_TOKEN} short note") == (
        False,
        "short note",
        True,
    )


def test_strip_heartbeat_token_heartbeat_mode_suppresses_short_ack_text() -> None:
    assert strip_heartbeat_token(
        f"{HEARTBEAT_TOKEN} short note",
        mode="heartbeat",
        max_ack_chars=10,
    ) == (True, "", True)


def test_strip_heartbeat_token_heartbeat_mode_keeps_long_text() -> None:
    assert strip_heartbeat_token(
        f"{HEARTBEAT_TOKEN} work still remains",
        mode="heartbeat",
        max_ack_chars=5,
    ) == (False, "work still remains", True)


def test_strip_heartbeat_token_does_not_strip_excess_trailing_punctuation() -> None:
    raw = f"message {HEARTBEAT_TOKEN}!!!!!"

    assert strip_heartbeat_token(raw) == (False, raw, False)
