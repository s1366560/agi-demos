import importlib.util
from pathlib import Path

import pytest

from memstack_agent_evals.models import EvaluationCase
from memstack_agent_evals.runners.mini_runner import MiniSweAgentRunner


def test_mini_runner_dry_run_builds_command(tmp_path: Path) -> None:
    case = EvaluationCase(
        id="case-1",
        category="bug_fix",
        prompt="Fix the bug",
        verification_command="pytest",
        target_repo=tmp_path,
    )
    runner = MiniSweAgentRunner(model="openai/gpt-test", config=Path("mini.yaml"))

    result = runner.run(case, workspace=tmp_path, output_dir=tmp_path / "reports", dry_run=True)

    assert result.dry_run is True
    assert result.planned_command is not None
    assert result.planned_command.argv[:3] == ["mini", "--task", "Fix the bug"]
    assert "--model" in result.planned_command.argv
    assert "--config" in result.planned_command.argv


def test_mini_runner_deterministic_case_completes_round(tmp_path: Path) -> None:
    if importlib.util.find_spec("minisweagent") is None:
        pytest.skip("mini-swe-agent is not installed in this Python environment")

    (tmp_path / "calculator.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a - b\n",
        encoding="utf-8",
    )
    case = EvaluationCase(
        id="case-1",
        category="failing_test_repair",
        prompt="Fix add",
        verification_command=(
            "python3 - <<'PY'\n"
            "import importlib.util\n"
            "from pathlib import Path\n"
            "spec = importlib.util.spec_from_file_location('calculator', Path('calculator.py'))\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "assert spec.loader is not None\n"
            "spec.loader.exec_module(module)\n"
            "assert module.add(2, 3) == 5\n"
            "PY\n"
        ),
        target_repo=tmp_path,
        expected_files=["calculator.py"],
        deterministic_commands=[
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "path = Path('calculator.py')\n"
            "path.write_text(path.read_text().replace('return a - b', 'return a + b'))\n"
            "PY\n"
        ],
    )
    runner = MiniSweAgentRunner()

    result = runner.run(case, workspace=tmp_path, output_dir=tmp_path / "reports")

    assert result.resolved is True
    assert result.patch_applied is True
    assert result.failure_reason is None
    assert "return a + b" in (tmp_path / "calculator.py").read_text(encoding="utf-8")
    assert result.trajectory_path is not None
    assert result.trajectory_path.exists()
