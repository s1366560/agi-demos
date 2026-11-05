"""Owned service lifecycle behavior, independent of the developer's running services."""

import asyncio
import dataclasses
import signal
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.dev.processes import ProbeError, ProcessIdentity, ProcessProbe
from scripts.dev.services import DevServices, ServiceError, ServiceSpec, probe_health

pytestmark = pytest.mark.unit


class FakeProbe:
    def __init__(self):
        self.processes = {}
        self.ports = {}
        self.signals = []
        self.spawned = []
        self.exit_immediately = None
        self.ignore_term = False

    def inspect(self, pid):
        return self.processes.get(pid)

    def group(self, group):
        return [p for p in self.processes.values() if p.group == group]

    def listeners(self, port):
        return [pid for pid in self.ports.get(port, []) if pid in self.processes]

    def signal(self, identity, number):
        if self.inspect(identity.pid) != identity:
            return
        self.signals.append((identity.pid, number))
        if number == signal.SIGKILL or not self.ignore_term:
            self.processes.pop(identity.pid, None)

    def spawn(self, spec, env, log):
        del log
        pid = len(self.spawned) + 100
        identity = ProcessIdentity(
            pid,
            f"birth-{pid}",
            pid,
            env["MEMSTACK_DEV_REPO"],
            spec.role,
            env["MEMSTACK_DEV_LAUNCH_ID"],
            env.get("AGISTACK_DESKTOP_QA_PROFILE_DIR", ""),
        )
        self.processes[pid] = identity
        self.ports[spec.port] = [pid]
        self.spawned.append(spec.role)
        return SimpleNamespace(
            pid=pid, poll=lambda: 1 if self.exit_immediately == spec.role else None
        )


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.delenv("AGISTACK_DESKTOP_QA_PROFILE_DIR", raising=False)
    probe = FakeProbe()
    specs = [
        ServiceSpec("api", ("fixture-api",), tmp_path, 18001, "/health"),
        ServiceSpec("web", ("fixture-web",), tmp_path, 18002, "/"),
    ]
    health = Mock(side_effect=lambda *_: asyncio.sleep(0, result=True))
    manager = DevServices(tmp_path, specs, probe=probe, spawn=probe.spawn, health=health)
    return manager, probe, specs, health


async def test_both_services_launch_and_probe_in_parallel(harness):
    manager, processes, _, _ = harness
    entered = []
    barrier = asyncio.Event()

    async def health(spec, *_):
        assert processes.spawned == ["api", "web"]
        entered.append(spec.role)
        if len(entered) == 2:
            barrier.set()
        await barrier.wait()
        return True

    manager.health = health
    result = await manager.start(timeout=0.2)
    assert [r["status"] for r in result] == ["ready", "ready"]
    assert set(entered) == {"api", "web"}


async def test_owned_healthy_start_is_idempotent(harness):
    manager, processes, _, health = harness
    await manager.start(timeout=0.2)
    await manager.start(timeout=0.2)
    assert processes.spawned == ["api", "web"]
    assert health.call_count == 4
    assert processes.signals == []


async def test_immediate_exit_fails_without_spending_startup_timeout(harness):
    manager, processes, _, _ = harness
    processes.exit_immediately = "api"
    started = time.monotonic()
    with pytest.raises(ServiceError, match="exited"):
        await manager.start(timeout=10)
    assert time.monotonic() - started < 0.5
    assert not processes.processes


async def test_foreign_healthy_port_is_not_accepted_or_killed(harness):
    manager, processes, specs, health = harness
    foreign = ProcessIdentity(777, "foreign", 777, str(manager.repo), "api", "foreign", "")
    processes.processes[777] = foreign
    processes.ports[specs[0].port] = [777]
    with pytest.raises(ServiceError, match="port_in_use"):
        await manager.start(timeout=0.2)
    assert processes.spawned == []
    assert processes.signals == []
    health.assert_not_called()


