"""Real socket + Redis bridge tests; OS input and production credentials are never used."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import socket
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from websockets.asyncio.client import connect

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent import computer_use_device as routes
from src.infrastructure.adapters.primary.web.websocket.handlers.computer_use_handler import (
    ComputerUseHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.primary.web.websocket.message_router import MessageRouter
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.agent.native_computer_use import devices, media, store
from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker
from src.infrastructure.agent.native_computer_use.schema import validator
from src.infrastructure.agent.native_computer_use.websocket import (
    STATE_KEY,
    close_device_connection,
)
from src.infrastructure.agent.tools import native_computer_use as native
from src.infrastructure.agent.tools.context import ToolContext
from src.tests.integration.agent.test_native_computer_bridge import DEFINITION, PNG, authorization
from src.tests.integration.agent.test_native_computer_claims import authority
from src.tests.unit.infrastructure.agent.test_native_connector_effects import (
    arguments as connector_arguments,
    definition as connector_definition,
    row as connector_row,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(loop_scope="function")
async def transport(monkeypatch):  # noqa: PLR0915 - real socket lifecycle fixture
    prefix = f"test:computer-ws:{uuid4()}"
    for module in (store, devices, media):
        monkeypatch.setattr(module, "PREFIX", prefix)
    redis = Redis.from_url("redis://localhost:6379", decode_responses=True)
    try:
        await redis.ping()
    except Exception:
        await redis.aclose()
        pytest.skip("Redis integration environment unavailable")
    broker = NativeComputerBroker(redis, timeout=3)
    app = FastAPI()
    app.state.container = SimpleNamespace(redis_client=redis)
    app.state.run = authority()
    app.state.db = AsyncMock()
    app.state.db.scalar.return_value = "p"
    app.state.closed = asyncio.Event()
    app.state.connection = None
    app.include_router(routes.router, prefix="/api/v1/agent")
    tokens = {"fixture-u": "u", "fixture-other": "other"}

    async def user(request: Request):
        user_id = tokens.get(request.headers.get("authorization", "").removeprefix("Bearer "))
        if user_id is None:
            raise HTTPException(status_code=401, detail="Fixture authentication required")
        return SimpleNamespace(id=user_id)

    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_db] = lambda: app.state.db
    monkeypatch.setattr(
        routes,
        "_load_scoped_run",
        AsyncMock(
            side_effect=lambda *_args, **_kwargs: (
                app.state.run,
                SimpleNamespace(workspace_id=None),
            )
        ),
    )
    monkeypatch.setattr(
        routes, "load_chat_permission_policy", AsyncMock(return_value={"permission_mode": "ask"})
    )
    router = MessageRouter().register_all(
        [
            ComputerUseHandler(kind)
            for kind in (
                "computer_use_device",
                "computer_use_result",
                "computer_use_media",
                "computer_use_control_state",
            )
        ]
    )

    @app.websocket("/native-test")
    async def websocket_endpoint(websocket: WebSocket):
        user_id = tokens.get(websocket.headers.get("authorization", "").removeprefix("Bearer "))
        if user_id is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        context = MessageContext(
            websocket=websocket,
            user_id=user_id,
            tenant_id="t",
            session_id="fixture",
            db=app.state.db,
            container=app.state.container,
        )
        try:
            while True:
                await router.route(context, await websocket.receive_json())
                app.state.connection = websocket.scope.get(STATE_KEY)
        except WebSocketDisconnect:
            pass
        finally:
            await close_device_connection(websocket.scope)
            app.state.closed.set()

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", log_level="critical", lifespan="off")
    )
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started
    address = f"127.0.0.1:{listener.getsockname()[1]}"
    try:
        yield SimpleNamespace(broker=broker, app=app, address=address)
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, 5)
        listener.close()
        keys = [key async for key in redis.scan_iter(match=f"{prefix}:*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()


async def receive(websocket):
    return json.loads(await asyncio.wait_for(websocket.recv(), 3))


async def register(websocket, device_id="d"):
    await websocket.send(
        json.dumps(
            {
                "type": "computer_use_device",
                "device_id": device_id,
                "scope": {"tenant_id": "t", "project_id": "p"},
                "tool_definitions": [DEFINITION],
            }
        )
    )
    assert await receive(websocket) == {
        "type": "computer_use_device_ready",
        "device_id": device_id,
        "ready": True,
    }


async def claim(client, request_id, **kwargs):
    return await client.post(
        f"/api/v1/agent/device/requests/{request_id}/claim", json={"device_id": "d"}, **kwargs
    )


async def complete(websocket, request_id, *, image=False):
    await websocket.send(
        json.dumps(
            {
                "type": "computer_use_result",
                "request_id": request_id,
                "output_json": '{"snapshot_id":"fresh"}',
                "is_error": False,
                "media": [
                    {"artifact_id": "image", "mime_type": "image/png", "size_bytes": len(PNG)}
                ]
                if image
                else [],
            }
        )
    )
    if image:
        await websocket.send(
            json.dumps(
                {
                    "type": "computer_use_media",
                    "request_id": request_id,
                    "artifact_id": "image",
                    "mime_type": "image/png",
                    "offset": 0,
                    "data_base64": base64.b64encode(PNG).decode(),
                    "eof": True,
                }
            )
        )


async def test_real_socket_pause_wait_resume_and_disconnect_cancellation(transport):
    from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError
    from src.infrastructure.agent.tools.result import ToolControlOutcome
    from src.tests.integration.agent.test_native_computer_control import result_frame, state_frame

    headers = {"Authorization": "Bearer fixture-u"}
    async with connect(f"ws://{transport.address}/native-test", additional_headers=headers) as ws:
        await register(ws)
        task = asyncio.create_task(
            transport.broker.request(authorization(), DEFINITION["name"], {"app": "fixture"})
        )
        request = await receive(ws)
        request_id = request["request_id"]
        async with httpx.AsyncClient(base_url=f"http://{transport.address}") as client:
            response = await claim(client, request_id, headers=headers)
        assert response.status_code == 200
        generation = str(uuid4())
        await ws.send(
            json.dumps(
                {"type": "computer_use_control_state", **state_frame(request_id, generation)}
            )
        )
        await ws.send(
            json.dumps({"type": "computer_use_result", **result_frame(request_id, generation)})
        )
        result = await asyncio.wait_for(task, 3)
        assert result.control_outcome is ToolControlOutcome.USER_PAUSED
        assert await asyncio.wait_for(result.control_wait(), 1) is None
    await asyncio.wait_for(transport.app.state.closed.wait(), 3)
    with pytest.raises(DeviceBridgeError, match="control_cancelled"):
        await result.control_wait()


async def test_proxy_two_devices_selector_is_removed_before_native_schema_and_result_roundtrip(
    transport, monkeypatch
):
    headers = {"Authorization": "Bearer fixture-u"}
    async with (
        connect(f"ws://{transport.address}/native-test", additional_headers=headers) as first,
        connect(f"ws://{transport.address}/native-test", additional_headers=headers) as selected,
    ):
        await register(first, "device-a")
        await register(selected, "device-b")
        tools = await native.create_native_computer_tools(
            tenant_id="t", project_id="p", user_id="u", broker=transport.broker
        )
        monkeypatch.setattr(
            native,
            "authorize_native_call",
            AsyncMock(return_value=authorization(device_id="device-b")),
        )
        context = ToolContext(
            session_id="session",
            message_id="message",
            call_id="call",
            agent_name="fixture",
            conversation_id="conversation",
            user_id="u",
            tenant_id="t",
            project_id="p",
        )
        task = asyncio.create_task(
            tools[DEFINITION["name"]].execute(context, app="fixture", device_id="device-b")
        )
        request = await receive(selected)
        async with httpx.AsyncClient(base_url=f"http://{transport.address}") as client:
            response = await client.post(
                f"/api/v1/agent/device/requests/{request['request_id']}/claim",
                json={"device_id": "device-b"},
                headers=headers,
            )
        assert response.status_code == 200
        payload = response.json()
        native_input = json.loads(payload["input_json"])
        assert payload["device_id"] == "device-b"
        assert native_input == {"app": "fixture"}
        assert validator(DEFINITION["inputSchema"]).is_valid(native_input)
        assert not validator(DEFINITION["inputSchema"]).is_valid(
            {**native_input, "device_id": "device-b"}
        )
        await complete(selected, request["request_id"])
        result = await asyncio.wait_for(task, 3)
        assert not result.is_error and json.loads(result.output) == {"snapshot_id": "fresh"}
        # A request must not leak to the unselected, authenticated device.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(first.recv(), 0.05)


async def test_real_websocket_registration_http_claim_png_result_and_session_release(transport):
    async with connect(
        f"ws://{transport.address}/native-test",
        additional_headers={"Authorization": "Bearer fixture-u"},
    ) as websocket:
        await register(websocket)
        assert await transport.broker.describe_tools(
            user_id="u", tenant_id="t", project_id="p"
        ) == [DEFINITION]
        task = asyncio.create_task(
            transport.broker.request(authorization(), DEFINITION["name"], {"app": "fixture"})
        )
        event = await receive(websocket)
        assert set(event) == {"type", "request_id", "expires_at"}
        assert event["type"] == "computer_use_request"
        assert isinstance(event["expires_at"], int)
        request_id = event["request_id"]
        async with httpx.AsyncClient(base_url=f"http://{transport.address}") as client:
            assert (await claim(client, request_id)).status_code == 401
            assert (
                await claim(client, request_id, headers={"Authorization": "Bearer fixture-other"})
            ).status_code == 409
            response = await claim(
                client, request_id, headers={"Authorization": "Bearer fixture-u"}
            )
            assert response.status_code == 200
            assert response.json()["user_id"] == "u" and "connection_id" not in response.json()
        await complete(websocket, request_id, image=True)
        result = await asyncio.wait_for(task, 3)
        assert (
            result.attachments[0].content == PNG and result.attachments[0].mime_type == "image/png"
        )
        assert "iVBOR" not in result.output and "base64" not in result.output
        await transport.broker.cancel_session(
            "run", user_id="u", tenant_id="t", project_id="p", session_id="session"
        )
        assert await receive(websocket) == {"type": "computer_use_cancel", "request_id": request_id}


@pytest.mark.parametrize("catalog_changed", [False, True])
async def test_read_only_connector_claim_uses_current_authenticated_operation_metadata(
    transport, catalog_changed
):
    declared = connector_definition(connector_row())
    async with connect(
        f"ws://{transport.address}/native-test",
        additional_headers={"Authorization": "Bearer fixture-u"},
    ) as websocket:

        async def announce(definition):
            await websocket.send(
                json.dumps(
                    {
                        "type": "computer_use_device",
                        "device_id": "d",
                        "scope": {"tenant_id": "t", "project_id": "p"},
                        "tool_definitions": [definition],
                    }
                )
            )
            assert await receive(websocket) == {
                "type": "computer_use_device_ready",
                "device_id": "d",
                "ready": True,
            }

        await announce(declared)
        task = asyncio.create_task(
            transport.broker.request(authorization(), declared["name"], connector_arguments())
        )
        request_id = (await receive(websocket))["request_id"]
        if catalog_changed:
            await announce(connector_definition())
        async with httpx.AsyncClient(
            base_url=f"http://{transport.address}", headers={"Authorization": "Bearer fixture-u"}
        ) as client:
            response = await claim(client, request_id)
            assert response.status_code == (409 if catalog_changed else 200)
            if catalog_changed:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert (await receive(websocket))["type"] == "computer_use_cancel"
            else:
                assert response.json()["tool_effect"] == "read"
                assert response.json()["allowed_mcp_servers"] == []
                await complete(websocket, request_id)
                assert not (await asyncio.wait_for(task, 3)).is_error


async def test_disconnect_revokes_claimed_work_and_registry_lease(transport):
    async with connect(
        f"ws://{transport.address}/native-test",
        additional_headers={"Authorization": "Bearer fixture-u"},
    ) as websocket:
        await register(websocket)
        task = asyncio.create_task(
            transport.broker.request(authorization(), DEFINITION["name"], {"app": "fixture"})
        )
        request_id = (await receive(websocket))["request_id"]
        async with httpx.AsyncClient(
            base_url=f"http://{transport.address}", headers={"Authorization": "Bearer fixture-u"}
        ) as client:
            assert (await claim(client, request_id)).status_code == 200
    await asyncio.wait_for(transport.app.state.closed.wait(), 3)
    result = await asyncio.wait_for(task, 3)
    assert json.loads(result.output) == {"error": "action_outcome_unknown", "retry_allowed": False}
    assert not transport.app.state.connection.task or transport.app.state.connection.task.done()
    listed = await transport.broker.devices.list(user_id="u", tenant_id="t", project_id="p")
    assert all(not device["tool_definitions"] for device in listed)


async def test_disabled_empty_catalog_revokes_pending_claim_and_heartbeat_keeps_it_empty(transport):
    async with connect(
        f"ws://{transport.address}/native-test",
        additional_headers={"Authorization": "Bearer fixture-u"},
    ) as websocket:
        await register(websocket)
        task = asyncio.create_task(
            transport.broker.request(authorization(), DEFINITION["name"], {"app": "fixture"})
        )
        request_id = (await receive(websocket))["request_id"]
        await websocket.send(
            json.dumps(
                {
                    "type": "computer_use_device",
                    "device_id": "d",
                    "scope": {"tenant_id": "t", "project_id": "p"},
                    "tool_definitions": [],
                }
            )
        )
        responses = [await receive(websocket), await receive(websocket)]
        assert {"type": "computer_use_device_ready", "device_id": "d", "ready": False} in responses
        assert {"type": "computer_use_cancel", "request_id": request_id} in responses
        await transport.broker.devices.heartbeat(transport.app.state.connection.connection_id)
        assert (
            await transport.broker.describe_tools(user_id="u", tenant_id="t", project_id="p") == []
        )
        async with httpx.AsyncClient(
            base_url=f"http://{transport.address}", headers={"Authorization": "Bearer fixture-u"}
        ) as client:
            response = await client.get(
                "/api/v1/agent/device/status",
                params={"device_id": "d", "tenant_id": "t", "project_id": "p"},
            )
            assert response.status_code == 200 and response.json()["ready"] is False
            assert (await claim(client, request_id)).status_code == 409
        assert (
            json.loads((await asyncio.wait_for(task, 3)).output)["error"]
            == "action_outcome_unknown"
        )


async def test_cancel_one_session_keeps_other_completed_sessions_active(transport):
    async with connect(
        f"ws://{transport.address}/native-test",
        additional_headers={"Authorization": "Bearer fixture-u"},
    ) as websocket:
        await register(websocket)
        request_ids = []
        for session in ("parent-session", "child-session"):
            task = asyncio.create_task(
                transport.broker.request(
                    authorization(session_id=session), DEFINITION["name"], {"app": "fixture"}
                )
            )
            request_id = (await receive(websocket))["request_id"]
            request_ids.append(request_id)
            async with httpx.AsyncClient(
                base_url=f"http://{transport.address}",
                headers={"Authorization": "Bearer fixture-u"},
            ) as client:
                assert (await claim(client, request_id)).status_code == 200
            await complete(websocket, request_id)
            await task
        await transport.broker.cancel_session(
            "run", user_id="u", tenant_id="t", project_id="p", session_id="parent-session"
        )
        assert await receive(websocket) == {
            "type": "computer_use_cancel",
            "request_id": request_ids[0],
        }
        assert (await transport.broker.read(store.request_key(request_ids[1])))[
            "status"
        ] == "completed"
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(websocket.recv(), 0.15)


async def test_expired_authority_cannot_consume_request_and_can_be_stopped(transport):
    async with connect(
        f"ws://{transport.address}/native-test",
        additional_headers={"Authorization": "Bearer fixture-u"},
    ) as websocket:
        await register(websocket)
        task = asyncio.create_task(
            transport.broker.request(authorization(), DEFINITION["name"], {"app": "fixture"})
        )
        request_id = (await receive(websocket))["request_id"]
        transport.app.state.run.revision += 1
        async with httpx.AsyncClient(
            base_url=f"http://{transport.address}", headers={"Authorization": "Bearer fixture-u"}
        ) as client:
            assert (await claim(client, request_id)).status_code == 409
        assert (await transport.broker.read(store.request_key(request_id)))["status"] == "requested"
        await transport.broker.cancel_run("run", user_id="u", tenant_id="t", project_id="p")
        assert (await receive(websocket))["type"] == "computer_use_cancel"
        assert (await asyncio.wait_for(task, 3)).is_error


@pytest.mark.parametrize("expire_during_policy", [False, True])
async def test_child_claim_requires_live_owner_bound_to_completed_parent(
    transport, monkeypatch, expire_during_policy
):
    from src.infrastructure.adapters.secondary.persistence.subagent_owner_model_v2 import (
        SubAgentOwnerLeaseV2,
    )
    from src.infrastructure.adapters.secondary.persistence.subagent_run_snapshot_model_v2 import (
        SubAgentRunSnapshotV2,
    )
    from src.infrastructure.agent.subagent import owner_lease_v2

    now = datetime.now(UTC)
    clock = [now]
    token = "fixture-child-owner"
    owner = SimpleNamespace(
        state="active", owner_token=token, expires_at=now + timedelta(seconds=30)
    )
    snapshot = SimpleNamespace(
        tenant_id="t",
        project_id="p",
        runs={
            "child-run": {
                "status": "running",
                "metadata": {"chat_permission_run_id": "run", "chat_permission_mode": "ask"},
            }
        },
    )
    transport.app.state.db.get.side_effect = (
        lambda model, *_args, **_kwargs: owner
        if model is SubAgentOwnerLeaseV2
        else (snapshot if model is SubAgentRunSnapshotV2 else None)
    )
    monkeypatch.setattr(
        owner_lease_v2, "database_now_v2", AsyncMock(side_effect=lambda _db: clock[0])
    )
    if expire_during_policy:

        async def policy(_conversation):
            clock[0] = now + timedelta(seconds=31)
            return {"permission_mode": "ask"}

        monkeypatch.setattr(routes, "load_chat_permission_policy", policy)
    transport.app.state.run.status = "completed"
    async with connect(
        f"ws://{transport.address}/native-test",
        additional_headers={"Authorization": "Bearer fixture-u"},
    ) as websocket:
        await register(websocket)
        auth = authorization(
            child_run_id="child-run", child_owner_digest=hashlib.sha256(token.encode()).hexdigest()
        )
        task = asyncio.create_task(
            transport.broker.request(auth, DEFINITION["name"], {"app": "fixture"})
        )
        request_id = (await receive(websocket))["request_id"]
        async with httpx.AsyncClient(
            base_url=f"http://{transport.address}", headers={"Authorization": "Bearer fixture-u"}
        ) as client:
            response = await claim(client, request_id)
        if expire_during_policy:
            assert response.status_code == 409
            assert (await transport.broker.read(store.request_key(request_id)))[
                "status"
            ] == "requested"
            await transport.broker.cancel_run("run", user_id="u", tenant_id="t", project_id="p")
            assert (await asyncio.wait_for(task, 3)).is_error
        else:
            assert response.status_code == 200 and response.json()["child_run_id"] == "child-run"
            assert response.json()["browser_scope"] == {
                "execution_id": "child-run",
                "main_conversation_id": auth.conversation_id,
                "parent_run_id": auth.run_id,
                "engine_session_id": auth.session_id,
                "is_child": True,
            }
            assert "child_owner_digest" not in response.json()
            await complete(websocket, request_id)
            assert not (await asyncio.wait_for(task, 3)).is_error


async def test_competing_http_claims_execute_exactly_once(transport):
    async with connect(
        f"ws://{transport.address}/native-test",
        additional_headers={"Authorization": "Bearer fixture-u"},
    ) as websocket:
        await register(websocket)
        task = asyncio.create_task(
            transport.broker.request(authorization(), DEFINITION["name"], {"app": "fixture"})
        )
        request_id = (await receive(websocket))["request_id"]
        async with httpx.AsyncClient(
            base_url=f"http://{transport.address}", headers={"Authorization": "Bearer fixture-u"}
        ) as client:
            responses = await asyncio.gather(claim(client, request_id), claim(client, request_id))
        assert sorted(response.status_code for response in responses) == [200, 409]
        await complete(websocket, request_id)
        assert not (await asyncio.wait_for(task, 3)).is_error


async def test_policy_downgrade_rejects_previously_admitted_full_access(transport):
    transport.app.state.run.permission_profile = "full_access"
    transport.app.state.run.authorization_snapshot["effective_permission_mode"] = "full_access"
    async with connect(
        f"ws://{transport.address}/native-test",
        additional_headers={"Authorization": "Bearer fixture-u"},
    ) as websocket:
        await register(websocket)
        task = asyncio.create_task(
            transport.broker.request(
                authorization(permission_profile="full_access"),
                DEFINITION["name"],
                {"app": "fixture"},
            )
        )
        request_id = (await receive(websocket))["request_id"]
        async with httpx.AsyncClient(
            base_url=f"http://{transport.address}", headers={"Authorization": "Bearer fixture-u"}
        ) as client:
            assert (await claim(client, request_id)).status_code == 409
        assert (await transport.broker.read(store.request_key(request_id)))["status"] == "requested"
        await transport.broker.cancel_run("run", user_id="u", tenant_id="t", project_id="p")
        assert (await asyncio.wait_for(task, 3)).is_error
