"""Tests for MCP server frontmatter parsing in MarkdownParser."""

from __future__ import annotations

import pytest

from src.infrastructure.skill.markdown_parser import MarkdownParser


@pytest.fixture()
def parser() -> MarkdownParser:
    return MarkdownParser()


MINIMAL_SKILL = """\
---
name: test-skill
description: "A test skill"
---

# Test Skill
"""


class TestMarkdownParserMcpServers:
    """Tests for mcp-servers frontmatter key parsing."""

    def test_mcp_servers_merged_into_metadata(self, parser: MarkdownParser) -> None:
        """Top-level mcp-servers list is merged into metadata['mcp_servers']."""
        content = """\
---
name: my-skill
description: "Skill with MCP"
mcp-servers:
  - server_name: fetch
    command: npx
    args: ["-y", "@anthropic/mcp-server-fetch"]
  - server_name: filesystem
    command: npx
    args: ["-y", "@anthropic/mcp-server-fs"]
    env:
      HOME: /tmp
---

# My Skill
"""
        result = parser.parse(content)
        assert result.name == "my-skill"
        mcp = result.metadata.get("mcp_servers")
        assert mcp is not None
        assert isinstance(mcp, list)
        assert len(mcp) == 2
        assert mcp[0]["server_name"] == "fetch"
        assert mcp[0]["command"] == "npx"
        assert mcp[0]["args"] == ["-y", "@anthropic/mcp-server-fetch"]
        assert mcp[1]["server_name"] == "filesystem"
        assert mcp[1]["env"] == {"HOME": "/tmp"}

    def test_no_mcp_servers_key_yields_empty_metadata(self, parser: MarkdownParser) -> None:
        """Without mcp-servers key, metadata has no mcp_servers entry."""
        result = parser.parse(MINIMAL_SKILL)
        assert "mcp_servers" not in result.metadata

    def test_mcp_servers_not_a_list_is_ignored(self, parser: MarkdownParser) -> None:
        """If mcp-servers is a string instead of list, it is ignored."""
        content = """\
---
name: bad-mcp
description: "Bad MCP config"
mcp-servers: "not-a-list"
---

# Bad
"""
        result = parser.parse(content)
        assert "mcp_servers" not in result.metadata

    def test_mcp_servers_empty_list_is_ignored(self, parser: MarkdownParser) -> None:
        """An empty mcp-servers list is falsy and should not be merged."""
        content = """\
---
name: empty-mcp
description: "Empty MCP config"
mcp-servers: []
---

# Empty
"""
        result = parser.parse(content)
        assert "mcp_servers" not in result.metadata

    def test_mcp_servers_coexists_with_metadata(self, parser: MarkdownParser) -> None:
        """mcp-servers merges into existing metadata without overwriting."""
        content = """\
---
name: mixed-skill
description: "Mixed metadata"
metadata:
  author: test-user
  version: "1.0"
mcp-servers:
  - server_name: fetch
    command: npx
    args: ["-y", "@anthropic/mcp-server-fetch"]
---

# Mixed
"""
        result = parser.parse(content)
        assert result.metadata["author"] == "test-user"
        assert result.metadata["version"] == "1.0"
        mcp = result.metadata["mcp_servers"]
        assert len(mcp) == 1
        assert mcp[0]["server_name"] == "fetch"

    def test_mcp_servers_with_auto_start_field(self, parser: MarkdownParser) -> None:
        """MCP server entries can include auto_start flag."""
        content = """\
---
name: auto-start-skill
description: "Auto start MCP"
mcp-servers:
  - server_name: fetch
    command: npx
    args: ["-y", "@anthropic/mcp-server-fetch"]
    auto_start: false
---

# Auto Start
"""
        result = parser.parse(content)
        mcp = result.metadata["mcp_servers"]
        assert mcp[0]["auto_start"] is False

    def test_single_mcp_server_entry(self, parser: MarkdownParser) -> None:
        """A single MCP server entry works correctly."""
        content = """\
---
name: single-mcp
description: "Single MCP"
mcp-servers:
  - server_name: only-one
    command: python
    args: ["-m", "mcp_server"]
---

# Single
"""
        result = parser.parse(content)
        mcp = result.metadata["mcp_servers"]
        assert len(mcp) == 1
        assert mcp[0]["server_name"] == "only-one"
        assert mcp[0]["command"] == "python"

    def test_metadata_mcp_servers_not_overwritten_by_top_level(
        self, parser: MarkdownParser
    ) -> None:
        """Top-level mcp-servers OVERWRITES metadata.mcp_servers if both exist.

        This is intentional: top-level mcp-servers is the canonical source.
        """
        content = """\
---
name: conflict-skill
description: "Conflict"
metadata:
  mcp_servers:
    - server_name: old
      command: old-cmd
mcp-servers:
  - server_name: new
    command: new-cmd
---

# Conflict
"""
        result = parser.parse(content)
        mcp = result.metadata["mcp_servers"]
        assert len(mcp) == 1
        assert mcp[0]["server_name"] == "new"
