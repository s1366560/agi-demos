"""Temporary workspace preparation for black-box agent runs."""

from __future__ import annotations

import shutil
from pathlib import Path

from memstack_agent_evals.subprocess_utils import run_command


def prepare_workspace(
    *,
    target_repo: Path,
    destination_root: Path,
    case_id: str,
    repo_ref: str | None = None,
) -> Path:
    """Create an isolated git clone or source copy for one eval case."""
    if not target_repo.exists():
        raise FileNotFoundError(f"Target repo does not exist: {target_repo}")
    destination_root = destination_root.resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    workspace = destination_root / case_id
    if workspace.exists():
        shutil.rmtree(workspace)

    if (target_repo / ".git").exists():
        result = run_command(
            ["git", "clone", "--local", "--no-hardlinks", str(target_repo), str(workspace)],
            cwd=destination_root,
            timeout_sec=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr.strip()}")
        if repo_ref:
            checkout = run_command(["git", "checkout", repo_ref], cwd=workspace, timeout_sec=120)
            if checkout.returncode != 0:
                raise RuntimeError(f"git checkout failed: {checkout.stderr.strip()}")
    else:
        shutil.copytree(
            target_repo, workspace, ignore=shutil.ignore_patterns("__pycache__", ".venv")
        )
    return workspace.resolve()


def git_diff_summary(workspace: Path) -> str:
    """Return a compact diff summary for a workspace."""
    if not (workspace / ".git").exists():
        return ""
    result = run_command(["git", "diff", "--stat"], cwd=workspace, timeout_sec=120)
    return result.stdout.strip() if result.returncode == 0 else ""


def has_patch(workspace: Path) -> bool:
    """Return whether the workspace has tracked file modifications."""
    if not (workspace / ".git").exists():
        return False
    result = run_command(["git", "status", "--porcelain"], cwd=workspace, timeout_sec=120)
    return bool(result.stdout.strip()) if result.returncode == 0 else False
