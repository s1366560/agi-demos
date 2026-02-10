"""Unit tests for SkillReverseSync service."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.application.services.skill_reverse_sync import SkillReverseSync
from src.domain.model.agent.skill.skill_version import SkillVersion

SAMPLE_SKILL_MD = """---
name: test-skill
version: "1.0.0"
description: A test skill
trigger_type: keyword
trigger_patterns:
  - test
tools:
  - terminal
---

## System Prompt
You are a test skill.
"""


@pytest.mark.unit
class TestSkillReverseSync:
    """Tests for SkillReverseSync service."""

    def _make_service(self):
        skill_repo = AsyncMock()
        version_repo = AsyncMock()
        host_path = Path("/tmp/test-project")
        service = SkillReverseSync(
            skill_repository=skill_repo,
            skill_version_repository=version_repo,
            host_project_path=host_path,
        )
        return service, skill_repo, version_repo

    async def test_sync_from_sandbox_no_files(self):
        service, skill_repo, version_repo = self._make_service()
        adapter = AsyncMock()
        # Return empty content list (no files)
        adapter.call_tool.return_value = {"content": []}

        result = await service.sync_from_sandbox(
            skill_name="my-skill",
            tenant_id="t1",
            sandbox_adapter=adapter,
            sandbox_id="sb-1",
        )

        assert "error" in result

    async def test_sync_from_sandbox_no_skill_md(self):
        service, skill_repo, version_repo = self._make_service()
        adapter = AsyncMock()

        # glob returns workspace-relative paths (no SKILL.md)
        adapter.call_tool.side_effect = [
            {"content": [{"type": "text", "text": ".memstack/skills/my-skill/readme.txt"}]},
            {"content": [{"type": "text", "text": "Hello"}]},
        ]

        result = await service.sync_from_sandbox(
            skill_name="my-skill",
            tenant_id="t1",
            sandbox_adapter=adapter,
            sandbox_id="sb-1",
        )

        assert "error" in result
        assert "SKILL.md not found" in result["error"]

    @patch("src.application.services.skill_reverse_sync.SkillReverseSync._write_to_host")
    async def test_sync_from_sandbox_new_skill(self, mock_write):
        service, skill_repo, version_repo = self._make_service()
        mock_write.return_value = None

        adapter = AsyncMock()
        # MCP glob returns workspace-relative paths as newline-separated text
        adapter.call_tool.side_effect = [
            # glob result: workspace-relative paths
            {
                "content": [
                    {
                        "type": "text",
                        "text": ".memstack/skills/test-skill/SKILL.md\n"
                        ".memstack/skills/test-skill/scripts/run.py",
                    }
                ]
            },
            # read SKILL.md
            {"content": [{"type": "text", "text": SAMPLE_SKILL_MD}]},
            # read scripts/run.py
            {"content": [{"type": "text", "text": "print('hello')"}]},
        ]

        skill_repo.get_by_name.return_value = None
        skill_repo.create.return_value = None
        skill_repo.update.return_value = None
        version_repo.get_max_version_number.return_value = 0
        version_repo.create.return_value = None

        result = await service.sync_from_sandbox(
            skill_name="test-skill",
            tenant_id="t1",
            sandbox_adapter=adapter,
            sandbox_id="sb-1",
        )

        assert "error" not in result
        assert result["version_number"] == 1
        assert result["version_label"] == "1.0.0"
        skill_repo.create.assert_called_once()
        version_repo.create.assert_called_once()

    async def test_rollback_version_not_found(self):
        service, skill_repo, version_repo = self._make_service()
        version_repo.get_by_version.return_value = None

        result = await service.rollback_to_version(
            skill_id="skill-1",
            version_number=99,
        )

        assert "error" in result
        assert "not found" in result["error"]

    async def test_rollback_skill_not_found(self):
        service, skill_repo, version_repo = self._make_service()
        version_repo.get_by_version.return_value = SkillVersion(
            id="v-1",
            skill_id="skill-1",
            version_number=1,
            skill_md_content=SAMPLE_SKILL_MD,
            resource_files={},
        )
        skill_repo.get_by_id.return_value = None

        result = await service.rollback_to_version(
            skill_id="skill-1",
            version_number=1,
        )

        assert "error" in result
        assert "not found" in result["error"]

    def test_generate_change_summary(self):
        service, _, _ = self._make_service()
        prev = SkillVersion(
            id="v-1",
            skill_id="s1",
            version_number=1,
            skill_md_content="# Old",
            resource_files={"a.txt": "old", "b.txt": "data"},
        )

        summary = service._generate_change_summary(
            prev,
            new_md_content="# New content",
            new_resource_files={"a.txt": "new", "c.txt": "added"},
        )

        assert "SKILL.md modified" in summary
        assert "Added" in summary
        assert "Removed" in summary

    def test_extract_file_paths_newline_separated(self):
        """MCP glob returns newline-separated paths in a single text item."""
        glob_result = {
            "content": [
                {
                    "type": "text",
                    "text": ".memstack/skills/my-skill/SKILL.md\n"
                    ".memstack/skills/my-skill/scripts/run.py\n"
                    ".memstack/skills/my-skill/templates/report.html",
                }
            ]
        }
        paths = SkillReverseSync._extract_file_paths(glob_result)
        assert len(paths) == 3
        assert ".memstack/skills/my-skill/SKILL.md" in paths
        assert ".memstack/skills/my-skill/scripts/run.py" in paths

    def test_extract_file_paths_filters_errors(self):
        """Error messages and trailing info should be filtered."""
        glob_result = {
            "content": [
                {
                    "type": "text",
                    "text": "file1.py\nfile2.py\n... and 50 more files",
                }
            ]
        }
        paths = SkillReverseSync._extract_file_paths(glob_result)
        assert len(paths) == 2
        assert "file1.py" in paths
