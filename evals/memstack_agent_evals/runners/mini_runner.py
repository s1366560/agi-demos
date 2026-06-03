"""mini-swe-agent baseline runner."""

from __future__ import annotations

import difflib
from pathlib import Path

from memstack_agent_evals.harness.verify import run_verification
from memstack_agent_evals.harness.workspace import git_diff_summary, has_patch
from memstack_agent_evals.models import EvaluationCase, EvaluationResult, RunnerCommand
from memstack_agent_evals.subprocess_utils import run_command


class MiniSweAgentRunner:
    """Run a case through the mini-swe-agent CLI."""

    name = "mini"

    def __init__(
        self,
        *,
        model: str | None = None,
        config: Path | None = None,
        yolo: bool = True,
        timeout_sec: int = 3600,
    ) -> None:
        self.model = model
        self.config = config
        self.yolo = yolo
        self.timeout_sec = timeout_sec

    def build_command(self, case: EvaluationCase) -> list[str]:
        """Build the mini CLI command for one case."""
        if case.deterministic_commands:
            return [
                "python",
                "-m",
                "minisweagent",
                "DefaultAgent",
                "DeterministicModel",
                f"{len(case.deterministic_commands)} command(s)",
            ]
        command = ["mini", "--task", case.prompt]
        if self.model:
            command.extend(["--model", self.model])
        if self.config:
            command.extend(["--config", str(self.config)])
        if self.yolo:
            command.append("--yolo")
        return command

    def run(
        self,
        case: EvaluationCase,
        *,
        workspace: Path,
        output_dir: Path,
        dry_run: bool = False,
    ) -> EvaluationResult:
        """Run mini-swe-agent and verify the resulting workspace."""
        output_dir.mkdir(parents=True, exist_ok=True)
        command = self.build_command(case)
        planned = RunnerCommand(cwd=workspace, argv=command)
        trajectory_path = output_dir / f"{case.id}.mini.log"
        before_files = _capture_expected_files(workspace, case.expected_files)

        if dry_run:
            return EvaluationResult(
                case_id=case.id,
                runner=self.name,
                resolved=False,
                patch_applied=False,
                verification_command=case.verification_command,
                duration_sec=0.0,
                trajectory_path=trajectory_path,
                diff_summary="",
                workspace_path=workspace,
                dry_run=True,
                planned_command=planned,
            )

        if case.deterministic_commands:
            agent_result = _run_deterministic_mini(
                case=case,
                workspace=workspace,
                trajectory_path=trajectory_path,
            )
        else:
            agent_result = run_command(command, cwd=workspace, timeout_sec=self.timeout_sec)
            trajectory_path.write_text(
                _format_log("mini", agent_result.stdout, agent_result.stderr),
                encoding="utf-8",
            )

        verify_result = run_verification(
            workspace=workspace,
            command=case.verification_command,
            timeout_sec=self.timeout_sec,
        )
        resolved = verify_result.returncode == 0
        failure_reason = None
        if not resolved:
            failure_reason = verify_result.stderr.strip() or verify_result.stdout.strip()
        return EvaluationResult(
            case_id=case.id,
            runner=self.name,
            resolved=resolved,
            patch_applied=has_patch(workspace) or _expected_files_changed(workspace, before_files),
            verification_command=case.verification_command,
            duration_sec=agent_result.duration_sec + verify_result.duration_sec,
            steps=_count_steps(agent_result.stdout),
            trajectory_path=trajectory_path,
            failure_reason=failure_reason,
            diff_summary=git_diff_summary(workspace)
            or _expected_files_diff(workspace, before_files),
            workspace_path=workspace,
            planned_command=planned,
        )


def _run_deterministic_mini(
    *,
    case: EvaluationCase,
    workspace: Path,
    trajectory_path: Path,
):
    """Run mini-swe-agent through its Python API with deterministic outputs."""
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.local import LocalEnvironment
    from minisweagent.models.test_models import DeterministicModel, make_output

    outputs = [
        make_output(
            f"Execute deterministic eval command {index + 1}.",
            [{"command": command}],
            cost=0.0,
        )
        for index, command in enumerate(case.deterministic_commands)
    ]
    outputs.append(
        make_output(
            "Submit final output.",
            [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}],
            cost=0.0,
        )
    )
    model = DeterministicModel(outputs=outputs)
    env = LocalEnvironment(cwd=str(workspace), timeout=600)
    agent = DefaultAgent(
        model,
        env,
        system_template="You are a deterministic mini-swe-agent baseline runner.",
        instance_template="Task: {{task}}",
        step_limit=len(outputs) + 1,
        cost_limit=0,
        output_path=str(trajectory_path),
    )

    import time

    start = time.monotonic()
    run_result = agent.run(case.prompt)
    duration = time.monotonic() - start

    class AgentResult:
        def __init__(self) -> None:
            self.returncode = 0 if run_result.get("exit_status") == "Submitted" else 1
            self.stdout = str(run_result)
            self.stderr = ""
            self.duration_sec = duration

    return AgentResult()


def _format_log(label: str, stdout: str, stderr: str) -> str:
    return f"## {label} stdout\n\n{stdout}\n\n## {label} stderr\n\n{stderr}\n"


def _count_steps(output: str) -> int | None:
    markers = ["Step ", "STEP ", "Thought:", "Action:"]
    count = sum(output.count(marker) for marker in markers)
    return count or None


def _capture_expected_files(workspace: Path, expected_files: list[str]) -> dict[str, str | None]:
    snapshots: dict[str, str | None] = {}
    for name in expected_files:
        path = workspace / name
        snapshots[name] = path.read_text(encoding="utf-8") if path.exists() else None
    return snapshots


def _expected_files_changed(workspace: Path, before_files: dict[str, str | None]) -> bool:
    return any(
        _read_optional_text(workspace / name) != before for name, before in before_files.items()
    )


def _expected_files_diff(workspace: Path, before_files: dict[str, str | None]) -> str:
    chunks: list[str] = []
    for name, before in before_files.items():
        path = workspace / name
        after = _read_optional_text(path)
        if before == after:
            continue
        before_lines = [] if before is None else before.splitlines(keepends=True)
        after_lines = [] if after is None else after.splitlines(keepends=True)
        chunks.extend(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )
    return "".join(chunks).strip()


def _read_optional_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None
