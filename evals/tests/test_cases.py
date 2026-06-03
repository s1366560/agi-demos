from pathlib import Path

from memstack_agent_evals.cases import load_case


def test_load_case_resolves_relative_target_repo() -> None:
    evals_root = Path(__file__).resolve().parents[1]
    case = load_case(evals_root / "cases" / "smoke_toy_repo.yaml")

    assert case.id == "smoke-toy-repo"
    assert case.target_repo.is_absolute()
    assert case.category == "failing_test_repair"
