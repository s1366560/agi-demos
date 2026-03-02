"""Tests for skill_installer @tool_define implementation.

This module tests the skill_installer_tool function and its helper
functions (_inst_parse_skill_source, _inst_get_install_path, _inst_fetch_file).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.skill_installer import (
    _inst_fetch_file,
    _inst_get_install_path,
    _inst_parse_skill_source,
    configure_skill_installer,
    skill_installer_tool,
)


def _make_ctx(**overrides: Any) -> ToolContext:
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


class TestSkillInstallerTool:
    """Test cases for skill_installer @tool_define implementation."""

    def test_tool_info_name_and_description(self) -> None:
        """Test that the ToolInfo has correct name and description."""
        assert skill_installer_tool.name == "skill_installer"
        assert "skills.sh" in skill_installer_tool.description

    def test_parameters_schema(self) -> None:
        """Test parameters schema from ToolInfo."""
        schema = skill_installer_tool.parameters
        assert schema["type"] == "object"
        assert "skill_source" in schema["properties"]
        assert "skill_name" in schema["properties"]
        assert "install_location" in schema["properties"]
        assert "branch" in schema["properties"]
        assert "skill_source" in schema["required"]

    def test_parse_skill_source_owner_repo(self) -> None:
        """Test parsing owner/repo format."""
        owner, repo, skill = _inst_parse_skill_source("vercel-labs/agent-skills")
        assert owner == "vercel-labs"
        assert repo == "agent-skills"
        assert skill is None

    def test_parse_skill_source_github_url(self) -> None:
        """Test parsing GitHub URL format."""
        owner, repo, skill = _inst_parse_skill_source("https://github.com/vercel-labs/agent-skills")
        assert owner == "vercel-labs"
        assert repo == "agent-skills"
        assert skill is None

    def test_parse_skill_source_skills_sh_url(self) -> None:
        """Test parsing skills.sh URL format."""
        owner, repo, skill = _inst_parse_skill_source(
            "https://skills.sh/vercel-labs/agent-skills/react-best-practices"
        )
        assert owner == "vercel-labs"
        assert repo == "agent-skills"
        assert skill == "react-best-practices"

    def test_parse_skill_source_invalid(self) -> None:
        """Test parsing invalid format."""
        with pytest.raises(ValueError):
            _ = _inst_parse_skill_source("invalid-format")

    def test_get_install_path_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test getting project-level install path."""
        monkeypatch.setattr(
            "src.infrastructure.agent.tools.skill_installer._skill_inst_project_path",
            tmp_path,
        )
        path = _inst_get_install_path("project", "my-skill")
        assert path == tmp_path / ".memstack" / "skills" / "my-skill"

    def test_get_install_path_global(self) -> None:
        """Test getting global install path."""
        path = _inst_get_install_path("global", "my-skill")
        assert str(path).endswith(".memstack/skills/my-skill")
        assert "~" not in str(path)  # Should be expanded

    async def test_execute_missing_skill_source(
        self, tmp_path: Path,
    ) -> None:
        """Test execute with empty skill_source."""
        configure_skill_installer(project_path=tmp_path)
        ctx = _make_ctx()
        result = await skill_installer_tool.execute(ctx, skill_source="")
        assert (
            result.is_error
            or "required" in result.output.lower()
            or "empty" in result.output.lower()
        )

    async def test_execute_invalid_install_location(
        self, tmp_path: Path,
    ) -> None:
        """Test execute with invalid install_location."""
        configure_skill_installer(project_path=tmp_path)
        ctx = _make_ctx()
        result = await skill_installer_tool.execute(
            ctx,
            skill_source="owner/repo",
            skill_name="my-skill",
            install_location="invalid",
        )
        assert "Invalid install_location" in result.output

    async def test_execute_skill_already_exists(
        self, tmp_path: Path,
    ) -> None:
        """Test execute when skill already exists."""
        configure_skill_installer(project_path=tmp_path)
        # Create existing skill directory
        skill_dir = tmp_path / ".memstack" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        _ = (skill_dir / "SKILL.md").write_text("# Existing Skill")

        ctx = _make_ctx()
        result = await skill_installer_tool.execute(
            ctx,
            skill_source="owner/repo",
            skill_name="my-skill",
            install_location="project",
        )

        assert result.title is not None
        assert "already installed" in result.title
        assert result.metadata.get("reason") == "already_exists"

    @patch(
        "src.infrastructure.agent.tools.skill_installer._inst_fetch_file",
        new_callable=AsyncMock,
    )
    async def test_execute_successful_install(self, mock_fetch: AsyncMock, tmp_path: Path) -> None:
        """Test successful skill installation."""
        configure_skill_installer(project_path=tmp_path)
        skill_content = "# Test Skill\n\nThis is a test skill."
        mock_fetch.return_value = skill_content

        ctx = _make_ctx()
        result = await skill_installer_tool.execute(
            ctx,
            skill_source="owner/repo",
            skill_name="test-skill",
            install_location="project",
        )

        assert result.title is not None
        assert "Successfully installed" in result.title
        assert result.metadata.get("action") == "install"
        assert result.metadata.get("skill_name") == "test-skill"

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

    @patch(
        "src.infrastructure.agent.tools.skill_installer._inst_fetch_file",
        new_callable=AsyncMock,
    )
    async def test_execute_skill_not_found(self, mock_fetch: AsyncMock, tmp_path: Path) -> None:
        """Test execute when skill is not found."""
        configure_skill_installer(project_path=tmp_path)
        mock_fetch.return_value = None

        ctx = _make_ctx()
        result = await skill_installer_tool.execute(
            ctx,
            skill_source="owner/repo",
            skill_name="nonexistent-skill",
            install_location="project",
        )

        assert "Could not find SKILL.md" in result.output

    @patch(
        "src.infrastructure.agent.tools.skill_installer._inst_discover_skills_in_repo",
        new_callable=AsyncMock,
    )
    async def test_execute_discover_multiple_skills(
        self, mock_discover: AsyncMock, tmp_path: Path
    ) -> None:
        """Test execute discovering multiple skills in repo."""
        configure_skill_installer(project_path=tmp_path)
        mock_discover.return_value = ["skill-a", "skill-b", "skill-c"]

        ctx = _make_ctx()
        result = await skill_installer_tool.execute(
            ctx,
            skill_source="owner/repo",
            install_location="project",
        )

        assert result.title is not None
        assert "Multiple skills available" in result.title
        assert result.metadata.get("action") == "list"
        assert len(result.metadata.get("available_skills", [])) == 3

    async def test_fetch_file_success(self) -> None:
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

            content = await _inst_fetch_file("owner", "repo", "SKILL.md")

            assert content == "# Test Content"

    async def test_fetch_file_not_found(self) -> None:
        """Test fetching non-existent file."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 404

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            content = await _inst_fetch_file("owner", "repo", "nonexistent.md")

            assert content is None


@pytest.mark.unit
class TestSkillInstallerToolUnit:
    """Unit tests for skill_installer with markers."""

    def test_description_contains_usage_examples(self) -> None:
        """Test that description contains usage examples."""
        desc = skill_installer_tool.description
        assert "skill_installer" in desc
        assert "vercel-labs/agent-skills" in desc
        assert "project" in desc
        assert "global" in desc

    def test_parameters_have_descriptions(self) -> None:
        """Test that all parameters have descriptions."""
        schema = skill_installer_tool.parameters
        for prop_name, prop_def in schema["properties"].items():
            assert "description" in prop_def, f"Parameter {prop_name} missing description"
