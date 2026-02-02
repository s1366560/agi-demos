"""
Tests for V2 SqlPlanSnapshotRepository using BaseRepository.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.plan_snapshot import PlanSnapshot, StepState
from src.infrastructure.adapters.secondary.persistence.v2_sql_plan_snapshot_repository import (
    V2SqlPlanSnapshotRepository,
)


@pytest.fixture
async def v2_plan_snapshot_repo(v2_db_session: AsyncSession) -> V2SqlPlanSnapshotRepository:
    """Create a V2 plan snapshot repository for testing."""
    return V2SqlPlanSnapshotRepository(v2_db_session)


def make_step_state(step_id: str, status: str = "pending") -> StepState:
    """Factory for creating StepState objects."""
    return StepState(
        step_id=step_id,
        status=status,
        result=None,
        error=None,
        started_at=None,
        completed_at=None,
    )


def make_snapshot(
    snapshot_id: str,
    plan_id: str,
    name: str = "Test Snapshot",
) -> PlanSnapshot:
    """Factory for creating PlanSnapshot objects."""
    return PlanSnapshot(
        id=snapshot_id,
        plan_id=plan_id,
        name=name,
        step_states={
            "step1": make_step_state("step1", "pending"),
            "step2": make_step_state("step2", "pending"),
        },
        description=f"Description for {name}",
        auto_created=False,
        snapshot_type="manual",
        created_at=datetime.now(timezone.utc),
    )


class TestV2SqlPlanSnapshotRepositoryCreate:
    """Tests for creating snapshots."""

    @pytest.mark.asyncio
    async def test_save_new_snapshot(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test saving a new plan snapshot."""
        snapshot = make_snapshot("snapshot-test-1", "plan-1", "Test Snapshot")

        result = await v2_plan_snapshot_repo.save(snapshot)

        assert result.id == "snapshot-test-1"
        assert result.name == "Test Snapshot"

    @pytest.mark.asyncio
    async def test_save_auto_created_snapshot(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test saving an auto-created snapshot."""
        snapshot = make_snapshot("snapshot-auto-1", "plan-1", "Auto Snapshot")
        snapshot.auto_created = True
        snapshot.snapshot_type = "auto"

        result = await v2_plan_snapshot_repo.save(snapshot)

        assert result.auto_created is True
        assert result.snapshot_type == "auto"


class TestV2SqlPlanSnapshotRepositoryFind:
    """Tests for finding snapshots."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test finding a snapshot by ID."""
        snapshot = make_snapshot("snapshot-find-1", "plan-1", "Find me")
        await v2_plan_snapshot_repo.save(snapshot)

        result = await v2_plan_snapshot_repo.find_by_id("snapshot-find-1")
        assert result is not None
        assert result.name == "Find me"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test finding a non-existent snapshot returns None."""
        result = await v2_plan_snapshot_repo.find_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_execution(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test finding snapshots by execution ID."""
        for i in range(3):
            snapshot = make_snapshot(f"snapshot-exec-{i}", "exec-1", f"Snapshot {i}")
            await v2_plan_snapshot_repo.save(snapshot)

        results = await v2_plan_snapshot_repo.find_by_execution("exec-1")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_find_latest_by_execution(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test finding latest snapshot by execution ID."""
        snapshot1 = make_snapshot("snapshot-latest-1", "exec-latest-1", "First")
        await v2_plan_snapshot_repo.save(snapshot1)

        snapshot2 = make_snapshot("snapshot-latest-2", "exec-latest-1", "Latest")
        await v2_plan_snapshot_repo.save(snapshot2)

        result = await v2_plan_snapshot_repo.find_latest_by_execution("exec-latest-1")
        assert result is not None
        assert result.id == "snapshot-latest-2"

    @pytest.mark.asyncio
    async def test_find_latest_by_execution_empty(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test finding latest snapshot when none exist returns None."""
        result = await v2_plan_snapshot_repo.find_latest_by_execution("non-existent")
        assert result is None


class TestV2SqlPlanSnapshotRepositoryDelete:
    """Tests for deleting snapshots."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test deleting an existing snapshot."""
        snapshot = make_snapshot("snapshot-delete-1", "plan-1")
        await v2_plan_snapshot_repo.save(snapshot)

        result = await v2_plan_snapshot_repo.delete("snapshot-delete-1")
        assert result is True

        retrieved = await v2_plan_snapshot_repo.find_by_id("snapshot-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test deleting a non-existent snapshot returns False."""
        result = await v2_plan_snapshot_repo.delete("non-existent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_by_execution(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test deleting all snapshots for an execution."""
        for i in range(3):
            snapshot = make_snapshot(f"snapshot-del-exec-{i}", "exec-del-1")
            await v2_plan_snapshot_repo.save(snapshot)

        count = await v2_plan_snapshot_repo.delete_by_execution("exec-del-1")
        assert count == 3

        results = await v2_plan_snapshot_repo.find_by_execution("exec-del-1")
        assert len(results) == 0


class TestV2SqlPlanSnapshotRepositoryStepStates:
    """Tests for step state handling."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve_step_states(self, v2_plan_snapshot_repo: V2SqlPlanSnapshotRepository):
        """Test that step states are properly serialized and deserialized."""
        step_states = {
            "step1": StepState(
                step_id="step1",
                status="completed",
                result="Step 1 result",
                error=None,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            ),
            "step2": StepState(
                step_id="step2",
                status="failed",
                result=None,
                error="Step 2 failed",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            ),
        }

        snapshot = PlanSnapshot(
            id="snapshot-states-1",
            plan_id="plan-1",
            name="States Test",
            step_states=step_states,
            description="Test step states",
            auto_created=False,
            snapshot_type="manual",
            created_at=datetime.now(timezone.utc),
        )

        await v2_plan_snapshot_repo.save(snapshot)

        result = await v2_plan_snapshot_repo.find_by_id("snapshot-states-1")
        assert result is not None
        assert len(result.step_states) == 2
        assert result.step_states["step1"].status == "completed"
        assert result.step_states["step1"].result == "Step 1 result"
        assert result.step_states["step2"].status == "failed"
        assert result.step_states["step2"].error == "Step 2 failed"
