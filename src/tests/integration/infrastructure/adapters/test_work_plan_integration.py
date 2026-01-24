"""Integration tests for work plan creation and persistence."""

import pytest

from src.domain.model.agent import (
    PlanStatus,
    PlanStep,
    WorkPlan,
)
from src.infrastructure.adapters.secondary.persistence.sql_work_plan_repository import (
    SQLWorkPlanRepository,
)


class TestWorkPlanIntegration:
    """Integration tests for WorkPlan with database persistence."""

    @pytest.mark.asyncio
    async def test_create_and_save_work_plan(self, test_db):
        """Test creating and saving a work plan to the database."""
        repository = SQLWorkPlanRepository(test_db)

        work_plan = WorkPlan(
            id="plan-123",
            conversation_id="conv-456",
            status=PlanStatus.PLANNING,
            steps=[
                PlanStep(
                    step_number=0,
                    description="Search for memories about project planning",
                    thought_prompt="What keywords should I use to search?",
                    required_tools=["memory_search"],
                    expected_output="List of relevant memories",
                    dependencies=[],
                ),
                PlanStep(
                    step_number=1,
                    description="Analyze the retrieved memories",
                    thought_prompt="What are the key insights?",
                    required_tools=["analyze"],
                    expected_output="Analysis summary",
                    dependencies=[0],
                ),
                PlanStep(
                    step_number=2,
                    description="Generate final response",
                    thought_prompt="How should I structure the answer?",
                    required_tools=["summarize"],
                    expected_output="Final response",
                    dependencies=[1],
                ),
            ],
            current_step_index=0,
            workflow_pattern_id="pattern-789",
        )

        # Save the work plan
        saved_plan = await repository.save(work_plan)

        assert saved_plan.id == "plan-123"
        assert saved_plan.conversation_id == "conv-456"
        assert saved_plan.status == PlanStatus.PLANNING
        assert len(saved_plan.steps) == 3
        assert saved_plan.current_step_index == 0
        assert saved_plan.workflow_pattern_id == "pattern-789"

    @pytest.mark.asyncio
    async def test_save_and_retrieve_work_plan(self, test_db):
        """Test saving and retrieving a work plan."""
        repository = SQLWorkPlanRepository(test_db)

        original_plan = WorkPlan(
            id="plan-456",
            conversation_id="conv-789",
            status=PlanStatus.IN_PROGRESS,
            steps=[
                PlanStep(
                    step_number=0,
                    description="Step 1",
                    thought_prompt="Think 1",
                    required_tools=["tool1"],
                    expected_output="Output 1",
                    dependencies=[],
                ),
            ],
            current_step_index=0,
        )

        # Save
        await repository.save(original_plan)

        # Retrieve by ID
        retrieved_plan = await repository.get_by_id("plan-456")

        assert retrieved_plan is not None
        assert retrieved_plan.id == "plan-456"
        assert retrieved_plan.conversation_id == "conv-789"
        assert retrieved_plan.status == PlanStatus.IN_PROGRESS
        assert len(retrieved_plan.steps) == 1
        assert retrieved_plan.steps[0].description == "Step 1"

    @pytest.mark.asyncio
    async def test_update_existing_work_plan(self, test_db):
        """Test updating an existing work plan."""
        repository = SQLWorkPlanRepository(test_db)

        # Create initial plan with multiple steps so advance_step works
        work_plan = WorkPlan(
            id="plan-789",
            conversation_id="conv-123",
            status=PlanStatus.PLANNING,
            steps=[
                PlanStep(
                    step_number=0,
                    description="Step 1",
                    thought_prompt="Original thought 1",
                    required_tools=["tool1"],
                    expected_output="Output 1",
                    dependencies=[],
                ),
                PlanStep(
                    step_number=1,
                    description="Step 2",
                    thought_prompt="Original thought 2",
                    required_tools=["tool2"],
                    expected_output="Output 2",
                    dependencies=[0],
                ),
            ],
            current_step_index=0,
        )

        await repository.save(work_plan)

        # Update the plan
        work_plan.mark_in_progress()
        work_plan.advance_step()

        updated_plan = await repository.save(work_plan)

        assert updated_plan.status == PlanStatus.IN_PROGRESS
        assert updated_plan.current_step_index == 1
        assert updated_plan.updated_at is not None

    @pytest.mark.asyncio
    async def test_get_all_plans_for_conversation(self, test_db):
        """Test retrieving all work plans for a conversation."""
        repository = SQLWorkPlanRepository(test_db)

        conversation_id = "conv-multi"

        # Create multiple plans for the same conversation
        for i in range(3):
            plan = WorkPlan(
                id=f"plan-{i}",
                conversation_id=conversation_id,
                status=PlanStatus.COMPLETED if i < 2 else PlanStatus.PLANNING,
                steps=[
                    PlanStep(
                        step_number=0,
                        description=f"Step {i}",
                        thought_prompt=f"Think {i}",
                        required_tools=["tool1"],
                        expected_output=f"Output {i}",
                        dependencies=[],
                    ),
                ],
            )
            await repository.save(plan)

        # Retrieve all plans
        plans = await repository.get_by_conversation(conversation_id)

        assert len(plans) == 3
        assert all(p.conversation_id == conversation_id for p in plans)

    @pytest.mark.asyncio
    async def test_get_active_plan_for_conversation(self, test_db):
        """Test retrieving the active (in-progress) plan for a conversation."""
        repository = SQLWorkPlanRepository(test_db)

        conversation_id = "conv-active"

        # Create a completed plan
        completed_plan = WorkPlan(
            id="plan-completed",
            conversation_id=conversation_id,
            status=PlanStatus.COMPLETED,
            steps=[
                PlanStep(
                    step_number=0,
                    description="Completed step",
                    thought_prompt="Think",
                    required_tools=["tool1"],
                    expected_output="Output",
                    dependencies=[],
                ),
            ],
        )
        await repository.save(completed_plan)

        # Create an in-progress plan
        active_plan = WorkPlan(
            id="plan-active",
            conversation_id=conversation_id,
            status=PlanStatus.IN_PROGRESS,
            steps=[
                PlanStep(
                    step_number=0,
                    description="Active step",
                    thought_prompt="Think",
                    required_tools=["tool1"],
                    expected_output="Output",
                    dependencies=[],
                ),
            ],
        )
        await repository.save(active_plan)

        # Retrieve active plan
        retrieved = await repository.get_active_by_conversation(conversation_id)

        assert retrieved is not None
        assert retrieved.id == "plan-active"
        assert retrieved.status == PlanStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_delete_work_plan(self, test_db):
        """Test deleting a work plan."""
        repository = SQLWorkPlanRepository(test_db)

        # Create a plan
        work_plan = WorkPlan(
            id="plan-delete",
            conversation_id="conv-delete",
            status=PlanStatus.PLANNING,
            steps=[
                PlanStep(
                    step_number=0,
                    description="Step",
                    thought_prompt="Think",
                    required_tools=["tool1"],
                    expected_output="Output",
                    dependencies=[],
                ),
            ],
        )
        await repository.save(work_plan)

        # Verify it exists
        assert await repository.get_by_id("plan-delete") is not None

        # Delete it
        deleted = await repository.delete("plan-delete")
        assert deleted is True

        # Verify it's gone
        assert await repository.get_by_id("plan-delete") is None

    @pytest.mark.asyncio
    async def test_work_plan_with_workflow_pattern(self, test_db):
        """Test saving and retrieving a work plan with workflow pattern reference."""
        repository = SQLWorkPlanRepository(test_db)

        work_plan = WorkPlan(
            id="plan-pattern",
            conversation_id="conv-pattern",
            status=PlanStatus.IN_PROGRESS,
            steps=[
                PlanStep(
                    step_number=0,
                    description="Search memories",
                    thought_prompt="Search query?",
                    required_tools=["memory_search"],
                    expected_output="Results",
                    dependencies=[],
                ),
            ],
            current_step_index=0,
            workflow_pattern_id="pattern-successful-query",
        )

        await repository.save(work_plan)

        retrieved = await repository.get_by_id("plan-pattern")

        assert retrieved is not None
        assert retrieved.workflow_pattern_id == "pattern-successful-query"
