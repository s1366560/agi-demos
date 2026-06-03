from pathlib import Path

from memstack_agent_evals.harness.verify import run_verification


def test_run_verification_executes_in_workspace(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("ok\n", encoding="utf-8")

    result = run_verification(workspace=tmp_path, command="test -f marker.txt")

    assert result.returncode == 0
