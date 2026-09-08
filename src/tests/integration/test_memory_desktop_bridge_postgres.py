"""Node renderer/main -> real HTTP -> isolated PostgreSQL memory command contract."""

import asyncio
import json
import os
import socket
from pathlib import Path

import pytest
import uvicorn
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncReceiptModel as Receipt,
    KnowledgeSyncTombstoneModel as Tombstone,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory
from src.tests.integration.test_memory_online_http_postgres import (
    enroll,
    http_memory as _http_memory,
    pg_sync as _pg_sync,
)

pg_sync = _pg_sync
http_memory = _http_memory
pytestmark = pytest.mark.skipif(
    os.getenv("KNOWLEDGE_SYNC_POSTGRES_TESTS") != "1" or not os.getenv("CLOUD_MEMORY_HTTP_DIST"),
    reason="Requires isolated PostgreSQL and compiled Desktop renderer/main modules",
)


def install_identity_fixture(app, scope):
    @app.get("/api/v1/workspace-context")
    async def context():
        return {
            "context": {"tenant_id": scope.tenant_id, "project_id": scope.project_id, "revision": 1}
        }

    @app.get("/api/v1/auth/me")
    async def identity():
        return {"user_id": scope.actor_id}


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("scoped", [False, True, "typed"])
async def test_real_desktop_http_memory_commands_are_scoped_and_replayable(
    http_memory, enabled, scoped
):
    client, sessions, scope, graph, _ = http_memory
    graph.get_memory_graph_context.return_value = ([], [])
    if enabled:
        await enroll(sessions, scope)
    app = client._transport.app
    install_identity_fixture(app, scope)
    observed = []

    @app.middleware("http")
    async def observe(request, call_next):
        if request.url.path.startswith("/api/v1/memories") and request.method != "GET":
            observed.append(
                (
                    request.headers.get("x-memory-expected-revision"),
                    request.headers.get("x-expected-revision"),
                    request.headers.get("idempotency-key"),
                )
            )
        return await call_next(request)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    address = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                    raise AssertionError("HTTP fixture stopped before startup")
                await asyncio.sleep(0.01)
        runner = (
            Path(__file__).parents[3]
            / "agi-stack/apps/desktop/tests"
            / (
                "cloud-memory-typed-http-runner.cjs"
                if scoped == "typed"
                else "cloud-memory-command-http-runner.cjs"
            )
        )
        process = await asyncio.create_subprocess_exec(
            "node",
            str(runner),
            os.environ["CLOUD_MEMORY_HTTP_DIST"],
            address,
            "enabled" if enabled else "disabled",
            "scoped" if scoped else "legacy",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        assert process.returncode == 0, stderr.decode()
        result = json.loads(stdout)
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, timeout=10)
        listener.close()

    async with sessions() as db:
        assert (await db.scalars(select(Memory))).all() == []
        changes = (await db.scalars(select(Change).order_by(Change.sequence))).all()
        receipts = (await db.scalars(select(Receipt))).all()
        if enabled:
            assert [change.revision for change in changes] == [1, 2, 3]
            assert len(receipts) == 3
            assert (await db.get(Tombstone, result["memoryId"])).revision == 3
            assert [entry[0] for entry in observed] == ["0", "0", "1", "1", "1", "2", "2"]
            assert observed[0][2] == observed[1][2] == result["createKey"]
            assert observed[2][2] == observed[3][2] == result["patchKey"]
            assert observed[5][2] == observed[6][2] == result["deleteKey"]
        else:
            assert result == {"disabled": True}
            assert changes == receipts == []
            assert len(observed) == 1
        assert all(entry[1] is None for entry in observed)
