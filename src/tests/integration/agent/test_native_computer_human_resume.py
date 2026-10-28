"""Cooperative cloud HITL resume over a real Redis/WebSocket device transport."""

from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from websockets.asyncio.client import connect

from src.application.services import (
    approved_run_tool_permission_v2 as approved,
    chat_run_tool_permission_v2 as chat,
)
from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.hitl.coordinator import HITLCoordinator, ResolveResult
from src.infrastructure.agent.native_computer_use.permission_result import (
    input_digest as permission_input_digest,
)
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.tools import native_computer_use as native
from src.tests.integration.agent.test_native_computer_bridge import PNG
from src.tests.integration.agent.test_native_computer_websocket import (
    claim,
    receive,
    register,
    transport as _transport,
)
from src.tests.unit.infrastructure.agent.test_native_computer_use import Artifacts
from src.tests.unit.infrastructure.agent.test_native_permission import decision

pytestmark = pytest.mark.integration
transport = _transport


async def test_native_permission_resume_keeps_session_and_next_model_receives_png(  # noqa: PLR0915 - full protocol scenario
    transport, monkeypatch
):
    guard = chat.ChatRunToolPermissionV2(
        operation=SimpleNamespace(),
        run_id="run",
        identity=("t", "p", "conversation", "u"),
        mode="ask",
        sessions=None,
    )
    for module in (native, chat):
        monkeypatch.setattr(module, "current_chat_run_guard_v2", lambda: guard)
    for module in (native, approved):
        monkeypatch.setattr(module, "current_approved_run_guard_v2", lambda: None)
        monkeypatch.setattr(module, "_identity", lambda _operation: guard.identity)
        monkeypatch.setattr(
            module,
            "_read_run",
            AsyncMock(
                return_value=SimpleNamespace(
                    run_kind="chat",
                    revision=1,
                    permission_profile="read_only",
                    plan_version_id=None,
                )
            ),
        )
    monkeypatch.setattr(chat.ChatRunToolPermissionV2, "revalidate_current_authority", AsyncMock())
    monkeypatch.setattr(native, "current_native_computer_broker", lambda: transport.broker)
    persist = AsyncMock()
    monkeypatch.setattr("src.infrastructure.agent.hitl.coordinator._persist_hitl_request", persist)
    monkeypatch.setattr(
        "src.infrastructure.agent.hitl.coordinator.mark_hitl_request_completed",
        AsyncMock(return_value=True),
    )
    scope = {"user_id": "u", "tenant_id": "t", "project_id": "p", "conversation_id": "conversation"}
    coordinator = HITLCoordinator(conversation_id="conversation", tenant_id="t", project_id="p")
    model_messages = []

    async def generate(_stream, messages, **_kwargs):
        model_messages.append(messages)
        step = len(model_messages)
        if step == 4:
            yield SimpleNamespace(
                type=StreamEventType.TEXT_END, data={"full_text": "Image received."}
            )
            yield SimpleNamespace(type=StreamEventType.FINISH, data={"reason": "stop"})
            return
        name = "request_permission" if step == 2 else "computer_get_app_state"
        arguments = {"decision": decision()} if step == 2 else {"app": "fixture"}
        yield SimpleNamespace(
            type=StreamEventType.TOOL_CALL_START, data={"call_id": f"call-{step}", "name": name}
        )
        yield SimpleNamespace(
            type=StreamEventType.TOOL_CALL_END,
            data={"call_id": f"call-{step}", "name": name, "arguments": arguments},
        )
        yield SimpleNamespace(type=StreamEventType.FINISH, data={"reason": "tool_calls"})

    monkeypatch.setattr("src.infrastructure.agent.processor.processor.LLMStream.generate", generate)
    async with connect(
        f"ws://{transport.address}/native-test",
        additional_headers={"Authorization": "Bearer fixture-u"},
    ) as websocket:
        await register(websocket)
        tools = await native.create_native_computer_tools(
            user_id="u", tenant_id="t", project_id="p", broker=transport.broker
        )
        processor = SessionProcessor(
            config=ProcessorConfig(model="test", run_id="run"),
            tools=convert_tools(tools),
            artifact_service=Artifacts(),
        )
        processor._langfuse_context = scope
        processor._artifact_handler.set_langfuse_context(scope)
        processor._get_hitl_coordinator = lambda: coordinator
        messages = [{"role": "user", "content": "Observe the fixture, then inspect the image."}]
        sessions = []

        async def device():
            for attempt in range(2):
                event = await receive(websocket)
                assert event["type"] == "computer_use_request"
                async with httpx.AsyncClient(
                    base_url=f"http://{transport.address}",
                    headers={"Authorization": "Bearer fixture-u"},
                ) as client:
                    response = await claim(client, event["request_id"])
                    assert response.status_code == 200
                    claim_data = response.json()
                sessions.append(claim_data["session_id"])
                if attempt == 0:
                    output = {
                        "error": "cua_permission_required",
                        "request": {
                            "request_id": "native-pending",
                            "session_id": "cua-cloud-native-fixture",
                            "engine_session_id": claim_data["session_id"],
                            "app": "ai.memstack.cua.fixture",
                            "identity_digest": "fixture-code-identity",
                            "capability": "screenshots",
                            "tool_name": "computer_get_app_state",
                            "input_digest": "exact-arguments",
                        },
                        "scopes": ["once", "session", "always"],
                    }
                    media = []
                else:
                    output = {"snapshot_id": "observed-after-grant"}
                    media = [
                        {"artifact_id": "image", "mime_type": "image/png", "size_bytes": len(PNG)}
                    ]
                await websocket.send(
                    json.dumps(
                        {
                            "type": "computer_use_result",
                            "request_id": event["request_id"],
                            "output_json": json.dumps(output),
                            "is_error": False,
                            "media": media,
                            "authorization_revision": claim_data["authorization_revision"],
                            "permission_required": {
                                "kind": "native_consent",
                                "binding": {
                                    "tool_name": claim_data["tool_name"],
                                    "input_digest": permission_input_digest(
                                        claim_data["input_json"]
                                    ),
                                    "engine_session_id": claim_data["session_id"],
                                    "cell_id": None,
                                    "step_id": None,
                                },
                                "demand": output,
                            }
                            if attempt == 0
                            else None,
                        }
                    )
                )
                if media:
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "computer_use_media",
                                "request_id": event["request_id"],
                                "artifact_id": "image",
                                "mime_type": "image/png",
                                "offset": 0,
                                "data_base64": base64.b64encode(PNG).decode(),
                                "eof": True,
                            }
                        )
                    )

        device_task = asyncio.create_task(device())
        processor._step_count = 1
        _ = [event async for event in processor._process_step("engine-session", messages)]
        processor._append_tool_results_to_messages(messages)
        processor._step_count = 2
        asked = asyncio.Event()
        permission_events = []

        async def permission_step():
            async for event in processor._process_step("engine-session", messages):
                permission_events.append(event)
                if getattr(event, "permission", None) == "computer_use":
                    asked.set()

        human_step = asyncio.create_task(permission_step())
        await asyncio.wait_for(asked.wait(), 3)
        event = next(
            event
            for event in permission_events
            if getattr(event, "permission", None) == "computer_use"
        )
        assert event.metadata["decision"]["risk"]["level"] == "high"
        assert persist.call_args.kwargs["type_data"]["native_binding"]["device_id"] == "d"
        assert not human_step.done()
        assert (
            coordinator.resolve(
                event.request_id,
                {"action": "allow", "granted": True, "scope": "session"},
                tenant_id="t",
                project_id="p",
                conversation_id="conversation",
            )
            == ResolveResult.RESOLVED
        )
        await asyncio.wait_for(human_step, 3)
        processor._append_tool_results_to_messages(messages)
        processor._step_count = 3
        _ = [event async for event in processor._process_step("engine-session", messages)]
        processor._append_tool_results_to_messages(messages)
        await asyncio.wait_for(device_task, 3)
        assert sessions[0] == sessions[1] == native.native_session_id("engine-session", "run")
        assert "base64" not in json.dumps(messages)
        processor._step_count = 4
        _ = [event async for event in processor._process_step("engine-session", messages)]
        urls = [
            part["image_url"]["url"]
            for message in model_messages[-1]
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if isinstance(part, dict) and part.get("type") == "image_url"
        ]
        assert len(urls) == 1 and base64.b64decode(urls[0].split(",", 1)[1]) == PNG
        assert "base64" not in json.dumps(messages)
