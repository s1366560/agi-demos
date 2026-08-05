"""Run-input state machine tests."""

import pytest

from src.domain.model.agent.run_input import (
    AgentRunInput,
    AgentRunInputDelivery,
    AgentRunInputStatus,
    InvalidAgentRunInputTransition,
)


def _run_input(delivery: AgentRunInputDelivery) -> AgentRunInput:
    return AgentRunInput(
        id="input-1",
        tenant_id="tenant-1",
        project_id="project-1",
        conversation_id="conversation-1",
        run_id="run-1",
        actor_user_id="user-1",
        expected_run_revision=3,
        message="Continue with the reviewed direction.",
        message_id="message-1",
        idempotency_key="key-1",
        payload_hash="hash-1",
        delivery=delivery,
    )


@pytest.mark.unit
def test_initial_status_matches_delivery_boundary() -> None:
    assert _run_input(AgentRunInputDelivery.STEER_NOW).status == (
        AgentRunInputStatus.PENDING_BOUNDARY
    )
    assert _run_input(AgentRunInputDelivery.QUEUE_NEXT).status == AgentRunInputStatus.QUEUED


@pytest.mark.unit
def test_queue_terminal_settlement_is_explicit() -> None:
    queued = _run_input(AgentRunInputDelivery.QUEUE_NEXT)

    assert queued.settle_run_terminal(succeeded=True).status == AgentRunInputStatus.READY
    assert queued.settle_run_terminal(succeeded=False).status == AgentRunInputStatus.BLOCKED


@pytest.mark.unit
def test_only_ready_queue_can_promote_and_replay_is_idempotent() -> None:
    ready = _run_input(AgentRunInputDelivery.QUEUE_NEXT).settle_run_terminal(succeeded=True)
    promoted = ready.promote(promoted_run_id="run-2", promotion_key="promote-1")

    assert promoted.status == AgentRunInputStatus.PROMOTED_TO_PLAN
    assert promoted.promoted_run_id == "run-2"
    assert promoted.promote(
        promoted_run_id="run-2",
        promotion_key="promote-1",
    ) == promoted


@pytest.mark.unit
def test_invalid_promotion_and_conflicting_replay_are_rejected() -> None:
    queued = _run_input(AgentRunInputDelivery.QUEUE_NEXT)
    with pytest.raises(InvalidAgentRunInputTransition):
        queued.promote(promoted_run_id="run-2", promotion_key="promote-1")

    promoted = queued.settle_run_terminal(succeeded=True).promote(
        promoted_run_id="run-2",
        promotion_key="promote-1",
    )
    with pytest.raises(InvalidAgentRunInputTransition):
        promoted.promote(promoted_run_id="run-3", promotion_key="promote-2")


@pytest.mark.unit
def test_steer_can_only_be_applied_from_pending_boundary() -> None:
    pending = _run_input(AgentRunInputDelivery.STEER_NOW)
    applied = pending.mark_applied(injected_via="control_channel")

    assert applied.status == AgentRunInputStatus.APPLIED
    assert applied.injected_via == "control_channel"
    assert applied.mark_applied(injected_via="control_channel") == applied
    with pytest.raises(InvalidAgentRunInputTransition):
        _run_input(AgentRunInputDelivery.QUEUE_NEXT).mark_applied(
            injected_via="control_channel"
        )
