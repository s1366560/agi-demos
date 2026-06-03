from pathlib import Path

import pytest

from memstack_agent_evals.harness.isolation import (
    assert_no_forbidden_imports,
    find_forbidden_imports,
)


def test_current_eval_package_has_no_forbidden_imports() -> None:
    assert_no_forbidden_imports(Path("memstack_agent_evals"))


def test_detects_forbidden_imports(tmp_path: Path) -> None:
    module = tmp_path / "bad.py"
    module.write_text("from src.infrastructure import something\n", encoding="utf-8")

    violations = find_forbidden_imports(tmp_path)

    assert len(violations) == 1
    assert "imports src" in violations[0]
    with pytest.raises(AssertionError):
        assert_no_forbidden_imports(tmp_path)
