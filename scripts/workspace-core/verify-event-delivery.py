#!/usr/bin/env python3
"""Execute the real Redis Workspace event publish/consume/crash-replay contract."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
REDIS_IMAGE = "redis:7-alpine"
REDIS_READY_TIMEOUT_SECONDS = 30.0


def run_delivery_contract(
    redis_port: int,
    *,
    repo_root: Path = REPO_ROOT,
    environment: Mapping[str, str] | None = None,
) -> None:
    command_environment = dict(environment or os.environ)
    command_environment["BCS_TEST_REDIS_PORT"] = str(redis_port)
    subprocess.run(
        [
            "scripts/avernet-bcs/cargo.sh",
            "test",
            "-p",
            "memstack-workspace-core",
            "--test",
            "plan_update_outbox_delivery",
            "--locked",
            "workspace_plan_updated_outbox_publishes_consumer_once_and_replays_after_crash",
            "--",
            "--ignored",
            "--exact",
            "--test-threads=1",
        ],
        cwd=repo_root,
        env=command_environment,
        check=True,
    )


def _wait_for_redis(port: int) -> None:
    deadline = time.monotonic() + REDIS_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"disposable Redis did not become ready on port {port}")


def _docker_port(container_id: str) -> int:
    completed = subprocess.run(
        ["docker", "port", container_id, "6379/tcp"],
        check=True,
        capture_output=True,
        text=True,
    )
    endpoint = completed.stdout.strip().rsplit(":", maxsplit=1)
    if len(endpoint) != 2 or not endpoint[1].isdigit():
        raise RuntimeError("Docker did not report a valid disposable Redis port")
    return int(endpoint[1])


def run_with_disposable_redis(*, repo_root: Path = REPO_ROOT) -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("BCS_TEST_REDIS_PORT is required when Docker is unavailable")
    container_name = f"memstack-workspace-evidence-{uuid.uuid4().hex[:12]}"
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container_name,
            "--publish",
            "127.0.0.1::6379",
            REDIS_IMAGE,
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    container_id = completed.stdout.strip()
    if not container_id:
        raise RuntimeError("Docker did not return a disposable Redis container id")
    try:
        redis_port = _docker_port(container_id)
        _wait_for_redis(redis_port)
        run_delivery_contract(redis_port, repo_root=repo_root)
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container_id],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-port", type=int)
    args = parser.parse_args()
    redis_port = args.redis_port
    if redis_port is None and os.environ.get("BCS_TEST_REDIS_PORT"):
        redis_port = int(os.environ["BCS_TEST_REDIS_PORT"])
    if redis_port is None:
        run_with_disposable_redis()
    else:
        _wait_for_redis(redis_port)
        run_delivery_contract(redis_port)
    print("Workspace Redis event delivery and crash replay contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
