"""
Tests for V2 SqlSkillRepository using BaseRepository.

TDD Approach: RED -> GREEN -> REFACTOR

These tests verify that the migrated repository maintains 100% compatibility
with the original implementation while leveraging the BaseRepository.

Key features tested:
- CRUD operations
- Three-level scoping (system, tenant, project)
- Complex query filters
- Find matching skills
- Increment usage statistics
- Count operations
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus, TriggerPattern, TriggerType
from src.domain.model.agent.skill_source import SkillSource
from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
    SqlSkillRepository,
)


@pytest.fixture
async def v2_skill_repo(db_session: AsyncSession) -> SqlSkillRepository:
    """Create a V2 skill repository for testing."""
    return SqlSkillRepository(db_session)


def create_test_skill(
    skill_id: str,
    tenant_id: str = "tenant-1",
    project_id: str | None = None,
    name: str = "test-skill",
    status: SkillStatus = SkillStatus.ACTIVE,
    scope: SkillScope = SkillScope.TENANT,
) -> Skill:
    """Helper to create a test skill."""
    return Skill(
        id=skill_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name=name,
        description="Test description",
        trigger_type=TriggerType.KEYWORD,
        trigger_patterns=[
            TriggerPattern(
                pattern="test",
                weight=0.8,
            ),
        ],
        tools=["search", "analyze"],
        prompt_template="Test prompt template",
        status=status,
        success_count=10,
        failure_count=2,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        metadata={"key": "value"},
        source=SkillSource.DATABASE,
        scope=scope,
        is_system_skill=False,
        full_content=None,
    )


class TestSqlSkillRepositoryCreate:
    """Tests for creating new skills."""

    @pytest.mark.asyncio
    async def test_create_new_skill(self, v2_skill_repo: SqlSkillRepository):
        """Test creating a new skill."""
        skill = create_test_skill("skill-test-1")

        result = await v2_skill_repo.create(skill)

        assert result.id == "skill-test-1"

        # Verify was saved
        retrieved = await v2_skill_repo.get_by_id("skill-test-1")
        assert retrieved is not None
        assert retrieved.name == "test-skill"


class TestSqlSkillRepositoryFind:
    """Tests for finding skills."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_skill_repo: SqlSkillRepository):
        """Test finding an existing skill by ID."""
        skill = create_test_skill("skill-find-1")
        await v2_skill_repo.create(skill)

        retrieved = await v2_skill_repo.get_by_id("skill-find-1")
        assert retrieved is not None
        assert retrieved.id == "skill-find-1"
        assert retrieved.name == "test-skill"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, v2_skill_repo: SqlSkillRepository):
        """Test finding a non-existent skill returns None."""
        retrieved = await v2_skill_repo.get_by_id("non-existent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_by_name_existing(self, v2_skill_repo: SqlSkillRepository):
        """Test getting a skill by name within a tenant."""
        skill = create_test_skill("skill-name-1", name="unique-name")
        await v2_skill_repo.create(skill)

        retrieved = await v2_skill_repo.get_by_name("tenant-1", "unique-name")
        assert retrieved is not None
        assert retrieved.id == "skill-name-1"
        assert retrieved.name == "unique-name"

    @pytest.mark.asyncio
    async def test_get_by_name_with_scope(self, v2_skill_repo: SqlSkillRepository):
        """Test getting a skill by name with scope filter."""
        skill = create_test_skill("skill-name-scope", name="project-skill", scope=SkillScope.PROJECT)
        await v2_skill_repo.create(skill)

        retrieved = await v2_skill_repo.get_by_name(
            "tenant-1", "project-skill", scope=SkillScope.PROJECT
        )
        assert retrieved is not None
        assert retrieved.scope == SkillScope.PROJECT

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(self, v2_skill_repo: SqlSkillRepository):
        """Test getting a non-existent skill by name returns None."""
        retrieved = await v2_skill_repo.get_by_name("tenant-1", "nonexistent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_exists_true(self, v2_skill_repo: SqlSkillRepository):
        """Test exists returns True for existing skill."""
        skill = create_test_skill("skill-exists-1")
        await v2_skill_repo.create(skill)

        assert await v2_skill_repo.exists("skill-exists-1") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, v2_skill_repo: SqlSkillRepository):
        """Test exists returns False for non-existent skill."""
        assert await v2_skill_repo.exists("non-existent") is False


class TestSqlSkillRepositoryUpdate:
    """Tests for updating skills."""

    @pytest.mark.asyncio
    async def test_update_existing_skill(self, v2_skill_repo: SqlSkillRepository):
        """Test updating an existing skill."""
        skill = create_test_skill("skill-update-1")
        await v2_skill_repo.create(skill)

        # Update the skill
        updated_skill = Skill(
            id="skill-update-1",
            tenant_id="tenant-1",
            project_id=None,
            name="updated-name",
            description="Updated description",
            trigger_type=TriggerType.SEMANTIC,
            trigger_patterns=[],
            tools=["new_tool"],
            prompt_template="New prompt",
            status=SkillStatus.DISABLED,
            success_count=15,
            failure_count=3,
            created_at=skill.created_at,
            updated_at=datetime.now(UTC),
            metadata={"updated": True},
            source=SkillSource.DATABASE,
            scope=SkillScope.TENANT,
            is_system_skill=False,
            full_content=None,
        )

        result = await v2_skill_repo.update(updated_skill)

        assert result.name == "updated-name"

        # Verify updates
        retrieved = await v2_skill_repo.get_by_id("skill-update-1")
        assert retrieved.name == "updated-name"
        assert retrieved.description == "Updated description"
        assert retrieved.status == SkillStatus.DISABLED

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_error(self, v2_skill_repo: SqlSkillRepository):
        """Test updating a non-existent skill raises ValueError."""
        skill = create_test_skill("non-existent")

        with pytest.raises(ValueError, match="Skill not found"):
            await v2_skill_repo.update(skill)


class TestSqlSkillRepositoryList:
    """Tests for listing skills."""

    @pytest.mark.asyncio
    async def test_list_by_tenant(self, v2_skill_repo: SqlSkillRepository):
        """Test listing skills by tenant."""
        # Create skills for different tenants
        for i in range(3):
            skill = create_test_skill(f"skill-tenant-1-{i}", tenant_id="tenant-1")
            await v2_skill_repo.create(skill)

        # Add skill for different tenant
        other_skill = create_test_skill("skill-tenant-2", tenant_id="tenant-2")
        await v2_skill_repo.create(other_skill)

        # List tenant-1 skills
        skills = await v2_skill_repo.list_by_tenant("tenant-1")
        assert len(skills) == 3
        assert all(s.tenant_id == "tenant-1" for s in skills)

    @pytest.mark.asyncio
    async def test_list_by_tenant_with_status_filter(self, v2_skill_repo: SqlSkillRepository):
        """Test listing skills by tenant with status filter."""
        # Create skills with different statuses
        active_skill = create_test_skill("skill-active", status=SkillStatus.ACTIVE)
        await v2_skill_repo.create(active_skill)

        disabled_skill = create_test_skill("skill-disabled", status=SkillStatus.DISABLED)
        await v2_skill_repo.create(disabled_skill)

        # List only active skills
        active_skills = await v2_skill_repo.list_by_tenant("tenant-1", status=SkillStatus.ACTIVE)
        assert len(active_skills) == 1
        assert active_skills[0].status == SkillStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_list_by_tenant_with_scope_filter(self, v2_skill_repo: SqlSkillRepository):
        """Test listing skills by tenant with scope filter."""
        # Create skills with different scopes
        tenant_skill = create_test_skill("skill-tenant-scope", scope=SkillScope.TENANT)
        await v2_skill_repo.create(tenant_skill)

        project_skill = create_test_skill("skill-project-scope", scope=SkillScope.PROJECT)
        await v2_skill_repo.create(project_skill)

        # List only tenant-scoped skills
        tenant_skills = await v2_skill_repo.list_by_tenant("tenant-1", scope=SkillScope.TENANT)
        assert len(tenant_skills) == 1
        assert tenant_skills[0].scope == SkillScope.TENANT

    @pytest.mark.asyncio
    async def test_list_by_tenant_with_pagination(self, v2_skill_repo: SqlSkillRepository):
        """Test listing skills by tenant with pagination."""
        # Create 5 skills
        for i in range(5):
            skill = create_test_skill(f"skill-page-{i}")
            await v2_skill_repo.create(skill)

        # Get first page
        page1 = await v2_skill_repo.list_by_tenant("tenant-1", limit=2, offset=0)
        assert len(page1) == 2

        # Get second page
        page2 = await v2_skill_repo.list_by_tenant("tenant-1", limit=2, offset=2)
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_list_by_project(self, v2_skill_repo: SqlSkillRepository):
        """Test listing skills by project."""
        # Create skills for different projects
        skill1 = create_test_skill("skill-proj-A", project_id="proj-A")
        await v2_skill_repo.create(skill1)

        skill2 = create_test_skill("skill-proj-B", project_id="proj-B")
        await v2_skill_repo.create(skill2)

        # List proj-A skills
        skills = await v2_skill_repo.list_by_project("proj-A")
        assert len(skills) == 1
        assert skills[0].project_id == "proj-A"

    @pytest.mark.asyncio
    async def test_list_by_project_with_filters(self, v2_skill_repo: SqlSkillRepository):
        """Test listing skills by project with filters."""
        # Create skills with different statuses
        active_skill = create_test_skill(
            "skill-proj-active",
            project_id="proj-filter",
            status=SkillStatus.ACTIVE,
        )
        await v2_skill_repo.create(active_skill)

        inactive_skill = create_test_skill(
            "skill-proj-inactive",
            project_id="proj-filter",
            status=SkillStatus.DISABLED,
        )
        await v2_skill_repo.create(inactive_skill)

        # List only active skills
        active_skills = await v2_skill_repo.list_by_project(
            "proj-filter", status=SkillStatus.ACTIVE
        )
        assert len(active_skills) == 1
        assert active_skills[0].status == SkillStatus.ACTIVE


class TestSqlSkillRepositoryDelete:
    """Tests for deleting skills."""

    @pytest.mark.asyncio
    async def test_delete_existing_skill(self, v2_skill_repo: SqlSkillRepository):
        """Test deleting an existing skill."""
        skill = create_test_skill("skill-delete-1")
        await v2_skill_repo.create(skill)

        # Delete
        await v2_skill_repo.delete("skill-delete-1")

        # Verify deleted
        retrieved = await v2_skill_repo.get_by_id("skill-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises_error(self, v2_skill_repo: SqlSkillRepository):
        """Test deleting a non-existent skill raises ValueError."""
        with pytest.raises(ValueError, match="Skill not found"):
            await v2_skill_repo.delete("non-existent")


class TestSqlSkillRepositoryFindMatching:
    """Tests for finding matching skills."""

    @pytest.mark.asyncio
    async def test_find_matching_skills(self, v2_skill_repo: SqlSkillRepository):
        """Test finding skills that match a query."""
        # Create skills with different patterns
        search_skill = create_test_skill("skill-search", name="search-skill")
        search_skill.trigger_patterns = [
            TriggerPattern(pattern="search", weight=0.8)
        ]
        await v2_skill_repo.create(search_skill)

        analyze_skill = create_test_skill("skill-analyze", name="analyze-skill")
        analyze_skill.trigger_patterns = [
            TriggerPattern(pattern="analyze", weight=0.8)
        ]
        await v2_skill_repo.create(analyze_skill)

        # Find skills matching "search"
        matching = await v2_skill_repo.find_matching_skills("tenant-1", "search")
        assert len(matching) >= 1
        assert any(s.name == "search-skill" for s in matching)


class TestSqlSkillRepositoryIncrementUsage:
    """Tests for incrementing usage statistics."""

    @pytest.mark.asyncio
    async def test_increment_usage_success(self, v2_skill_repo: SqlSkillRepository):
        """Test incrementing usage after successful execution."""
        skill = create_test_skill("skill-inc-success")
        await v2_skill_repo.create(skill)

        # Increment success
        result = await v2_skill_repo.increment_usage("skill-inc-success", success=True)

        assert result.success_count == 11
        assert result.failure_count == 2

        # Verify in DB
        retrieved = await v2_skill_repo.get_by_id("skill-inc-success")
        assert retrieved.success_count == 11

    @pytest.mark.asyncio
    async def test_increment_usage_failure(self, v2_skill_repo: SqlSkillRepository):
        """Test incrementing usage after failed execution."""
        skill = create_test_skill("skill-inc-failure")
        await v2_skill_repo.create(skill)

        # Increment failure
        result = await v2_skill_repo.increment_usage("skill-inc-failure", success=False)

        assert result.success_count == 10
        assert result.failure_count == 3

        # Verify in DB
        retrieved = await v2_skill_repo.get_by_id("skill-inc-failure")
        assert retrieved.failure_count == 3

    @pytest.mark.asyncio
    async def test_increment_nonexistent_raises_error(self, v2_skill_repo: SqlSkillRepository):
        """Test incrementing a non-existent skill raises ValueError."""
        with pytest.raises(ValueError, match="Skill not found"):
            await v2_skill_repo.increment_usage("non-existent", success=True)


class TestSqlSkillRepositoryCount:
    """Tests for counting skills."""

    @pytest.mark.asyncio
    async def test_count_by_tenant(self, v2_skill_repo: SqlSkillRepository):
        """Test counting skills by tenant."""
        # Create skills
        for i in range(3):
            skill = create_test_skill(f"skill-count-{i}")
            await v2_skill_repo.create(skill)

        count = await v2_skill_repo.count_by_tenant("tenant-1")
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_by_tenant_with_status_filter(self, v2_skill_repo: SqlSkillRepository):
        """Test counting skills by tenant with status filter."""
        # Create skills with different statuses
        active_skill = create_test_skill("skill-count-active", status=SkillStatus.ACTIVE)
        await v2_skill_repo.create(active_skill)

        disabled_skill = create_test_skill("skill-count-disabled", status=SkillStatus.DISABLED)
        await v2_skill_repo.create(disabled_skill)

        # Count only active
        active_count = await v2_skill_repo.count_by_tenant("tenant-1", status=SkillStatus.ACTIVE)
        assert active_count == 1

    @pytest.mark.asyncio
    async def test_count_by_tenant_with_scope_filter(self, v2_skill_repo: SqlSkillRepository):
        """Test counting skills by tenant with scope filter."""
        # Create skills with different scopes
        tenant_skill = create_test_skill("skill-count-tenant", scope=SkillScope.TENANT)
        await v2_skill_repo.create(tenant_skill)

        project_skill = create_test_skill("skill-count-project", scope=SkillScope.PROJECT)
        await v2_skill_repo.create(project_skill)

        # Count only tenant-scoped
        tenant_count = await v2_skill_repo.count_by_tenant("tenant-1", scope=SkillScope.TENANT)
        assert tenant_count == 1


class TestSqlSkillRepositoryToDomain:
    """Tests for _to_domain conversion."""

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(self, v2_skill_repo: SqlSkillRepository):
        """Test that _to_domain correctly converts all DB fields."""
        skill = create_test_skill("skill-domain-1")
        await v2_skill_repo.create(skill)

        retrieved = await v2_skill_repo.get_by_id("skill-domain-1")
        assert retrieved.id == "skill-domain-1"
        assert retrieved.tenant_id == "tenant-1"
        assert retrieved.name == "test-skill"
        assert retrieved.description == "Test description"
        assert retrieved.trigger_type == TriggerType.KEYWORD
        assert retrieved.status == SkillStatus.ACTIVE
        assert retrieved.success_count == 10
        assert retrieved.failure_count == 2
        assert retrieved.scope == SkillScope.TENANT
        assert retrieved.is_system_skill is False

    @pytest.mark.asyncio
    async def test_to_domain_with_none_db_model(self, v2_skill_repo: SqlSkillRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_skill_repo._to_domain(None)
        assert result is None


class TestSqlSkillRepositoryTransaction:
    """Tests for transaction support."""

    @pytest.mark.asyncio
    async def test_transaction_context_manager(self, v2_skill_repo: SqlSkillRepository):
        """Test using transaction context manager."""
        async with v2_skill_repo.transaction():
            skill1 = create_test_skill("skill-tx-1")
            await v2_skill_repo.create(skill1)

            skill2 = create_test_skill("skill-tx-2")
            await v2_skill_repo.create(skill2)

        # Verify both were saved
        s1 = await v2_skill_repo.get_by_id("skill-tx-1")
        s2 = await v2_skill_repo.get_by_id("skill-tx-2")
        assert s1 is not None
        assert s2 is not None

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_error(self, v2_skill_repo: SqlSkillRepository):
        """Test that transaction rolls back on error."""
        try:
            async with v2_skill_repo.transaction():
                skill1 = create_test_skill("skill-tx-rollback-1")
                await v2_skill_repo.create(skill1)

                # Raise error to trigger rollback
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify rollback occurred
        s1 = await v2_skill_repo.get_by_id("skill-tx-rollback-1")
        assert s1 is None


class TestSqlSkillRepositoryCountAll:
    """Tests for count method from BaseRepository."""

    @pytest.mark.asyncio
    async def test_count_all(self, v2_skill_repo: SqlSkillRepository):
        """Test counting all skills."""
        # Initially empty
        count = await v2_skill_repo.count()
        assert count == 0

        # Add skills
        for i in range(3):
            skill = create_test_skill(f"skill-count-all-{i}")
            await v2_skill_repo.create(skill)

        count = await v2_skill_repo.count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_with_filters(self, v2_skill_repo: SqlSkillRepository):
        """Test counting with filters."""
        # Create skills for different tenants
        for i in range(2):
            skill = create_test_skill(f"skill-filter-1-{i}", tenant_id="tenant-1")
            await v2_skill_repo.create(skill)

        for i in range(3):
            skill = create_test_skill(f"skill-filter-2-{i}", tenant_id="tenant-2")
            await v2_skill_repo.create(skill)

        # Count by tenant
        count_tenant1 = await v2_skill_repo.count(tenant_id="tenant-1")
        assert count_tenant1 == 2

        count_tenant2 = await v2_skill_repo.count(tenant_id="tenant-2")
        assert count_tenant2 == 3
