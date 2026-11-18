"""Fault injection for the production restart recipe, without live services."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
MAKEFILE = ROOT / "Makefile"

pytestmark = pytest.mark.unit


def _override(tmp_path: Path, stop: str | None = None) -> Path:
    log = tmp_path / "order"
    stop_command = stop or f"printf '%s\\n' stop >> {log}"
    path = tmp_path / "Makefile"
    path.write_text(
        "\n".join(
            [
                f"include {MAKEFILE}",
                "dev-prepare:",
                f"\tprintf '%s\\n' prepare >> {log}; exit 9",
                "dev-app-stop:",
                f"\t{stop_command}",
                "dev-app-start:",
                f"\tprintf '%s\\n' start >> {log}",
                "",
            ]
        )
    )
    return log


def test_restart_skips_preparation_and_replaces_only_application_processes(tmp_path: Path):
    log = _override(tmp_path)
    run = subprocess.run(
        ["make", "restart"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert log.read_text().splitlines() == ["stop", "start"]


def test_stop_failure_does_not_start_services(tmp_path: Path):
    log = _override(tmp_path, f"printf '%s\\n' stop >> {tmp_path / 'order'}; exit 9")
    run = subprocess.run(
        ["make", "restart"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert run.returncode != 0
    assert log.read_text().splitlines() == ["stop"]


def test_full_start_retains_image_reuse_and_workspace_health():
    text = MAKEFILE.read_text()
    compute = text.split("dev-compute:", 1)[1].split("\n\n", 1)[0]
    assert "$(DEV_BUILD_CMD)" in compute
    assert "--wait" in compute
    core = text.split("workspace-core-start:", 1)[1].split("\n\n", 1)[0]
    assert "workspace-core-health" in core
    assert "dev-all: dev-prepare" in text
    restart = text.split("\nrestart:", 1)[1].split("\n\n", 1)[0]
    assert "dev-prepare" not in restart
    assert restart.index("dev-app-stop") < restart.index("dev-app-start")
