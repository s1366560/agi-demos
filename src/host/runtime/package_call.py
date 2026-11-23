"""Enforce per-release concurrency for calls admitted on this host."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedPackageBytesV2,
)

_running: set[tuple[str, str, str, str]] = set()
_running_lock = Lock()


@contextmanager
def admit_package_call(scope: ScopeBindingV2, package: SignedPackageBytesV2) -> Iterator[None]:
    key = (scope.tenant_id, scope.project_id, package.plugin_id, package.digest)
    with _running_lock:
        if key in _running:
            raise OptionalBusinessError("busy", "package concurrency limit reached")
        _running.add(key)
    try:
        yield
    finally:
        with _running_lock:
            _running.remove(key)
