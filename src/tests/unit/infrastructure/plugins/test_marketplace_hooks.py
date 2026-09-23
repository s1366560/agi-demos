"""Hook runtime tests: failure propagates and only exact approved events execute."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.plugins.marketplace_hooks import (
    MarketplaceHookError,
    execute_marketplace_hooks,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def lease_dependency(monkeypatch):
    # Snapshot lease concurrency is exercised by its own database integration tests.
    @asynccontextmanager
    async def lease(*args, **kwargs):
        yield

    monkeypatch.setattr(
        "src.infrastructure.plugins.marketplace_hooks.lease_marketplace_snapshots", lease
    )


def installation(*, status="enabled", permissions=None):
    return SimpleNamespace(
        id="installed",
        payload={
            "status": status,
            "approved_permissions": ["process:execute"] if permissions is None else permissions,
            "runtime_root": "/workspace/.memstack/plugins/installed/abc",
            "package": {
                "resources": {
                    "hooks": [
                        {
                            "event": "before_request",
                            "command": "python3 ${PLUGIN_ROOT}/hook.py",
                            "timeout_seconds": 30,
                        }
                    ]
                }
            },
        },
    )


async def run(db, sandbox):
    await execute_marketplace_hooks(
        db=db,
        sandbox=sandbox,
        tenant_id="tenant",
        project_id="project",
        event="agent.before_request",
        payload={"session_id": "session", "secret": "must-not-be-forwarded"},
    )


async def test_approved_hook_executes_in_project_sandbox():
    db = SimpleNamespace(scalars=AsyncMock(return_value=[installation()]))
    sandbox = SimpleNamespace(execute_tool=AsyncMock(return_value={"metadata": {"exit_code": 0}}))
    await run(db, sandbox)
    call = sandbox.execute_tool.call_args.kwargs
    assert call["project_id"] == "project"
    assert call["tool_name"] == "bash"
    assert call["timeout"] == 30
    assert "must-not-be-forwarded" not in call["arguments"]["command"]
    assert "before_request" in call["arguments"]["command"]
    assert "${PLUGIN_ROOT}" not in call["arguments"]["command"]


async def test_disabled_hook_is_not_dispatched():
    db = SimpleNamespace(scalars=AsyncMock(return_value=[installation(status="disabled")]))
    sandbox = SimpleNamespace(execute_tool=AsyncMock())
    await run(db, sandbox)
    sandbox.execute_tool.assert_not_called()


async def test_missing_permission_blocks_execution():
    db = SimpleNamespace(scalars=AsyncMock(return_value=[installation(permissions=[])]))
    sandbox = SimpleNamespace(execute_tool=AsyncMock())
    with pytest.raises(MarketplaceHookError, match="permission"):
        await run(db, sandbox)
    sandbox.execute_tool.assert_not_called()


@pytest.mark.parametrize(
    "result", [{"isError": True}, {"is_error": True}, {"metadata": {"exit_code": 2}}]
)
async def test_hook_failure_stops_operation(result):
    db = SimpleNamespace(scalars=AsyncMock(return_value=[installation()]))
    sandbox = SimpleNamespace(execute_tool=AsyncMock(return_value=result))
    with pytest.raises(MarketplaceHookError, match="failed"):
        await run(db, sandbox)


async def test_hook_timeout_stops_operation():
    db = SimpleNamespace(scalars=AsyncMock(return_value=[installation()]))
    sandbox = SimpleNamespace(execute_tool=AsyncMock(side_effect=TimeoutError))
    with pytest.raises(MarketplaceHookError, match="timeout"):
        await run(db, sandbox)
