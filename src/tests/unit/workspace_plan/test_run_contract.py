from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.agent.workspace_plan.run_contract import WorkspaceRunContract


@pytest.mark.unit
def test_run_contract_merges_metadata_and_workflow_overrides() -> None:
    contract = WorkspaceRunContract.from_sources(
        workspace_metadata={
            "workspace_run_contract": {
                "concurrency": 2,
                "max_iterations": 12,
                "workspace_root": "/workspace",
            }
        },
        root_metadata={"run_contract": {"max_retries": 1}},
        workflow_text="""
        # Workspace Run Contract
        concurrency: 3
        stall_timeout_seconds: 120
        """,
    )

    assert contract.concurrency == 3
    assert contract.max_iterations == 12
    assert contract.max_retries == 1
    assert contract.stall_timeout_seconds == 120
    assert contract.workspace_root == "/workspace"


@pytest.mark.unit
def test_run_contract_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        WorkspaceRunContract.from_mapping({"concurrency": 0})

    with pytest.raises(ValueError, match="workspace_root"):
        WorkspaceRunContract.from_mapping({"workspace_root": "../escape"})


@pytest.mark.unit
def test_validate_paths_allows_code_root_and_worktree_inside_workspace_root() -> None:
    contract = WorkspaceRunContract.from_mapping({"workspace_root": "/workspace"})

    result = contract.validate_paths(
        code_root="/workspace/repo",
        worktree_path="/workspace/.memstack/worktrees/attempt-1",
    )

    assert result.allowed is True
    assert result.workspace_root == "/workspace"
    assert result.code_root == "/workspace/repo"
    assert result.worktree_path == "/workspace/.memstack/worktrees/attempt-1"


@pytest.mark.unit
def test_validate_paths_rejects_traversal_outside_workspace_root() -> None:
    contract = WorkspaceRunContract.from_mapping({"workspace_root": "/workspace"})

    result = contract.validate_paths(
        code_root="/workspace/repo",
        worktree_path="/workspace/repo/../../etc",
    )

    assert result.allowed is False
    assert result.reason == "worktree_path is outside workspace_root"


@pytest.mark.unit
def test_validate_paths_defaults_workspace_root_to_code_root_parent() -> None:
    contract = WorkspaceRunContract.from_mapping({})

    result = contract.validate_paths(
        code_root="/workspace/repo",
        worktree_path="/workspace/.memstack/worktrees/attempt-1",
    )

    assert result.allowed is True
    assert result.workspace_root == "/workspace"


@pytest.mark.unit
def test_validate_paths_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    repo = workspace_root / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = workspace_root / "escaped"
    escaped.symlink_to(outside)
    contract = WorkspaceRunContract.from_mapping({"workspace_root": str(workspace_root)})

    result = contract.validate_paths(
        code_root=str(repo),
        worktree_path=str(escaped / "attempt-1"),
    )

    assert result.allowed is False
    assert result.reason == "worktree_path is outside workspace_root"


@pytest.mark.unit
def test_validate_paths_rejects_root_equal_to_workspace() -> None:
    contract = WorkspaceRunContract.from_mapping({"workspace_root": "/workspace"})

    result = contract.validate_paths(
        code_root="/workspace",
        worktree_path="/workspace/.memstack/worktrees/attempt-1",
    )

    assert result.allowed is False
    assert result.reason == "code_root cannot equal workspace_root"
