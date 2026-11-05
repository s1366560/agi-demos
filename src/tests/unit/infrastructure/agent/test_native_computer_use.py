"""Cloud native tools preserve scoped authority and real image attachments."""

from __future__ import annotations

import base64
import inspect
import json
import struct
import zlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services import chat_run_tool_permission_v2 as chat
from src.domain.model.artifact.artifact import Artifact, ArtifactCategory, ArtifactStatus
from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.native_computer_use.contracts import READ_TOOL_NAMES, TOOL_NAMES
from src.infrastructure.agent.native_computer_use.image_messages import (
    hydrate_image_messages,
    persist_tool_attachments,
    tool_image_message,
)
from src.infrastructure.agent.processor.message_utils import extract_user_query
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    ProcessorState,
    SessionProcessor,
)
from src.infrastructure.agent.tools import native_computer_use as native
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolAttachment, ToolResult
from src.infrastructure.plugins.v2.agent_operation_tool_contributions import (
    lease_operation_tool_definitions_v2,
)
from src.infrastructure.plugins.v2.model_request_log import prepared_model_request_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit
SCOPE = {"tenant_id": "tenant", "project_id": "project", "conversation_id": "conversation"}


def image_bytes() -> bytes:
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixels = (b"\x00" + b"\xff\x00\x00" * 23) * 17
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 23, 17, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


class Artifacts:
    def __init__(self) -> None:
        self.artifacts = {}
        self.content = {}

    async def create_artifact(self, *, file_content, filename, **kwargs):
        artifact = Artifact(
            id="artifact-1",
            filename=filename,
            mime_type="image/png",
            category=ArtifactCategory.IMAGE,
            size_bytes=len(file_content),
            object_key="private/object",
            status=ArtifactStatus.READY,
            project_id=kwargs["project_id"],
            tenant_id=kwargs["tenant_id"],
            conversation_id=kwargs["conversation_id"],
        )
        self.artifacts[artifact.id] = artifact
        self.content[artifact.id] = file_content
        return artifact

    async def get_artifact(self, artifact_id):
        return self.artifacts.get(artifact_id)

    async def get_artifact_bytes(self, artifact_id):
        return self.content.get(artifact_id)


def context() -> ToolContext:
    return ToolContext(
        session_id="engine-session",
        message_id="message",
        call_id="call-1",
        agent_name="main",
        user_id="user",
        conversation_id="conversation",
        tenant_id="tenant",
        project_id="project",
        runtime_context={"run_id": "run", "round": 2},
    )


def setup_guard(monkeypatch, *, mode="ask"):
    guard = chat.ChatRunToolPermissionV2(
        operation=SimpleNamespace(),
        run_id="run",
        identity=("tenant", "project", "conversation", "user"),
        mode=mode,
        sessions=None,
    )
    monkeypatch.setattr(native, "current_approved_run_guard_v2", lambda: None)
    monkeypatch.setattr(native, "current_chat_run_guard_v2", lambda: guard)
    monkeypatch.setattr(chat, "current_chat_run_guard_v2", lambda: guard)
    monkeypatch.setattr(chat.ChatRunToolPermissionV2, "revalidate_current_authority", AsyncMock())
    monkeypatch.setattr(native, "_identity", lambda _operation: guard.identity)
    monkeypatch.setattr(
        native,
        "_read_run",
        AsyncMock(
            return_value=SimpleNamespace(
                permission_profile="read_only",
                run_kind="chat",
                revision=7,
                plan_version_id=None,
            )
        ),
    )
    return guard


