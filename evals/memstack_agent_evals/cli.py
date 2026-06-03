"""Command line interface for the eval harness."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import yaml
import typer
from rich.console import Console

from memstack_agent_evals.cases import load_case
from memstack_agent_evals.harness.isolation import assert_no_forbidden_imports
from memstack_agent_evals.harness.results import append_result, write_json
from memstack_agent_evals.harness.workspace import prepare_workspace
from memstack_agent_evals.runners.memstack_runner import MemStackBlackBoxRunner
from memstack_agent_evals.runners.mini_runner import MiniSweAgentRunner

app = typer.Typer(help="Run independent MemStack agent evaluations.")
console = Console()


@app.command()
def run(
    case_file: Annotated[Path, typer.Argument(help="Path to a JSON/YAML evaluation case.")],
    runner: Annotated[str, typer.Option(help="Runner to use: mini or memstack.")] = "mini",
    output_dir: Annotated[Path, typer.Option(help="Directory for reports and logs.")] = Path(
        "reports"
    ),
    workspace_root: Annotated[
        Path | None,
        typer.Option(help="Temporary workspace root. Defaults to a new temp directory."),
    ] = None,
    model: Annotated[str | None, typer.Option(help="mini-swe-agent model name.")] = None,
    config: Annotated[Path | None, typer.Option(help="mini-swe-agent config file.")] = None,
    dry_run: Annotated[bool, typer.Option(help="Prepare workspace and show command only.")] = False,
) -> None:
    """Run one evaluation case."""
    project_root = Path(__file__).resolve().parents[1]
    assert_no_forbidden_imports(project_root)

    case = load_case(case_file)
    with tempfile.TemporaryDirectory(prefix="memstack-agent-evals-") as tmp:
        root = (workspace_root or Path(tmp)).resolve()
        workspace = prepare_workspace(
            target_repo=case.target_repo,
            destination_root=root,
            case_id=case.id,
            repo_ref=case.repo_ref,
        )
        agent_runner = _select_runner(runner=runner, model=model, config=config)
        result = agent_runner.run(
            case,
            workspace=workspace,
            output_dir=output_dir.resolve(),
            dry_run=dry_run,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    append_result(output_dir / "results.jsonl", result)
    write_json(output_dir / f"{case.id}.{runner}.json", result.model_dump(mode="json"))
    console.print(result.model_dump_json(indent=2))


@app.command("run-dataset")
def run_dataset(
    dataset_file: Annotated[Path, typer.Argument(help="Path to a YAML dataset manifest.")],
    runner: Annotated[str, typer.Option(help="Runner to use: mini or memstack.")] = "mini",
    output_dir: Annotated[Path, typer.Option(help="Directory for reports and logs.")] = Path(
        "reports"
    ),
    workspace_root: Annotated[
        Path | None,
        typer.Option(help="Workspace root. Defaults to output_dir/workspaces."),
    ] = None,
    model: Annotated[str | None, typer.Option(help="mini-swe-agent model name.")] = None,
    config: Annotated[Path | None, typer.Option(help="mini-swe-agent config file.")] = None,
    dry_run: Annotated[
        bool, typer.Option(help="Prepare workspaces and show commands only.")
    ] = False,
) -> None:
    """Run every case in a dataset manifest."""
    project_root = Path(__file__).resolve().parents[1]
    assert_no_forbidden_imports(project_root)

    output_dir = output_dir.resolve()
    workspace_root = (workspace_root or output_dir / "workspaces").resolve()
    case_files = _load_dataset_cases(dataset_file)
    agent_runner = _select_runner(runner=runner, model=model, config=config)

    results = []
    for case_file in case_files:
        case = load_case(case_file)
        workspace = prepare_workspace(
            target_repo=case.target_repo,
            destination_root=workspace_root,
            case_id=case.id,
            repo_ref=case.repo_ref,
        )
        result = agent_runner.run(
            case,
            workspace=workspace,
            output_dir=output_dir,
            dry_run=dry_run,
        )
        append_result(output_dir / "results.jsonl", result)
        write_json(output_dir / f"{case.id}.{runner}.json", result.model_dump(mode="json"))
        results.append(result)

    summary = {
        "dataset": str(dataset_file),
        "runner": runner,
        "total": len(results),
        "resolved": sum(1 for result in results if result.resolved),
        "patch_applied": sum(1 for result in results if result.patch_applied),
        "failures": [
            {"case_id": result.case_id, "failure_reason": result.failure_reason}
            for result in results
            if not result.resolved
        ],
        "cases": [result.model_dump(mode="json") for result in results],
    }
    write_json(output_dir / "summary.json", summary)
    console.print_json(data=summary)


@app.command("check-isolation")
def check_isolation() -> None:
    """Validate that eval code does not import application internals."""
    project_root = Path(__file__).resolve().parents[1]
    assert_no_forbidden_imports(project_root)
    console.print("[green]No forbidden imports found.[/green]")


def _select_runner(
    *,
    runner: str,
    model: str | None,
    config: Path | None,
) -> MiniSweAgentRunner | MemStackBlackBoxRunner:
    if runner == "mini":
        return MiniSweAgentRunner(model=model, config=config)
    if runner == "memstack":
        return MemStackBlackBoxRunner()
    raise typer.BadParameter("runner must be 'mini' or 'memstack'")


def _load_dataset_cases(dataset_file: Path) -> list[Path]:
    data = yaml.safe_load(dataset_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise typer.BadParameter("dataset file must contain a 'cases' list")
    case_files = []
    for item in data["cases"]:
        if not isinstance(item, str) or not item.strip():
            raise typer.BadParameter("dataset cases must be non-empty paths")
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = (dataset_file.parent / path).resolve()
        case_files.append(path)
    return case_files


if __name__ == "__main__":
    app()
