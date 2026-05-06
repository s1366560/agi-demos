"""Canonical story — distilled from routa's `canonical-story.ts`.

A canonical story is the structured contract that Backlog produces and Todo
trusts. It is the single source of truth for ``problem_statement``,
``acceptance_criteria``, ``invest`` checks, and dependencies.

We accept the YAML block embedded inside a fenced ```yaml``` region in the
card body. Parsing failures, missing keys, and INVEST FAILs are all
reported as structured ``CanonicalStoryIssue`` items so the UI can render
them as a checklist instead of crashing on the LLM's output.

Per Agent-First: this module only parses + checks **structural** invariants
(field presence, type, INVEST status enum). Whether an AC is "actually
testable" remains a subjective call delegated upstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import yaml

from src.domain.shared_kernel import ValueObject


class InvestStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"


_INVEST_KEYS: tuple[str, ...] = (
    "independent",
    "negotiable",
    "valuable",
    "estimable",
    "small",
    "testable",
)


@dataclass(frozen=True, kw_only=True)
class AcceptanceCriterion(ValueObject):
    id: str
    text: str
    testable: bool


@dataclass(frozen=True, kw_only=True)
class InvestCheck(ValueObject):
    key: str
    status: InvestStatus
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class CanonicalStory(ValueObject):
    """Parsed canonical story document."""

    version: int
    language: str
    title: str
    problem_statement: str
    user_value: str
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    constraints_and_affected_areas: tuple[str, ...] = field(default_factory=tuple)
    out_of_scope: tuple[str, ...] = field(default_factory=tuple)
    invest: tuple[InvestCheck, ...] = field(default_factory=tuple)
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    independent_story_check: str = "pass"  # "pass" | "fail"
    unblock_condition: str = ""


@dataclass(frozen=True, kw_only=True)
class CanonicalStoryIssue(ValueObject):
    path: str
    message: str


@dataclass(frozen=True, kw_only=True)
class CanonicalStoryParseResult(ValueObject):
    has_yaml_block: bool
    story: CanonicalStory | None
    issues: tuple[CanonicalStoryIssue, ...] = field(default_factory=tuple)
    raw_yaml: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.story is not None and not self.issues


_YAML_BLOCK_RE = re.compile(r"```yaml\s*\n([\s\S]*?)\n```", re.IGNORECASE)


def parse_canonical_story(card_body: str) -> CanonicalStoryParseResult:
    """Extract the first ```yaml``` block and validate it.

    Returns a result with ``story=None`` on any structural failure; specific
    failure points are captured in ``issues``. Successful parses produce a
    fully-typed ``CanonicalStory``.
    """
    match = _YAML_BLOCK_RE.search(card_body)
    if not match:
        return CanonicalStoryParseResult(
            has_yaml_block=False,
            story=None,
            issues=(
                CanonicalStoryIssue(
                    path="card_body",
                    message="No fenced ```yaml block found.",
                ),
            ),
        )

    raw = match.group(1)
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return CanonicalStoryParseResult(
            has_yaml_block=True,
            story=None,
            raw_yaml=raw,
            issues=(
                CanonicalStoryIssue(path="yaml", message=f"YAML parse error: {exc}"),
            ),
        )

    if not isinstance(loaded, dict) or "story" not in loaded:
        return CanonicalStoryParseResult(
            has_yaml_block=True,
            story=None,
            raw_yaml=raw,
            issues=(
                CanonicalStoryIssue(
                    path="yaml.story",
                    message="Top-level `story` key missing.",
                ),
            ),
        )

    story_node = loaded["story"]
    if not isinstance(story_node, dict):
        return CanonicalStoryParseResult(
            has_yaml_block=True,
            story=None,
            raw_yaml=raw,
            issues=(
                CanonicalStoryIssue(
                    path="yaml.story",
                    message="`story` must be a mapping.",
                ),
            ),
        )

    issues: list[CanonicalStoryIssue] = []
    story = _build_story(story_node, issues)
    if issues and story is None:
        return CanonicalStoryParseResult(
            has_yaml_block=True,
            story=None,
            raw_yaml=raw,
            issues=tuple(issues),
        )
    return CanonicalStoryParseResult(
        has_yaml_block=True,
        story=story,
        raw_yaml=raw,
        issues=tuple(issues),
    )


def _build_story(
    node: dict[str, Any], issues: list[CanonicalStoryIssue]
) -> CanonicalStory | None:
    title = _read_str(node, "title", issues)
    problem = _read_str(node, "problem_statement", issues)
    if not title or not problem:
        return None

    acs = _read_acceptance_criteria(node.get("acceptance_criteria"), issues)
    invest = _read_invest(node.get("invest"), issues)

    deps_node = node.get("dependencies_and_sequencing") or {}
    depends_on = _read_str_tuple(deps_node.get("depends_on"))
    independent_check = (
        str(deps_node.get("independent_story_check", "pass")).lower()
        if isinstance(deps_node, dict)
        else "pass"
    )

    return CanonicalStory(
        version=int(node.get("version") or 1),
        language=str(node.get("language") or "en"),
        title=title,
        problem_statement=problem,
        user_value=str(node.get("user_value") or ""),
        acceptance_criteria=acs,
        constraints_and_affected_areas=_read_str_tuple(
            node.get("constraints_and_affected_areas")
        ),
        out_of_scope=_read_str_tuple(node.get("out_of_scope")),
        invest=invest,
        depends_on=depends_on,
        independent_story_check=independent_check,
        unblock_condition=str(deps_node.get("unblock_condition", ""))
        if isinstance(deps_node, dict)
        else "",
    )


def _read_str(node: dict[str, Any], key: str, issues: list[CanonicalStoryIssue]) -> str:
    value = node.get(key)
    if not isinstance(value, str) or not value.strip():
        issues.append(
            CanonicalStoryIssue(
                path=f"story.{key}",
                message=f"`{key}` must be a non-empty string.",
            )
        )
        return ""
    return value.strip()


def _read_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _read_acceptance_criteria(
    value: object, issues: list[CanonicalStoryIssue]
) -> tuple[AcceptanceCriterion, ...]:
    if not isinstance(value, list) or not value:
        issues.append(
            CanonicalStoryIssue(
                path="story.acceptance_criteria",
                message="acceptance_criteria must be a non-empty list.",
            )
        )
        return ()
    out: list[AcceptanceCriterion] = []
    for idx, raw in enumerate(value):
        if not isinstance(raw, dict):
            issues.append(
                CanonicalStoryIssue(
                    path=f"story.acceptance_criteria[{idx}]",
                    message="Each AC must be a mapping with id/text/testable.",
                )
            )
            continue
        ac_id = str(raw.get("id") or f"AC{idx + 1}").strip()
        text = str(raw.get("text") or "").strip()
        if not text:
            issues.append(
                CanonicalStoryIssue(
                    path=f"story.acceptance_criteria[{idx}].text",
                    message="AC text is required.",
                )
            )
            continue
        out.append(
            AcceptanceCriterion(
                id=ac_id,
                text=text,
                testable=bool(raw.get("testable", False)),
            )
        )
    return tuple(out)


def _read_invest(
    value: object, issues: list[CanonicalStoryIssue]
) -> tuple[InvestCheck, ...]:
    if not isinstance(value, dict):
        issues.append(
            CanonicalStoryIssue(
                path="story.invest",
                message="invest must be a mapping with the six INVEST keys.",
            )
        )
        return ()
    out: list[InvestCheck] = []
    for key in _INVEST_KEYS:
        sub = value.get(key)
        if not isinstance(sub, dict):
            issues.append(
                CanonicalStoryIssue(
                    path=f"story.invest.{key}",
                    message=f"invest.{key} must be a mapping with status + reason.",
                )
            )
            continue
        status_raw = str(sub.get("status", "")).lower()
        try:
            status = InvestStatus(status_raw)
        except ValueError:
            issues.append(
                CanonicalStoryIssue(
                    path=f"story.invest.{key}.status",
                    message=f"invest.{key}.status must be pass/fail/warning.",
                )
            )
            continue
        out.append(
            InvestCheck(
                key=key,
                status=status,
                reason=str(sub.get("reason") or "").strip(),
            )
        )
    return tuple(out)


def invest_blocking_failures(story: CanonicalStory) -> tuple[InvestCheck, ...]:
    """Return INVEST checks that are FAIL (warnings allowed).

    Used by Todo's entry-gate: a story with any FAIL in
    independent/valuable/small/testable should not move forward.
    """
    blocking_keys = {"independent", "valuable", "small", "testable"}
    return tuple(
        c for c in story.invest if c.key in blocking_keys and c.status is InvestStatus.FAIL
    )


__all__ = [
    "AcceptanceCriterion",
    "CanonicalStory",
    "CanonicalStoryIssue",
    "CanonicalStoryParseResult",
    "InvestCheck",
    "InvestStatus",
    "invest_blocking_failures",
    "parse_canonical_story",
]
