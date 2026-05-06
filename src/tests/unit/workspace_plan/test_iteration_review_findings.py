"""Tests for the structured-findings channel on LLMIterationReviewProvider."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.domain.model.review.review_finding import FindingVerdict, ReviewSeverity
from src.domain.ports.services.iteration_review_port import IterationReviewContext
from src.infrastructure.agent.workspace_plan.iteration_review import (
    LLMIterationReviewProvider,
)


@dataclass
class _StubLLM:
    response: dict[str, Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def generate(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def _tool_response(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_calls": [
            {
                "function": {
                    "arguments": json.dumps(args),
                }
            }
        ]
    }


def _base_context(**overrides: Any) -> IterationReviewContext:
    defaults: dict[str, Any] = {
        "workspace_id": "ws-1",
        "plan_id": "plan-1",
        "iteration_index": 1,
        "goal_title": "Goal",
        "goal_description": "Goal description.",
        "max_next_tasks": 6,
    }
    defaults.update(overrides)
    return IterationReviewContext(**defaults)


@pytest.mark.asyncio
async def test_provider_filters_test_file_and_keeps_critical() -> None:
    llm = _StubLLM(
        response=_tool_response(
            {
                "verdict": "complete_goal",
                "confidence": 0.9,
                "summary": "Done.",
                "findings": [
                    {
                        "file": "src/tests/unit/test_x.py",
                        "line": 12,
                        "category": "input validation",
                        "severity": "WARNING",
                        "raw_confidence": 70,
                        "description": "Missing input validation in fixture.",
                        "suggestion": "Add validation.",
                    },
                    {
                        "file": "src/server.py",
                        "line": 42,
                        "category": "sql injection",
                        "severity": "CRITICAL",
                        "raw_confidence": 95,
                        "description": "User input concatenated into SQL query.",
                        "suggestion": "Use parameterized queries.",
                        "concrete_evidence": True,
                    },
                ],
            }
        )
    )
    provider = LLMIterationReviewProvider(llm, max_next_tasks=6)  # type: ignore[arg-type]

    verdict = await provider.review(_base_context())

    assert verdict.verdict == "complete_goal"
    assert len(verdict.findings) == 1
    assert verdict.findings[0].file == "src/server.py"
    assert verdict.findings[0].verdict is FindingVerdict.KEEP
    assert verdict.findings[0].severity is ReviewSeverity.CRITICAL
    assert verdict.rejected_finding_count == 1


@pytest.mark.asyncio
async def test_provider_handles_missing_findings_field() -> None:
    llm = _StubLLM(
        response=_tool_response(
            {
                "verdict": "complete_goal",
                "confidence": 0.9,
                "summary": "Done.",
            }
        )
    )
    provider = LLMIterationReviewProvider(llm, max_next_tasks=6)  # type: ignore[arg-type]

    verdict = await provider.review(_base_context())

    assert verdict.findings == ()
    assert verdict.rejected_finding_count == 0


@pytest.mark.asyncio
async def test_provider_skips_malformed_findings() -> None:
    llm = _StubLLM(
        response=_tool_response(
            {
                "verdict": "complete_goal",
                "confidence": 0.9,
                "summary": "Done.",
                "findings": [
                    # Missing severity → skipped silently.
                    {
                        "file": "src/server.py",
                        "line": 1,
                        "category": "logic",
                        "raw_confidence": 50,
                        "description": "Something.",
                        "suggestion": "Fix.",
                    },
                    # Bad line type → skipped.
                    {
                        "file": "src/server.py",
                        "line": "not-an-int",
                        "category": "logic",
                        "severity": "WARNING",
                        "raw_confidence": 50,
                        "description": "Something.",
                        "suggestion": "Fix.",
                    },
                    # Well-formed.
                    {
                        "file": "src/server.py",
                        "line": 99,
                        "category": "race condition",
                        "severity": "CRITICAL",
                        "raw_confidence": 90,
                        "description": "Concrete race shown by trace.",
                        "suggestion": "Add lock.",
                        "concrete_evidence": True,
                    },
                ],
            }
        )
    )
    provider = LLMIterationReviewProvider(llm, max_next_tasks=6)  # type: ignore[arg-type]

    verdict = await provider.review(_base_context())

    assert len(verdict.findings) == 1
    assert verdict.findings[0].file == "src/server.py"
    assert verdict.findings[0].line == 99


@pytest.mark.asyncio
async def test_linter_covered_categories_threaded_from_context() -> None:
    llm = _StubLLM(
        response=_tool_response(
            {
                "verdict": "complete_goal",
                "confidence": 0.9,
                "summary": "Done.",
                "findings": [
                    {
                        "file": "src/server.py",
                        "line": 5,
                        "category": "import-order",
                        "severity": "WARNING",
                        "raw_confidence": 60,
                        "description": "Imports out of order.",
                        "suggestion": "Reorder.",
                    },
                ],
            }
        )
    )
    provider = LLMIterationReviewProvider(llm, max_next_tasks=6)  # type: ignore[arg-type]

    verdict = await provider.review(_base_context(linter_covered_categories=("import-order",)))

    assert verdict.findings == ()
    assert verdict.rejected_finding_count == 1
