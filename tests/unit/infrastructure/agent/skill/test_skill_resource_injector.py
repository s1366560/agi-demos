"""
Unit tests for SkillResourceInjector.

TDD Approach: Tests written first, then implementation.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock
import pytest

from src.infrastructure.agent.skill.skill_resource_injector import SkillResourceInjector
from src.infrastructure.agent.skill.skill_resource_loader import SkillResourceLoader


@pytest.fixture
def temp_project_path(tmp_path: Path) -> Path:
    """Create a temporary project path with skill directories."""
    project_skill = tmp_path / ".memstack" / "skills" / "test-skill"
    project_skill.mkdir(parents=True)

    (project_skill / "SKILL.md").write_text("---\nname: test-skill\n---")

    # Create scripts directory
    scripts_dir = project_skill / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "analyze.py").write_text("print('analyze')")

    # Create references directory
    refs_dir = project_skill / "references"
    refs_dir.mkdir()
    (refs_dir / "guide.md").write_text("# Guide")

    return tmp_path


@pytest.fixture
def mock_sandbox_adapter():
    """Create a mock SandboxPort adapter."""
    adapter = AsyncMock()
    adapter.call_tool.return_value = {
        "content": [{"type": "text", "text": "Success"}],
        "isError": False,
    }
    return adapter


@pytest.fixture
def resource_loader(temp_project_path: Path):
    """Create a SkillResourceLoader with temp path."""
    from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner

    return SkillResourceLoader(temp_project_path)


class TestSkillResourceInjector:
    """Tests for SkillResourceInjector."""

    def test_init(self, resource_loader: SkillResourceLoader):
        """Test SkillResourceInjector initialization."""
        injector = SkillResourceInjector(resource_loader)

        assert injector.loader == resource_loader
        assert injector._injected_cache == {}

    @pytest.mark.asyncio
    async def test_inject_skill_success(
        self, resource_loader: SkillResourceLoader, mock_sandbox_adapter
    ):
        """Test successful resource injection."""
        injector = SkillResourceInjector(resource_loader)

        path_mapping = await injector.inject_skill(
            mock_sandbox_adapter,
            sandbox_id="test-sandbox",
            skill_name="test-skill",
        )

        # Should have injected 2 resources (analyze.py and guide.md)
        assert len(path_mapping) == 2

        # Check that call_tool was called for each resource
        assert mock_sandbox_adapter.call_tool.call_count == 2

    @pytest.mark.asyncio
    async def test_inject_skill_with_content_detection(
        self, resource_loader: SkillResourceLoader, mock_sandbox_adapter
    ):
        """Test injection with content-based resource detection."""
        injector = SkillResourceInjector(resource_loader)

        skill_content = "Run: python3 scripts/analyze.py"
        path_mapping = await injector.inject_skill(
            mock_sandbox_adapter,
            sandbox_id="test-sandbox",
            skill_name="test-skill",
            skill_content=skill_content,
        )

        # Should still inject all found resources
        assert len(path_mapping) >= 1

    @pytest.mark.asyncio
    async def test_inject_skill_empty_skill(
        self, resource_loader: SkillResourceLoader, mock_sandbox_adapter
    ):
        """Test injection when skill has no resources."""
        injector = SkillResourceInjector(resource_loader)

        path_mapping = await injector.inject_skill(
            mock_sandbox_adapter,
            sandbox_id="test-sandbox",
            skill_name="non-existent",
        )

        assert len(path_mapping) == 0
        assert mock_sandbox_adapter.call_tool.call_count == 0

    @pytest.mark.asyncio
    async def test_inject_skill_handles_write_error(
        self, resource_loader: SkillResourceLoader
    ):
        """Test injection handles write errors gracefully."""
        # Mock adapter that returns error
        mock_adapter = AsyncMock()
        mock_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": "Error"}],
            "isError": True,
        }

        injector = SkillResourceInjector(resource_loader)

        path_mapping = await injector.inject_skill(
            mock_adapter,
            sandbox_id="test-sandbox",
            skill_name="test-skill",
        )

        # Should return empty mapping on error
        assert len(path_mapping) == 0

    @pytest.mark.asyncio
    async def test_setup_skill_environment(
        self, resource_loader: SkillResourceLoader, mock_sandbox_adapter
    ):
        """Test setting up skill environment variables."""
        injector = SkillResourceInjector(resource_loader)

        result = await injector.setup_skill_environment(
            mock_sandbox_adapter,
            sandbox_id="test-sandbox",
            skill_name="test-skill",
        )

        # Should succeed
        assert result is True

        # Check that env.sh was written
        call_args = mock_sandbox_adapter.call_tool.call_args
        assert call_args is not None
        assert call_args[1]["sandbox_id"] == "test-sandbox"
        assert call_args[1]["tool_name"] == "write"

        # Check content contains environment setup
        content = call_args[1]["arguments"]["content"]
        assert "SKILL_ROOT" in content
        assert "test-skill" in content
