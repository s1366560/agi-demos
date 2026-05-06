"""Tests for the canonical story parser."""

from __future__ import annotations

import textwrap

import pytest

from src.domain.model.canonical_story import (
    InvestStatus,
    invest_blocking_failures,
    parse_canonical_story,
)


def _wrap(yaml_text: str) -> str:
    return f"Some preamble.\n\n```yaml\n{textwrap.dedent(yaml_text).strip()}\n```\n\nTrailing notes."


_FULL_STORY = """
story:
  version: 1
  language: en
  title: Add password reset endpoint
  problem_statement: Users cannot recover lost passwords without admin help.
  user_value: Self-service recovery cuts support tickets.
  acceptance_criteria:
    - id: AC1
      text: POST /password-reset returns 200 for known emails.
      testable: true
    - id: AC2
      text: Token expires after 30 minutes.
      testable: true
  constraints_and_affected_areas:
    - src/auth/
    - alembic/
  out_of_scope:
    - SSO providers
  dependencies_and_sequencing:
    independent_story_check: pass
    depends_on:
      - none
    unblock_condition: ''
  invest:
    independent: { status: pass, reason: standalone }
    negotiable: { status: pass, reason: scoped }
    valuable: { status: pass, reason: reduces tickets }
    estimable: { status: pass, reason: well-known }
    small: { status: pass, reason: one route }
    testable: { status: pass, reason: ACs are concrete }
"""


class TestParseCanonicalStory:
    def test_full_story_parses_cleanly(self) -> None:
        result = parse_canonical_story(_wrap(_FULL_STORY))
        assert result.has_yaml_block is True
        assert result.is_valid
        assert result.story is not None
        assert result.story.title == "Add password reset endpoint"
        assert len(result.story.acceptance_criteria) == 2
        assert result.story.acceptance_criteria[0].id == "AC1"
        assert all(c.status is InvestStatus.PASS for c in result.story.invest)

    def test_missing_yaml_block(self) -> None:
        result = parse_canonical_story("Just a description without YAML.")
        assert result.has_yaml_block is False
        assert result.story is None
        assert any("yaml" in i.message.lower() for i in result.issues)

    def test_invalid_yaml_syntax(self) -> None:
        body = "```yaml\nstory:\n  title: : :\n```"
        result = parse_canonical_story(body)
        assert result.has_yaml_block is True
        assert result.story is None
        assert result.issues

    def test_missing_required_field(self) -> None:
        bad = """
        story:
          version: 1
          language: en
          problem_statement: Missing title
          acceptance_criteria:
            - id: AC1
              text: x
              testable: true
          invest:
            independent: { status: pass, reason: x }
            negotiable: { status: pass, reason: x }
            valuable: { status: pass, reason: x }
            estimable: { status: pass, reason: x }
            small: { status: pass, reason: x }
            testable: { status: pass, reason: x }
        """
        result = parse_canonical_story(_wrap(bad))
        assert result.story is None
        assert any(i.path == "story.title" for i in result.issues)

    def test_invest_blocking_failures(self) -> None:
        bad = _FULL_STORY.replace(
            "small: { status: pass, reason: one route }",
            "small: { status: fail, reason: too big }",
        )
        result = parse_canonical_story(_wrap(bad))
        assert result.story is not None
        blocking = invest_blocking_failures(result.story)
        assert len(blocking) == 1
        assert blocking[0].key == "small"


@pytest.mark.parametrize(
    "missing_key",
    ["independent", "valuable", "small", "testable"],
)
def test_invest_warning_does_not_block(missing_key: str) -> None:
    body = _FULL_STORY.replace(
        f"{missing_key}: {{ status: pass,",
        f"{missing_key}: {{ status: warning,",
    )
    result = parse_canonical_story(_wrap(body))
    assert result.story is not None
    assert not invest_blocking_failures(result.story)
