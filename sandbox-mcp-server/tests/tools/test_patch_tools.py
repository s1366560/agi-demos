"""Tests for patch tool using TDD methodology."""

import os
import pytest
from pathlib import Path

from src.tools.file_tools import apply_patch


class TestPatchTool:
    """Test suite for patch tool."""

    @pytest.fixture
    def workspace(self, tmp_path):
        """Provide a temporary workspace with test files."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        return str(ws)

    @pytest.mark.asyncio
    async def test_apply_simple_patch(self, workspace):
        """Test applying a simple unified diff patch."""
        # Create original file
        file_path = os.path.join(workspace, "test.txt")
        with open(file_path, "w") as f:
            f.write("line1\nline2\nline3\nline4\nline5\n")

        # Create unified diff patch
        patch_content = """--- a/test.txt
+++ b/test.txt
@@ -1,5 +1,5 @@
 line1
-line2
+line2_modified
 line3
 line4
 line5
"""

        result = await apply_patch(
            file_path="test.txt",
            patch=patch_content,
            strip=0,
            _workspace_dir=workspace,
        )

        assert isinstance(result, dict)
        assert not result.get("isError")

        # Verify the file was modified
        with open(file_path, "r") as f:
            content = f.read()
        assert "line2_modified" in content
        # Check that original line2 was replaced (not just contains string)
        lines = content.strip().split("\n")
        assert lines[1] == "line2_modified"

    @pytest.mark.asyncio
    async def test_apply_patch_with_strip(self, workspace):
        """Test applying patch with strip level."""
        # Create original file
        os.makedirs(os.path.join(workspace, "subdir"), exist_ok=True)
        file_path = os.path.join(workspace, "subdir", "test.txt")
        with open(file_path, "w") as f:
            f.write("original\n")

        # Patch with a/ and b/ prefixes (strip=1 should handle it)
        patch_content = """--- a/subdir/test.txt
+++ b/subdir/test.txt
@@ -1,1 +1,1 @@
-original
+modified
"""

        result = await apply_patch(
            file_path="subdir/test.txt",
            patch=patch_content,
            strip=1,
            _workspace_dir=workspace,
        )

        assert not result.get("isError")

        with open(file_path, "r") as f:
            content = f.read()
        assert "modified" in content

    @pytest.mark.asyncio
    async def test_patch_nonexistent_file(self, workspace):
        """Test patching a nonexistent file."""
        patch_content = """--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,1 @@
-old
+new
"""

        result = await apply_patch(
            file_path="test.txt",
            patch=patch_content,
            strip=0,
            _workspace_dir=workspace,
        )

        assert result.get("isError") is True
        content = result.get("content", [{}])[0].get("text", "")
        assert "not found" in content.lower() or "error" in content.lower()

    @pytest.mark.asyncio
    async def test_patch_invalid_format(self, workspace):
        """Test applying invalid patch format."""
        file_path = os.path.join(workspace, "test.txt")
        with open(file_path, "w") as f:
            f.write("content\n")

        # Invalid patch - missing headers
        patch_content = "invalid patch content"

        result = await apply_patch(
            file_path="test.txt",
            patch=patch_content,
            strip=0,
            _workspace_dir=workspace,
        )

        assert result.get("isError") is True

    @pytest.mark.asyncio
    async def test_patch_hunks_out_of_order(self, workspace):
        """Test patch with hunks that don't match file content."""
        file_path = os.path.join(workspace, "test.txt")
        with open(file_path, "w") as f:
            f.write("different content\n")

        # Patch expects "old content" but file has "different content"
        patch_content = """--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,1 @@
-old content
+new content
"""

        result = await apply_patch(
            file_path="test.txt",
            patch=patch_content,
            strip=0,
            _workspace_dir=workspace,
        )

        assert result.get("isError") is True
        content = result.get("content", [{}])[0].get("text", "").lower()
        assert "hunk" in content or "match" in content or "fail" in content

    @pytest.mark.asyncio
    async def test_patch_multiple_hunks(self, workspace):
        """Test patch with multiple hunks."""
        file_path = os.path.join(workspace, "test.txt")
        with open(file_path, "w") as f:
            f.write("line1\nline2\nline3\nline4\nline5\nline6\n")

        patch_content = """--- a/test.txt
+++ b/test.txt
@@ -1,3 +1,3 @@
 line1
-line2
+line2_modified
 line3
@@ -4,3 +4,3 @@
 line4
-line5
+line5_modified
 line6
"""

        result = await apply_patch(
            file_path="test.txt",
            patch=patch_content,
            strip=0,
            _workspace_dir=workspace,
        )

        assert not result.get("isError")

        with open(file_path, "r") as f:
            content = f.read()
        assert "line2_modified" in content
        assert "line5_modified" in content

    @pytest.mark.asyncio
    async def test_patch_add_lines(self, workspace):
        """Test patch that adds new lines."""
        file_path = os.path.join(workspace, "test.txt")
        with open(file_path, "w") as f:
            f.write("line1\nline3\n")

        patch_content = """--- a/test.txt
+++ b/test.txt
@@ -1,2 +1,3 @@
 line1
+line2
 line3
"""

        result = await apply_patch(
            file_path="test.txt",
            patch=patch_content,
            strip=0,
            _workspace_dir=workspace,
        )

        assert not result.get("isError")

        with open(file_path, "r") as f:
            content = f.read()
        assert "line2" in content
        assert content == "line1\nline2\nline3\n"

    @pytest.mark.asyncio
    async def test_patch_delete_lines(self, workspace):
        """Test patch that deletes lines."""
        file_path = os.path.join(workspace, "test.txt")
        with open(file_path, "w") as f:
            f.write("line1\nline2\nline3\n")

        patch_content = """--- a/test.txt
+++ b/test.txt
@@ -1,3 +1,2 @@
 line1
-line2
 line3
"""

        result = await apply_patch(
            file_path="test.txt",
            patch=patch_content,
            strip=0,
            _workspace_dir=workspace,
        )

        assert not result.get("isError")

        with open(file_path, "r") as f:
            content = f.read()
        assert "line2" not in content
        assert content == "line1\nline3\n"

    @pytest.mark.asyncio
    async def test_patch_security_path_escape(self, workspace):
        """Test that patch tool prevents path traversal attacks."""
        file_path = os.path.join(workspace, "test.txt")
        with open(file_path, "w") as f:
            f.write("content\n")

        patch_content = """--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,1 @@
-content
+modified
"""

        # Try to escape workspace
        result = await apply_patch(
            file_path="../etc/passwd",  # Should be blocked
            patch=patch_content,
            strip=0,
            _workspace_dir=workspace,
        )

        assert result.get("isError") is True
        content = result.get("content", [{}])[0].get("text", "").lower()
        assert "outside" in content or "escape" in content or "security" in content
