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


@pytest.mark.parametrize(
    ("has_env", "standard_owner", "overrides", "expected"),
    [
        (True, False, [], "full"),
        (False, False, [], "package-host"),
        (True, True, [], "package-host"),
        (True, True, ["MEMSTACK_DEV_PROFILE=full"], "full"),
        (True, False, ["AGISTACK_DESKTOP_PROFILE=package-host"], "package-host"),
        (False, False, ["AGISTACK_DESKTOP_PROFILE=full"], "full"),
        (True, False, ["AGISTACK_LOCAL_PLUGIN_TRUSTED_KEYS_FILE=/operator/trust.json"], "full"),
    ],
)
def test_native_dev_matches_root_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, has_env, standard_owner, overrides, expected
):
    for variable in (
        "MEMSTACK_DEV_PROFILE",
        "AGISTACK_DESKTOP_PROFILE",
        "AGISTACK_DESKTOP_GRANTS_API_BASE",
        "AGISTACK_WEB_CONTROL_PLANE_ORIGIN",
        "AGISTACK_LOCAL_PLUGIN_TRUSTED_KEYS_FILE",
        "STANDARD_DIRECTORY",
    ):
        monkeypatch.delenv(variable, raising=False)
    desktop = tmp_path / "agi-stack"
    desktop.mkdir()
    provisioned = tmp_path / ".cache" / "desktop-dev" / "publisher-trust.json"
    if has_env:
        (tmp_path / ".env").touch()
        provisioned.parent.mkdir(parents=True)
        provisioned.touch()
    if standard_owner:
        standard = tmp_path / ".memstack" / "standard"
        standard.mkdir(parents=True)
        (standard / "owner.json").touch()
    (desktop / "Makefile").write_text(
        "AGISTACK_DESKTOP_FIXED_BUILD := 1\n"
        f"include {ROOT / 'agi-stack' / 'Makefile'}\n"
        "run-desktop:\n"
        '\t@echo "$$AGISTACK_DESKTOP_PROFILE $$AGISTACK_WEB_CONTROL_PLANE_ORIGIN '
        '$$AGISTACK_DESKTOP_GRANTS_API_BASE $$AGISTACK_LOCAL_PLUGIN_TRUSTED_KEYS_FILE"\n'
    )
    result = subprocess.run(
        ["make", "--no-print-directory", "run-desktop", *overrides],
        cwd=desktop,
        check=True,
        capture_output=True,
        text=True,
    )
    expected_values = [expected, "http://localhost:3000", "http://127.0.0.1:8000"]
    if "AGISTACK_LOCAL_PLUGIN_TRUSTED_KEYS_FILE=/operator/trust.json" in overrides:
        expected_values.append("/operator/trust.json")
    elif provisioned.exists():
        expected_values.append(str(provisioned))
    assert result.stdout.strip().split() == expected_values
