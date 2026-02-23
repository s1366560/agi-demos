"""
Unit tests for SkillResourceLoader.

TDD Approach: Tests written first, then implementation.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.infrastructure.agent.skill.skill_resource_loader import SkillResourceLoader


@pytest.fixture
def temp_project_path(tmp_path: Path) -> Path:
    """Create a temporary project path with skill directories."""
    # Create project-level skill
    project_skill = tmp_path / ".memstack" / "skills" / "test-skill"
    project_skill.mkdir(parents=True)

    # Create SKILL.md
    (project_skill / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test skill\n---\n"
        "# Test Skill\n\nRun: python3 scripts/analyze.py"
    )

    # Create scripts directory with a file
    scripts_dir = project_skill / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "analyze.py").write_text("print('analyze')")

    # Create references directory
    refs_dir = project_skill / "references"
    refs_dir.mkdir()
    (refs_dir / "guide.md").write_text("# Guide")

    # Create assets directory
    assets_dir = project_skill / "assets"
    assets_dir.mkdir()
    (assets_dir / "template.json").write_text("{}")

    return tmp_path


@pytest.fixture
def mock_scanner():
    """Create a mock FileSystemSkillScanner."""
    scanner = Mock()

    # Setup find_skill to return a mock SkillFileInfo
    file_info = Mock()
    file_info.skill_dir = Path("/project/.memstack/skills/test-skill")
    file_info.exists.return_value = True

    scanner.find_skill.return_value = file_info
    return scanner


class TestSkillResourceLoader:
    """Tests for SkillResourceLoader."""

    def test_init(self, temp_project_path: Path):
        """Test SkillResourceLoader initialization."""
        from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner

        loader = SkillResourceLoader(temp_project_path)

        assert loader.project_path == temp_project_path
        assert loader.scanner is not None
        assert isinstance(loader.scanner, FileSystemSkillScanner)

    def test_init_with_custom_scanner(self, temp_project_path: Path, mock_scanner):
        """Test initialization with custom scanner."""
        loader = SkillResourceLoader(temp_project_path, scanner=mock_scanner)

        assert loader.scanner == mock_scanner

    @pytest.mark.asyncio
    async def test_get_skill_resources_returns_all_files(
        self, temp_project_path: Path, mock_scanner
    ):
        """Test get_skill_resources returns all resource files."""
        # Setup mock to return actual temp path
        file_info = mock_scanner.find_skill.return_value
        file_info.skill_dir = temp_project_path / ".memstack" / "skills" / "test-skill"

        loader = SkillResourceLoader(temp_project_path, scanner=mock_scanner)

        resources = await loader.get_skill_resources("test-skill")

        # Should find 3 resource files (analyze.py, guide.md, template.json)
        assert len(resources) == 3
        assert any(r.name == "analyze.py" for r in resources)
        assert any(r.name == "guide.md" for r in resources)
        assert any(r.name == "template.json" for r in resources)

    @pytest.mark.asyncio
    async def test_get_skill_resources_empty_skill(
        self, temp_project_path: Path, mock_scanner
    ):
        """Test get_skill_resources with skill that has no resources."""
        # Create skill without resource directories
        empty_skill = temp_project_path / ".memstack" / "skills" / "empty-skill"
        empty_skill.mkdir(parents=True)
        (empty_skill / "SKILL.md").write_text("---\nname: empty\n---")

        file_info = mock_scanner.find_skill.return_value
        file_info.skill_dir = empty_skill

        loader = SkillResourceLoader(temp_project_path, scanner=mock_scanner)

        resources = await loader.get_skill_resources("empty-skill")

        assert len(resources) == 0

    @pytest.mark.asyncio
    async def test_get_skill_resources_skill_not_found(
        self, temp_project_path: Path, mock_scanner
    ):
        """Test get_skill_resources when skill is not found."""
        mock_scanner.find_skill.return_value = None

        loader = SkillResourceLoader(temp_project_path, scanner=mock_scanner)

        resources = await loader.get_skill_resources("non-existent")

        assert len(resources) == 0

    def test_scan_directory_finds_all_files(self, temp_project_path: Path):
        """Test _scan_directory finds all files recursively."""
        from src.infrastructure.agent.skill.skill_resource_loader import (
            SkillResourceLoader,
        )

        loader = SkillResourceLoader(temp_project_path)
        scripts_dir = temp_project_path / ".memstack" / "skills" / "test-skill" / "scripts"

        results = loader._scan_directory(scripts_dir)

        assert len(results) == 1
        assert results[0].name == "analyze.py"

    @pytest.mark.asyncio
    async def test_detect_referred_resources_finds_scripts_references(
        self, temp_project_path: Path
    ):
        """Test detect_referred_resources finds scripts/ references."""
        loader = SkillResourceLoader(temp_project_path)

        content = """
        # Run the analyzer
        ```bash
        python3 scripts/analyze.py
        ```

        See references/guide.md for details.
        """

        referred = await loader.detect_referred_resources("test-skill", content)

        assert "scripts/analyze.py" in referred
        assert "references/guide.md" in referred

    @pytest.mark.asyncio
    async def test_detect_referred_resources_empty_content(
        self, temp_project_path: Path
    ):
        """Test detect_referred_resources with empty content."""
        loader = SkillResourceLoader(temp_project_path)

        referred = await loader.detect_referred_resources("test-skill", "")

        assert len(referred) == 0

    def test_get_resource_container_path(self, temp_project_path: Path):
        """Test get_resource_container_path returns correct sandbox path."""
        from src.infrastructure.agent.skill.skill_resource_loader import (
            SkillResourceLoader,
        )

        loader = SkillResourceLoader(temp_project_path)
        resource_path = Path("/some/path/scripts/analyze.py")
        skill_dir = Path("/some/path")

        container_path = loader.get_resource_container_path(
            "test-skill", resource_path, skill_dir
        )

        # Should be /workspace/.memstack/skills/test-skill/scripts/analyze.py
        assert container_path == "/workspace/.memstack/skills/test-skill/scripts/analyze.py"

    def test_get_resource_container_path_fallback(self, temp_project_path: Path):
        """Test get_resource_container_path fallback without skill_dir."""
        from src.infrastructure.agent.skill.skill_resource_loader import (
            SkillResourceLoader,
        )

        loader = SkillResourceLoader(temp_project_path)
        resource_path = Path("/some/path/scripts/analyze.py")

        container_path = loader.get_resource_container_path("test-skill", resource_path)

        # Fallback: uses filename only
        assert container_path == "/workspace/.memstack/skills/test-skill/analyze.py"
