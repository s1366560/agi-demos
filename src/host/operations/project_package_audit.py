"""Operation receipts for signed project packages. Only host-owned metadata is recorded."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import SignedPackageBytesV2

logger = logging.getLogger("plugin_audit.project_package")


def configure_project_package_audit() -> None:
    # Uvicorn configures its own loggers. A standalone worker may have no root sink.
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    if not logger.hasHandlers():
        logger.addHandler(logging.StreamHandler())


@dataclass(slots=True)
class PackageAudit:
    operation: str
    actor_id: str | None
    tenant_id: str | None
    project_id: str | None
    run_id: str | None = None
    plugin_id: str | None = None
    version: str | None = None
    digest: str | None = None
    executor: str | None = None
    tool_id: str | None = None
    command_id: str | None = None
    subject_id: str | None = None
    generation_id: str | None = None

    def release(self, package: SignedPackageBytesV2) -> None:
        self.plugin_id, self.version, self.digest = (
            package.plugin_id,
            package.version,
            package.digest,
        )
        self.executor = "oci" if package.worker is not None else "wasm"


_current: ContextVar[PackageAudit | None] = ContextVar("project_package_audit", default=None)


def identify_signed_operation(
    package: SignedPackageBytesV2, *, tool: str | None = None, command: str | None = None
) -> None:
    audit = _current.get()
    if audit is not None:
        # A caller may submit an arbitrary string in either field. Only log names
        # that belong to a verified release; payloads and exception text never enter the event.
        if tool is not None and any(row.name == tool for row in package.contribution.tools):
            audit.tool_id = tool
            if audit.operation == "call":
                audit.operation = "tool"
        if command is not None and any(
            row.command_id == command for row in package.contribution.commands
        ):
            audit.command_id = command
            if audit.operation == "call":
                audit.operation = "command"


@contextmanager
def project_operation(
    operation: str,
    *,
    actor_id: str | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
    run_id: str | None = None,
    failures_only: bool = False,
) -> Iterator[PackageAudit]:
    audit = PackageAudit(operation, actor_id, tenant_id, project_id, run_id)
    token = _current.set(audit)
    started = time.monotonic()
    outcome = "error"
    try:
        yield audit
        outcome = "ok"
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        _current.reset(token)
        if outcome != "ok" or not failures_only:
            # A disconnected sink must not turn a completed side effect into a client retry.
            try:
                fields = {k: v for k, v in asdict(audit).items() if v is not None}
                logger.info(
                    "%s",
                    json.dumps(
                        {
                            "event": "project_package_operation",
                            **fields,
                            "outcome": outcome,
                            "duration_ms": int((time.monotonic() - started) * 1000),
                        },
                        sort_keys=True,
                    ),
                )
            except Exception:
                pass