async def test_claimed_receipt_is_exact_and_can_be_read_without_reconsuming(monkeypatch):
    guard = setup_guard(monkeypatch)
    arguments = {"app": "pid:12", "x": 5, "y": 8, "device_id": "device"}
    with chat.approved_chat_tool_call_v2("computer_click", arguments):
        assert chat.current_claimed_chat_tool_invocation_v2("computer_click", arguments) is None
        chat.claim_chat_tool_invocation_v2("computer_click", arguments, permission="mcp")
        assert chat.current_claimed_chat_tool_invocation_v2("computer_click", arguments) is guard
        assert (
            chat.current_claimed_chat_tool_invocation_v2("computer_click", {**arguments, "x": 6})
            is None
        )
        authorization = await native.authorize_native_call(context(), "computer_click", arguments)
        assert authorization.approved_tools == ("computer_click",)
        assert authorization.authorization_revision == 7
        assert authorization.round == 2
        assert authorization.session_id == native.native_session_id("engine-session", "run")
        assert chat.current_claimed_chat_tool_invocation_v2("computer_click", arguments) is guard
    assert chat.current_claimed_chat_tool_invocation_v2("computer_click", arguments) is None


async def test_unclaimed_mutation_and_forged_scope_are_denied(monkeypatch):
    setup_guard(monkeypatch)
    monkeypatch.setattr(chat.ChatRunToolPermissionV2, "decision", AsyncMock(return_value="ask"))
    with pytest.raises(RuntimeV2Error, match="approval"):
        await native.authorize_native_call(context(), "computer_click", {"app": "pid:12"})
    ctx = context()
    ctx.user_id = "another-user"
    with pytest.raises(RuntimeV2Error, match="scope"):
        await native.authorize_native_call(ctx, "computer_get_app_state", {"app": "pid:12"})


async def test_claimed_receipt_still_revalidates_peer_and_current_policy(monkeypatch):
    setup_guard(monkeypatch)
    fresh = AsyncMock(
        side_effect=RuntimeV2Error(
            "peer_sender_permission_denied", "Sending run no longer authorizes this operation"
        )
    )
    monkeypatch.setattr(chat.ChatRunToolPermissionV2, "revalidate_current_authority", fresh)
    arguments = {"app": "pid:12", "x": 1, "y": 2}
    with chat.approved_chat_tool_call_v2("computer_click", arguments):
        chat.claim_chat_tool_invocation_v2("computer_click", arguments, permission="mcp")
        with pytest.raises(RuntimeV2Error, match="Sending run"):
            await native.authorize_native_call(context(), "computer_click", arguments)
    fresh.assert_awaited_once_with("mcp")


async def test_discovery_is_user_scoped_and_strips_device_selector(monkeypatch):
    broker = SimpleNamespace(
        describe_tools=AsyncMock(
            return_value=[
                {
                    "name": "computer_get_app_state",
                    "description": "Capture",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"app": {"type": "string"}},
                        "required": ["app"],
                        "additionalProperties": False,
                    },
                }
            ]
        ),
        request=AsyncMock(return_value=ToolResult(output="state")),
    )
    assert (
        await native.create_native_computer_tools(
            tenant_id="tenant",
            project_id="project",
            user_id=None,
            broker=broker,
        )
        == {}
    )
    broker.describe_tools.assert_not_awaited()
    tools = await native.create_native_computer_tools(
        tenant_id="tenant",
        project_id="project",
        user_id="user",
        broker=broker,
    )
    broker.describe_tools.assert_awaited_once_with(
        tenant_id="tenant", project_id="project", user_id="user"
    )
    setup_guard(monkeypatch, mode="full_access")
    monkeypatch.setattr(chat.ChatRunToolPermissionV2, "decision", AsyncMock(return_value="allow"))
    result = await tools["computer_get_app_state"].execute(
        context(), app="pid:12", device_id="device"
    )
    assert result.output == "state"
    authorization, tool_name, args = broker.request.call_args.args
    assert authorization.device_id == "device" and tool_name == "computer_get_app_state"
    assert args == {"app": "pid:12"}
    assert "device_id" in tools[tool_name].parameters["properties"]
    assert tools[tool_name].permission == "read"


