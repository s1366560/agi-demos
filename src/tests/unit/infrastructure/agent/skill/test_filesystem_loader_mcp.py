"""Tests for metadata passthrough in FileSystemSkillLoader."""

from __future__ import annotations

from pathlib import Path

from src.infrastructure.agent.skill.filesystem_loader import (
    FileSystemSkillLoader,
)
from src.infrastructure.skill.filesystem_scanner import SkillFileInfo
from src.infrastructure.skill.markdown_parser import (
    MarkdownParser,
    SkillMarkdown,
)


def _make_file_info(name: str = "test-skill", is_system: bool = False) -> SkillFileInfo:
    """Create a SkillFileInfo for testing."""
    return SkillFileInfo(
        skill_id=name,
        file_path=Path(f"/fake/skills/{name}/SKILL.md"),
        skill_dir=Path(f"/fake/skills/{name}"),
        is_system=is_system,
    )


def _make_markdown(
    name: str = "test-skill",
    description: str = "A test skill",
    metadata: dict | None = None,
    trigger_patterns: list[str] | None = None,
    tools: list[str] | None = None,
    agent: list[str] | None = None,
) -> SkillMarkdown:
    """Create a SkillMarkdown for testing."""
    return SkillMarkdown(
        frontmatter={"name": name, "description": description},
        content="# Test\nInstructions here.",
        name=name,
        description=description,
        trigger_patterns=trigger_patterns or ["test"],
        tools=tools or ["web_search"],
        metadata=metadata or {},
        agent=agent or ["*"],
    )


class TestFileSystemSkillLoaderMetadata:
    """Tests that metadata flows from SkillMarkdown to Skill entity."""

    def test_metadata_with_mcp_servers_passes_through(self) -> None:
        """Skill.metadata contains mcp_servers when markdown has them."""
        mcp_config = [
            {
                "server_name": "fetch",
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-server-fetch"],
            }
        ]
        markdown = _make_markdown(metadata={"mcp_servers": mcp_config, "author": "tester"})
        file_info = _make_file_info()

        loader = FileSystemSkillLoader(
            base_path=Path("/fake"),
            tenant_id="tenant-1",
        )
        skill = loader._create_skill_from_markdown(markdown, file_info)

        assert skill.metadata is not None
        assert skill.metadata["mcp_servers"] == mcp_config
        assert skill.metadata["author"] == "tester"

    def test_empty_metadata_becomes_none(self) -> None:
        """Empty dict metadata becomes None on Skill entity."""
        markdown = _make_markdown(metadata={})
        file_info = _make_file_info()

        loader = FileSystemSkillLoader(
            base_path=Path("/fake"),
            tenant_id="tenant-1",
        )
        skill = loader._create_skill_from_markdown(markdown, file_info)

        # Empty dict is falsy, so `metadata or None` yields None
        assert skill.metadata is None

    def test_metadata_without_mcp_passes_through(self) -> None:
        """Non-MCP metadata (author, version) still passes through."""
        markdown = _make_markdown(metadata={"author": "test-user", "version": "2.0"})
        file_info = _make_file_info()

        loader = FileSystemSkillLoader(
            base_path=Path("/fake"),
            tenant_id="tenant-1",
        )
        skill = loader._create_skill_from_markdown(markdown, file_info)

        assert skill.metadata is not None
        assert skill.metadata["author"] == "test-user"
        assert skill.metadata["version"] == "2.0"
        assert "mcp_servers" not in skill.metadata

    def test_none_metadata_stays_none(self) -> None:
        """When SkillMarkdown.metadata is default empty dict, Skill gets None."""
        markdown = _make_markdown()  # default metadata={}
        file_info = _make_file_info()

        loader = FileSystemSkillLoader(
            base_path=Path("/fake"),
            tenant_id="tenant-1",
        )
        skill = loader._create_skill_from_markdown(markdown, file_info)

        assert skill.metadata is None

    def test_end_to_end_mcp_frontmatter_to_skill(self) -> None:
        """Full pipeline: SKILL.md with mcp-servers -> parse -> Skill entity."""
        content = """\
---
name: e2e-skill
description: "End to end test"
trigger_patterns:
  - e2e
tools:
  - web_search
mcp-servers:
  - server_name: fetch
    command: npx
    args: ["-y", "@anthropic/mcp-server-fetch"]
  - server_name: fs
    command: npx
    args: ["-y", "@anthropic/mcp-server-fs"]
    env:
      HOME: /tmp
---

# E2E Skill

Do the thing.
"""
        parser = MarkdownParser()
        markdown = parser.parse(content)

        file_info = _make_file_info(name="e2e-skill")
        loader = FileSystemSkillLoader(
            base_path=Path("/fake"),
            tenant_id="tenant-1",
            project_id="proj-1",
        )
        skill = loader._create_skill_from_markdown(markdown, file_info)

        assert skill.name == "e2e-skill"
        assert skill.metadata is not None

        mcp = skill.metadata.get("mcp_servers")
        assert mcp is not None
        assert len(mcp) == 2
        assert mcp[0]["server_name"] == "fetch"
        assert mcp[1]["server_name"] == "fs"
        assert mcp[1]["env"] == {"HOME": "/tmp"}

    def test_end_to_end_no_mcp_frontmatter(self) -> None:
        """Full pipeline: SKILL.md without mcp-servers -> Skill.metadata is None."""
        content = """\
---
name: no-mcp-skill
description: "No MCP"
trigger_patterns:
  - plain
tools:
  - memory_search
---

# Plain Skill
"""
        parser = MarkdownParser()
        markdown = parser.parse(content)

        file_info = _make_file_info(name="no-mcp-skill")
        loader = FileSystemSkillLoader(
            base_path=Path("/fake"),
            tenant_id="tenant-1",
        )
        skill = loader._create_skill_from_markdown(markdown, file_info)

        assert skill.name == "no-mcp-skill"
        # No metadata or mcp-servers -> metadata is None
        assert skill.metadata is None
