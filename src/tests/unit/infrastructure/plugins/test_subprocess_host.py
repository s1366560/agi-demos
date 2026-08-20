"""Unit tests for the I5 subprocess runtime boundary."""

from __future__ import annotations

import sys
import textwrap

import pytest

from src.domain.ports.plugins import ResourceQuota
from src.infrastructure.plugins.governance import (
    PluginQuotaExceededError,
    ResourceQuotaEnforcer,
)
from src.infrastructure.plugins.subprocess_host import (
    SubprocessHostError,
    SubprocessToolHost,
)

ECHO_CHILD = textwrap.dedent(
    """
    import json, sys
    request = json.loads(sys.stdin.read())
    params = request["params"]
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                      "result": {"echo": params["input"], "tool": params["tool"]}}))
    """
)

HANG_CHILD = "import time; time.sleep(30)"
CRASH_CHILD = "import sys; sys.exit(3)"
GARBAGE_CHILD = "print('not json')"


def _host(command: list[str], **kwargs: object) -> SubprocessToolHost:
    return SubprocessToolHost("plug", command, **kwargs)  # type: ignore[arg-type]


@pytest.mark.unit
class TestSubprocessToolHost:
    async def test_call_round_trip_with_audit(self) -> None:
        events: list[dict[str, object]] = []
        host = _host([sys.executable, "-c", ECHO_CHILD], audit=events.append)

        outcome = await host.call("demo", '{"q": 1}')

        assert outcome.result == {"echo": '{"q": 1}', "tool": "demo"}
        assert events[0]["event"] == "subprocess_tool_call"
        assert events[0]["result"] == "ok"

    async def test_timeout_kills_child(self) -> None:
        host = _host([sys.executable, "-c", HANG_CHILD], timeout_seconds=0.2)
        with pytest.raises(SubprocessHostError, match="timed out"):
            await host.call("demo", "")

    async def test_crash_isolated(self) -> None:
        host = _host([sys.executable, "-c", CRASH_CHILD])
        with pytest.raises(SubprocessHostError, match="exited with 3"):
            await host.call("demo", "")

    async def test_invalid_response_rejected(self) -> None:
        host = _host([sys.executable, "-c", GARBAGE_CHILD])
        with pytest.raises(SubprocessHostError, match="invalid JSON-RPC response"):
            await host.call("demo", "")

    async def test_concurrency_quota_enforced(self) -> None:
        enforcer = ResourceQuotaEnforcer({"plug": ResourceQuota(max_concurrent_calls=1)})
        import asyncio

        host = _host(
            [sys.executable, "-c", "import time; time.sleep(0.5); print('{}')"],
            quota_enforcer=enforcer,
        )
        first = asyncio.create_task(host.call("demo", ""))
        await asyncio.sleep(0.05)
        with pytest.raises(PluginQuotaExceededError):
            await host.call("demo", "")
        outcome = await first
        assert outcome.result is None  # child printed "{}" with no result field
