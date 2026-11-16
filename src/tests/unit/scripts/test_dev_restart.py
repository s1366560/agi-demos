"""Fault injection for the production restart recipe, without live services."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
MAKEFILE = ROOT / "Makefile"

pytestmark = pytest.mark.unit


def _override(tmp_path: Path, prepare: str) -> Path:
    log = tmp_path / "order"
    path = tmp_path / "Makefile"
    path.write_text(
        "\n".join(
            [
                f"include {MAKEFILE}",
                "dev-infra-base db-init db-schema plugin-bundle-upgrade dev-compute workspace-core-start:",
                "\ttrue",
                "dev-prepare:",
                f"\t{prepare}",
                "dev-app-stop:",
                f"\tprintf '%s\\n' stop >> {log}",
                "dev-app-start:",
                f"\tprintf '%s\\n' start >> {log}",
                "",
            ]
        )
    )
    return log


def test_prepare_failure_does_not_stop_or_start_services(tmp_path: Path):
    log = _override(tmp_path, f"printf '%s\\n' prepare >> {tmp_path / 'order'}; exit 9")
    run = subprocess.run(
        ["make", "restart"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert run.returncode != 0
    assert log.read_text().splitlines() == ["prepare"]
    assert "stopped" not in log.read_text()


def test_successful_restart_prepares_before_replacing_services(tmp_path: Path):
    log = _override(tmp_path, f"printf '%s\\n' prepare >> {tmp_path / 'order'}")
    run = subprocess.run(
        ["make", "restart"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert log.read_text().splitlines() == ["prepare", "stop", "start"]


def test_image_reuse_does_not_skip_compose_or_workspace_health():
    text = MAKEFILE.read_text()
    compute = text.split("dev-compute:", 1)[1].split("\n\n", 1)[0]
    assert "$(DEV_BUILD_CMD)" in compute
    assert "--wait" in compute
    core = text.split("workspace-core-start:", 1)[1].split("\n\n", 1)[0]
    assert "workspace-core-health" in core
    restart = text.split("\nrestart:", 1)[1].split("\n\n", 1)[0]
    assert restart.index("dev-prepare") < restart.index("dev-app-stop")
    assert restart.index("dev-app-stop") < restart.index("dev-app-start")
