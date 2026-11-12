from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_START_RUNTIME = _REPOSITORY_ROOT / "docker" / "ray" / "start-runtime.py"
_RUNTIME_ENTRYPOINT = ["python", "/usr/local/libexec/memstack-ray/start-runtime.py", "--"]


@pytest.mark.unit
def test_agent_runtime_import_dependencies_are_required() -> None:
    project = tomllib.loads((_REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = {Requirement(value).name for value in project["project"]["dependencies"]}

    assert {"numpy", "rfc8785", "wasmtime"} <= dependencies


def _service(base_file: str, service_name: str, override_file: str | None) -> dict[str, object]:
    base = yaml.safe_load((_REPOSITORY_ROOT / base_file).read_text(encoding="utf-8"))
    service = dict(base["services"][service_name])
    if override_file is not None:
        override = yaml.safe_load((_REPOSITORY_ROOT / override_file).read_text(encoding="utf-8"))
        service.update(override["services"][service_name])
    return service


def _command_argv(command: object) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    if isinstance(command, list) and all(isinstance(item, str) for item in command):
        return list(command)
    raise AssertionError(f"compose command must be a string or string list, got {command!r}")


def _write_lock_pair(root: Path, marker: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(f"[project]\nname = {marker!r}\n", encoding="utf-8")
    (root / "uv.lock").write_text(f"marker = {marker!r}\n", encoding="utf-8")


@pytest.mark.unit
@pytest.mark.parametrize("dependencies_match", [True, False])
@pytest.mark.parametrize(
    ("base_file", "override_file", "service_name", "executable_name"),
    [
        ("docker-compose.agent-actor.yml", None, "agent-actor-worker", "python"),
        ("docker-compose.ray.yml", "docker-compose.ray.override.yml", "ray-head", "ray"),
        ("docker-compose.ray.yml", "docker-compose.ray.override.yml", "ray-worker", "ray"),
    ],
)
def test_actor_startup_requires_successful_dependency_install(
    tmp_path: Path,
    dependencies_match: bool,
    base_file: str,
    override_file: str | None,
    service_name: str,
    executable_name: str,
) -> None:
    """Startup refuses a drifted image and never installs dependencies itself."""
    service = _service(base_file, service_name, override_file)
    assert service["entrypoint"] == _RUNTIME_ENTRYPOINT
    command = _command_argv(service["command"])
    assert command[0] == executable_name

    executable = tmp_path / executable_name
    executable.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" > "$WORKER_TRACE"\n',
        encoding="utf-8",
    )
    executable.chmod(0o700)
    project = tmp_path / "project"
    installed = tmp_path / "installed"
    _write_lock_pair(project, "current")
    _write_lock_pair(installed, "current" if dependencies_match else "stale")
    worker_trace = tmp_path / "worker.trace"
    result = subprocess.run(
        [
            sys.executable,
            str(_START_RUNTIME),
            "--project-root",
            str(project),
            "--installed-root",
            str(installed),
            "--",
            *command,
        ],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "WORKER_TRACE": str(worker_trace),
        },
        capture_output=True,
        check=False,
        timeout=10,
    )

    if dependencies_match:
        assert result.returncode == 0, result.stderr
        assert worker_trace.read_text(encoding="utf-8").split() == command[1:]
    else:
        assert result.returncode == 78, result.stderr
        assert b"rebuild the Ray image" in result.stderr
        assert not worker_trace.exists()
