"""Tests for git tools using TDD methodology.

TDD Cycle:
1. RED - Write failing test
2. GREEN - Implement minimal code to pass
3. REFACTOR - Improve while keeping tests passing
"""

import tempfile
from pathlib import Path

import pytest

from src.tools.git_tools import (
    generate_commit,
    git_diff,
    git_log,
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
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

            # Create a file and commit it
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("original content\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"], cwd=tmpdir, capture_output=True
            )

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
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

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
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

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
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

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

    @pytest.mark.asyncio
    async def test_git_diff_uses_nested_working_dir(self):
        """git_diff should inspect a git repo below the workspace root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess

            repo_dir = Path(tmpdir) / "my-evo"
            repo_dir.mkdir()
            subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=repo_dir, capture_output=True
            )

            test_file = repo_dir / "test.txt"
            test_file.write_text("original\n")
            subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_dir, capture_output=True)
            test_file.write_text("modified\n")

            result = await git_diff(
                repo_path="my-evo",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("in_git_repo") is True
            assert metadata.get("files_changed") == 1


class TestGitLog:
    """Test suite for git_log tool."""

    @pytest.mark.asyncio
    async def test_git_log_default(self):
        """Test getting git log with default parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess

            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

            # Create some commits
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content1\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "First commit"], cwd=tmpdir, capture_output=True)

            test_file.write_text("content2\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Second commit"], cwd=tmpdir, capture_output=True
            )

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
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

            test_file = Path(tmpdir) / "test.txt"
            for i in range(5):
                test_file.write_text(f"content{i}\n")
                subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
                subprocess.run(
                    ["git", "commit", "-m", f"Commit {i}"], cwd=tmpdir, capture_output=True
                )

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
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

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

    @pytest.mark.asyncio
    async def test_git_log_uses_nested_working_dir(self):
        """git_log should inspect a git repo below the workspace root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess

            repo_dir = Path(tmpdir) / "my-evo"
            repo_dir.mkdir()
            subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=repo_dir, capture_output=True
            )

            test_file = repo_dir / "test.txt"
            test_file.write_text("content\n")
            subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Nested commit"], cwd=repo_dir, capture_output=True
            )

            result = await git_log(
                max_count=1,
                working_dir="my-evo",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("in_git_repo") is True
            assert metadata.get("commit_count") == 1
            assert metadata["commits"][0]["message"] == "Nested commit"

    @pytest.mark.asyncio
    async def test_git_log_file_path_is_relative_to_working_dir(self):
        """A nested repo file is not looked up from the workspace root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess

            repo_dir = Path(tmpdir) / "temp" / "r10" / "gitrepo"
            source = repo_dir / "src"
            source.mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=repo_dir, capture_output=True
            )
            calc = source / "calc.py"
            calc.write_text("def add(a, b):\n    return a + b\n")
            subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "add calc"], cwd=repo_dir, capture_output=True)

            relative = await git_log(
                file_path="src/calc.py",
                working_dir="temp/r10/gitrepo",
                _workspace_dir=tmpdir,
            )
            absolute = await git_log(
                file_path=str(calc),
                working_dir="temp/r10/gitrepo",
                _workspace_dir=tmpdir,
            )
            outside = await git_log(
                file_path="../outside.py",
                working_dir="temp/r10/gitrepo",
                _workspace_dir=tmpdir,
            )

            assert relative.get("isError") is False
            assert relative["metadata"]["commit_count"] == 1
            assert absolute.get("isError") is False
            assert absolute["metadata"]["commit_count"] == 1
            assert outside.get("isError") is True


class TestGenerateCommit:
    """Test suite for generate_commit tool."""

    @pytest.mark.asyncio
    async def test_generate_commit_message(self):
        """Test generating a commit message from diff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess

            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

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
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

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
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

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
    async def test_generate_commit_non_repo_is_structured_error_and_does_not_write(self):
        """A non-repository dry run reports the cause and does not create a repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "notes.txt").write_text("not a repo\n")

            result = await generate_commit(
                message="test message",
                auto_add=False,
                dry_run=True,
                _workspace_dir=tmpdir,
            )

            assert result.get("isError") is True
            assert result.get("code") == "not_a_git_repository"
            hint = result.get("hint", "")
            assert "working_dir" in hint
            assert "repo_path" in hint
            assert "workspace-relative" in hint
            assert not (workspace / ".git").exists()
            assert result["metadata"]["in_git_repo"] is False
            assert result["metadata"]["requested_repo"] == "."

    @pytest.mark.asyncio
    async def test_generate_commit_dry_run(self):
        """Test generating commit in dry-run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess

            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

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

    @pytest.mark.asyncio
    async def test_generate_commit_uses_nested_working_dir(self):
        """generate_commit must honor working_dir instead of the workspace root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess

            workspace = Path(tmpdir)
            (workspace / "root.txt").write_text("workspace root is not a repo\n")
            repo_dir = workspace / "my-evo"
            repo_dir.mkdir()
            subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_dir,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_dir,
                capture_output=True,
                check=True,
            )
            (repo_dir / "tracked.txt").write_text("original\n")
            subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial nested"],
                cwd=repo_dir,
                capture_output=True,
                check=True,
            )
            (repo_dir / "tracked.txt").write_text("modified in nested repo\n")

            result = await generate_commit(
                message="Update nested file",
                auto_add=True,
                working_dir="my-evo",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("in_git_repo") is True
            assert metadata.get("committed") is True
            assert Path(metadata["working_dir"]).resolve() == repo_dir.resolve()
            log = subprocess.run(
                ["git", "log", "-1", "--pretty=%s"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            assert log.stdout.strip() == "Update nested file"

    @pytest.mark.asyncio
    async def test_generate_commit_uses_repo_path_alias(self):
        """repo_path is accepted as an alias for working_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess

            repo_dir = Path(tmpdir) / "alias-repo"
            repo_dir.mkdir()
            subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_dir,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_dir,
                capture_output=True,
                check=True,
            )
            (repo_dir / "file.txt").write_text("v1\n")
            subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"],
                cwd=repo_dir,
                capture_output=True,
                check=True,
            )
            (repo_dir / "file.txt").write_text("v2\n")

            result = await generate_commit(
                auto_add=True,
                dry_run=True,
                repo_path="alias-repo",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("in_git_repo") is True
            assert metadata.get("dry_run") is True
            assert Path(metadata["working_dir"]).resolve() == repo_dir.resolve()

    @pytest.mark.asyncio
    async def test_generate_commit_rejects_path_escape(self, tmp_path):
        """working_dir must stay inside the workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = await generate_commit(
            working_dir="../outside",
            _workspace_dir=str(workspace),
        )
        assert result.get("isError") is True


class TestGitToolsIntegration:
    """Integration tests for git tools."""

    @pytest.mark.asyncio
    async def test_full_git_workflow(self):
        """Test complete workflow: diff -> log -> commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess

            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True
            )

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
