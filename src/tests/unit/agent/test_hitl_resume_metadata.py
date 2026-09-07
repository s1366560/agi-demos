"""Ordinary HITL answers retain the exact payload consumed by durable runtimes."""

import json

import pytest

from src.infrastructure.agent.hitl.utils import summarize_hitl_response

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("hitl_type", "field"), [("clarification", "answer"), ("decision", "decision")]
)
def test_ordinary_answer_keeps_exact_text_separate_from_display_summary(
    hitl_type: str, field: str
) -> None:
    answer = "  保留原文\n<choice>\t" + "正文" * 2000 + "  "
    summary, metadata = summarize_hitl_response(
        hitl_type, {field: answer, "resume_answer": "untrusted override"}
    )

    assert metadata == {"resume_answer": answer, "resume_answer_encoding": "utf-8"}
    assert summary != answer


@pytest.mark.parametrize(
    ("hitl_type", "field"), [("clarification", "answer"), ("decision", "decision")]
)
def test_ordinary_choices_encode_compact_json_without_reusing_sanitized_summary(
    hitl_type: str, field: str
) -> None:
    choices = ["  keep whitespace  ", "中文", "<second>"]
    _, metadata = summarize_hitl_response(hitl_type, {field: choices})

    assert metadata is not None
    assert metadata["resume_answer"] == '["  keep whitespace  ","中文","<second>"]'
    assert json.loads(metadata["resume_answer"]) == choices


def test_permission_response_does_not_gain_ordinary_resume_authority() -> None:
    assert summarize_hitl_response("permission", {"action": "allow_once"}) == (
        "allow_once",
        None,
    )