async def test_artifact_reference_hydrates_actual_image_bytes_without_durable_base64():
    content = image_bytes()
    service = Artifacts()
    events, references = await persist_tool_attachments(
        service,
        [ToolAttachment(name="native-id", content=content, mime_type="image/png")],
        scope=SCOPE,
        tool_name="computer_get_app_state",
        tool_execution_id="execution",
    )
    durable = tool_image_message("call-1", references)
    assert events[0].artifact_id == "artifact-1"
    assert references[0]["width"] == 23 and references[0]["height"] == 17
    assert "base64" not in json.dumps(durable)
    hydrated = await hydrate_image_messages([durable], service, SCOPE)
    url = hydrated[0]["content"][1]["image_url"]["url"]
    assert base64.b64decode(url.split(",", 1)[1]) == content
    assert "_native_tool_images" not in hydrated[0]
    recorded = prepared_model_request_v2({"messages": hydrated})
    assert (
        recorded["messages"][0]["content"][1]["image_url"]["media_artifact"]["artifact_id"]
        == "artifact-1"
    )
    assert "base64" not in json.dumps(durable)
    assert (
        extract_user_query([{"role": "user", "content": "click the red circle"}, durable])
        == "click the red circle"
    )
    assert content.hex() not in repr(ToolAttachment(name="safe", content=content))


async def test_rehydration_rejects_cross_scope_and_changed_bytes():
    service = Artifacts()
    _, references = await persist_tool_attachments(
        service,
        [ToolAttachment(name="native-id", content=image_bytes(), mime_type="image/png")],
        scope=SCOPE,
        tool_name="computer_get_app_state",
        tool_execution_id=None,
    )
    message = tool_image_message("call", references)
    with pytest.raises(RuntimeV2Error, match="scope"):
        await hydrate_image_messages([message], service, {**SCOPE, "tenant_id": "another"})
    service.content["artifact-1"] = b"replaced"
    with pytest.raises(RuntimeV2Error, match="changed"):
        await hydrate_image_messages([message], service, SCOPE)


def test_actual_provider_media_is_redacted_without_changing_transmitted_body():
    encoded = base64.b64encode(image_bytes()).decode()
    body = {
        "model": "vision",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": encoded},
                    },
                ],
            }
        ],
        "contents": [{"parts": [{"inlineData": {"mimeType": "image/png", "data": encoded}}]}],
    }
    recorded = prepared_model_request_v2(body)
    assert encoded not in json.dumps(recorded)
    assert encoded in json.dumps(body)
    assert recorded["model"] == "vision"
    assert prepared_model_request_v2(recorded) == recorded


def test_roster_has_all_declared_tools_and_sessions_are_separate():
    assert len(TOOL_NAMES) == 29 and len(READ_TOOL_NAMES) == 8
    assert "computer_audio_read" in READ_TOOL_NAMES
    assert "computer_connector_call" not in READ_TOOL_NAMES
    assert native.native_session_id("same-conversation", "parent") != native.native_session_id(
        "same-conversation", "child"
    )


def test_firstparty_guidance_is_packaged_and_exposed_only_with_real_observation_tool():
    from pathlib import Path

    assert native.native_computer_guidance({"read_file", "web_search"}) == ""
    assert native.native_computer_guidance({"computer_capabilities"}) == ""
    body = native.native_computer_guidance({"computer_get_app_state", "computer_click"})
    assert 'coordinate_space: "screenshot"' in body
    assert "observe again" in body and "action_outcome_unknown" in body
    source = Path("agi-stack/apps/desktop/cua-plugin/skills/computer-use/SKILL.md").read_text()
    assert body == source.split("---", 2)[2].strip() + "\n"


async def test_session_cleanup_does_not_cancel_other_run_sessions(monkeypatch):
    setup_guard(monkeypatch)
    broker = SimpleNamespace(cancel_session=AsyncMock())
    monkeypatch.setattr(native, "current_native_computer_broker", lambda: broker)
    await native.cancel_native_computer_run("engine-session")
    broker.cancel_session.assert_awaited_once_with(
        "run",
        session_id=native.native_session_id("engine-session", "run"),
        user_id="user",
        tenant_id="tenant",
        project_id="project",
    )


