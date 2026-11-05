#!/usr/bin/env python3
"""Start, stop and inspect only explicitly owned development API/Web processes."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import fcntl
import json
import math
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.dev.processes import (
    LAUNCH_ENV,
    PROFILE_ENV,
    REPO_ENV,
    ROLE_ENV,
    ProbeError,
    ProcessIdentity,
    ProcessProbe,
)


class ServiceError(RuntimeError):
    def __init__(self, role: str, reason: str) -> None:
        self.role, self.reason = role, reason
        super().__init__(f"{role}:{reason}")


@dataclass(frozen=True)
class ServiceSpec:
    role: str
    command: tuple[str, ...]
    cwd: Path
    port: int
    path: str


class ProcessBackend(Protocol):
    deadline: float

    def inspect(self, pid: int) -> ProcessIdentity | None: ...
    def group(self, group: int) -> list[ProcessIdentity]: ...
    def listeners(self, port: int) -> list[int]: ...
    def signal(self, identity: ProcessIdentity, number: signal.Signals) -> None: ...


class Child(Protocol):
    pid: int

    def poll(self) -> int | None: ...


async def probe_health(spec: ServiceSpec, deadline: float, connect: float, read: float) -> bool:
    """Bound the entire header/body read, including a peer that trickles bytes."""
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", spec.port),
            max(0.001, min(connect, deadline - time.monotonic())),
        )
        writer.write(
            f"GET {spec.path} HTTP/1.1\r\nHost: 127.0.0.1:{spec.port}\r\nConnection: close\r\n\r\n".encode()
        )
        await asyncio.wait_for(writer.drain(), max(0.001, min(read, deadline - time.monotonic())))
        raw = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"), max(0.001, min(read, deadline - time.monotonic()))
        )
        lines = raw.decode("iso-8859-1").split("\r\n")
        if len(lines[0].split()) < 2 or lines[0].split()[1] != "200":
            return False
        headers = dict(line.lower().split(":", 1) for line in lines[1:] if ":" in line)
        if spec.role == "web":
            return headers.get("content-type", "").strip().startswith("text/html")
        length = int(headers.get("content-length", "0"))
        if not 0 < length <= 65536:
            return False
        body = await asyncio.wait_for(
            reader.readexactly(length), max(0.001, min(read, deadline - time.monotonic()))
        )
        value: object = json.loads(body)
        return isinstance(value, dict) and cast("dict[str, object]", value).get("status") == "ok"
    except (
        OSError,
        ValueError,
        TimeoutError,
        asyncio.IncompleteReadError,
        asyncio.LimitOverrunError,
    ):
        return False
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, TimeoutError):
                await asyncio.wait_for(
                    writer.wait_closed(), max(0.001, min(read, deadline - time.monotonic()))
                )


Health = Callable[[ServiceSpec, float, float, float], Awaitable[bool]]
Spawn = Callable[[ServiceSpec, dict[str, str], Path], Child]


def spawn_service(spec: ServiceSpec, env: dict[str, str], log: Path) -> Child:
    descriptor = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "ab") as output:
        return subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


class DevServices:
    def __init__(
        self,
        repo: Path,
        specs: Sequence[ServiceSpec],
        *,
        probe: ProcessBackend | None = None,
        spawn: Spawn = spawn_service,
        health: Health = probe_health,
        connect_timeout: float = 1,
        read_timeout: float = 1,
    ) -> None:
        super().__init__()
        self.repo = repo.resolve()
        self.specs = list(specs)
        self.probe = probe if probe is not None else ProcessProbe()
        self.spawn, self.health = spawn, health
        self.connect_timeout, self.read_timeout = connect_timeout, read_timeout
        self.directory = self.repo / "logs/dev-services"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.profile = os.environ.get(PROFILE_ENV, "")

    def _path(self, role: str) -> Path:
        return self.directory / f"{role}.json"

    def _read(self, role: str) -> ProcessIdentity | None:
        try:
            descriptor = os.open(self._path(role), os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ServiceError(role, "invalid_identity_record") from error
        try:
            with os.fdopen(descriptor) as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise ValueError
            value: object = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            data = cast("dict[str, object]", value)
            if set(data) != {
                "version",
                "pid",
                "birth",
                "group",
                "repo",
                "role",
                "nonce",
                "profile",
            }:
                raise ValueError
            if type(data["version"]) is not int or data["version"] != 1:
                raise ValueError
            pid, group = data["pid"], data["group"]
            if type(pid) is not int or pid <= 1 or type(group) is not int or group != pid:
                raise ValueError
            strings: dict[str, str] = {}
            for field in ("birth", "repo", "role", "nonce", "profile"):
                item = data[field]
                if not isinstance(item, str):
                    raise ValueError
                strings[field] = item
            record = ProcessIdentity(
                pid,
                strings["birth"],
                group,
                strings["repo"],
                strings["role"],
                strings["nonce"],
                strings["profile"],
            )
            if (
                record.repo != str(self.repo)
                or record.role != role
                or record.profile != self.profile
                or not record.birth
                or len(record.nonce) != 32
                or any(char not in "0123456789abcdef" for char in record.nonce)
            ):
                raise ValueError
            return record
        except (TypeError, ValueError) as error:
            raise ServiceError(role, "invalid_identity_record") from error

    def _write(self, record: ProcessIdentity) -> None:
        descriptor, name = tempfile.mkstemp(dir=self.directory, prefix=f".{record.role}-")
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump({"version": 1, **dataclasses.asdict(record)}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self._path(record.role))
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name)

    @staticmethod
    def _belongs(current: ProcessIdentity, record: ProcessIdentity) -> bool:
        return (current.group, current.repo, current.role, current.nonce, current.profile) == (
            record.group,
            record.repo,
            record.role,
            record.nonce,
            record.profile,
        )

    def _leader(self, record: ProcessIdentity) -> ProcessIdentity | None:
        try:
            current = self.probe.inspect(record.pid)
        except ProbeError as error:
            raise ServiceError(record.role, "identity_unavailable") from error
        if current is not None and current != record:
            raise ServiceError(record.role, "identity_changed")
        return current

    def _members(self, record: ProcessIdentity) -> list[ProcessIdentity]:
        return [
            member for member in self.probe.group(record.group) if self._belongs(member, record)
        ]

    def _port(self, spec: ServiceSpec, record: ProcessIdentity | None) -> bool:
        try:
            pids = self.probe.listeners(spec.port)
            for pid in pids:
                current = self.probe.inspect(pid)
                if current is None or record is None or not self._belongs(current, record):
                    raise ServiceError(spec.role, "port_in_use_by_unmanaged_process")
        except ProbeError as error:
            raise ServiceError(spec.role, "listener_identity_unavailable") from error
        return bool(pids)

    async def _health(self, spec: ServiceSpec, record: ProcessIdentity, deadline: float) -> bool:
        if not self._leader(record) or not self._port(spec, record):
            return False
        try:
            healthy = await asyncio.wait_for(
                self.health(spec, deadline, self.connect_timeout, self.read_timeout),
                max(0.001, deadline - time.monotonic()),
            )
        except TimeoutError:
            return False
        return bool(
            healthy
            and time.monotonic() < deadline
            and self._leader(record)
            and self._port(spec, record)
        )

    def _launch(
        self, spec: ServiceSpec, launched: list[ProcessIdentity]
    ) -> tuple[ProcessIdentity, Child]:
        nonce = uuid.uuid4().hex
        env = {**os.environ, REPO_ENV: str(self.repo), ROLE_ENV: spec.role, LAUNCH_ENV: nonce}
        if spec.role == "api":
            _ = env.setdefault("RAY_ADDRESS", "ray://localhost:10001")
            _ = env.setdefault("RAY_NAMESPACE", "memstack")
        child = self.spawn(spec, env, self.repo / f"logs/{spec.role}.log")
        pending = ProcessIdentity(
            child.pid, "", child.pid, str(self.repo), spec.role, nonce, self.profile
        )
        launched.append(pending)
        return pending, child

    async def _bind_launch(
        self,
        pending: ProcessIdentity,
        child: Child,
        deadline: float,
        observations: dict[int, ProcessIdentity],
    ) -> ProcessIdentity:
        birth: str | None = None
        transient = {"process_environment_unavailable", "process_birth_unavailable"}
        while True:
            if child.poll() is not None:
                raise ServiceError(pending.role, "process_exited")
            if time.monotonic() >= deadline:
                raise ServiceError(pending.role, "startup_identity_timeout")
            try:
                actual = self.probe.inspect(child.pid)
            except ProbeError as error:
                if str(error) not in transient:
                    raise ServiceError(pending.role, "identity_unavailable") from error
                actual = None
            if actual is not None:
                if birth is not None and actual.birth != birth:
                    raise ServiceError(pending.role, "identity_changed")
                birth = actual.birth
                pairs = (
                    (actual.repo, pending.repo),
                    (actual.role, pending.role),
                    (actual.nonce, pending.nonce),
                    (actual.profile, pending.profile),
                )
                if any(observed and observed != expected for observed, expected in pairs):
                    raise ServiceError(pending.role, "identity_changed")
                if actual.group != pending.group and any(observed for observed, _ in pairs):
                    raise ServiceError(pending.role, "identity_changed")
                # This ephemeral observation belongs only to the Popen child just
                # created here; it is never persisted or used to adopt a service.
                observations[child.pid] = actual
                if self._belongs(actual, pending):
                    self._write(actual)
                    return actual
            await asyncio.sleep(min(0.01, max(0, deadline - time.monotonic())))

    async def _bind_all(
        self,
        pending: dict[str, ProcessIdentity],
        children: dict[str, Child],
        deadline: float,
        observations: dict[int, ProcessIdentity],
    ) -> dict[str, ProcessIdentity]:
        tasks = {
            role: asyncio.create_task(
                self._bind_launch(record, children[role], deadline, observations)
            )
            for role, record in pending.items()
        }
        try:
            results = await asyncio.gather(*tasks.values())
            return dict(zip(tasks, results, strict=True))
        finally:
            for task in tasks.values():
                if not task.done():
                    _ = task.cancel()
            _ = await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def _wait_ready(
        self, records: dict[str, ProcessIdentity], children: dict[str, Child], deadline: float
    ) -> None:
        pending_roles = {spec.role for spec in self.specs}
        while pending_roles:
            if time.monotonic() >= deadline:
                raise ServiceError("startup", "timeout")
            for role, record in records.items():
                if self._leader(record) is None:
                    raise ServiceError(role, "process_exited")
            for role, child in children.items():
                if child.poll() is not None:
                    raise ServiceError(role, "process_exited")
            pending_specs = [spec for spec in self.specs if spec.role in pending_roles]
            healthy = await asyncio.gather(
                *[self._health(spec, records[spec.role], deadline) for spec in pending_specs]
            )
            for role, record in records.items():
                if self._leader(record) is None:
                    raise ServiceError(role, "process_exited")
            pending_roles -= {
                spec.role for spec, ready in zip(pending_specs, healthy, strict=True) if ready
            }
            if pending_roles:
                await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))

    async def start(self, timeout: float = 60) -> list[dict[str, object]]:
        deadline = time.monotonic() + timeout
        self.probe.deadline = deadline
        existing = {spec.role: self._read(spec.role) for spec in self.specs}
        for spec in self.specs:
            record = existing[spec.role]
            if record is not None and self._leader(record) is None and self._members(record):
                raise ServiceError(spec.role, "orphaned_owned_launch_requires_stop")
            _ = self._port(spec, record)
        launched: list[ProcessIdentity] = []
        records: dict[str, ProcessIdentity] = {}
        children: dict[str, Child] = {}
        observations: dict[int, ProcessIdentity] = {}
        try:
            for spec in self.specs:
                if time.monotonic() >= deadline:
                    raise ServiceError("startup", "timeout")
                record = existing[spec.role]
                if record is None or self._leader(record) is None:
                    record, children[spec.role] = self._launch(spec, launched)
                records[spec.role] = record
            pending = {record.role: record for record in launched}
            records.update(await self._bind_all(pending, children, deadline, observations))
            await self._wait_ready(records, children, deadline)
            return [
                {"role": spec.role, "status": "ready", "pid": records[spec.role].pid}
                for spec in self.specs
            ]
        except BaseException:
            await self._stop_records(launched, time.monotonic() + 1, tuple(observations.values()))
            raise

    def _cleanup_members(
        self,
        records: Sequence[ProcessIdentity],
        observations: Sequence[ProcessIdentity],
    ) -> list[ProcessIdentity]:
        members = {member.pid: member for record in records for member in self._members(record)}
        for observed in observations:
            if self.probe.inspect(observed.pid) == observed:
                members[observed.pid] = observed
        return list(members.values())

    async def _stop_records(
        self,
        records: Sequence[ProcessIdentity],
        deadline: float,
        observations: Sequence[ProcessIdentity] = (),
    ) -> None:
        self.probe.deadline = deadline
        for record in records:
            if record.birth:
                _ = self._leader(record)
        terminated: set[ProcessIdentity] = set()
        while True:
            current = self._cleanup_members(records, observations)
            for identity in current:
                if identity not in terminated:
                    self.probe.signal(identity, signal.SIGTERM)
                    terminated.add(identity)
            if not current or time.monotonic() >= deadline:
                break
            await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                break
        await self._kill_until_empty(records, observations)
        for record in records:
            with contextlib.suppress(FileNotFoundError):
                self._path(record.role).unlink()

    async def _kill_until_empty(
        self,
        records: Sequence[ProcessIdentity],
        observations: Sequence[ProcessIdentity],
    ) -> None:
        # Reobserve the launch group until empty; a parent can fork while dying.
        self.probe.deadline = time.monotonic() + 0.2
        while True:
            remaining = self._cleanup_members(records, observations)
            if not remaining:
                break
            for identity in remaining:
                if time.monotonic() >= self.probe.deadline:
                    raise ServiceError("stop", "owned_process_did_not_exit")
                self.probe.signal(identity, signal.SIGKILL)
            await asyncio.sleep(0.01)

    async def stop(self, timeout: float = 5) -> list[dict[str, object]]:
        self.probe.deadline = time.monotonic() + timeout
        records = [record for spec in self.specs if (record := self._read(spec.role)) is not None]
        try:
            for record in records:
                _ = self._leader(record)
            for spec in self.specs:
                if not any(record.role == spec.role for record in records):
                    _ = self._port(spec, None)
            await self._stop_records(records, self.probe.deadline)
        except ProbeError as error:
            raise ServiceError("stop", "identity_unavailable") from error
        return [
            {
                "role": spec.role,
                "status": "stopped"
                if any(r.role == spec.role for r in records)
                else "unmanaged"
                if (self.repo / f"logs/{spec.role}.pid").exists()
                else "stopped",
            }
            for spec in self.specs
        ]

    async def status(self, timeout: float = 2) -> list[dict[str, object]]:
        deadline = time.monotonic() + timeout
        self.probe.deadline = deadline
        result: list[dict[str, object]] = []
        for spec in self.specs:
            record = self._read(spec.role)
            ready = record is not None and await self._health(spec, record, deadline)
            if record is None:
                _ = self._port(spec, None)
            result.append(
                {
                    "role": spec.role,
                    "status": "ready" if ready else "unhealthy" if record else "stopped",
                }
            )
        return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("action", choices=("start", "stop", "status"))
    _ = parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    _ = parser.add_argument("--timeout", type=float)
    _ = parser.add_argument("--connect-timeout", type=float, default=1)
    _ = parser.add_argument("--read-timeout", type=float, default=1)
    _ = parser.add_argument("--service", action="append", choices=("api", "web"))
    _ = parser.add_argument(
        "--web-command",
        default="node_modules/.bin/vite --config vite.config.ts --host 0.0.0.0 --port 3000 --strictPort",
    )
    args = parser.parse_args(argv)
    timeout = (
        args.timeout
        if args.timeout is not None
        else {"start": 60, "stop": 5, "status": 2}[args.action]
    )
    if any(
        not math.isfinite(value) or value <= 0
        for value in (timeout, args.connect_timeout, args.read_timeout)
    ):
        parser.error("timeouts must be finite positive seconds")
    repo = args.repo.resolve()
    web_command = tuple(shlex.split(args.web_command))
    if "--strictPort" not in web_command:
        web_command += ("--strictPort",)
    specs = [
        ServiceSpec(
            "api",
            (
                "uv",
                "run",
                "uvicorn",
                "src.infrastructure.adapters.primary.web.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ),
            repo,
            8000,
            "/health",
        ),
        ServiceSpec("web", web_command, repo / "web", 3000, "/"),
    ]
    manager = DevServices(
        repo,
        [spec for spec in specs if spec.role in (args.service or ("api", "web"))],
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
    )
    lock = os.open(manager.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = asyncio.run(getattr(manager, args.action)(timeout=timeout))
        print(json.dumps(result))
        return (
            0 if args.action != "status" or all(item["status"] == "ready" for item in result) else 1
        )
    except (ServiceError, ProbeError, OSError) as error:
        reason = str(error) if isinstance(error, (ServiceError, ProbeError)) else "service_os_error"
        print(json.dumps({"status": "error", "reason": reason}), file=sys.stderr)
        return 1
    finally:
        os.close(lock)


if __name__ == "__main__":
    raise SystemExit(main())
