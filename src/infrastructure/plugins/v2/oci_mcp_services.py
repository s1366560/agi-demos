"""Scope one guest's service alias callbacks to the dependencies admitted with the call."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.infrastructure.plugins.v2.oci_mcp_records import worker_record_call
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from memstack_plugin_sdk.contract import ToolContribution

    from src.infrastructure.plugins.v2.oci_mcp_records import RecordCall
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
        ScopeBindingV2,
        SignedPackageBytesV2,
    )


@dataclass(kw_only=True)
class WorkerServices:
    scope: ScopeBindingV2
    package: SignedPackageBytesV2
    invoke: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
    calls: int = 0
    used_bytes: int = 0

    def _consume(self, document: dict[str, Any]) -> None:
        self.used_bytes += len(
            json.dumps(document, allow_nan=False, separators=(",", ":")).encode()
        )
        if self.used_bytes > 64 * 1024:
            raise OptionalBusinessError("quota_exceeded", "worker service exchange exceeded 64 KiB")

    async def call(self, tool: ToolContribution, params: dict[str, Any]) -> dict[str, Any]:
        alias = params.get("alias")
        payload = params.get("input")
        if (
            params.keys() != {"alias", "input"}
            or not isinstance(alias, str)
            or alias not in tool.service_aliases
            or not isinstance(payload, dict)
            or "services.call" not in (self.package.approved_permissions & tool.permissions)
        ):
            raise OptionalBusinessError(
                "forbidden", "worker service alias was not approved for this tool"
            )
        self.calls += 1
        if self.calls > 4:
            raise OptionalBusinessError("quota_exceeded", "worker service call count exceeded")
        self._consume(payload)
        result = await self.invoke(alias, payload)
        self._consume(result)
        return result


_current: ContextVar[WorkerServices | None] = ContextVar("worker_services", default=None)


@contextmanager
def bind_worker_services(services: WorkerServices | None) -> Iterator[None]:
    token = _current.set(services)
    try:
        yield
    finally:
        _current.reset(token)


def worker_host_callback(
    package: SignedPackageBytesV2, scope: ScopeBindingV2, tool: ToolContribution
) -> RecordCall | None:
    records = worker_record_call(package, scope, tool.permissions)
    services = _current.get()
    if services is None or services.package is not package or services.scope != scope:
        return records

    async def callback(method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "memstack/services/call":
            return await services.call(tool, params)
        if records is not None:
            return await records(method, params)
        raise OptionalBusinessError("forbidden", "unknown worker host callback")

    return callback