async def test_one_failure_cleans_only_new_launches_not_existing_healthy(harness):
    manager, processes, specs, _ = harness
    only_api = DevServices(
        manager.repo,
        specs[:1],
        probe=processes,
        spawn=processes.spawn,
        health=lambda *_: asyncio.sleep(0, result=True),
    )
    await only_api.start(timeout=0.2)
    old_api = next(iter(processes.processes))
    processes.exit_immediately = "web"
    with pytest.raises(ServiceError, match="exited"):
        await manager.start(timeout=0.2)
    assert old_api in processes.processes
    assert all(pid != old_api for pid, _ in processes.signals)


async def test_global_deadline_bounds_even_a_stuck_mock_health(harness):
    manager, processes, _, _ = harness

    async def never(*_):
        await asyncio.Event().wait()

    manager.health = never
    started = time.monotonic()
    with pytest.raises(ServiceError, match="timeout"):
        await manager.start(timeout=0.05)
    assert time.monotonic() - started < 0.5
    assert not processes.processes


@pytest.mark.parametrize("change", ["birth", "repo", "role", "nonce", "profile"])
async def test_stale_or_different_profile_identity_never_receives_a_signal(harness, change):
    manager, processes, _, _ = harness
    await manager.start(timeout=0.2)
    original = processes.processes[100]
    processes.processes[100] = dataclasses.replace(original, **{change: "different"})
    with pytest.raises(ServiceError, match="identity"):
        await manager.stop(timeout=0.05)
    assert processes.signals == []


async def test_legacy_pid_file_is_not_a_signal_authority(harness):
    manager, processes, _, _ = harness
    (manager.repo / "logs").mkdir(exist_ok=True)
    (manager.repo / "logs/api.pid").write_text("777")
    result = await manager.stop(timeout=0.05)
    assert result[0]["status"] == "unmanaged"
    assert processes.signals == []
    assert (manager.repo / "logs/api.pid").read_text() == "777"


async def test_stop_escalates_only_still_owned_processes_after_grace(harness):
    manager, processes, _, _ = harness
    await manager.start(timeout=0.2)
    processes.ignore_term = True
    await manager.stop(timeout=0.03)
    assert processes.signals[:2] == [(100, signal.SIGTERM), (101, signal.SIGTERM)]
    assert processes.signals[2:] == [(100, signal.SIGKILL), (101, signal.SIGKILL)]


async def test_pid_reuse_after_term_does_not_receive_kill(harness):
    manager, processes, _, _ = harness
    await manager.start(timeout=0.2)
    original_signal = processes.signal

    def reused(identity, number):
        original_signal(identity, number)
        if identity.pid == 100 and number == signal.SIGTERM:
            processes.processes[100] = dataclasses.replace(identity, birth="reused", nonce="other")

    processes.signal = reused
    await manager.stop(timeout=0.03)
    assert processes.processes[100].nonce == "other"
    assert (100, signal.SIGKILL) not in processes.signals


async def test_unknown_process_probe_fails_closed(harness):
    manager, processes, _, _ = harness
    await manager.start(timeout=0.2)
    processes.inspect = Mock(side_effect=ProbeError("identity_unavailable"))
    with pytest.raises(ServiceError, match="identity"):
        await manager.stop(timeout=0.05)
    assert processes.signals == []


async def test_status_rechecks_ownership_and_actual_health(harness):
    manager, _, _, health = harness
    await manager.start(timeout=0.2)
    health.side_effect = lambda *_: asyncio.sleep(0, result=False)
    result = await manager.status(timeout=0.05)
    assert all(item["status"] == "unhealthy" for item in result)


