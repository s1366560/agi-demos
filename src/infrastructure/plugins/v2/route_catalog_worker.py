"""Disposable, fail-closed worker boundary for V2 route catalog generation."""

from __future__ import annotations

import _thread
import multiprocessing
import os
import sys
import threading
from collections.abc import Mapping
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Protocol, cast

_CATALOG_BUILD_TIMEOUT_SECONDS_V2 = 60.0
_BLOCKED_AUDIT_EVENTS_V2 = frozenset(
    {
        "os.chmod",
        "os.chown",
        "os.fork",
        "os.link",
        "os.mkdir",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.remove",
        "os.rename",
        "os.rmdir",
        "os.symlink",
        "os.system",
        "os.truncate",
        "os.utime",
        "pty.spawn",
    }
)
_BLOCKED_AUDIT_PREFIXES_V2 = ("socket.", "subprocess.")


class RouteCatalogWorkerErrorV2(RuntimeError):
    """Raised when the disposable catalog worker cannot return a complete payload."""


class RouteCatalogWorkerEffectViolationV2(RuntimeError):
    """Raised inside the worker when catalog extraction attempts an external effect."""

    def __init__(self, effect: str) -> None:
        self.effect = effect
        super().__init__(f"route catalog worker effect forbidden: {effect}")


class _WorkerProcessV2(Protocol):
    def is_alive(self) -> bool: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...


def build_route_catalog_in_worker_v2(inventory_path: Path) -> Mapping[str, object]:
    """Build one complete payload without importing inventory targets in the host."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_route_catalog_worker_main_v2,
        args=(str(inventory_path), sender),
        daemon=True,
    )
    try:
        process.start()
    except BaseException:
        receiver.close()
        sender.close()
        raise
    sender.close()
    try:
        if not receiver.poll(_CATALOG_BUILD_TIMEOUT_SECONDS_V2):
            _stop_worker_process_v2(process)
            raise RouteCatalogWorkerErrorV2("builtin route contract catalog worker timed out")
        try:
            message = receiver.recv()
        except EOFError as exc:
            raise RouteCatalogWorkerErrorV2(
                "builtin route contract catalog worker exited without a result"
            ) from exc
    finally:
        receiver.close()
        process.join(timeout=5)
        if process.is_alive():
            _stop_worker_process_v2(process)
    if (
        not isinstance(message, tuple)
        or len(message) != 2
        or not isinstance(message[0], str)
    ):
        raise RouteCatalogWorkerErrorV2("builtin route contract catalog worker sent bad data")
    status, payload = message
    if status != "ok":
        raise RouteCatalogWorkerErrorV2(f"catalog worker failed: {payload}")
    if not isinstance(payload, dict):
        raise RouteCatalogWorkerErrorV2("catalog worker payload must be an object")
    return cast("dict[str, object]", payload)


def _route_catalog_worker_main_v2(inventory_path: str, sender: Connection) -> None:
    try:
        _install_route_catalog_worker_guards_v2()
        from .builtin_route_contracts import _build_builtin_route_contract_catalog_in_process_v2

        catalog = _build_builtin_route_contract_catalog_in_process_v2(Path(inventory_path))
        sender.send(("ok", catalog.to_payload()))
    except BaseException as exc:  # worker must marshal every preflight failure
        sender.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        sender.close()


def _install_route_catalog_worker_guards_v2() -> None:
    """Forbid external mutations while trusted builtin registration code is inspected."""
    sys.dont_write_bytecode = True
    sys.addaudithook(_route_catalog_audit_hook_v2)

    def reject_thread_start(*_args: object, **_kwargs: object) -> None:
        raise RouteCatalogWorkerEffectViolationV2("thread.start")

    setattr(_thread, "start_new_thread", reject_thread_start)  # noqa: B010
    setattr(threading, "_start_new_thread", reject_thread_start)  # noqa: B010
    setattr(threading.Thread, "start", reject_thread_start)  # noqa: B010


def _route_catalog_audit_hook_v2(event: str, args: tuple[object, ...]) -> None:
    if event == "open" and _open_event_writes_v2(args):
        raise RouteCatalogWorkerEffectViolationV2("file.write")
    if event in _BLOCKED_AUDIT_EVENTS_V2 or event.startswith(_BLOCKED_AUDIT_PREFIXES_V2):
        raise RouteCatalogWorkerEffectViolationV2(event)


def _open_event_writes_v2(args: tuple[object, ...]) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else None
    if isinstance(mode, str) and any(marker in mode for marker in ("a", "w", "x", "+")):
        return True
    if isinstance(flags, int):
        access_mode = flags & os.O_ACCMODE
        write_flags = os.O_APPEND | os.O_CREAT | os.O_TRUNC
        return access_mode in {os.O_WRONLY, os.O_RDWR} or bool(flags & write_flags)
    return False


def _stop_worker_process_v2(process: _WorkerProcessV2) -> None:
    if not process.is_alive():
        return
    process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)


__all__ = [
    "RouteCatalogWorkerEffectViolationV2",
    "RouteCatalogWorkerErrorV2",
    "build_route_catalog_in_worker_v2",
]
