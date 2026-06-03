import subprocess
from pathlib import Path

from memstack_agent_evals.harness.workspace import git_diff_summary, has_patch, prepare_workspace


def test_prepare_workspace_clones_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "eval@example.com"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Eval"], cwd=source, check=True)
    (source / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=source, check=True, stdout=subprocess.PIPE)

    workspace = prepare_workspace(
        target_repo=source, destination_root=tmp_path / "runs", case_id="c1"
    )
    (workspace / "README.md").write_text("changed\n", encoding="utf-8")

    assert workspace != source
    assert (source / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert has_patch(workspace)
    assert "README.md" in git_diff_summary(workspace)
