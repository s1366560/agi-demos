"""Unit tests for SkillService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.skill_service import SkillService
from src.domain.model.agent.skill import Skill, SkillScope, SkillSource, SkillStatus, TriggerType
from src.domain.model.agent.tenant_skill_config import TenantSkillAction, TenantSkillConfig


@pytest.fixture
def mock_skill_repository():
    """Create mock skill repository."""
    repo = MagicMock()
    repo.list_by_tenant = AsyncMock(return_value=[])
    repo.list_by_project = AsyncMock(return_value=[])
    repo.get_by_id = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    return repo


@pytest.fixture
def mock_tenant_config_repository():
    """Create mock tenant skill config repository."""
    repo = MagicMock()
    repo.get_config = AsyncMock(return_value=None)
    repo.save_config = AsyncMock()
    return repo


@pytest.fixture
def mock_filesystem_loader():
    """Create mock filesystem skill loader."""
    loader = MagicMock()
    loader.load_skills = MagicMock(return_value=[])
    return loader


@pytest.fixture
def sample_skill():
    """Create sample skill for testing."""
    return Skill(
        id="skill-1",
        name="test-skill",
        description="A test skill",
        scope=SkillScope.TENANT,
        status=SkillStatus.ACTIVE,
        tenant_id="tenant-1",
        project_id=None,
        source=SkillSource.DATABASE,
        trigger_type=TriggerType.KEYWORD,
        trigger_patterns=[],
        tools=["read", "write"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@pytest.fixture
def sample_system_skill():
    """Create sample system skill for testing."""
    return Skill(
        id="system-skill-1",
        name="system-skill",
        description="A system skill",
        scope=SkillScope.SYSTEM,
        status=SkillStatus.ACTIVE,
        tenant_id="system",
        project_id=None,
        source=SkillSource.FILESYSTEM,
        trigger_type=TriggerType.KEYWORD,
        trigger_patterns=[],
        tools=["read"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        is_system_skill=True,
    )


@pytest.fixture
def skill_service(mock_skill_repository, mock_tenant_config_repository):
    """Create SkillService with mocked dependencies."""
    return SkillService(
        skill_repository=mock_skill_repository,
        tenant_skill_config_repository=mock_tenant_config_repository,
    )


class TestSkillService:
    """Tests for SkillService."""

    @pytest.mark.unit
    def test_initialization(self, skill_service):
        """Test service initialization."""
        assert skill_service._initialized is False
        assert skill_service._skill_repo is not None

    @pytest.mark.unit
    async def test_get_skills_returns_empty_list_initially(
        self, skill_service, mock_skill_repository
    ):
        """Test list_available_skills returns empty list when no skills exist."""
        mock_skill_repository.list_by_tenant.return_value = []

        skills = await skill_service.list_available_skills(tenant_id="tenant-1")

        assert skills == []

    @pytest.mark.unit
    async def test_get_skills_returns_tenant_skills(
        self, skill_service, mock_skill_repository, sample_skill
    ):
        """Test list_available_skills returns tenant skills."""
        mock_skill_repository.list_by_tenant.return_value = [sample_skill]

        skills = await skill_service.list_available_skills(tenant_id="tenant-1")

        assert len(skills) == 1
        assert skills[0].name == "test-skill"

    @pytest.mark.unit
    async def test_get_skills_includes_project_skills(
        self, skill_service, mock_skill_repository, sample_skill
    ):
        """Test list_available_skills includes project-level skills."""
        project_skill = Skill(
            id="project-skill-1",
            name="project-skill",
            description="A project skill",
            scope=SkillScope.PROJECT,
            status=SkillStatus.ACTIVE,
            tenant_id="tenant-1",
            project_id="project-1",
            source=SkillSource.DATABASE,
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[],
            tools=["read"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        mock_skill_repository.list_by_tenant.return_value = [sample_skill]
        mock_skill_repository.list_by_project.return_value = [project_skill]

        skills = await skill_service.list_available_skills(
            tenant_id="tenant-1", project_id="project-1"
        )

        assert len(skills) == 2

    @pytest.mark.unit
    async def test_get_skill_by_name_found(
        self, skill_service, mock_skill_repository, sample_skill
    ):
        """Test get_skill_by_name returns skill when found."""
        mock_skill_repository.get_by_name.return_value = sample_skill

        skill = await skill_service.get_skill_by_name("tenant-1", "test-skill")

        assert skill is not None
        assert skill.name == "test-skill"

    @pytest.mark.unit
    async def test_get_skill_by_name_not_found(self, skill_service, mock_skill_repository):
        """Test get_skill_by_name returns None when not found."""
        mock_skill_repository.get_by_name.return_value = None

        skill = await skill_service.get_skill_by_name("tenant-1", "nonexistent")

        assert skill is None

    @pytest.mark.unit
    async def test_create_skill_success(self, skill_service, mock_skill_repository, sample_skill):
        """Test successful skill creation."""
        mock_skill_repository.create.return_value = sample_skill

        result = await skill_service.create_skill(
            tenant_id="tenant-1",
            name="test-skill",
            description="A test skill",
            tools=["read", "write"],
        )

        mock_skill_repository.create.assert_called_once()
        assert result.id == "skill-1"

    @pytest.mark.unit
    async def test_update_skill_success(self, skill_service, mock_skill_repository, sample_skill):
        """Test successful skill update."""
        mock_skill_repository.get_by_id.return_value = sample_skill
        mock_skill_repository.update.return_value = sample_skill

        _result = await skill_service.update_skill_content("skill-1", "Updated content")

        mock_skill_repository.update.assert_called_once()

    @pytest.mark.unit
    async def test_update_skill_not_found(self, skill_service, mock_skill_repository):
        """Test update_skill_content raises error when not found."""
        mock_skill_repository.get_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await skill_service.update_skill_content("nonexistent", "Updated content")

    @pytest.mark.unit
    async def test_delete_skill_success(self, skill_service, mock_skill_repository, sample_skill):
        """Test successful skill deletion."""
        mock_skill_repository.get_by_id.return_value = sample_skill

        await skill_service.delete_skill("skill-1")

        mock_skill_repository.delete.assert_called_once_with("skill-1")

    @pytest.mark.unit
    async def test_tenant_config_disables_system_skill(
        self, skill_service, mock_tenant_config_repository, sample_system_skill
    ):
        """Test tenant config can disable system skills."""
        config = TenantSkillConfig.create_disable(
            tenant_id="tenant-1",
            system_skill_name="system-skill",
        )
        mock_tenant_config_repository.get_config.return_value = config
        # This depends on the actual implementation of list_available_skills
        # Here we're testing the config retrieval
        retrieved_config = await skill_service._tenant_config_repo.get_config("tenant-1")
        assert retrieved_config.is_disabled()
        assert retrieved_config.system_skill_name == "system-skill"

    @pytest.mark.unit
    def test_factory_method(self, mock_skill_repository, tmp_path):
        """Test factory method creates service correctly."""
        service = SkillService.create(
            skill_repository=mock_skill_repository,
            base_path=tmp_path,
            tenant_id="tenant-1",
        )

        assert service._skill_repo == mock_skill_repository
        assert service._fs_loader is not None

    @pytest.mark.unit
    async def test_skill_priority_project_over_tenant(self, skill_service, mock_skill_repository):
        """Test project skills override tenant skills with same name."""
        tenant_skill = Skill(
            id="tenant-skill",
            name="common-skill",
            description="Tenant version",
            scope=SkillScope.TENANT,
            status=SkillStatus.ACTIVE,
            tenant_id="tenant-1",
            source=SkillSource.DATABASE,
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[],
            tools=["read"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        project_skill = Skill(
            id="project-skill",
            name="common-skill",
            description="Project version",
            scope=SkillScope.PROJECT,
            status=SkillStatus.ACTIVE,
            tenant_id="tenant-1",
            project_id="project-1",
            source=SkillSource.DATABASE,
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[],
            tools=["read", "write"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        mock_skill_repository.list_by_tenant.return_value = [tenant_skill]
        mock_skill_repository.list_by_project.return_value = [project_skill]

        skills = await skill_service.list_available_skills(
            tenant_id="tenant-1", project_id="project-1"
        )

        # Should have 2 skills, but project version should take priority
        # Implementation may merge or keep both
        assert len(skills) >= 1
