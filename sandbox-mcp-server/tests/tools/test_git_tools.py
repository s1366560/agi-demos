"""Tests for git tools using TDD methodology.

TDD Cycle:
1. RED - Write failing test
2. GREEN - Implement minimal code to pass
3. REFACTOR - Improve while keeping tests passing
"""

import asyncio
import pytest
import tempfile
from pathlib import Path

from src.tools.git_tools import (
    git_diff,
    git_log,
    generate_commit,
)


class TestGitDiff:
    """Test suite for git_diff tool."""

    @pytest.mark.asyncio
    async def test_git_diff_default(self):
        """Test getting git diff with default parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            # Create a file and commit it
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("original content\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmpdir, capture_output=True)

            # Modify the file
            test_file.write_text("modified content\n")

            result = await git_diff(
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            # Should show diff
            metadata = result.get("metadata", {})
            assert metadata.get("files_changed", 0) >= 1

    @pytest.mark.asyncio
    async def test_git_diff_with_file(self):
        """Test getting git diff for a specific file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("original\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmpdir, capture_output=True)

            test_file.write_text("modified\n")

            result = await git_diff(
                file_path="test.txt",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_git_diff_with_context_lines(self):
        """Test git diff with custom context lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("line1\nline2\nline3\nline4\nline5\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmpdir, capture_output=True)

            test_file.write_text("line1\nline2-modified\nline3\nline4\nline5\n")

            result = await git_diff(
                context_lines=3,
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_git_diff_no_changes(self):
        """Test git diff when there are no changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmpdir, capture_output=True)

            result = await git_diff(
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            # No files changed
            assert metadata.get("files_changed", 0) == 0


class TestGitLog:
    """Test suite for git_log tool."""

    @pytest.mark.asyncio
    async def test_git_log_default(self):
        """Test getting git log with default parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            # Create some commits
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content1\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "First commit"], cwd=tmpdir, capture_output=True)

            test_file.write_text("content2\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Second commit"], cwd=tmpdir, capture_output=True)

            result = await git_log(
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("commit_count", 0) >= 2

    @pytest.mark.asyncio
    async def test_git_log_with_limit(self):
        """Test git log with commit limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            test_file = Path(tmpdir) / "test.txt"
            for i in range(5):
                test_file.write_text(f"content{i}\n")
                subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
                subprocess.run(["git", "commit", "-m", f"Commit {i}"], cwd=tmpdir, capture_output=True)

            result = await git_log(
                max_count=3,
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            # Should return at most 3 commits
            assert metadata.get("commit_count", 0) <= 3

    @pytest.mark.asyncio
    async def test_git_log_with_file(self):
        """Test git log for a specific file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("v1\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Commit 1"], cwd=tmpdir, capture_output=True)

            other_file = Path(tmpdir) / "other.txt"
            other_file.write_text("other\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Commit 2"], cwd=tmpdir, capture_output=True)

            result = await git_log(
                file_path="test.txt",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            # Should only have history for test.txt

    @pytest.mark.asyncio
    async def test_git_log_no_commits(self):
        """Test git log in a repo with no commits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)

            result = await git_log(
                _workspace_dir=tmpdir,
            )

            # Should not error, just return empty
            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("commit_count", 0) == 0


class TestGenerateCommit:
    """Test suite for generate_commit tool."""

    @pytest.mark.asyncio
    async def test_generate_commit_message(self):
        """Test generating a commit message from diff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            # Create initial commit
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("original\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmpdir, capture_output=True)

            # Make a change
            test_file.write_text("modified content\n")

            result = await generate_commit(
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert "commit_message" in metadata
            assert metadata["commit_message"]

    @pytest.mark.asyncio
    async def test_generate_commit_with_custom_message(self):
        """Test generating commit with a custom message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("original\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmpdir, capture_output=True)

            test_file.write_text("modified\n")

            result = await generate_commit(
                message="Custom commit message",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("commit_message") == "Custom commit message"

    @pytest.mark.asyncio
    async def test_generate_commit_auto_add(self):
        """Test generating commit with auto_add enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("new file\n")
            # Don't stage the file

            result = await generate_commit(
                auto_add=True,
                message="Add new file",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            # Check that the commit was made
            result_log = subprocess.run(
                ["git", "log", "-1", "--pretty=%s"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
            )
            assert "Add new file" in result_log.stdout

    @pytest.mark.asyncio
    async def test_generate_commit_dry_run(self):
        """Test generating commit in dry-run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("original\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmpdir, capture_output=True)

            test_file.write_text("modified\n")

            result = await generate_commit(
                dry_run=True,
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("dry_run") is True
            # No commit should have been made
            result_log = subprocess.run(
                ["git", "log", "--oneline"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
            )
            # Should still have only 1 commit (the initial one)
            assert result_log.stdout.strip().count("\n") == 0  # Only one line = one commit


class TestGitToolsIntegration:
    """Integration tests for git tools."""

    @pytest.mark.asyncio
    async def test_full_git_workflow(self):
        """Test complete workflow: diff -> log -> commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            # Initial commit
            test_file = Path(tmpdir) / "feature.py"
            test_file.write_text('def old_function():\n    return "old"\n')
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmpdir, capture_output=True)

            # Step 1: Check log
            log_result = await git_log(_workspace_dir=tmpdir)
            assert not log_result.get("isError")

            # Step 2: Make changes and check diff
            test_file.write_text('def new_function():\n    return "new"\n')
            diff_result = await git_diff(_workspace_dir=tmpdir)
            assert not diff_result.get("isError")

            # Step 3: Generate and apply commit
            commit_result = await generate_commit(
                message="Refactor: Rename function",
                auto_add=True,
                _workspace_dir=tmpdir,
            )
            assert not commit_result.get("isError")

            # Verify the commit
            final_log = await git_log(max_count=1, _workspace_dir=tmpdir)
            assert not final_log.get("isError")
