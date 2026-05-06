"""Lane contract definitions and deterministic gate evaluation.

Distilled from routa's `resources/specialists/workflows/kanban/*.yaml`. Each
lane's required sections + entry/exit gates are declared as data, so the
agent runtime can:

1. Show the user *which* gate is failing (Lane Inspector UI).
2. Refuse to advance the card without forcing the LLM to remember the rule.

The gate evaluator only checks **structural** facts (section presence,
substring match) — never semantic quality. Quality verdicts go through an
agent tool-call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from src.domain.shared_kernel import ValueObject


class GateResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True, kw_only=True)
class GateCheck(ValueObject):
    """One structural check on a card body or context.

    ``key`` is a stable id (e.g. ``"has_dev_evidence"``) used by the UI to
    render localized check labels.

    ``required_section`` (when set) — the heading string that must appear
    in the card body, e.g. ``"## Dev Evidence"``.

    ``required_substring`` (when set) — a literal substring or regex that
    must appear inside the matched section (or anywhere in the body when
    ``required_section`` is empty).
    """

    key: str
    label: str
    required_section: str | None = None
    required_substring: str | None = None
    is_regex: bool = False
    rejection_reason: str = ""

    def matches(self, card_body: str) -> bool:
        section_text = card_body
        if self.required_section:
            idx = card_body.find(self.required_section)
            if idx < 0:
                return False
            # Section text is from the heading until the next '## ' heading.
            tail = card_body[idx + len(self.required_section) :]
            next_h = re.search(r"\n##\s", tail)
            section_text = tail[: next_h.start()] if next_h else tail
        if self.required_substring is None:
            return True
        if self.is_regex:
            return re.search(self.required_substring, section_text) is not None
        return self.required_substring in section_text


@dataclass(frozen=True, kw_only=True)
class LaneContract(ValueObject):
    """The contract one lane enforces."""

    lane_id: str
    display_name: str
    required_sections: tuple[str, ...] = field(default_factory=tuple)
    entry_gate: tuple[GateCheck, ...] = field(default_factory=tuple)
    exit_gate: tuple[GateCheck, ...] = field(default_factory=tuple)
    next_lane_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class GateEvaluation(ValueObject):
    """Result of evaluating one gate against a card body."""

    lane_id: str
    gate: str  # "entry" | "exit"
    overall: GateResult
    checks: tuple[tuple[str, GateResult, str], ...]
    """Per-check tuple: (check_key, result, label_for_display)."""


def evaluate_gate(
    contract: LaneContract,
    *,
    gate: str,
    card_body: str,
) -> GateEvaluation:
    """Run every check in the named gate. Pure function."""
    checks = contract.entry_gate if gate == "entry" else contract.exit_gate
    results: list[tuple[str, GateResult, str]] = []
    overall = GateResult.PASS
    for check in checks:
        ok = check.matches(card_body)
        result = GateResult.PASS if ok else GateResult.FAIL
        if not ok:
            overall = GateResult.FAIL
        results.append((check.key, result, check.label))
    return GateEvaluation(
        lane_id=contract.lane_id,
        gate=gate,
        overall=overall,
        checks=tuple(results),
    )


# ---------------------------------------------------------------------------
# Default Kanban contracts (mirrors routa's lane prompts)
# ---------------------------------------------------------------------------


def default_kanban_contracts() -> tuple[LaneContract, ...]:
    """Return the canonical 6-lane Kanban contract set."""
    return (
        LaneContract(
            lane_id="backlog",
            display_name="Backlog",
            required_sections=("```yaml",),
            entry_gate=(),
            exit_gate=(
                GateCheck(
                    key="has_canonical_yaml",
                    label="Canonical story YAML block present",
                    required_substring="```yaml",
                    rejection_reason="Backlog must produce a canonical YAML story block.",
                ),
                GateCheck(
                    key="has_acceptance_criteria",
                    label="At least one acceptance_criteria item",
                    required_substring="acceptance_criteria",
                    rejection_reason="Story must declare acceptance_criteria.",
                ),
            ),
            next_lane_id="todo",
        ),
        LaneContract(
            lane_id="todo",
            display_name="Todo",
            required_sections=(
                "## Execution Plan",
                "## Key Files & Entry Points",
                "## Dependency Plan",
                "## Risk Notes",
            ),
            entry_gate=(
                GateCheck(
                    key="has_canonical_yaml",
                    label="Backlog left a canonical YAML story",
                    required_substring="```yaml",
                    rejection_reason="Reject to backlog: canonical story missing.",
                ),
            ),
            exit_gate=(
                GateCheck(
                    key="has_execution_plan",
                    label="Execution Plan section present",
                    required_section="## Execution Plan",
                    rejection_reason="Add Execution Plan before moving to Dev.",
                ),
                GateCheck(
                    key="has_key_files",
                    label="Key Files & Entry Points present",
                    required_section="## Key Files & Entry Points",
                    rejection_reason="Identify key files before Dev can start.",
                ),
                GateCheck(
                    key="has_dependency_plan",
                    label="Dependency Plan declares sequencing",
                    required_section="## Dependency Plan",
                    rejection_reason="Declare Dependency Plan explicitly.",
                ),
            ),
            next_lane_id="dev",
        ),
        LaneContract(
            lane_id="dev",
            display_name="Dev",
            required_sections=("## Dev Evidence",),
            entry_gate=(
                GateCheck(
                    key="has_execution_plan",
                    label="Todo left an Execution Plan",
                    required_section="## Execution Plan",
                    rejection_reason="Reject to todo: no execution plan.",
                ),
                GateCheck(
                    key="has_key_files",
                    label="Todo identified key files",
                    required_section="## Key Files & Entry Points",
                    rejection_reason="Reject to todo: no entry points.",
                ),
            ),
            exit_gate=(
                GateCheck(
                    key="has_dev_evidence",
                    label="Dev Evidence section present",
                    required_section="## Dev Evidence",
                    rejection_reason="Add Dev Evidence with changed files + tests.",
                ),
                GateCheck(
                    key="has_changed_files",
                    label="Changed files listed in Dev Evidence",
                    required_section="## Dev Evidence",
                    required_substring="Changed files",
                    rejection_reason="List changed files in Dev Evidence.",
                ),
                GateCheck(
                    key="has_ac_verification",
                    label="AC verification documented",
                    required_section="## Dev Evidence",
                    required_substring="AC verification",
                    rejection_reason="Document AC verification per item.",
                ),
            ),
            next_lane_id="review",
        ),
        LaneContract(
            lane_id="review",
            display_name="Review",
            required_sections=("## Review Findings",),
            entry_gate=(
                GateCheck(
                    key="has_dev_evidence",
                    label="Dev provided Dev Evidence",
                    required_section="## Dev Evidence",
                    rejection_reason="Reject to dev: no Dev Evidence.",
                ),
            ),
            exit_gate=(
                GateCheck(
                    key="has_review_findings",
                    label="Review Findings section present",
                    required_section="## Review Findings",
                    rejection_reason="Write Review Findings with verdict.",
                ),
                GateCheck(
                    key="approved_verdict",
                    label="Verdict explicitly APPROVED",
                    required_section="## Review Findings",
                    required_substring="APPROVED",
                    rejection_reason="Verdict must be APPROVED to advance to done.",
                ),
            ),
            next_lane_id="done",
        ),
        LaneContract(
            lane_id="done",
            display_name="Done",
            required_sections=("## Completion Summary",),
            entry_gate=(
                GateCheck(
                    key="approved_verdict",
                    label="Review APPROVED the card",
                    required_section="## Review Findings",
                    required_substring="APPROVED",
                    rejection_reason="Reject to review: card not approved.",
                ),
            ),
            exit_gate=(),
            next_lane_id=None,
        ),
        LaneContract(
            lane_id="blocked",
            display_name="Blocked",
            required_sections=("## Blocker Analysis",),
            entry_gate=(),
            exit_gate=(
                GateCheck(
                    key="has_blocker_analysis",
                    label="Blocker Analysis section present",
                    required_section="## Blocker Analysis",
                    rejection_reason="Document blocker before routing.",
                ),
                GateCheck(
                    key="has_routing_decision",
                    label="Routing decision recorded",
                    required_section="## Blocker Analysis",
                    required_substring="Routing decision",
                    rejection_reason="Decide which lane the card returns to.",
                ),
            ),
            next_lane_id=None,
        ),
    )


@dataclass(frozen=True)
class LaneContractRegistry:
    """In-memory registry mapping ``lane_id`` to its contract."""

    contracts: tuple[LaneContract, ...]

    def get(self, lane_id: str) -> LaneContract | None:
        for contract in self.contracts:
            if contract.lane_id == lane_id:
                return contract
        return None

    @classmethod
    def default(cls) -> LaneContractRegistry:
        return cls(contracts=default_kanban_contracts())