async def test_child_authority_uses_only_live_owner_token_and_independent_session(monkeypatch):
    from dataclasses import replace

    from src.infrastructure.agent.subagent.owner_lease_v2 import current_owner_v2

    guard = replace(setup_guard(monkeypatch, mode="full_access"), child_run_id="child-run")
    monkeypatch.setattr(native, "current_chat_run_guard_v2", lambda: guard)
    monkeypatch.setattr(chat.ChatRunToolPermissionV2, "decision", AsyncMock(return_value="allow"))
    ctx = context()
    ctx.runtime_context["run_id"] = "child-run"
    with pytest.raises(RuntimeV2Error, match="owner"):
        await native.authorize_native_call(ctx, "computer_get_app_state", {"app": "pid:12"})
    token = current_owner_v2.set(
        SimpleNamespace(
            run_id="child-run", conversation_id="conversation", token="private-owner-token"
        )
    )
    try:
        authorization = await native.authorize_native_call(
            ctx, "computer_get_app_state", {"app": "pid:12"}
        )
        assert authorization.child_run_id == "child-run"
        assert (
            authorization.child_owner_digest
            and authorization.child_owner_digest != "private-owner-token"
        )
        assert authorization.session_id == native.native_session_id("engine-session", "child-run")
        assert authorization.run_kind == "chat"
        assert "private-owner-token" not in repr(authorization)
    finally:
        current_owner_v2.reset(token)


@pytest.mark.parametrize("failure", [False, True])
async def test_processor_termination_releases_completed_native_session(monkeypatch, failure):
    cleanup = AsyncMock()
    monkeypatch.setattr(native, "cancel_native_computer_run", cleanup)
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.boundary.attach_current_generation_v2", lambda _ctx: None
    )
    processor = SessionProcessor(config=ProcessorConfig(model="test"), tools=[])
    processor._resolve_agent_loop = lambda: None

    async def loop(*_args):
        if failure:
            raise RuntimeError("loop failed")
        yield {"type": "done"}

    processor._dispatch_external_loop = loop
    if failure:
        with pytest.raises(RuntimeError, match="loop failed"):
            _ = [event async for event in processor.process("engine-session", [])]
    else:
        _ = [event async for event in processor.process("engine-session", [])]
    cleanup.assert_awaited_once_with("engine-session")


async def test_hitl_pause_preserves_native_session_and_resume_uses_same_identity(monkeypatch):
    cleanup = AsyncMock()
    monkeypatch.setattr(native, "cancel_native_computer_run", cleanup)
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.boundary.attach_current_generation_v2", lambda _ctx: None
    )
    processor = SessionProcessor(config=ProcessorConfig(model="test"), tools=[])
    processor._resolve_agent_loop = lambda: None

    async def paused(*_args):
        processor._state = ProcessorState.WAITING_PERMISSION
        yield {"type": "permission_asked"}

    processor._dispatch_external_loop = paused
    _ = [event async for event in processor.process("engine-session", [])]
    cleanup.assert_not_awaited()
    first_identity = native.native_session_id("engine-session", "run")

    async def resumed(*_args):
        processor._state = ProcessorState.COMPLETED
        yield {"type": "done"}

    processor._dispatch_external_loop = resumed
    _ = [event async for event in processor.process("engine-session", [])]
    assert native.native_session_id("engine-session", "run") == first_identity
    cleanup.assert_awaited_once_with("engine-session")


