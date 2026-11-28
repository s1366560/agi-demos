"""Commands must not execute in a missing or detached workspace directory."""

import os
import sys
from pathlib import Path

import pytest

from src.tools.bash_tool import execute_bash


@pytest.mark.asyncio
async def test_missing_workspace_fails_without_creation_or_fallback(tmp_path: Path) -> None:
    workspace = tmp_path / "missing"
    result = await execute_bash(command="printf SHOULD_NOT_RUN", _workspace_dir=str(workspace))
    assert result["isError"] is True
    assert "unavailable" in result["content"][0]["text"]
    assert "SHOULD_NOT_RUN" not in result["content"][0]["text"]
    assert "working_dir" not in result.get("metadata", {})
    assert not workspace.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="detached cwd requires Linux procfs")
@pytest.mark.asyncio
async def test_detached_directory_fails_before_user_command(tmp_path: Path) -> None:
    directory = tmp_path / "detached"
    directory.mkdir()
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        directory.rmdir()
        # The directory is reachable through the parent's open fd, but getcwd
        # inside it fails. This models a detached workspace bind mount.
        workspace = f"/proc/{os.getpid()}/fd/{descriptor}"
        assert os.path.isdir(workspace)
        result = await execute_bash(command="printf SHOULD_NOT_RUN", _workspace_dir=workspace)
        assert result["isError"] is True
        assert "cannot be resolved" in result["content"][0]["text"]
        assert "SHOULD_NOT_RUN" not in result["content"][0]["text"]
        assert "working_dir" not in result.get("metadata", {})
    finally:
        os.close(descriptor)
