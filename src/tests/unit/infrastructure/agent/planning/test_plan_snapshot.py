"""
Unit tests for PlanSnapshot domain model.

Tests follow TDD: Write first, verify FAIL, implement, verify PASS.
"""

from datetime import datetime, timezone

import pytest

from src.domain.model.agent.plan_snapshot import PlanSnapshot, StepState


class TestStepState:
    """Tests for StepState value object."""

    def test_create_step_state(self) -> None:
        """Test creating a step state."""
        state = StepState(
            step_id="step-1",
            status="running",
            result="Partial result",
        )

        assert state.step_id == "step-1"
        assert state.status == "running"
        assert state.result == "Partial result"
        assert state.error is None
        assert state.started_at is None

    def test_create_step_state_with_all_fields(self) -> None:
        """Test creating step state with all fields."""
        now = datetime.now(timezone.utc)
        state = StepState(
            step_id="step-1",
            status="completed",
            result="Done",
            error=None,
            started_at=now,
            completed_at=now,
        )

        assert state.step_id == "step-1"
        assert state.status == "completed"
        assert state.result == "Done"
        assert state.started_at == now
        assert state.completed_at == now

    def test_step_state_is_immutable(self) -> None:
        """Test that StepState is immutable."""
        from dataclasses import FrozenInstanceError

        state = StepState(
            step_id="step-1",
            status="pending",
        )

        with pytest.raises(FrozenInstanceError):
            state.status = "running"

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        state = StepState(
            step_id="step-1",
            status="completed",
            result="Success",
        )

        result = state.to_dict()

        assert result["step_id"] == "step-1"
        assert result["status"] == "completed"
        assert result["result"] == "Success"

    def test_from_execution_step(self) -> None:
        """Test creating StepState from ExecutionStep."""
        from src.domain.model.agent.execution_plan import (
            ExecutionStep,
            ExecutionStepStatus,
        )

        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
            status=ExecutionStepStatus.RUNNING,
            result="In progress",
        )

        state = StepState.from_execution_step(step)

        assert state.step_id == "step-1"
        assert state.status == "running"
        assert state.result == "In progress"


class TestPlanSnapshot:
    """Tests for PlanSnapshot entity."""

    def test_create_snapshot_minimal(self) -> None:
        """Test creating a snapshot with minimal fields."""
        snapshot = PlanSnapshot(
            plan_id="plan-1",
            name="checkpoint",
            step_states={},
        )

        assert snapshot.plan_id == "plan-1"
        assert snapshot.name == "checkpoint"
        assert snapshot.step_states == {}
        assert snapshot.description is None
        assert snapshot.auto_created is True  # Default
        assert snapshot.snapshot_type == "last_step"  # Default

    def test_create_snapshot_full(self) -> None:
        """Test creating a snapshot with all fields."""
        state = StepState(step_id="step-1", status="completed")
        snapshot = PlanSnapshot(
            plan_id="plan-1",
            name="Manual checkpoint",
            step_states={"step-1": state},
            description="Before complex operation",
            auto_created=False,
            snapshot_type="named",
        )

        assert snapshot.plan_id == "plan-1"
        assert snapshot.name == "Manual checkpoint"
        assert snapshot.description == "Before complex operation"
        assert snapshot.auto_created is False
        assert snapshot.snapshot_type == "named"
        assert "step-1" in snapshot.step_states

    def test_create_named_snapshot(self) -> None:
        """Test creating a named snapshot factory method."""
        state = StepState(step_id="step-1", status="completed")
        snapshot = PlanSnapshot.create_named(
            plan_id="plan-1",
            name="Before API call",
            step_states={"step-1": state},
            description="Snapshot before risky operation",
        )

        assert snapshot.name == "Before API call"
        assert snapshot.snapshot_type == "named"
        assert snapshot.auto_created is False
        assert snapshot.description == "Snapshot before risky operation"

    def test_create_auto_snapshot(self) -> None:
        """Test creating an auto snapshot factory method."""
        state = StepState(step_id="step-1", status="completed")
        snapshot = PlanSnapshot.create_auto(
            plan_id="plan-1",
            snapshot_type="last_step",
            step_states={"step-1": state},
        )

        assert snapshot.snapshot_type == "last_step"
        assert snapshot.auto_created is True
        assert snapshot.name.startswith("Auto snapshot")

    def test_get_step_state(self) -> None:
        """Test retrieving step state from snapshot."""
        state = StepState(step_id="step-1", status="completed")
        snapshot = PlanSnapshot(
            plan_id="plan-1",
            name="checkpoint",
            step_states={"step-1": state},
        )

        retrieved = snapshot.get_step_state("step-1")
        assert retrieved is not None
        assert retrieved.status == "completed"

    def test_get_step_state_not_found(self) -> None:
        """Test retrieving non-existent step state."""
        snapshot = PlanSnapshot(
            plan_id="plan-1",
            name="checkpoint",
            step_states={},
        )

        assert snapshot.get_step_state("nonexistent") is None

    def test_has_step_state(self) -> None:
        """Test checking if step state exists."""
        state = StepState(step_id="step-1", status="completed")
        snapshot = PlanSnapshot(
            plan_id="plan-1",
            name="checkpoint",
            step_states={"step-1": state},
        )

        assert snapshot.has_step_state("step-1") is True
        assert snapshot.has_step_state("step-2") is False

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        state = StepState(step_id="step-1", status="completed")
        snapshot = PlanSnapshot(
            plan_id="plan-1",
            name="checkpoint",
            step_states={"step-1": state},
        )

        result = snapshot.to_dict()

        assert result["plan_id"] == "plan-1"
        assert result["name"] == "checkpoint"
        assert "step-1" in result["step_states"]
        assert result["auto_created"] is True
        assert result["snapshot_type"] == "last_step"

    def test_from_execution_plan(self) -> None:
        """Test creating snapshot from ExecutionPlan."""
        from src.domain.model.agent.execution_plan import (
            ExecutionPlan,
            ExecutionStep,
        )

        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
        )

        snapshot = PlanSnapshot.from_execution_plan(
            plan,
            name="Plan snapshot",
        )

        assert snapshot.plan_id == plan.id
        assert snapshot.name == "Plan snapshot"
        assert "step-1" in snapshot.step_states
        assert snapshot.step_states["step-1"].status == "pending"
