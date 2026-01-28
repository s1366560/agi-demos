"""Tests for list tool.

TDD approach: Write tests first, expect failures, then implement.
"""

import os
import pytest
from pathlib import Path

from src.tools.file_tools import list_directory


class TestListTool:
    """Test suite for list tool."""

    @pytest.fixture
    def workspace(self, tmp_path):
        """Provide a temporary workspace with test files."""
        ws = tmp_path / "workspace"
        ws.mkdir()

        # Create test structure
        (ws / "file1.txt").write_text("content1")
        (ws / "file2.md").write_text("content2")
        (ws / "subdir").mkdir()
        (ws / "subdir" / "file3.py").write_text("content3")

        # Create hidden file
        (ws / ".hidden").write_text("hidden")

        return str(ws)

    @pytest.mark.asyncio
    async def test_list_directory(self, workspace):
        """Test listing a directory."""
        result = await list_directory(
            path=workspace,
            recursive=False,
            include_hidden=False,
            detailed=False,
            _workspace_dir=workspace,
        )

        assert isinstance(result, dict)
        assert not result.get("isError")
        content = result.get("content", [{}])[0].get("text", "")
        assert "file1.txt" in content
        assert "file2.md" in content
        assert "subdir" in content
        # Hidden files not included by default
        assert ".hidden" not in content

    @pytest.mark.asyncio
    async def test_list_with_detailed(self, workspace):
        """Test listing with detailed info."""
        result = await list_directory(
            path=workspace,
            recursive=False,
            include_hidden=False,
            detailed=True,
            _workspace_dir=workspace,
        )

        assert isinstance(result, dict)
        assert not result.get("isError")
        content = result.get("content", [{}])[0].get("text", "")
        # Detailed format should include permissions, size, etc.
        assert "file1.txt" in content
        assert "file2.md" in content

    @pytest.mark.asyncio
    async def test_list_recursive(self, workspace):
        """Test listing with recursion."""
        result = await list_directory(
            path=workspace,
            recursive=True,
            include_hidden=False,
            detailed=False,
            _workspace_dir=workspace,
        )

        assert isinstance(result, dict)
        assert not result.get("isError")
        content = result.get("content", [{}])[0].get("text", "")
        # Should include nested files
        assert "file1.txt" in content
        assert "file3.py" in content
        assert "subdir" in content

    @pytest.mark.asyncio
    async def test_list_with_hidden(self, workspace):
        """Test listing with hidden files."""
        result = await list_directory(
            path=workspace,
            recursive=False,
            include_hidden=True,
            detailed=False,
            _workspace_dir=workspace,
        )

        assert isinstance(result, dict)
        assert not result.get("isError")
        content = result.get("content", [{}])[0].get("text", "")
        # Hidden files should be included
        assert ".hidden" in content

    @pytest.mark.asyncio
    async def test_list_recursive_with_hidden(self, workspace):
        """Test listing with recursion and hidden files."""
        result = await list_directory(
            path=workspace,
            recursive=True,
            include_hidden=True,
            detailed=False,
            _workspace_dir=workspace,
        )

        assert isinstance(result, dict)
        assert not result.get("isError")
        content = result.get("content", [{}])[0].get("text", "")
        # Should include all files including hidden
        assert ".hidden" in content
        assert "file3.py" in content

    @pytest.mark.asyncio
    async def test_list_single_file(self, workspace):
        """Test listing a single file."""
        file_path = os.path.join(workspace, "file1.txt")
        result = await list_directory(
            path=file_path,
            recursive=False,
            include_hidden=False,
            detailed=False,
            _workspace_dir=workspace,
        )

        # Should indicate it's a file, not list directory
        assert isinstance(result, dict)
        assert not result.get("isError")
        content = result.get("content", [{}])[0].get("text", "")
        assert "file1.txt" in content

    @pytest.mark.asyncio
    async def test_list_nonexistent_path(self, workspace):
        """Test listing a nonexistent path."""
        result = await list_directory(
            path=os.path.join(workspace, "nonexistent"),
            recursive=False,
            include_hidden=False,
            detailed=False,
            _workspace_dir=workspace,
        )

        # Should indicate error
        assert isinstance(result, dict)
        assert result.get("isError") is True

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, tmp_path):
        """Test listing an empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = await list_directory(
            path=str(empty_dir),
            recursive=False,
            include_hidden=False,
            detailed=False,
            _workspace_dir=str(empty_dir),
        )

        assert isinstance(result, dict)
        assert not result.get("isError")
        content = result.get("content", [{}])[0].get("text", "")
        # Should indicate empty or list with just the directory name
        assert "empty" in content or "Empty" in content

    @pytest.mark.asyncio
    async def test_list_workspace_root(self, workspace):
        """Test listing workspace root with default parameters."""
        # Use "." for current directory
        result = await list_directory(
            path=".",
            recursive=False,
            include_hidden=False,
            detailed=False,
            _workspace_dir=workspace,
        )

        assert isinstance(result, dict)
        assert not result.get("isError")
