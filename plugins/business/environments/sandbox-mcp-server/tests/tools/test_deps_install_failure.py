"""Install failures distinguish an unwritable sandbox from a missing package."""

import os
import stat
import tempfile
from pathlib import Path

from src.tools.deps_tools import classify_install_failure


def test_permission_denied_is_an_environment_limit() -> None:
    message = classify_install_failure(
        "Permission denied: [Errno 13] /opt/sandbox-mcp-venv/lib/python3.12/site-packages"
    )
    assert message.startswith("environment_not_writable:")
    assert "Errno 13" in message


def test_other_install_failures_stay_verbatim() -> None:
    assert classify_install_failure("No matching distribution") == "No matching distribution"


def test_real_unwritable_directory_is_classified_without_changing_permissions() -> None:
    with tempfile.TemporaryDirectory(prefix="selftest-install-") as raw:
        target = Path(raw) / "venv"
        target.mkdir()
        target.chmod(stat.S_IREAD | stat.S_IEXEC)
        try:
            (target / "blocked.txt").write_text("nope", encoding="utf-8")
            observed = ""
        except OSError as exc:
            observed = str(exc)
        finally:
            os.chmod(target, stat.S_IRWXU)
    assert "Permission denied" in observed or "Errno 13" in observed
    assert classify_install_failure(observed).startswith("environment_not_writable:")
