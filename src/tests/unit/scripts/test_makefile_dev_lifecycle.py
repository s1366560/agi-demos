from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def lifecycle(tmp_path: Path) -> tuple[Path, dict[str, str], list[str]]:
    (tmp_path / "Makefile").write_text((REPO_ROOT / "Makefile").read_text())
    tool = tmp_path / "tool.py"
    tool.write_text(
        """import json, os, pathlib, sys
args=sys.argv[1:]
state=pathlib.Path(os.environ['LIFECYCLE_STATE'])
kind=args.pop(0)
if kind=='uv' and 'initialize_database' in ' '.join(args):
    (state/'schema').touch(); event='schema'
elif kind=='uv' and any('upgrade_root_builtin_bundle' in a for a in args):
    if not (state/'schema').exists(): sys.exit(44)
    event='upgrade'
elif kind=='uv': event='configure'
elif kind=='services': event='services:'+args[0]
elif kind=='wait': event='wait:'+args[args.index('--state')+1]
elif kind=='build': event='build'
else:
    event='compose:'+args[0]
    if args[0]=='exec' and '-lqt' in args: print('memstack')
    if args[0]=='ps': print('{"Health":"healthy"}')
with (state/'trace').open('a') as stream:
    stream.write(json.dumps({'event':event,'args':args})+'\\n')
""",
        encoding="utf-8",
    )
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{tool}" uv "$@"\n')
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "LIFECYCLE_STATE": str(tmp_path),
    }
    compose = f"{sys.executable} {tool} compose"
    args = [
        "make",
        "--no-print-directory",
        "-j4",
        "-f",
        str(tmp_path / "Makefile"),
        f"COMPOSE_CMD={compose}",
        f"COMPOSE_DEV={compose}",
        f"DEV_SERVICES_CMD={sys.executable} {tool} services",
        f"DEV_COMPOSE_WAIT_CMD={sys.executable} {tool} wait",
        f"DEV_BUILD_CMD={sys.executable} {tool} build",
        "DEV_STARTUP_TIMEOUT=2",
    ]
    return tmp_path, env, args


def run_lifecycle(lifecycle: tuple[Path, dict[str, str], list[str]], target: str) -> list[dict]:
    directory, env, command = lifecycle
    result = subprocess.run(
        [*command, target],
        cwd=directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line) for line in (directory / "trace").read_text().splitlines()]


def test_parallel_make_migrates_before_plugin_upgrade_and_application_start(lifecycle) -> None:
    trace = run_lifecycle(lifecycle, "dev")
    events = [row["event"] for row in trace]
    assert events.index("schema") < events.index("upgrade") < events.index("services:start")
    assert any(row["event"] == "compose:up" and "ray-head" in row["args"] for row in trace)
    assert any(
        row["event"] == "compose:up" and "memstack-workspace-core" in row["args"] for row in trace
    )


def test_restart_stops_managed_processes_before_launch_but_keeps_core_running(lifecycle) -> None:
    trace = run_lifecycle(lifecycle, "restart")
    events = [row["event"] for row in trace]
    assert events.index("services:stop") < events.index("services:start")
    stops = [row["args"] for row in trace if row["event"] == "compose:stop"]
    assert stops == []
    assert any(
        row["event"] == "build" and row["args"][row["args"].index("--service") + 1] == "ray-head"
        for row in trace
    )


def test_stop_uses_scoped_manager_and_explicit_compose_services(lifecycle) -> None:
    trace = run_lifecycle(lifecycle, "dev-stop")
    assert trace[0]["event"] == "services:stop"
    assert trace[-1]["event"] == "compose:stop"
    assert "memstack-workspace-core" in trace[-1]["args"]


def test_database_commands_honor_configured_compose_command(lifecycle) -> None:
    trace = run_lifecycle(lifecycle, "db-init")
    assert sum(row["event"] == "compose:exec" for row in trace) >= 3


def test_one_shot_setup_is_waited_separately_from_healthy_services(lifecycle) -> None:
    trace = run_lifecycle(lifecycle, "dev-infra-base")
    running, setup, completed = trace
    assert "--wait" in running["args"] and "minio-setup" not in running["args"]
    assert setup["event"] == "compose:up" and "minio-setup" in setup["args"]
    assert completed["event"] == "wait:completed" and "minio-setup" in completed["args"]
