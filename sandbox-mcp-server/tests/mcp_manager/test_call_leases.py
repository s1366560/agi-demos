"""An update may drain a server without cancelling its running tool calls."""
import asyncio

import pytest

from src.mcp_manager.call_leases import drain_tool_calls, tool_call_lease


class Server:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.stopped = False

    @tool_call_lease
    async def call_tool(self, server_name: str):
        self.started.set()
        await self.release.wait()
        assert not self.stopped
        return "finished"

    @drain_tool_calls
    async def stop_server(self, name: str):
        self.stopped = True
        return "stopped"


@pytest.mark.asyncio
async def test_stop_waits_for_running_call_and_rejects_new_admission():
    server = Server()
    call = asyncio.create_task(server.call_tool("old-version"))
    await server.started.wait()
    stop = asyncio.create_task(server.stop_server("old-version"))
    await asyncio.sleep(0)
    assert not server.stopped
    with pytest.raises(RuntimeError, match="stopping"):
        await server.call_tool("old-version")
    server.release.set()
    assert await call == "finished"
    assert await stop == "stopped"


@pytest.mark.asyncio
async def test_cancelled_call_releases_lease():
    server = Server()
    call = asyncio.create_task(server.call_tool("old-version"))
    await server.started.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert await asyncio.wait_for(server.stop_server("old-version"), timeout=1) == "stopped"


@pytest.mark.asyncio
async def test_different_server_is_not_blocked_by_draining():
    server = Server()
    call = asyncio.create_task(server.call_tool("old-version"))
    await server.started.wait()
    assert await server.stop_server("another-version") == "stopped"
    server.stopped = False
    server.release.set()
    assert await call == "finished"
