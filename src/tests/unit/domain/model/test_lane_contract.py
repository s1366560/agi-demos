"""Tests for ``LaneContract`` + ``evaluate_gate``."""

from __future__ import annotations

from src.domain.model.lane_contract import (
    GateResult,
    LaneContractRegistry,
    evaluate_gate,
)

REGISTRY = LaneContractRegistry.default()


def test_default_registry_has_six_lanes() -> None:
    ids = {c.lane_id for c in REGISTRY.contracts}
    assert ids == {"backlog", "todo", "dev", "review", "done", "blocked"}


def test_dev_entry_gate_rejects_when_execution_plan_missing() -> None:
    contract = REGISTRY.get("dev")
    assert contract is not None
    body = "## Some Other Heading\nNo plan here."
    result = evaluate_gate(contract, gate="entry", card_body=body)
    assert result.overall is GateResult.FAIL
    failed_keys = {key for key, status, _ in result.checks if status is GateResult.FAIL}
    assert "has_execution_plan" in failed_keys


def test_dev_entry_gate_passes_with_required_sections() -> None:
    contract = REGISTRY.get("dev")
    assert contract is not None
    body = (
        "## Execution Plan\nStep 1.\n\n"
        "## Key Files & Entry Points\n- foo.py\n"
    )
    result = evaluate_gate(contract, gate="entry", card_body=body)
    assert result.overall is GateResult.PASS


def test_review_exit_gate_requires_approved_keyword() -> None:
    contract = REGISTRY.get("review")
    assert contract is not None
    pending_body = "## Review Findings\nVerdict: pending"
    pending = evaluate_gate(contract, gate="exit", card_body=pending_body)
    assert pending.overall is GateResult.FAIL

    approved_body = "## Review Findings\nVerdict: APPROVED"
    approved = evaluate_gate(contract, gate="exit", card_body=approved_body)
    assert approved.overall is GateResult.PASS


def test_blocked_exit_gate_requires_routing_decision() -> None:
    contract = REGISTRY.get("blocked")
    assert contract is not None
    body = "## Blocker Analysis\nRoot cause: env\nRouting decision: backlog"
    result = evaluate_gate(contract, gate="exit", card_body=body)
    assert result.overall is GateResult.PASS


def test_section_match_is_scoped_to_section_until_next_h2() -> None:
    contract = REGISTRY.get("dev")
    assert contract is not None
    # "Changed files" appears only in the Risk Notes section, not Dev Evidence.
    body = (
        "## Dev Evidence\nNo file list.\n\n"
        "## Risk Notes\nRisk: Changed files might break things.\n"
    )
    result = evaluate_gate(contract, gate="exit", card_body=body)
    failed_keys = {k for k, s, _ in result.checks if s is GateResult.FAIL}
    assert "has_changed_files" in failed_keys
