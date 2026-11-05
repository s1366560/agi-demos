"""Exercise the container entry point without starting Ray or changing an environment."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "docker/ray/start-runtime.py"


@pytest.fixture
def entry_point():
    spec = importlib.util.spec_from_file_location("ray_runtime_entrypoint", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runtime_fixture(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    installed = tmp_path / "installed"
    project.mkdir()
    installed.mkdir()
    for filename in ["pyproject.toml", "uv.lock"]:
        contents = f"# Neutral {filename} fixture\n".encode()
        (project / filename).write_bytes(contents)
        (installed / filename).write_bytes(contents)
    return project, installed


def run_runtime(project: Path, installed: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--project-root",
            str(project),
            "--installed-root",
            str(installed),
            "--",
            *command,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def test_unchanged_dependencies_exec_exact_arguments_without_resolving(tmp_path: Path) -> None:
    project, installed = runtime_fixture(tmp_path)
    argument = "literal ; $(not-a-shell) --flag=one two"
    result = run_runtime(
        project,
        installed,
        sys.executable,
        "-c",
        "import json,sys; print(json.dumps(sys.argv[1:]))",
        argument,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [argument]
    assert result.stderr == ""


def test_child_exit_status_is_preserved(tmp_path: Path) -> None:
    project, installed = runtime_fixture(tmp_path)
    result = run_runtime(project, installed, sys.executable, "-c", "raise SystemExit(29)")
    assert result.returncode == 29


@pytest.mark.parametrize("filename", ["pyproject.toml", "uv.lock"])
def test_changed_dependency_declaration_blocks_execution(tmp_path: Path, filename: str) -> None:
    project, installed = runtime_fixture(tmp_path)
    marker = tmp_path / "must-not-execute"
    (project / filename).write_text("changed dependency declaration", encoding="utf-8")
    result = run_runtime(
        project,
        installed,
        sys.executable,
        "-c",
        f"from pathlib import Path; Path({str(marker)!r}).touch()",
    )
    assert result.returncode == 78
    assert "dependency configuration changed" in result.stderr
    assert not marker.exists()
    assert "changed dependency declaration" not in result.stderr


@pytest.mark.parametrize("filename", ["pyproject.toml", "uv.lock"])
@pytest.mark.parametrize("side", ["project", "installed"])
def test_missing_dependency_configuration_blocks_execution(
    tmp_path: Path, filename: str, side: str
) -> None:
    project, installed = runtime_fixture(tmp_path)
    (project if side == "project" else installed).joinpath(filename).unlink()
    result = run_runtime(project, installed, sys.executable, "-c", "print('must-not-execute')")
    assert result.returncode == 78
    assert result.stdout == ""
    assert "rebuild" in result.stderr


def test_source_only_change_reuses_installed_dependencies(tmp_path: Path) -> None:
    project, installed = runtime_fixture(tmp_path)
    (project / "source.py").write_text("print('new source')", encoding="utf-8")
    result = run_runtime(project, installed, sys.executable, str(project / "source.py"))
    assert result.returncode == 0
    assert result.stdout == "new source\n"


def test_no_command_is_an_explicit_usage_error(tmp_path: Path) -> None:
    project, installed = runtime_fixture(tmp_path)
    result = run_runtime(project, installed)
    assert result.returncode == 2
    assert "command" in result.stderr


def test_entry_point_replaces_process_instead_of_spawning_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_point
) -> None:
    project, installed = runtime_fixture(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--project-root",
            str(project),
            "--installed-root",
            str(installed),
            "--",
            "ray",
            "start",
            "--head",
        ],
    )

    class ReplacedProcess(Exception):
        pass

    def replace(program: str, arguments: list[str]) -> None:
        assert program == "ray"
        assert arguments == ["ray", "start", "--head"]
        raise ReplacedProcess

    monkeypatch.setattr(entry_point.os, "execvp", replace)
    with pytest.raises(ReplacedProcess):
        entry_point.main()


@pytest.mark.parametrize("missing", [False, True])
def test_entry_point_refuses_stale_or_missing_image_inputs_before_exec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_point, missing: bool
) -> None:
    project, installed = runtime_fixture(tmp_path)
    if missing:
        (installed / "uv.lock").unlink()
    else:
        (project / "uv.lock").write_text("changed", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--project-root",
            str(project),
            "--installed-root",
            str(installed),
            "--",
            "ray",
            "start",
        ],
    )
    assert entry_point.main() == 78


def test_entry_point_requires_an_explicit_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_point
) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    with pytest.raises(SystemExit, match="2"):
        entry_point.main()


def compose_config(tmp_path: Path, development: bool, image: str | None = None) -> dict:
    env_file = tmp_path / "compose.env"
    env_file.write_text("", encoding="utf-8")
    files = ["docker-compose.yml", "docker-compose.ray.yml"]
    if development:
        files.append("docker-compose.ray.override.yml")
    files.append("docker-compose.agent-actor.yml")
    command = ["docker", "compose", "--env-file", str(env_file)]
    for filename in files:
        command.extend(["-f", str(ROOT / filename)])
    environment = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
    if image is not None:
        environment["RAY_RUNTIME_IMAGE"] = image
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert result.returncode == 0, "compose configuration must resolve without starting a container"
    return json.loads(result.stdout)


@pytest.mark.parametrize("development", [False, True])
@pytest.mark.parametrize("image", [None, "neutral-ray-runtime:fixture"])
def test_compose_has_one_build_and_one_shared_runtime_image(
    tmp_path: Path, development: bool, image: str | None
) -> None:
    services = compose_config(tmp_path, development, image)["services"]
    expected = image or "agi-demos-ray-head:latest"
    assert services["ray-head"]["build"]["dockerfile"] == "Dockerfile.ray"
    for name in ["ray-head", "ray-worker", "agent-actor-worker"]:
        assert services[name]["image"] == expected
        assert services[name]["pull_policy"] == "never"
    assert "build" not in services["ray-worker"]
    assert "build" not in services["agent-actor-worker"]


@pytest.mark.parametrize("development", [False, True])
def test_compose_waits_for_gcs_and_starts_actor_without_pip(
    tmp_path: Path, development: bool
) -> None:
    services = compose_config(tmp_path, development)["services"]
    assert services["ray-head"]["healthcheck"]["test"] == [
        "CMD",
        "ray",
        "status",
        "--address=127.0.0.1:6379",
    ]
    assert services["ray-worker"]["depends_on"]["ray-head"]["condition"] == "service_healthy"
    assert (
        services["agent-actor-worker"]["depends_on"]["ray-head"]["condition"] == "service_healthy"
    )
    assert services["agent-actor-worker"]["command"] == [
        "python",
        "-m",
        "src.agent_actor_worker",
    ]
    assert services["agent-actor-worker"]["healthcheck"]["test"] == [
        "CMD",
        "python",
        "/usr/local/libexec/memstack-ray/check-actor-ready.py",
    ]
    for name in ["ray-head", "ray-worker", "agent-actor-worker"]:
        assert "pip install" not in " ".join(services[name]["command"])
    if development:
        for name in ["ray-head", "ray-worker", "agent-actor-worker"]:
            mounts = {item["target"]: item for item in services[name]["volumes"]}
            assert mounts["/app/pyproject.toml"]["read_only"] is True
            assert mounts["/app/uv.lock"]["read_only"] is True