async def test_toolinfo_lease_preserves_real_context_and_revokes_after_disposal():
    disposers = []

    class Operation:
        async def effect(self, setup, **_kwargs):
            result = setup()
            if inspect.isawaitable(result):
                result = await result
            disposers.append(result)

    seen = []

    async def execute(ctx, **_arguments):
        seen.append(ctx)
        return ToolResult(output="ok")

    info = ToolInfo(
        name="computer_list_apps",
        description="List",
        parameters={"type": "object"},
        execute=execute,
    )
    tool_set = await lease_operation_tool_definitions_v2(
        operation=Operation(),
        source_id="native",
        definitions=convert_tools({info.name: info}),
    )
    leased = tool_set.definitions[0]._tool_instance
    assert isinstance(leased, ToolInfo)
    ctx = context()
    await leased.execute(ctx)
    assert seen == [ctx]
    disposers[0]()
    with pytest.raises(RuntimeV2Error, match="no longer active"):
        await leased.execute(ctx)


@pytest.mark.parametrize("blocked", [False, True])
async def test_processor_consumes_images_as_model_blocks_and_withholds_rejected_attachments(
    monkeypatch, blocked
):
    content = image_bytes()
    artifact_service = Artifacts()
    executions = []
    received_messages = []

    async def execute(ctx, **arguments):
        executions.append((ctx, arguments))
        return ToolResult(
            output='{"state":"captured"}',
            attachments=[
                ToolAttachment(name="native-id", content=content, mime_type="image/png"),
            ],
        )

    async def generate(_stream, messages, **_kwargs):
        received_messages.append(messages)
        if len(received_messages) == 1:
            yield SimpleNamespace(
                type=StreamEventType.TOOL_CALL_START,
                data={"call_id": "image-call", "name": "computer_get_app_state"},
            )
            yield SimpleNamespace(
                type=StreamEventType.TOOL_CALL_END,
                data={
                    "call_id": "image-call",
                    "name": "computer_get_app_state",
                    "arguments": {"app": "pid:12"},
                },
            )
            yield SimpleNamespace(type=StreamEventType.FINISH, data={"reason": "tool_calls"})
        else:
            yield SimpleNamespace(
                type=StreamEventType.TEXT_END, data={"full_text": "Image inspected."}
            )
            yield SimpleNamespace(type=StreamEventType.FINISH, data={"reason": "stop"})

    monkeypatch.setattr("src.infrastructure.agent.processor.processor.LLMStream.generate", generate)
    info = ToolInfo(
        name="computer_get_app_state",
        description="Capture",
        permission="read",
        execute=execute,
        parameters={
            "type": "object",
            "properties": {"app": {"type": "string"}},
            "required": ["app"],
        },
    )
    processor = SessionProcessor(
        config=ProcessorConfig(model="test", run_id="run"),
        tools=convert_tools({info.name: info}),
        artifact_service=artifact_service,
    )
    processor._langfuse_context = {**SCOPE, "user_id": "user"}
    processor._artifact_handler.set_langfuse_context(processor._langfuse_context)
    if blocked:
        processor._apply_tool_result_policy = AsyncMock(return_value=("rejected", {}, True, True))
    messages = [{"role": "user", "content": "Inspect the image."}]
    events = [event async for event in processor._process_step("engine-session", messages)]
    processor._append_tool_results_to_messages(messages)
    assert executions[0][0].runtime_context == {"run_id": "run", "round": 1}
    assert "base64" not in json.dumps(messages)
    assert "base64" not in json.dumps([event for event in events if isinstance(event, dict)])
    if blocked:
        assert not artifact_service.artifacts
        assert not any(message.get("_native_tool_images") for message in messages)
    else:
        assert artifact_service.artifacts
        assert any(message.get("_native_tool_images") for message in messages)
        _ = [event async for event in processor._process_step("engine-session", messages)]
        urls = [
            part["image_url"]["url"]
            for message in received_messages[1]
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if isinstance(part, dict) and part.get("type") == "image_url"
        ]
        assert len(urls) == 1 and base64.b64decode(urls[0].split(",", 1)[1]) == content
        assert "base64" not in json.dumps(messages)
