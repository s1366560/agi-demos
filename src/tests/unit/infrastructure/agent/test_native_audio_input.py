"""Owned native recordings cross the model boundary only with current authority."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import wave
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.application.services import chat_run_tool_permission_v2 as chat
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.domain.model.artifact.artifact import Artifact, ArtifactCategory, ArtifactStatus
from src.infrastructure.adapters.primary.web.routers.agent import computer_use_steps
from src.infrastructure.agent.native_computer_use import (
    audio_authority as authority,
    audio_messages as audio,
)
from src.infrastructure.agent.native_computer_use.image_messages import (
    hydrate_image_messages,
    persist_tool_attachments,
    tool_image_message,
)
from src.infrastructure.agent.native_computer_use.store import request_key
from src.infrastructure.agent.tools import native_computer_use as native
from src.infrastructure.agent.tools.result import ToolAttachment
from src.infrastructure.plugins.v2.model_request_log import prepared_model_request_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit
SCOPE = {
    "tenant_id": "tenant",
    "project_id": "project",
    "conversation_id": "conversation",
    "user_id": "user",
    "session_id": "session",
}


def wav_bytes(frames=80):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x01\x00" * frames)
    return buffer.getvalue()


class Artifacts:
    def __init__(self):
        self.artifacts = {}
        self.content = {}
        self.byte_reads = 0

    async def create_artifact(self, *, file_content, filename, **kwargs):
        artifact = Artifact(
            id=f"artifact-{len(self.artifacts)}",
            filename=filename,
            mime_type="audio/wav",
            category=ArtifactCategory.AUDIO,
            size_bytes=len(file_content),
            object_key="owned/audio",
            status=ArtifactStatus.READY,
            **{
                key: kwargs[key]
                for key in ("project_id", "tenant_id", "conversation_id", "metadata")
            },
        )
        self.artifacts[artifact.id] = artifact
        self.content[artifact.id] = file_content
        return artifact

    async def get_artifact(self, artifact_id):
        return self.artifacts.get(artifact_id)

    async def get_artifact_bytes(self, artifact_id):
        self.byte_reads += 1
        return self.content.get(artifact_id)


@pytest.fixture
def harness(monkeypatch):
    content = wav_bytes()
    row = SimpleNamespace(
        revision=1, permission_profile="full_access", plan_version_id=None, status="running"
    )
    request = {
        **SCOPE,
        "request_id": "request",
        "session_id": native.native_session_id("session", "run"),
        "run_id": "run",
        "child_run_id": None,
        "status": "completed",
        "is_error": False,
        "authorization_revision": 1,
        "permission_profile": "full_access",
        "plan_version_id": None,
        "device_id": "device",
        "connection_id": "connection",
        "tool_name": "computer_use_execute",
        "media": {
            "native-audio": {
                "mime_type": "audio/wav",
                "size_bytes": len(content),
                "eof": True,
                "parts": ["part"],
            }
        },
    }
    records = {request_key("request"): request}

    async def update(key, change):
        updated = change(records.get(key))
        records[key].clear()
        records[key].update(updated)
        return records[key]

    broker = SimpleNamespace(
        update=update,
        read=AsyncMock(side_effect=lambda key: records.get(key)),
        members=AsyncMock(
            side_effect=lambda _key: [value["request_id"] for value in records.values()]
        ),
        require_live_control_device=AsyncMock(),
        redis=SimpleNamespace(mget=AsyncMock(return_value=[content.hex()])),
    )
    provider = ProviderConfig(
        id=uuid4(),
        name="audio",
        provider_type=ProviderType.OPENAI,
        api_key_encrypted="fixture-unused",
        llm_model="exact-audio-model",
        config={"audio_input_models": ["exact-audio-model"]},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    stored_provider = SimpleNamespace(
        is_active=True,
        is_enabled=True,
        updated_at=provider.updated_at,
        provider_type="openai",
        base_url=None,
        config=dict(provider.config),
    )
    sessions = MagicMock()
    sessions.return_value.__aenter__.return_value = SimpleNamespace(
        get=AsyncMock(return_value=stored_provider),
    )
    identity = ("tenant", "project", "conversation", "user")
    guard = chat.ChatRunToolPermissionV2(
        SimpleNamespace(), "run", identity, "full_access", sessions
    )
    monkeypatch.setattr(authority, "current_approved_run_guard_v2", lambda: None)
    monkeypatch.setattr(authority, "current_chat_run_guard_v2", lambda: guard)
    monkeypatch.setattr(authority, "_identity", lambda _operation: identity)
    monkeypatch.setattr(authority, "_read_run", AsyncMock(return_value=row))
    monkeypatch.setattr(chat.ChatRunToolPermissionV2, "revalidate_current_authority", AsyncMock())
    monkeypatch.setattr(native, "current_native_computer_broker", lambda: broker)
    monkeypatch.setattr(computer_use_steps, "current_agent_servers", AsyncMock(return_value=()))
    service = Artifacts()
    token = audio.bind_audio_context(service, SCOPE, "session")
    yield SimpleNamespace(
        service=service,
        request=request,
        records=records,
        broker=broker,
        provider=provider,
        stored_provider=stored_provider,
        content=content,
        row=row,
    )
    audio.reset_audio_context(token)


async def persist(harness, *, request_id="request"):
    events, references = await persist_tool_attachments(
        harness.service,
        [ToolAttachment("native-audio", harness.content, "audio/wav", request_id)],
        scope=SCOPE,
        tool_name="computer_use_execute",
        tool_execution_id="execution",
    )
    messages = await hydrate_image_messages(
        [tool_image_message("call", references)], harness.service, SCOPE
    )
    return events, references, messages


async def test_owned_recording_hydrates_only_for_declared_model_and_logs_reference(harness):
    events, references, messages = await persist(harness)
    assert events[0].category == "audio"
    assert references[0]["type"] == "artifact_audio"
    assert "base64" not in json.dumps(messages)
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    block = prepared.messages[0]["content"][1]["input_audio"]
    assert block["format"] == "wav"
    assert base64.b64decode(block["data"]) == harness.content
    recorded = prepared_model_request_v2({"messages": prepared.messages})
    logged = recorded["messages"][0]["content"][1]["input_audio"]
    assert logged["data"] == "[artifact bytes omitted]"
    assert logged["media_artifact"] == references[0]
    assert block["data"] not in json.dumps(recorded)
    await prepared.validate()


async def test_default_off_does_not_read_bytes_and_preserves_attachment(harness):
    events, _, messages = await persist(harness)
    prepared = await audio.prepare_audio_input(messages, supported=False, provider=harness.provider)
    assert "not explicitly enabled" in json.dumps(prepared.messages)
    assert not prepared.references and harness.service.byte_reads == 0
    assert harness.service.artifacts[events[0].artifact_id].status == ArtifactStatus.READY


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "other"),
        ("project_id", "other"),
        ("conversation_id", "other"),
        ("user_id", "other"),
        ("run_id", "other"),
        ("session_id", "other"),
        ("child_run_id", "child"),
        ("authorization_revision", 2),
        ("permission_profile", "read_only"),
        ("plan_version_id", "other"),
        ("cancelled", True),
        ("status", "claimed"),
    ],
)
async def test_changed_run_or_scope_omits_recording_before_byte_read(harness, field, value):
    _, _, messages = await persist(harness)
    harness.request[field] = value
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    assert not prepared.references and harness.service.byte_reads == 0
    assert "omitted" in json.dumps(prepared.messages)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "other"),
        ("project_id", "other"),
        ("conversation_id", "other"),
        ("status", ArtifactStatus.DELETED),
        ("mime_type", "audio/ogg"),
        ("size_bytes", 90),
    ],
)
async def test_artifact_ownership_and_format_rechecked(harness, field, value):
    _, references, messages = await persist(harness)
    setattr(harness.service.artifacts[references[0]["artifact_id"]], field, value)
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    assert not prepared.references and harness.service.byte_reads == 0


async def test_forged_native_attachment_cannot_claim_a_real_request(harness):
    harness.content = harness.content[:-1] + b"\x01"
    with pytest.raises(RuntimeV2Error):
        await persist(harness)
    assert not harness.service.artifacts


async def test_missing_provenance_remains_playable_but_not_model_visible(harness):
    events, _, messages = await persist(harness, request_id=None)
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    assert not prepared.references and harness.service.byte_reads == 0
    assert harness.service.artifacts[events[0].artifact_id].status == ArtifactStatus.READY


async def test_replaced_storage_bytes_are_not_sent(harness):
    _, references, messages = await persist(harness)
    harness.service.content[references[0]["artifact_id"]] = b"replaced"
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    assert not prepared.references


async def test_forged_artifact_metadata_cannot_replace_private_host_receipt(harness):
    _, references, messages = await persist(harness)
    artifact = harness.service.artifacts[references[0]["artifact_id"]]
    replacement = harness.content[:-1] + b"\x01"
    digest = hashlib.sha256(replacement).hexdigest()
    harness.service.content[artifact.id] = replacement
    artifact.metadata["native_audio_origin"]["sha256"] = digest
    references[0]["sha256"] = digest
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    assert not prepared.references and harness.service.byte_reads == 0


async def test_another_processor_session_cannot_replay_recording(harness):
    _, _, messages = await persist(harness)
    token = audio.bind_audio_context(harness.service, SCOPE, "different-session")
    try:
        prepared = await audio.prepare_audio_input(
            messages, supported=True, provider=harness.provider
        )
        assert not prepared.references and harness.service.byte_reads == 0
    finally:
        audio.reset_audio_context(token)


@pytest.mark.parametrize("state", ["user_paused", "user_stopped"])
async def test_native_control_fences_prior_recording(harness, state):
    _, _, messages = await persist(harness)
    harness.records[request_key("control")] = {
        "request_id": "control",
        "session_id": harness.request["session_id"],
        "control_outcome": state,
        "control_generation": "generation",
    }
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    assert not prepared.references and harness.service.byte_reads == 0


async def test_provider_declaration_revocation_omits_before_read(harness):
    _, _, messages = await persist(harness)
    harness.stored_provider.config = {"audio_input_models": []}
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    assert not prepared.references and harness.service.byte_reads == 0


async def test_selected_agent_change_omits_prior_recording(harness):
    _, _, messages = await persist(harness)
    computer_use_steps.current_agent_servers.side_effect = RuntimeV2Error(
        "agent_changed", "agent changed"
    )
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    assert not prepared.references and harness.service.byte_reads == 0


async def test_disconnect_during_provider_wait_cancels_without_late_response(harness):
    _, _, messages = await persist(harness)
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def pending_response():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = asyncio.create_task(prepared.wait(pending_response))
    await asyncio.wait_for(started.wait(), 1)
    harness.broker.require_live_control_device.side_effect = RuntimeV2Error("revoked", "revoked")
    with pytest.raises(RuntimeV2Error):
        await asyncio.wait_for(task, 2)
    assert cancelled.is_set()


async def test_pause_before_send_does_not_start_http(harness):
    _, _, messages = await persist(harness)
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    harness.request["cancelled"] = True
    send = AsyncMock()
    with pytest.raises(RuntimeV2Error):
        await prepared.wait(send)
    send.assert_not_awaited()


async def test_inline_input_audio_cannot_bypass_artifact_checks(harness):
    with pytest.raises(RuntimeV2Error):
        await audio.prepare_audio_input(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}}
                    ],
                },
            ],
            supported=True,
            provider=harness.provider,
        )


async def test_reference_hash_mismatch_and_aggregate_limits_omit(harness):
    _, references, messages = await persist(harness)
    reference = references[0]
    reference["sha256"] = hashlib.sha256(b"other").hexdigest()
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    assert not prepared.references and harness.service.byte_reads == 0
    reference["sha256"] = hashlib.sha256(harness.content).hexdigest()
    messages[0]["content"] = [reference] * 5
    prepared = await audio.prepare_audio_input(messages, supported=True, provider=harness.provider)
    assert len(prepared.references) == 4
    assert prepared.messages[0]["content"][-1]["type"] == "text"
