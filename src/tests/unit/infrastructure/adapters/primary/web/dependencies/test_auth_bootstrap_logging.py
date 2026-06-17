"""Security regressions for auth bootstrap logging."""

import ast
from pathlib import Path

LOGGER_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _logger_calls(path: str) -> list[str]:
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))

    calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in LOGGER_METHODS:
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
            continue
        calls.append(ast.get_source_segment(source, node) or ast.unparse(node))

    return calls


def test_auth_bootstrap_logs_do_not_expose_seed_secret_values() -> None:
    calls = "\n".join(
        _logger_calls("src/infrastructure/adapters/primary/web/dependencies/auth_dependencies.py")
    )

    assert "adminpassword" not in calls
    assert "userpassword" not in calls
    assert "plain_key" not in calls
    assert "plain_user_key" not in calls
    assert "value=<redacted>" in calls


def test_startup_logs_use_bootstrap_wording_instead_of_credentials() -> None:
    calls = "\n".join(
        _logger_calls("src/infrastructure/adapters/primary/web/startup/database.py")
    ).lower()

    assert "default credentials" not in calls
    assert "auth bootstrap data" in calls
