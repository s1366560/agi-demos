"""Fault injection for the production restart recipe, without live services."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
MAKEFILE = ROOT / "Makefile"

pytestmark = pytest.mark.unit


def test_full_dev_app_start_selects_the_full_web_client(tmp_path: Path):
    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-f",
            str(MAKEFILE),
            "dev-app-start",
            "MEMSTACK_DEV_PROFILE=full",
            "DEV_SERVICES_CMD=echo",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    _, command = result.stdout.strip().split("--web-command ")
    argv = shlex.split(command)
    assert argv[argv.index("--mode") + 1] == "full"


def _override(tmp_path: Path, stop: str | None = None) -> Path:
    log = tmp_path / "order"
    stop_command = stop or f"printf '%s\\n' stop >> {log}"
    path = tmp_path / "Makefile"
    path.write_text(
        "\n".join(
            [
                "MEMSTACK_DEV_PROFILE := full",
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
    restart = text.split("\nrestart-full-apps:", 1)[1].split("\n\n", 1)[0]
    assert "dev-prepare" not in restart
    assert restart.index("dev-app-stop") < restart.index("dev-app-start")