@pytest.mark.parametrize("reply", [b"", b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n"])
async def test_real_http_connect_and_read_have_a_total_bound(reply):
    async def serve(reader, writer):
        await reader.read(1024)
        writer.write(reply)
        await writer.drain()
        try:
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        started = time.monotonic()
        assert not await probe_health(
            ServiceSpec("api", (), Path("."), port, "/health"), started + 0.06, 0.02, 0.02
        )
        assert time.monotonic() - started < 0.2
    finally:
        server.close()
        await server.wait_closed()


def test_kernel_signal_guard_revalidates_before_signalling(monkeypatch):
    probe = ProcessProbe()
    original = ProcessIdentity(100, "original", 100, "/repo", "api", "nonce", "")
    monkeypatch.setattr(probe, "inspect", lambda _: dataclasses.replace(original, birth="changed"))
    kill = Mock()
    monkeypatch.setattr("scripts.dev.processes.os.kill", kill)
    probe.signal(original, signal.SIGKILL)
    kill.assert_not_called()


def test_kernel_probe_reads_only_public_identity_of_this_test_process(monkeypatch):
    import os

    probe = ProcessProbe()
    identity = probe.inspect(os.getpid())
    assert identity.pid == os.getpid()
    assert identity.group == os.getpgrp()
    assert identity.birth
    monkeypatch.setattr(
        probe,
        "_command",
        lambda _: SimpleNamespace(
            returncode=0, stdout=f"{os.getpid()} {os.getpgrp()}\n2000000000 {os.getpgrp()}\n"
        ),
    )
    assert any(p.pid == os.getpid() for p in probe.group(os.getpgrp()))
    assert probe.inspect(2_000_000_000) is None


async def test_listener_probe_identifies_the_owned_test_socket():
    import os

    server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", 0)
    try:
        probe = ProcessProbe()
        port = server.sockets[0].getsockname()[1]
        assert os.getpid() in probe.listeners(port)
    finally:
        server.close()
        await server.wait_closed()
    assert probe.listeners(port) == []


@pytest.mark.parametrize(
    "role,body,mime,expected",
    [
        ("api", b'{"status":"ok"}', "application/json", True),
        ("api", b"[]", "application/json", False),
        ("api", b'{"status":"failed"}', "application/json", False),
        ("web", b"<html></html>", "text/html", True),
        ("web", b"{}", "application/json", False),
    ],
)
async def test_real_http_validates_the_service_health_protocol(role, body, mime, expected):
    async def serve(reader, writer):
        await reader.read(1024)
        writer.write(
            f"HTTP/1.1 200 OK\r\nContent-Type: {mime}\r\nContent-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        assert (
            await probe_health(
                ServiceSpec(role, (), Path("."), port, "/"), time.monotonic() + 1, 0.1, 0.1
            )
            is expected
        )
    finally:
        server.close()
        await server.wait_closed()


async def test_state_does_not_persist_inherited_credentials(harness, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "fixture-secret-must-not-be-written")
    manager, _, _, _ = harness
    await manager.start(timeout=0.2)
    states = list(manager.directory.glob("*.json"))
    assert len(states) == 2
    assert all("fixture-secret-must-not-be-written" not in p.read_text() for p in states)
    assert all((p.stat().st_mode & 0o777) == 0o600 for p in states)


async def test_managed_state_symlink_is_rejected_without_reading_or_signalling(harness, tmp_path):
    manager, processes, _, _ = harness
    private = tmp_path / "unrelated-private"
    private.write_text("not a service record")
    (manager.directory / "api.json").symlink_to(private)
    with pytest.raises(ServiceError, match="identity_record"):
        await manager.start(timeout=0.2)
    assert processes.signals == []
    assert processes.spawned == []


async def test_orphaned_owned_children_require_stop_before_new_start(harness):
    manager, processes, _, _ = harness
    await manager.start(timeout=0.2)
    parent = processes.processes.pop(100)
    child = dataclasses.replace(parent, pid=999, birth="child-birth")
    processes.processes[999] = child
    with pytest.raises(ServiceError, match="orphaned"):
        await manager.start(timeout=0.2)
    await manager.stop(timeout=0.03)
    assert 999 not in processes.processes


def test_cli_preserves_timeout_and_web_command_without_shell_execution(
    tmp_path, monkeypatch, capsys
):
    from scripts.dev import services

    captured = {}

    class Manager:
        def __init__(self, repo, specs, **kwargs):
            captured.update(repo=repo, specs=specs, kwargs=kwargs)
            self.directory = tmp_path

        async def start(self, timeout):
            captured["timeout"] = timeout
            return [{"role": "web", "status": "ready"}]

    monkeypatch.setattr(services, "DevServices", Manager)
    assert (
        services.main(
            [
                "start",
                "--repo",
                str(tmp_path),
                "--timeout",
                "1.5",
                "--web-command",
                "node custom-vite --port 3000",
                "--service",
                "web",
            ]
        )
        == 0
    )
    assert captured["timeout"] == 1.5
    assert captured["specs"][0].command == ("node", "custom-vite", "--port", "3000", "--strictPort")
    assert "ready" in capsys.readouterr().out


async def test_owned_child_created_during_term_is_also_stopped(harness):
    manager, processes, _, _ = harness
    await manager.start(timeout=0.2)
    old_signal = processes.signal

    def spawn_during_term(identity, number):
        old_signal(identity, number)
        if identity.pid == 100 and number == signal.SIGTERM:
            processes.processes[999] = dataclasses.replace(identity, pid=999, birth="late-child")

    processes.signal = spawn_during_term
    await manager.stop(timeout=0.1)
    assert not processes.processes
    assert (999, signal.SIGTERM) in processes.signals


async def test_preexisting_leader_exit_during_other_health_fails_immediately(harness):
    manager, processes, specs, _ = harness
    one = DevServices(
        manager.repo,
        specs[:1],
        probe=processes,
        spawn=processes.spawn,
        health=lambda *_: asyncio.sleep(0, result=True),
    )
    await one.start(timeout=0.2)

    async def health(spec, *_):
        if spec.role == "web":
            processes.processes.pop(100, None)
        return True

    manager.health = health
    started = time.monotonic()
    with pytest.raises(ServiceError, match="exited"):
        await manager.start(timeout=10)
    assert time.monotonic() - started < 0.5


def test_linux_kernel_fields_bind_birth_group_and_only_lifecycle_tags(tmp_path, monkeypatch):
    from scripts.dev import processes

    root = tmp_path / "303"
    root.mkdir()
    fields = ["S", "1", "123", *["0"] * 16, "456"]
    (root / "stat").write_text("303 (fixture process) " + " ".join(fields))
    (root / "environ").write_bytes(
        b"MEMSTACK_DEV_REPO=/repo\0MEMSTACK_DEV_ROLE=api\0MEMSTACK_DEV_LAUNCH_ID=nonce\0SECRET_KEY=unused\0"
    )
    with monkeypatch.context() as patch:
        patch.setattr(processes.sys, "platform", "linux")
        patch.setattr(processes, "Path", lambda _: tmp_path)
        assert ProcessProbe().inspect(303) == ProcessIdentity(
            303, "456", 123, "/repo", "api", "nonce", ""
        )
        assert ProcessProbe().inspect(404) is None


def test_unsupported_platform_and_unknown_listener_output_fail_closed(monkeypatch):
    from scripts.dev import processes

    probe = ProcessProbe()
    with monkeypatch.context() as patch:
        patch.setattr(processes.sys, "platform", "unsupported")
        with pytest.raises(ProbeError, match="unsupported"):
            probe.inspect(1)
    monkeypatch.setattr(
        probe, "_command", lambda _: SimpleNamespace(returncode=0, stdout="invalid", stderr="")
    )
    with pytest.raises(ProbeError, match="listener"):
        probe.listeners(1234)


def test_process_command_timeout_is_bounded_and_fail_closed(monkeypatch):
    from scripts.dev import processes

    probe = ProcessProbe()
    probe.deadline = time.monotonic() - 1
    with pytest.raises(ProbeError, match="timeout"):
        probe._command(["unused"])
    probe.deadline = time.monotonic() + 1
    monkeypatch.setattr(
        processes.subprocess,
        "run",
        Mock(side_effect=processes.subprocess.TimeoutExpired("fixture", 0.1)),
    )
    with pytest.raises(ProbeError, match="unavailable"):
        probe._command(["unused"])


async def test_late_owned_child_at_kill_is_observed_before_state_is_removed(harness):
    manager, processes, _, _ = harness
    await manager.start(timeout=0.2)
    processes.ignore_term = True
    previous = processes.signal

    def spawn_at_kill(identity, number):
        previous(identity, number)
        if identity.pid == 100 and number == signal.SIGKILL:
            processes.processes[999] = dataclasses.replace(
                identity, pid=999, birth="late-kill-child"
            )

    processes.signal = spawn_at_kill
    await manager.stop(timeout=0.03)
    assert not processes.processes
    assert not list(manager.directory.glob("*.json"))


async def test_final_stop_deadline_retains_identity_records_if_process_cannot_exit(harness):
    manager, processes, _, _ = harness
    await manager.start(timeout=0.2)
    processes.signal = lambda identity, number: processes.signals.append((identity.pid, number))
    started = time.monotonic()
    with pytest.raises(ServiceError, match="did_not_exit"):
        await manager.stop(timeout=0.02)
    assert time.monotonic() - started < 0.5
    assert len(list(manager.directory.glob("*.json"))) == 2
    assert processes.processes


@pytest.mark.parametrize("transition", ["not_visible", "markers_not_visible"])
async def test_new_alive_exec_transition_converges_after_both_children_spawn(harness, transition):
    manager, processes, _, _ = harness
    original = processes.inspect
    seen = {}

    def during_exec(pid):
        assert processes.spawned == ["api", "web"]
        seen[pid] = seen.get(pid, 0) + 1
        value = original(pid)
        if value is not None and seen[pid] <= 2:
            return (
                None
                if transition == "not_visible"
                else dataclasses.replace(value, repo="", role="", nonce="")
            )
        return value

    processes.inspect = during_exec
    assert all(item["status"] == "ready" for item in await manager.start(timeout=0.2))
    assert all(count >= 3 for count in seen.values())


async def test_conflicting_new_process_identity_is_never_waited_into_or_signalled(harness):
    manager, processes, _, _ = harness
    original = processes.spawn

    def conflicting(spec, env, log):
        child = original(spec, env, log)
        if spec.role == "api":
            processes.processes[child.pid] = dataclasses.replace(
                processes.processes[child.pid], nonce="foreign"
            )
        return child

    manager.spawn = conflicting
    with pytest.raises(ServiceError, match="identity"):
        await manager.start(timeout=10)
    assert all(pid != 100 for pid, _ in processes.signals)
    assert processes.processes[100].nonce == "foreign"


async def test_unbound_created_child_times_out_and_is_cleaned_without_adoption(harness):
    manager, processes, _, health = harness
    original = processes.spawn

    def unbound(spec, env, log):
        child = original(spec, env, log)
        processes.processes[child.pid] = dataclasses.replace(
            processes.processes[child.pid], repo="", role="", nonce=""
        )
        return child

    manager.spawn = unbound
    with pytest.raises(ServiceError, match="identity_timeout"):
        await manager.start(timeout=0.03)
    assert not processes.processes
    assert not list(manager.directory.glob("*.json"))
    health.assert_not_called()


async def test_birth_change_during_new_exec_wait_is_not_adopted_or_signalled(harness):
    manager, processes, _, _ = harness
    original_spawn, original_inspect = processes.spawn, processes.inspect

    def unbound(spec, env, log):
        child = original_spawn(spec, env, log)
        if spec.role == "api":
            processes.processes[child.pid] = dataclasses.replace(
                processes.processes[child.pid], repo="", role="", nonce=""
            )
        return child

    seen = 0

    def inspect(pid):
        nonlocal seen
        if pid == 100:
            seen += 1
            if seen == 2:
                processes.processes[100] = dataclasses.replace(
                    processes.processes[100], birth="reused"
                )
        return original_inspect(pid)

    manager.spawn, processes.inspect = unbound, inspect
    with pytest.raises(ServiceError, match="identity_changed"):
        await manager.start(timeout=0.1)
    assert processes.processes[100].birth == "reused"
    assert all(pid != 100 for pid, _ in processes.signals)


async def test_cancelled_start_joins_tasks_and_cleans_only_new_launches(harness):
    manager, processes, _, _ = harness
    entered = asyncio.Event()

    async def never(*_):
        entered.set()
        await asyncio.Event().wait()

    manager.health = never
    task = asyncio.create_task(manager.start(timeout=10))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not processes.processes
    assert not list(manager.directory.glob("*.json"))
