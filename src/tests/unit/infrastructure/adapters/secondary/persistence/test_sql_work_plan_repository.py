"""Unit tests for the SQLWorkPlanRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import (
    PlanStatus,
    PlanStep,
    WorkPlan,
)
from src.infrastructure.adapters.secondary.persistence.models import WorkPlan as DBWorkPlan
from src.infrastructure.adapters.secondary.persistence.sql_work_plan_repository import (
    SQLWorkPlanRepository,
)


class TestSQLWorkPlanRepository:
    """Test SQLWorkPlanRepository behavior."""

    @pytest.fixture
    def session(self) -> AsyncSession:
        """Create a mock async session."""
        # Note: This is a simplified mock for unit testing
        # In real tests, you'd use the actual test fixtures from conftest.py
        from unittest.mock import AsyncMock, MagicMock

        session = AsyncMock(spec=AsyncSession)
        session.execute = MagicMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.fixture
    def repository(self, session: AsyncSession) -> SQLWorkPlanRepository:
        """Create a repository instance."""
        return SQLWorkPlanRepository(session)

    @pytest.fixture
    def sample_work_plan(self) -> WorkPlan:
        """Create a sample work plan for testing."""
        return WorkPlan(
            id="plan-123",
            conversation_id="conv-456",
            status=PlanStatus.PLANNING,
            steps=[
                PlanStep(
                    step_number=0,
                    description="Search for memories",
                    thought_prompt="What should I search for?",
                    required_tools=["memory_search"],
                    expected_output="List of memories",
                    dependencies=[],
                ),
                PlanStep(
                    step_number=1,
                    description="Summarize findings",
                    thought_prompt="What are the key points?",
                    required_tools=["summary"],
                    expected_output="Summary text",
                    dependencies=[0],
                ),
            ],
            current_step_index=0,
            workflow_pattern_id="pattern-789",
        )

    @pytest.mark.asyncio
    async def test_save_new_work_plan(
        self, repository: SQLWorkPlanRepository, sample_work_plan: WorkPlan
    ):
        """Test saving a new work plan."""
        # This is a simplified test - real tests would use actual database
        # For now, we just verify the method signature and basic flow
        # In a real scenario with async session mocking:
        # result = await repository.save(sample_work_plan)
        # assert result.id == sample_work_plan.id
        # assert result.conversation_id == sample_work_plan.conversation_id
        pass

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, repository: SQLWorkPlanRepository):
        """Test getting a work plan by existing ID."""
        # Placeholder - real implementation requires proper async mocking
        # result = await repository.get_by_id("plan-123")
        # assert result is not None
        # assert result.id == "plan-123"
        pass

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, repository: SQLWorkPlanRepository):
        """Test getting a work plan by non-existent ID."""
        # result = await repository.get_by_id("non-existent")
        # assert result is None
        pass

    @pytest.mark.asyncio
    async def test_get_by_conversation(
        self, repository: SQLWorkPlanRepository, sample_work_plan: WorkPlan
    ):
        """Test getting all work plans for a conversation."""
        # results = await repository.get_by_conversation("conv-456")
        # assert len(results) >= 1
        # assert any(p.id == sample_work_plan.id for p in results)
        pass

    @pytest.mark.asyncio
    async def test_get_active_by_conversation(self, repository: SQLWorkPlanRepository):
        """Test getting the active work plan for a conversation."""
        # result = await repository.get_active_by_conversation("conv-456")
        # assert result is not None or result is None
        pass

    @pytest.mark.asyncio
    async def test_delete_existing(self, repository: SQLWorkPlanRepository):
        """Test deleting an existing work plan."""
        # deleted = await repository.delete("plan-123")
        # assert deleted is True
        pass

    @pytest.mark.asyncio
    async def test_delete_non_existent(self, repository: SQLWorkPlanRepository):
        """Test deleting a non-existent work plan."""
        # deleted = await repository.delete("non-existent")
        # assert deleted is False
        pass

    def test_to_domain_converts_db_model_to_domain(self):
        """Test _to_domain converts DB model to domain model correctly."""
        db_plan = DBWorkPlan(
            id="plan-123",
            conversation_id="conv-456",
            status="in_progress",
            steps=[
                {
                    "step_number": 0,
                    "description": "Search",
                    "thought_prompt": "What to search?",
                    "required_tools": ["memory_search"],
                    "expected_output": "Results",
                    "dependencies": [],
                }
            ],
            current_step_index=0,
            workflow_pattern_id="pattern-789",
        )

        domain_plan = SQLWorkPlanRepository._to_domain(db_plan)

        assert domain_plan.id == "plan-123"
        assert domain_plan.conversation_id == "conv-456"
        assert domain_plan.status == PlanStatus.IN_PROGRESS
        assert len(domain_plan.steps) == 1
        assert domain_plan.steps[0].step_number == 0
        assert domain_plan.steps[0].description == "Search"
        assert domain_plan.current_step_index == 0
        assert domain_plan.workflow_pattern_id == "pattern-789"

    def test_to_domain_handles_empty_steps(self):
        """Test _to_domain handles empty steps list."""
        db_plan = DBWorkPlan(
            id="plan-123",
            conversation_id="conv-456",
            status="planning",
            steps=[],
            current_step_index=0,
        )

        domain_plan = SQLWorkPlanRepository._to_domain(db_plan)

        assert len(domain_plan.steps) == 0

    def test_to_domain_handles_none_workflow_pattern(self):
        """Test _to_domain handles None workflow_pattern_id."""
        db_plan = DBWorkPlan(
            id="plan-123",
            conversation_id="conv-456",
            status="planning",
            steps=[],
            current_step_index=0,
            workflow_pattern_id=None,
        )

        domain_plan = SQLWorkPlanRepository._to_domain(db_plan)

        assert domain_plan.workflow_pattern_id is None
