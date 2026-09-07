from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.unit
def test_agent_runtime_import_dependencies_are_required() -> None:
    project = tomllib.loads((_REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = {Requirement(value).name for value in project["project"]["dependencies"]}

    assert {"numpy", "rfc8785", "wasmtime"} <= dependencies


@pytest.mark.unit
@pytest.mark.parametrize("install_status", [0, 17])
@pytest.mark.parametrize(
    ("compose_file", "service_name", "entrypoint"),
    [
        ("docker-compose.agent-actor.yml", "agent-actor-worker", "python"),
        ("docker-compose.ray.override.yml", "ray-head", "ray"),
        ("docker-compose.ray.override.yml", "ray-worker", "ray"),
    ],
)
def test_actor_startup_requires_successful_dependency_install(
    tmp_path: Path, install_status: int, compose_file: str, service_name: str, entrypoint: str
) -> None:
    compose = yaml.safe_load((_REPOSITORY_ROOT / compose_file).read_text(encoding="utf-8"))
    for name, script in {
        "uv": '#!/bin/sh\nprintf "%s\\n" "$*" > "$INSTALL_TRACE"\nexit "$INSTALL_STATUS"\n',
        entrypoint: '#!/bin/sh\nprintf "%s\\n" "$*" > "$WORKER_TRACE"\n',
    }.items():
        executable = tmp_path / name
        executable.write_text(script, encoding="utf-8")
        executable.chmod(0o700)

    install_trace = tmp_path / "install.trace"
    worker_trace = tmp_path / "worker.trace"
    result = subprocess.run(
        compose["services"][service_name]["command"],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "INSTALL_STATUS": str(install_status),
            "INSTALL_TRACE": str(install_trace),
            "WORKER_TRACE": str(worker_trace),
        },
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == install_status, result.stderr
    assert install_trace.read_text().strip() == "pip install --system -r /app/pyproject.toml"
    if install_status == 0:
        started_command = worker_trace.read_text().strip()
        if entrypoint == "python":
            assert started_command == "-m src.agent_actor_worker"
        else:
            assert started_command.startswith("start ")
    else:
        assert not worker_trace.exists()
