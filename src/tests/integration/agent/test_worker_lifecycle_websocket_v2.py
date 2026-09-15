"""Actual Redis publisher to a network WebSocket, with fresh PostgreSQL authorization."""

import asyncio
import json
import socket
from uuid import uuid4

import pytest
import uvicorn
import websockets
from fastapi import FastAPI, WebSocket
from redis.asyncio import Redis

from src.configuration.config import get_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.websocket.connection_manager import ConnectionManager
from src.infrastructure.adapters.primary.web.websocket.lifecycle_stream_bridge_v2 import (
    lifecycle_project_access_v2,
    start_lifecycle_bridge_v2,
    stop_lifecycle_bridge_v2,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.agent_worker_lifecycle_transport_v2 import (
    AgentWorkerLifecycleTransportV2,
    lifecycle_routing_key_v2,
)
from src.tests.integration.agent import test_subagent_registry_postgres_v2 as fixtures

postgres_registry = fixtures.postgres_registry
pytestmark = pytest.mark.integration


async def test_worker_publication_reaches_real_websocket_and_revocation_stops_delivery(  # noqa: PLR0915
    postgres_registry,
):
    engine, sessions, scope = postgres_registry
    async with engine.begin() as connection:
        for model in (UserTenant, UserProject):
            await connection.run_sync(model.__table__.create)
    scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id="tenant",
        project_id="lifecycle-" + uuid4().hex,
        session_id="conversation-" + uuid4().hex,
    )
    async with sessions() as db, db.begin():
        db.add(Project(id=scope.project_id, tenant_id=scope.tenant_id, owner_id="user", name="QA"))
        await db.flush()
        db.add(
            Conversation(
                id=scope.session_id,
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                user_id="user",
                title="QA",
            )
        )
        db.add(User(id="private-owner", email="private@example.invalid", hashed_password="unused"))
        await db.flush()
        db.add(
            Conversation(
                id="private-conversation",
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                user_id="private-owner",
                title="Private QA",
            )
        )
        db.add(UserTenant(id="membership", user_id="user", tenant_id="tenant"))
        db.add(UserProject(id="membership", user_id="user", project_id=scope.project_id))
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    manager = ConnectionManager()
    app = FastAPI()
    ready = asyncio.Event()
    task_id = uuid4().hex
    key = "events:" + lifecycle_routing_key_v2(scope.tenant_id, scope.project_id)

    class Container:
        def with_db(self, db):
            return self

        def redis(self):
            return redis

    @app.websocket("/events")
    async def endpoint(websocket: WebSocket):
        await websocket.accept()
        async with sessions() as db:
            context = MessageContext(
                websocket=websocket,
                user_id="user",
                tenant_id=scope.tenant_id,
                session_id=task_id,
                db=db,
                container=Container(),
                session_factory=sessions,
                _connection_manager=manager,
            )
            assert await lifecycle_project_access_v2(context, scope.project_id)
            await start_lifecycle_bridge_v2(context, scope.project_id)
            await context.send_ack("subscribe_lifecycle_state")
            ready.set()
            try:
                await websocket.receive_text()
            finally:
                await stop_lifecycle_bridge_v2(context, scope.project_id)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        async with websockets.connect(f"ws://127.0.0.1:{port}/events") as websocket:
            await ready.wait()
            assert json.loads(await websocket.recv())["type"] == "ack"
            publisher = AgentWorkerLifecycleTransportV2()
            message = {
                "type": "subagent_lifecycle",
                "tenant_id": scope.tenant_id,
                "project_id": scope.project_id,
                "data": {
                    "type": "subagent_killed",
                    "data": {
                        "conversation_id": scope.session_id,
                        "run_id": task_id,
                        "subagent_id": "config-not-execution",
                    },
                },
            }
            private_message = {
                **message,
                "data": {
                    "type": "subagent_killed",
                    "data": {"conversation_id": "private-conversation", "run_id": "private-run"},
                },
            }
            await publisher.broadcast_to_project(scope.tenant_id, scope.project_id, private_message)
            mismatched_message = {
                **message,
                "data": {
                    "type": "subagent_killed",
                    "data": {
                        "tenant_id": "wrong-tenant",
                        "conversation_id": scope.session_id,
                        "run_id": task_id,
                    },
                },
            }
            await publisher.broadcast_to_project(
                scope.tenant_id, scope.project_id, mismatched_message
            )
            with pytest.raises(ValueError, match="scope mismatch"):
                await publisher.broadcast_to_project("wrong-tenant", scope.project_id, message)
            assert (
                await publisher.broadcast_to_project(scope.tenant_id, scope.project_id, message)
                == 1
            )
            delivered = json.loads(await asyncio.wait_for(websocket.recv(), 3))
            assert delivered["data"] == message["data"]
            assert delivered["event_id"]
            async with sessions() as db, db.begin():
                row = await db.get(UserProject, "membership")
                await db.delete(row)
            await publisher.broadcast_to_project(scope.tenant_id, scope.project_id, message)
            denied = json.loads(await asyncio.wait_for(websocket.recv(), 3))
            assert denied["type"] == "error"
            assert denied["data"]["code"] == "project_access_denied"
            await websocket.send("close")
    finally:
        server.should_exit = True
        await serving
        await redis.delete(key)
        await redis.aclose()
