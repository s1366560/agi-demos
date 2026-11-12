"""Install failures distinguish an unwritable sandbox from a missing package."""

from src.tools.deps_tools import classify_install_failure


def test_permission_denied_is_an_environment_limit() -> None:
    message = classify_install_failure(
        "Permission denied: [Errno 13] /opt/sandbox-mcp-venv/lib/python3.12/site-packages"
    )
    assert message.startswith("environment_not_writable:")
    assert "Errno 13" in message


def test_other_install_failures_stay_verbatim() -> None:
    assert classify_install_failure("No matching distribution") == "No matching distribution"
