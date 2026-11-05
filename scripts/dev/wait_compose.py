#!/usr/bin/env python3
"""Wait for one Compose service using bounded, read-only state observations."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence


class WaitError(RuntimeError):
    """A fixed diagnostic code; never include Docker output or environment."""


def _stop_probe(process: subprocess.Popen[str]) -> None:
    # Only a fresh session created by this waiter is signalled, never a service.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        _ = process.communicate(timeout=0.2)
    except subprocess.TimeoutExpired:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        with contextlib.suppress(subprocess.TimeoutExpired):
            _ = process.wait(timeout=0.2)


def _probe(command: Sequence[str], deadline: float) -> str | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
    except OSError as error:
        raise WaitError("compose_probe_failed") from error
    try:
        output, _ = process.communicate(timeout=min(2.0, remaining))
    except subprocess.TimeoutExpired:
        _stop_probe(process)
        return None
    except BaseException:
        _stop_probe(process)
        raise
    if process.returncode != 0:
        raise WaitError("compose_probe_failed")
    return output


def _rows(output: str, service: str) -> list[dict[str, object]]:
    if not output.strip():
        return []
    if len(output) > 1024 * 1024:
        raise WaitError("compose_state_invalid")
    try:
        try:
            decoded: object = json.loads(output)
        except json.JSONDecodeError:
            decoded = [json.loads(line) for line in output.splitlines() if line.strip()]
        values = cast("list[object]", decoded) if isinstance(decoded, list) else [decoded]
        rows: list[dict[str, object]] = []
        for item in values:
            if not isinstance(item, dict):
                raise ValueError
            row = cast("dict[str, object]", item)
            if (
                row.get("Service") != service
                or not isinstance(row.get("State"), str)
                or not isinstance(row.get("Health", ""), str)
            ):
                raise ValueError
            rows.append(row)
        return rows
    except (TypeError, ValueError) as error:
        raise WaitError("compose_state_invalid") from error


def _ready(rows: list[dict[str, object]], goal: str) -> bool:
    if not rows:
        return False
    ready = True
    for row in rows:
        state = cast("str", row["State"]).casefold()
        health = cast("str", row.get("Health", "")).casefold()
        if state not in {
            "running",
            "created",
            "paused",
            "restarting",
            "removing",
            "exited",
            "dead",
        }:
            raise WaitError("compose_state_invalid")
        if goal == "completed":
            code = row.get("ExitCode")
            if code is not None and type(code) is not int:
                raise WaitError("compose_state_invalid")
            if code is not None and code != 0:
                raise WaitError("compose_service_failed")
            if state == "dead":
                raise WaitError("compose_service_failed")
            if state == "exited":
                if type(code) is not int:
                    raise WaitError("compose_state_invalid")
            else:
                ready = False
        else:
            if state in {"exited", "dead"} or health == "unhealthy":
                raise WaitError("compose_service_failed")
            ready = ready and state == "running" and health == "healthy"
    return ready


def wait_for_service(command: Sequence[str], service: str, goal: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    probe = [*command, "ps", "--all", "--format", "json", service]
    while time.monotonic() < deadline:
        output = _probe(probe, deadline)
        if output is not None and _ready(_rows(output, service), goal):
            if time.monotonic() < deadline:
                return
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.1, remaining))
    raise WaitError("compose_wait_timeout")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--timeout", type=float, required=True)
    _ = parser.add_argument("--state", choices=("completed", "healthy"), required=True)
    _ = parser.add_argument("--service", required=True)
    _ = parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a Compose command prefix is required after --")
    try:
        wait_for_service(command, args.service, args.state, args.timeout)
    except WaitError as error:
        print(
            json.dumps({"status": "error", "service": args.service, "reason": str(error)}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"status": "ready", "service": args.service, "state": args.state}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
