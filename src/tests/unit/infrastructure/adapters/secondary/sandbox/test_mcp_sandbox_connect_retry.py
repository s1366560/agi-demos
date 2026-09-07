"""Connection startup retries preserve backoff and release unpublished clients."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
    MCPSandboxInstance,
)

_MODULE = "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter"
pytestmark = pytest.mark.unit


@pytest.fixture
def connection():
    with patch(f"{_MODULE}.docker.from_env", return_value=MagicMock()):
        adapter = MCPSandboxAdapter()
    instance = MCPSandboxInstance(
        id="retry-sandbox",
        status=SandboxStatus.RUNNING,
        config=SandboxConfig(image="sandbox-mcp-server:latest"),
        project_path="/tmp/retry-project",
        endpoint="ws://localhost:18765",
        websocket_url="ws://localhost:18765",
        mcp_auth_token="test-capability",
    )
    adapter._active_sandboxes[instance.id] = instance
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    with (
        patch.object(adapter, "_verify_container_running", new=AsyncMock(return_value=True)),
        patch(f"{_MODULE}.MCPWebSocketClient", return_value=client),
        patch(f"{_MODULE}.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        yield adapter, instance, client, sleep


@pytest.mark.parametrize("failure", [False, OSError("not ready")])
async def test_retry_waits_before_connecting_again(connection, failure):
    adapter, instance, client, sleep = connection
    events = []

    async def connect(**_kwargs):
        events.append("connect")
        if len(events) == 1:
            if isinstance(failure, Exception):
                raise failure
            return failure
        return True

    async def wait(delay):
        events.append(("wait", delay))

    client.connect.side_effect = connect
    sleep.side_effect = wait
    assert await adapter.connect_mcp(instance.id, backoff_factor=0.5) is True
    assert events == ["connect", ("wait", 0.5), "connect"]
    assert instance.mcp_client is client
    client.disconnect.assert_not_awaited()


@pytest.mark.parametrize("failure", [False, OSError("not ready")])
async def test_exhaustion_waits_only_between_attempts_and_releases_client(connection, failure):
    adapter, instance, client, sleep = connection
    client.connect.side_effect = [failure, failure, failure]
    assert await adapter.connect_mcp(instance.id, max_retries=3, backoff_factor=0.5) is False
    assert client.connect.await_count == 3
    assert sleep.await_args_list == [call(0.5), call(1.0)]
    client.disconnect.assert_awaited_once()
    assert instance.mcp_client is None


async def test_cancellation_during_connect_releases_client_and_propagates(connection):
    adapter, instance, client, sleep = connection
    client.connect.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await adapter.connect_mcp(instance.id)
    client.disconnect.assert_awaited_once()
    sleep.assert_not_awaited()
    assert instance.mcp_client is None


@pytest.mark.parametrize("failure", [False, OSError("not ready")])
async def test_cancellation_during_backoff_releases_client_and_stops_retries(connection, failure):
    adapter, instance, client, sleep = connection
    client.connect.side_effect = [failure, True]
    sleep.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await adapter.connect_mcp(instance.id)
    assert client.connect.await_count == 1
    client.disconnect.assert_awaited_once()
    assert instance.mcp_client is None


async def test_default_retries_until_service_is_ready_within_total_budget(connection):
    adapter, instance, client, sleep = connection
    clock = [0.0]
    results = iter([False, False, False, True])

    async def connect(**_kwargs):
        clock[0] += 1.0
        return next(results)

    async def wait(delay):
        clock[0] += delay

    client.connect.side_effect = connect
    sleep.side_effect = wait
    with patch(f"{_MODULE}.monotonic", side_effect=lambda: clock[0], create=True):
        assert await adapter.connect_mcp(instance.id, timeout=10, backoff_factor=0.5) is True
    assert [item.kwargs["timeout"] for item in client.connect.await_args_list] == [
        10.0,
        8.5,
        6.5,
        3.5,
    ]
    assert sleep.await_args_list == [call(0.5), call(1.0), call(2.0)]
    client.disconnect.assert_not_awaited()


async def test_total_budget_caps_backoff_and_prevents_another_attempt(connection):
    adapter, instance, client, sleep = connection
    clock = [0.0]

    async def connect(**_kwargs):
        clock[0] += 0.2
        return False

    async def wait(delay):
        clock[0] += delay

    client.connect.side_effect = connect
    sleep.side_effect = wait
    with patch(f"{_MODULE}.monotonic", side_effect=lambda: clock[0], create=True):
        assert await adapter.connect_mcp(instance.id, timeout=2.5) is False
    assert client.connect.await_count == 2
    assert [item.kwargs["timeout"] for item in client.connect.await_args_list] == pytest.approx(
        [2.5, 1.3]
    )
    assert [item.args[0] for item in sleep.await_args_list] == pytest.approx([1.0, 1.1])
    assert clock[0] == 2.5
    client.disconnect.assert_awaited_once()
    assert instance.mcp_client is None


async def test_total_budget_cancels_a_stalled_socket_and_releases_client(connection):
    adapter, instance, client, sleep = connection
    cancelled = []

    async def connect(**_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    client.connect.side_effect = connect
    result = await asyncio.wait_for(adapter.connect_mcp(instance.id, timeout=0.02), timeout=2)
    assert result is False
    assert cancelled == [True]
    client.disconnect.assert_awaited_once()
    sleep.assert_not_awaited()
    assert instance.mcp_client is None
