"""Run the Compose state waiter against isolated executable process fixtures."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.dev.wait_compose import main

SCRIPT = Path(__file__).resolve().parents[4] / "scripts/dev/wait_compose.py"
pytestmark = pytest.mark.unit


@pytest.fixture
def compose(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    executable = tmp_path / "compose.py"
    executable.write_text(
        "import json,os,subprocess,sys,time\n"
        "from pathlib import Path\n"
        "assert sys.argv[1:] == ['ps','--all','--format','json','fixture-service']\n"
        "mode=os.environ.get('FIXTURE_MODE','state')\n"
        "if mode=='hang':\n"
        " child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\n"
        " Path(os.environ['FIXTURE_PIDS']).write_text(json.dumps([os.getpid(),child.pid]))\n"
        " time.sleep(30)\n"
        "if mode=='error':\n"
        " print('fixture-private-payload',file=sys.stderr);sys.exit(23)\n"
        "if mode=='binary':\n"
        " sys.stdout.buffer.write(b'fixture-private-payload\\xff');sys.exit(0)\n"
        "states=json.loads(os.environ.get('FIXTURE_SEQUENCE','[]'))\n"
        "if states:\n"
        " counter=Path(os.environ['FIXTURE_COUNTER'])\n"
        " index=int(counter.read_text()) if counter.exists() else 0\n"
        " counter.write_text(str(index+1))\n"
        " print(json.dumps(states[min(index,len(states)-1)]))\n"
        "else:print(os.environ['FIXTURE_PAYLOAD'])\n"
    )
    return executable, {
        **os.environ,
        "FIXTURE_PIDS": str(tmp_path / "pids.json"),
        "FIXTURE_COUNTER": str(tmp_path / "counter"),
    }


def _run(compose, goal: str, payload: str = "[]", timeout: str = "2"):
    executable, environment = compose
    arguments = [
        "--timeout",
        timeout,
        "--state",
        goal,
        "--service",
        "fixture-service",
        "--",
        sys.executable,
        str(executable),
    ]
    output, errors = StringIO(), StringIO()
    with (
        patch.dict(os.environ, {**environment, "FIXTURE_PAYLOAD": payload}, clear=True),
        redirect_stdout(output),
        redirect_stderr(errors),
    ):
        try:
            code = main(arguments)
        except SystemExit as error:
            code = error.code
    return subprocess.CompletedProcess(arguments, code, output.getvalue(), errors.getvalue())


def _row(state="running", health="", exit_code=0):
    return {"Service": "fixture-service", "State": state, "Health": health, "ExitCode": exit_code}


@pytest.mark.parametrize(
    "goal,row", [("healthy", _row(health="healthy")), ("completed", _row("exited"))]
)
@pytest.mark.parametrize("array", [False, True])
def test_goal_accepts_ndjson_and_array_states(compose, goal, row, array):
    result = _run(compose, goal, json.dumps([row] if array else row))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "status": "ready",
        "service": "fixture-service",
        "state": goal,
    }


@pytest.mark.parametrize(
    "goal,finished", [("completed", _row("exited")), ("healthy", _row(health="healthy"))]
)
def test_running_state_is_polled_until_goal(compose, goal, finished):
    compose[1]["FIXTURE_SEQUENCE"] = json.dumps([[_row()], [finished]])
    result = _run(compose, goal)
    assert result.returncode == 0, result.stderr
    assert int(Path(compose[1]["FIXTURE_COUNTER"]).read_text()) >= 2


@pytest.mark.parametrize(
    "goal,row",
    [
        ("completed", _row("exited", exit_code=7)),
        ("completed", _row("restarting", exit_code=7)),
        ("healthy", _row("exited")),
        ("healthy", _row(health="unhealthy")),
    ],
)
def test_terminal_failure_is_immediate(compose, goal, row):
    started = time.monotonic()
    result = _run(compose, goal, json.dumps(row), timeout="3")
    assert result.returncode == 1
    assert time.monotonic() - started < 2
    assert json.loads(result.stderr)["reason"] == "compose_service_failed"


@pytest.mark.parametrize(
    "payload",
    [
        '{"Service":"other","State":"exited","ExitCode":0}',
        json.dumps(_row("exited", exit_code=False)),
        '["fixture-private-payload"]',
        "fixture-private-payload",
    ],
)
def test_invalid_or_wrong_service_payload_fails_without_printing_it(compose, payload):
    result = _run(compose, "completed", payload)
    assert result.returncode == 1
    assert "fixture-private-payload" not in result.stderr + result.stdout
    assert json.loads(result.stderr)["reason"] == "compose_state_invalid"


def test_failed_compose_command_does_not_print_its_stderr(compose):
    compose[1]["FIXTURE_MODE"] = "error"
    result = _run(compose, "completed")
    assert result.returncode == 1
    assert json.loads(result.stderr)["reason"] == "compose_probe_failed"
    assert "fixture-private-payload" not in result.stderr + result.stdout


def test_invalid_output_encoding_is_redacted_as_an_invalid_state(compose):
    compose[1]["FIXTURE_MODE"] = "binary"
    result = _run(compose, "completed")
    assert result.returncode == 1
    assert json.loads(result.stderr)["reason"] == "compose_state_invalid"
    assert "fixture-private-payload" not in result.stderr + result.stdout


def test_ndjson_checks_every_matching_container(compose):
    payload = "\n".join(
        json.dumps(row) for row in [_row(health="healthy"), _row(health="unhealthy")]
    )
    result = _run(compose, "healthy", payload)
    assert result.returncode == 1
    assert json.loads(result.stderr)["reason"] == "compose_service_failed"


def test_missing_container_waits_only_until_deadline(compose):
    result = _run(compose, "completed", "[]", timeout="0.2")
    assert result.returncode == 1
    assert json.loads(result.stderr)["reason"] == "compose_wait_timeout"


def _alive(pid: int) -> bool:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True, check=False
    )
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


def test_hanging_probe_has_total_deadline_and_leaves_no_probe_children(compose):
    compose[1]["FIXTURE_MODE"] = "hang"
    pids = []
    try:
        started = time.monotonic()
        result = _run(compose, "completed", timeout="0.4")
        pids = json.loads(Path(compose[1]["FIXTURE_PIDS"]).read_text())
        assert result.returncode == 1
        assert json.loads(result.stderr)["reason"] == "compose_wait_timeout"
        assert time.monotonic() - started < 2
        assert not any(_alive(pid) for pid in pids)
    finally:
        for pid in pids:
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)


@pytest.mark.parametrize("timeout", ["0", "nan", "inf", "-1"])
def test_timeout_must_be_finite_and_positive(compose, timeout):
    result = _run(compose, "completed", timeout=timeout)
    assert result.returncode == 2
    assert not Path(compose[1]["FIXTURE_COUNTER"]).exists()


def test_executable_cli_uses_the_same_waiter(compose):
    executable, environment = compose
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--timeout",
            "2",
            "--state",
            "healthy",
            "--service",
            "fixture-service",
            "--",
            sys.executable,
            str(executable),
        ],
        env={**environment, "FIXTURE_PAYLOAD": json.dumps(_row(health="healthy"))},
        capture_output=True,
        text=True,
        check=False,
        timeout=4,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["state"] == "healthy"
