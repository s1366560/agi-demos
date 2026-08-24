"""Fail-closed worker boundary tests for generated route contracts."""

from __future__ import annotations

import multiprocessing
import socket
import subprocess
import sys
import threading
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

from src.infrastructure.plugins.route_inventory import INVENTORY_PATH
from src.infrastructure.plugins.v2 import route_catalog_worker as worker_module
from src.infrastructure.plugins.v2.route_catalog_worker import (
    RouteCatalogWorkerEffectViolationV2,
    RouteCatalogWorkerErrorV2,
    build_route_catalog_in_worker_v2,
)

_ROOT = Path(__file__).resolve().parents[6]


def _guard_probe_worker_v2(effect: str, target_path: str, sender: Connection) -> None:
    try:
        worker_module._install_route_catalog_worker_guards_v2()
        if effect == "file":
            Path(target_path).write_text("forbidden", encoding="utf-8")
        elif effect == "network":
            _ = socket.socket()
        elif effect == "subprocess":
            _ = subprocess.run([sys.executable, "-c", "pass"], check=False)
        elif effect == "thread":
            threading.Thread(target=lambda: None).start()
        else:
            raise AssertionError(f"unsupported probe effect {effect}")
        sender.send(("unexpected-success", ""))
    except BaseException as exc:
        sender.send((type(exc).__name__, str(exc)))
    finally:
        sender.close()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        ("file", "file.write"),
        ("network", "socket."),
        ("subprocess", "subprocess."),
        ("thread", "thread.start"),
    ],
)
def test_worker_guard_rejects_external_effects(
    effect: str,
    expected: str,
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_guard_probe_worker_v2,
        args=(effect, str(tmp_path / "probe"), sender),
    )
    process.start()
    sender.close()
    assert receiver.poll(10), effect
    error_type, message = receiver.recv()
    receiver.close()
    process.join(timeout=10)

    assert not process.is_alive()
    assert error_type == RouteCatalogWorkerEffectViolationV2.__name__
    assert expected in message
    assert not (tmp_path / "probe").exists()


@pytest.mark.unit
def test_worker_timeout_terminates_without_orphan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = {process.pid for process in multiprocessing.active_children()}
    monkeypatch.setattr(worker_module, "_CATALOG_BUILD_TIMEOUT_SECONDS_V2", 0.0)

    with pytest.raises(RouteCatalogWorkerErrorV2, match="timed out"):
        build_route_catalog_in_worker_v2(_ROOT / INVENTORY_PATH)

    after = {process.pid for process in multiprocessing.active_children()}
    assert after == before
