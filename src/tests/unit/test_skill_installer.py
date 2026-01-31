"""Tests for SkillInstallerTool.

This module contains unit tests for the skill installer tool
that allows agents to install skills from skills.sh ecosystem.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.tools.skill_installer import SkillInstallerTool


class TestSkillInstallerTool:
    """Test cases for SkillInstallerTool."""

    @pytest.fixture
    def tool(self, tmp_path: Path) -> SkillInstallerTool:
        """Create a SkillInstallerTool instance with temp directory."""
        return SkillInstallerTool(project_path=tmp_path)

    def test_init(self, tmp_path: Path) -> None:
        """Test tool initialization."""
        tool = SkillInstallerTool(project_path=tmp_path)
        assert tool.name == "skill_installer"
        assert "skills.sh" in tool.description
        assert tool._project_path == tmp_path

    def test_get_parameters_schema(self, tool: SkillInstallerTool) -> None:
        """Test parameters schema."""
        schema = tool.get_parameters_schema()

        assert schema["type"] == "object"
        assert "skill_source" in schema["properties"]
        assert "skill_name" in schema["properties"]
        assert "install_location" in schema["properties"]
        assert "branch" in schema["properties"]
        assert "skill_source" in schema["required"]

    def test_validate_args_valid(self, tool: SkillInstallerTool) -> None:
        """Test argument validation with valid args."""
        assert tool.validate_args(skill_source="vercel-labs/agent-skills")
        assert tool.validate_args(skill_source="owner/repo", skill_name="my-skill")

    def test_validate_args_invalid(self, tool: SkillInstallerTool) -> None:
        """Test argument validation with invalid args."""
        assert not tool.validate_args()
        assert not tool.validate_args(skill_source="")
        assert not tool.validate_args(skill_source=123)

    def test_parse_skill_source_owner_repo(self, tool: SkillInstallerTool) -> None:
        """Test parsing owner/repo format."""
        owner, repo, skill = tool._parse_skill_source("vercel-labs/agent-skills")
        assert owner == "vercel-labs"
        assert repo == "agent-skills"
        assert skill is None

    def test_parse_skill_source_github_url(self, tool: SkillInstallerTool) -> None:
        """Test parsing GitHub URL format."""
        owner, repo, skill = tool._parse_skill_source("https://github.com/vercel-labs/agent-skills")
        assert owner == "vercel-labs"
        assert repo == "agent-skills"
        assert skill is None

    def test_parse_skill_source_skills_sh_url(self, tool: SkillInstallerTool) -> None:
        """Test parsing skills.sh URL format."""
        owner, repo, skill = tool._parse_skill_source(
            "https://skills.sh/vercel-labs/agent-skills/react-best-practices"
        )
        assert owner == "vercel-labs"
        assert repo == "agent-skills"
        assert skill == "react-best-practices"

    def test_parse_skill_source_invalid(self, tool: SkillInstallerTool) -> None:
        """Test parsing invalid format."""
        with pytest.raises(ValueError):
            tool._parse_skill_source("invalid-format")

    def test_get_install_path_project(self, tool: SkillInstallerTool, tmp_path: Path) -> None:
        """Test getting project-level install path."""
        path = tool._get_install_path("project", "my-skill")
        assert path == tmp_path / ".memstack" / "skills" / "my-skill"

    def test_get_install_path_global(self, tool: SkillInstallerTool) -> None:
        """Test getting global install path."""
        path = tool._get_install_path("global", "my-skill")
        assert str(path).endswith(".memstack/skills/my-skill")
        assert "~" not in str(path)  # Should be expanded

    @pytest.mark.asyncio
    async def test_execute_missing_skill_source(self, tool: SkillInstallerTool) -> None:
        """Test execute with missing skill_source."""
        result = await tool.execute()
        assert result["title"] == "Skill Installation Failed"
        assert "skill_source parameter is required" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_invalid_install_location(self, tool: SkillInstallerTool) -> None:
        """Test execute with invalid install_location."""
        result = await tool.execute(
            skill_source="owner/repo",
            skill_name="my-skill",
            install_location="invalid",
        )
        assert result["title"] == "Skill Installation Failed"
        assert "Invalid install_location" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_skill_already_exists(
        self, tool: SkillInstallerTool, tmp_path: Path
    ) -> None:
        """Test execute when skill already exists."""
        # Create existing skill directory
        skill_dir = tmp_path / ".memstack" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Existing Skill")

        result = await tool.execute(
            skill_source="owner/repo",
            skill_name="my-skill",
            install_location="project",
        )

        assert "already installed" in result["title"]
        assert result["metadata"]["reason"] == "already_exists"

    @pytest.mark.asyncio
    async def test_execute_successful_install(
        self, tool: SkillInstallerTool, tmp_path: Path
    ) -> None:
        """Test successful skill installation."""
        skill_content = "# Test Skill\n\nThis is a test skill."

        with patch.object(tool, "_fetch_file", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = skill_content

            result = await tool.execute(
                skill_source="owner/repo",
                skill_name="test-skill",
                install_location="project",
            )

        assert "Successfully installed" in result["title"]
        assert result["metadata"]["action"] == "install"
        assert result["metadata"]["skill_name"] == "test-skill"

        # Verify file was created
        skill_file = tmp_path / ".memstack" / "skills" / "test-skill" / "SKILL.md"
        assert skill_file.exists()
        assert skill_file.read_text() == skill_content

        # Verify metadata file
        meta_file = tmp_path / ".memstack" / "skills" / "test-skill" / ".skill-meta.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text())
        assert meta["skill_name"] == "test-skill"
        assert meta["source"] == "owner/repo"

    @pytest.mark.asyncio
    async def test_execute_skill_not_found(self, tool: SkillInstallerTool) -> None:
        """Test execute when skill is not found."""
        with patch.object(tool, "_fetch_file", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = None

            result = await tool.execute(
                skill_source="owner/repo",
                skill_name="nonexistent-skill",
                install_location="project",
            )

        assert result["title"] == "Skill Installation Failed"
        assert "Could not find SKILL.md" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_discover_multiple_skills(self, tool: SkillInstallerTool) -> None:
        """Test execute discovering multiple skills in repo."""
        with patch.object(
            tool, "_discover_skills_in_repo", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = ["skill-a", "skill-b", "skill-c"]

            result = await tool.execute(
                skill_source="owner/repo",
                install_location="project",
            )

        assert "Multiple skills available" in result["title"]
        assert result["metadata"]["action"] == "list"
        assert len(result["metadata"]["available_skills"]) == 3

    @pytest.mark.asyncio
    async def test_fetch_file_success(self, tool: SkillInstallerTool) -> None:
        """Test fetching file from GitHub."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "# Test Content"

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            content = await tool._fetch_file("owner", "repo", "SKILL.md")

            assert content == "# Test Content"

    @pytest.mark.asyncio
    async def test_fetch_file_not_found(self, tool: SkillInstallerTool) -> None:
        """Test fetching non-existent file."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 404

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            content = await tool._fetch_file("owner", "repo", "nonexistent.md")

            assert content is None


@pytest.mark.unit
class TestSkillInstallerToolUnit:
    """Unit tests for SkillInstallerTool with markers."""

    @pytest.fixture
    def tool(self, tmp_path: Path) -> SkillInstallerTool:
        """Create a SkillInstallerTool instance."""
        return SkillInstallerTool(project_path=tmp_path)

    def test_description_contains_usage_examples(self, tool: SkillInstallerTool) -> None:
        """Test that description contains usage examples."""
        desc = tool.description
        assert "skill_installer" in desc
        assert "vercel-labs/agent-skills" in desc
        assert "project" in desc
        assert "global" in desc

    def test_parameters_have_descriptions(self, tool: SkillInstallerTool) -> None:
        """Test that all parameters have descriptions."""
        schema = tool.get_parameters_schema()
        for prop_name, prop_def in schema["properties"].items():
            assert "description" in prop_def, f"Parameter {prop_name} missing description"
