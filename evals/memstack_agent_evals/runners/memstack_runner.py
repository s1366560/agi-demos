"""Black-box MemStack runner placeholder."""

from __future__ import annotations

from pathlib import Path

from memstack_agent_evals.models import EvaluationCase, EvaluationResult, RunnerCommand


class MemStackBlackBoxRunner:
    """Reserved interface for running MemStack agent evaluations via black-box boundaries."""

    name = "memstack"

    def __init__(self, *, command_template: str | None = None) -> None:
        self.command_template = command_template

    def run(
        self,
        case: EvaluationCase,
        *,
        workspace: Path,
        output_dir: Path,
        dry_run: bool = False,
    ) -> EvaluationResult:
        """Return a planned run until a public MemStack agent entrypoint is selected."""
        output_dir.mkdir(parents=True, exist_ok=True)
        command = self._planned_command(case=case, workspace=workspace)
        return EvaluationResult(
            case_id=case.id,
            runner=self.name,
            resolved=False,
            patch_applied=False,
            verification_command=case.verification_command,
            duration_sec=0.0,
            trajectory_path=output_dir / f"{case.id}.memstack.log",
            failure_reason="MemStack black-box runner is reserved; configure a public CLI/API entrypoint.",
            diff_summary="",
            workspace_path=workspace,
            dry_run=dry_run,
            planned_command=command,
        )

    def _planned_command(self, *, case: EvaluationCase, workspace: Path) -> RunnerCommand:
        if self.command_template:
            rendered = self.command_template.format(
                case_id=case.id,
                prompt=case.prompt,
                workspace=str(workspace),
                verification_command=case.verification_command,
            )
            return RunnerCommand(cwd=workspace, argv=["bash", "-lc", rendered])
        return RunnerCommand(
            cwd=workspace,
            argv=[
                "bash",
                "-lc",
                "echo 'Configure MemStack agent API/CLI runner before execution.'",
            ],
        )
