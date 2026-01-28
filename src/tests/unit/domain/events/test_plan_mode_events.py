"""
Unit tests for Plan Mode domain events.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.
"""

from unittest.mock import Mock
from typing import Any

import pytest

from src.domain.events.agent_events import (
    AgentEventType,
    AgentPlanExecutionStartEvent,
    AgentPlanExecutionCompleteEvent,
    AgentPlanStepReadyEvent,
    AgentPlanStepCompleteEvent,
    AgentPlanStepSkippedEvent,
    AgentPlanSnapshotCreatedEvent,
    AgentPlanRollbackEvent,
    AgentReflectionCompleteEvent,
    AgentAdjustmentAppliedEvent,
)


class TestPlanExecutionStartEvent:
    """Tests for AgentPlanExecutionStartEvent."""

    def test_create_event(self) -> None:
        """Test creating plan execution start event."""
        event = AgentPlanExecutionStartEvent(
            plan_id="plan-1",
            total_steps=5,
            user_query="Test query",
        )

        assert event.event_type == AgentEventType.PLAN_EXECUTION_START
        assert event.plan_id == "plan-1"
        assert event.total_steps == 5
        assert event.user_query == "Test query"
        assert event.timestamp > 0

    def test_event_is_immutable(self) -> None:
        """Test that event is immutable."""
        event = AgentPlanExecutionStartEvent(
            plan_id="plan-1",
            total_steps=5,
            user_query="Test",
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            event.plan_id = "plan-2"

    def test_to_event_dict(self) -> None:
        """Test converting event to dictionary."""
        event = AgentPlanExecutionStartEvent(
            plan_id="plan-1",
            total_steps=3,
            user_query="Search memories",
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "plan_execution_start"
        assert event_dict["data"]["plan_id"] == "plan-1"
        assert event_dict["data"]["total_steps"] == 3
        assert "timestamp" in event_dict


class TestPlanExecutionCompleteEvent:
    """Tests for AgentPlanExecutionCompleteEvent."""

    def test_create_event(self) -> None:
        """Test creating plan execution complete event."""
        event = AgentPlanExecutionCompleteEvent(
            plan_id="plan-1",
            total_duration_ms=5000,
            steps_completed=4,
            steps_failed=1,
            final_status="completed",
        )

        assert event.event_type == AgentEventType.PLAN_EXECUTION_COMPLETE
        assert event.plan_id == "plan-1"
        assert event.total_duration_ms == 5000
        assert event.steps_completed == 4
        assert event.steps_failed == 1
        assert event.final_status == "completed"

    def test_to_event_dict(self) -> None:
        """Test converting event to dictionary."""
        event = AgentPlanExecutionCompleteEvent(
            plan_id="plan-1",
            total_duration_ms=1000,
            steps_completed=2,
            steps_failed=0,
            final_status="completed",
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "plan_execution_complete"
        assert event_dict["data"]["plan_id"] == "plan-1"
        assert event_dict["data"]["total_duration_ms"] == 1000


class TestPlanStepReadyEvent:
    """Tests for AgentPlanStepReadyEvent."""

    def test_create_event(self) -> None:
        """Test creating plan step ready event."""
        event = AgentPlanStepReadyEvent(
            plan_id="plan-1",
            step_id="step-1",
            step_number=1,
            description="Search memory",
            tool_name="MemorySearch",
        )

        assert event.event_type == AgentEventType.PLAN_STEP_READY
        assert event.step_id == "step-1"
        assert event.step_number == 1
        assert event.description == "Search memory"
        assert event.tool_name == "MemorySearch"

    def test_to_event_dict(self) -> None:
        """Test converting event to dictionary."""
        event = AgentPlanStepReadyEvent(
            plan_id="plan-1",
            step_id="step-2",
            step_number=2,
            description="Summarize",
            tool_name="Summary",
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "plan_step_ready"
        assert event_dict["data"]["step_id"] == "step-2"
        assert event_dict["data"]["step_number"] == 2


class TestPlanStepCompleteEvent:
    """Tests for AgentPlanStepCompleteEvent."""

    def test_create_event_with_success(self) -> None:
        """Test creating step complete event with success."""
        event = AgentPlanStepCompleteEvent(
            plan_id="plan-1",
            step_id="step-1",
            status="completed",
            result="Step completed successfully",
        )

        assert event.event_type == AgentEventType.PLAN_STEP_COMPLETE
        assert event.status == "completed"
        assert event.result == "Step completed successfully"
        assert event.error is None

    def test_create_event_with_failure(self) -> None:
        """Test creating step complete event with failure."""
        event = AgentPlanStepCompleteEvent(
            plan_id="plan-1",
            step_id="step-1",
            status="failed",
            error="Step failed: timeout",
        )

        assert event.status == "failed"
        assert event.error == "Step failed: timeout"
        assert event.result is None

    def test_to_event_dict(self) -> None:
        """Test converting event to dictionary."""
        event = AgentPlanStepCompleteEvent(
            plan_id="plan-1",
            step_id="step-1",
            status="completed",
            result="Done",
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "plan_step_complete"
        assert event_dict["data"]["status"] == "completed"


class TestPlanStepSkippedEvent:
    """Tests for AgentPlanStepSkippedEvent."""

    def test_create_event(self) -> None:
        """Test creating plan step skipped event."""
        event = AgentPlanStepSkippedEvent(
            plan_id="plan-1",
            step_id="step-2",
            reason="No longer needed after adjustment",
        )

        assert event.event_type == AgentEventType.PLAN_STEP_SKIPPED
        assert event.step_id == "step-2"
        assert event.reason == "No longer needed after adjustment"

    def test_to_event_dict(self) -> None:
        """Test converting event to dictionary."""
        event = AgentPlanStepSkippedEvent(
            plan_id="plan-1",
            step_id="step-3",
            reason="Dependency skipped",
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "plan_step_skipped"
        assert event_dict["data"]["reason"] == "Dependency skipped"


class TestPlanSnapshotCreatedEvent:
    """Tests for AgentPlanSnapshotCreatedEvent."""

    def test_create_event(self) -> None:
        """Test creating plan snapshot created event."""
        event = AgentPlanSnapshotCreatedEvent(
            plan_id="plan-1",
            snapshot_id="snap-1",
            snapshot_name="Before step 2",
            snapshot_type="named",
        )

        assert event.event_type == AgentEventType.PLAN_SNAPSHOT_CREATED
        assert event.plan_id == "plan-1"
        assert event.snapshot_id == "snap-1"
        assert event.snapshot_name == "Before step 2"
        assert event.snapshot_type == "named"

    def test_create_auto_snapshot(self) -> None:
        """Test creating auto snapshot event."""
        event = AgentPlanSnapshotCreatedEvent(
            plan_id="plan-1",
            snapshot_id="snap-auto",
            snapshot_name="Auto snapshot 12:30:00",
            snapshot_type="last_step",
        )

        assert event.snapshot_type == "last_step"


class TestPlanRollbackEvent:
    """Tests for AgentPlanRollbackEvent."""

    def test_create_event(self) -> None:
        """Test creating plan rollback event."""
        event = AgentPlanRollbackEvent(
            plan_id="plan-1",
            snapshot_id="snap-1",
            reason="Adjustment failed, reverting",
        )

        assert event.event_type == AgentEventType.PLAN_ROLLBACK
        assert event.plan_id == "plan-1"
        assert event.snapshot_id == "snap-1"
        assert event.reason == "Adjustment failed, reverting"


class TestReflectionCompleteEvent:
    """Tests for AgentReflectionCompleteEvent."""

    def test_create_event_on_track(self) -> None:
        """Test creating reflection complete event with on_track assessment."""
        event = AgentReflectionCompleteEvent(
            reflection_id="ref-1",
            plan_id="plan-1",
            assessment="on_track",
            recommended_action="continue",
            summary="Execution progressing as expected",
            has_adjustments=False,
            adjustment_count=0,
        )

        assert event.event_type == AgentEventType.REFLECTION_COMPLETE
        assert event.assessment == "on_track"
        assert event.recommended_action == "continue"
        assert event.has_adjustments is False
        assert event.adjustment_count == 0

    def test_create_event_with_adjustments(self) -> None:
        """Test creating reflection complete event with adjustments."""
        event = AgentReflectionCompleteEvent(
            reflection_id="ref-2",
            plan_id="plan-1",
            assessment="needs_adjustment",
            recommended_action="adjust",
            summary="Step failed, needs retry",
            has_adjustments=True,
            adjustment_count=1,
        )

        assert event.assessment == "needs_adjustment"
        assert event.has_adjustments is True
        assert event.adjustment_count == 1

    def test_to_event_dict(self) -> None:
        """Test converting event to dictionary."""
        event = AgentReflectionCompleteEvent(
            reflection_id="ref-1",
            plan_id="plan-1",
            assessment="complete",
            recommended_action="complete",
            summary="Goal achieved",
            has_adjustments=False,
            adjustment_count=0,
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "reflection_complete"
        assert event_dict["data"]["assessment"] == "complete"
        assert event_dict["data"]["has_adjustments"] is False


class TestAdjustmentAppliedEvent:
    """Tests for AgentAdjustmentAppliedEvent."""

    def test_create_event_single_adjustment(self) -> None:
        """Test creating adjustment applied event with single adjustment."""
        adjustments = [
            {
                "step_id": "step-1",
                "adjustment_type": "retry",
                "reason": "Timeout",
                "new_tool_input": {"timeout": 60},
            }
        ]

        event = AgentAdjustmentAppliedEvent(
            plan_id="plan-1",
            adjustment_count=1,
            adjustments=adjustments,
        )

        assert event.event_type == AgentEventType.ADJUSTMENT_APPLIED
        assert event.plan_id == "plan-1"
        assert event.adjustment_count == 1
        assert len(event.adjustments) == 1

    def test_create_event_multiple_adjustments(self) -> None:
        """Test creating adjustment applied event with multiple adjustments."""
        adjustments = [
            {
                "step_id": "step-1",
                "adjustment_type": "modify",
                "reason": "Update params",
            },
            {
                "step_id": "step-2",
                "adjustment_type": "skip",
                "reason": "Not needed",
            },
        ]

        event = AgentAdjustmentAppliedEvent(
            plan_id="plan-1",
            adjustment_count=2,
            adjustments=adjustments,
        )

        assert event.adjustment_count == 2
        assert len(event.adjustments) == 2

    def test_to_event_dict(self) -> None:
        """Test converting event to dictionary."""
        adjustments = [{"step_id": "step-1", "action": "retry"}]

        event = AgentAdjustmentAppliedEvent(
            plan_id="plan-1",
            adjustment_count=1,
            adjustments=adjustments,
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "adjustment_applied"
        assert event_dict["data"]["adjustment_count"] == 1
        assert len(event_dict["data"]["adjustments"]) == 1
