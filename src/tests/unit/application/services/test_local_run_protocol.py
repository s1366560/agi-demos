"""Local run registration, seq upload, permission ceiling, and stop convergence."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.artifact_service import ArtifactService
from src.application.services.local_run_protocol import (
    LocalRunProtocolError,
    append_local_run_events,
    list_local_run_events,
    redact_uploaded_text,
    register_local_run,
    settle_local_run,
    stop_local_run,
    validate_root_label,
)
from src.domain.ports.services.storage_service_port import UploadResult
from src.infrastructure.adapters.primary.web.routers.agent.local_run_upload import (
    RegisterLocalRunBody,
    post_local_run,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentLocalRunEventModel,
    AgentRunAuthorityModel,
    Conversation,
    User,
    UserProject,
    UserTenant,
)
from src.tests.conftest import TEST_PROJECT_ID, TEST_TENANT_ID, TEST_USER_ID

pytestmark = pytest.mark.unit

_MACHINE = "machine-a1"
_OTHER_MACHINE = "machine-b2"
_LABEL = "agi-demos"
_ABSOLUTE = "/Users/alice/src/agi-demos/src/main.ts"
_SECRET = "sk-abcdefghijklmnopqrstuvwxyz"


class _RecordingStorage:
    def __init__(self) -> None:
        self.uploads: list[bytes] = []

    async def upload_file(
        self,
        file_content: bytes,
        object_key: str,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> UploadResult:
        del metadata
        self.uploads.append(file_content)
        return UploadResult(
            object_key=object_key,
            size_bytes=len(file_content),
            content_type=content_type,
            etag="test",
        )

    async def generate_presigned_url(self, object_key: str, expiration_seconds: int) -> str:
        del expiration_seconds
        return f"https://local-run.invalid/{object_key}"


class _Writer:
    def __init__(self) -> None:
        self.storage = _RecordingStorage()
        self.service = ArtifactService(storage_service=self.storage)  # type: ignore[arg-type]

    async def create_artifact(self, **kwargs: Any) -> str:
        artifact = await self.service.create_artifact(**kwargs)
        return artifact.id


async def _conversation(
    db: AsyncSession,
    *,
    owner: str = TEST_USER_ID,
    conversation_id: str = "conv-local-1",
) -> Conversation:
    conversation = Conversation(
        id=conversation_id,
        project_id=TEST_PROJECT_ID,
        tenant_id=TEST_TENANT_ID,
        user_id=owner,
        title="local",
        status="active",
        message_count=0,
        current_mode="build",
        merge_strategy="result_only",
        participant_agents=[],
    )
    db.add(conversation)
    await db.commit()
    return conversation


async def _register(
    db: AsyncSession,
    conversation: Conversation,
    *,
    key: str = "local-key-001",
    message: str = "inspect the workspace",
    permission_mode: str | None = None,
    machine: str = _MACHINE,
    label: str = _LABEL,
    user_id: str = TEST_USER_ID,
    surface: str | None = "desktop",
):
    return await register_local_run(
        db,
        conversation=conversation,
        user_id=user_id,
        surface=surface,
        idempotency_key=key,
        message=message,
        execution_machine_id=machine,
        local_root_label=label,
        permission_mode=permission_mode,
    )


def test_server_redaction_removes_absolute_paths_and_secrets() -> None:
    assert redact_uploaded_text(_ABSOLUTE) == "<local-root>/main.ts"
    assert "/Users/alice" not in redact_uploaded_text(f"see {_ABSOLUTE}")
    assert redact_uploaded_text(f"token {_SECRET}") == "<redacted>"
    assert redact_uploaded_text("<local-root>/src/main.ts") == "<local-root>/src/main.ts"
    with pytest.raises(LocalRunProtocolError) as rejected:
        validate_root_label(_SECRET)
    assert rejected.value.code == "LOCAL_ROOT_LABEL_REJECTED"
    with pytest.raises(LocalRunProtocolError):
        validate_root_label("/Users/alice/src/agi-demos")


async def test_register_freezes_local_run_and_replays_the_same_key(
    test_db: AsyncSession,
    test_project_db: object,
    test_user: User,
) -> None:
    del test_project_db, test_user
    conversation = await _conversation(test_db)
    created = await _register(test_db, conversation, message=f"read {_ABSOLUTE}")
    assert created.status == "queued"
    assert created.upload_state == "pending"
    assert created.permission_profile == "read_only"
    replay = await _register(test_db, conversation, message=f"read {_ABSOLUTE}")
    assert replay.run_id == created.run_id
    stored = await test_db.get(AgentRunAuthorityModel, created.run_id)
    assert stored is not None
    assert stored.execution_target == "local"
    assert stored.execution_machine_id == _MACHINE
    assert stored.local_root_label == _LABEL
    assert stored.request_message == "read <local-root>/main.ts"
    assert "/Users/alice" not in str(stored.authorization_snapshot)
    with pytest.raises(LocalRunProtocolError) as conflict:
        await _register(test_db, conversation, message="a different task")
    assert conflict.value.code == "LOCAL_RUN_IDEMPOTENCY_CONFLICT"


async def test_web_surface_and_other_owner_cannot_create(
    test_db: AsyncSession,
    test_project_db: object,
    test_user: User,
    another_user: User,
) -> None:
    del test_project_db, test_user
    conversation = await _conversation(test_db)
    with pytest.raises(LocalRunProtocolError) as web_error:
        await _register(test_db, conversation, surface="web")
    assert web_error.value.status_code == 403
    assert web_error.value.code == "WEB_LOCAL_RUN_READONLY"
    with pytest.raises(LocalRunProtocolError) as owner_error:
        await _register(test_db, conversation, user_id=another_user.id)
    assert owner_error.value.status_code == 403


async def test_permission_ceiling_rejects_full_access_and_freezes_allowed_mode(
    test_db: AsyncSession,
    test_project_db: object,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del test_project_db, test_user
    conversation = await _conversation(test_db)
    with pytest.raises(LocalRunProtocolError) as denied:
        await _register(test_db, conversation, permission_mode="full_access")
    assert denied.value.code == "LOCAL_RUN_PERMISSION_DENIED"
    assert await test_db.get(AgentRunAuthorityModel, "missing") is None

    async def allow_full(_conversation: Conversation) -> dict[str, Any]:
        return {"revision": 2, "permission_mode": "full_access", "source": "test"}

    monkeypatch.setattr(
        "src.application.services.chat_permission_admission_v2.load_chat_permission_policy",
        allow_full,
    )
    created = await _register(
        test_db,
        conversation,
        key="local-key-full",
        permission_mode="full_access",
    )
    stored = await test_db.get(AgentRunAuthorityModel, created.run_id)
    assert stored is not None
    assert stored.permission_profile == "full_access"
    other = await _conversation(test_db, conversation_id="conv-local-ask")
    narrowed = await _register(
        test_db,
        other,
        key="local-key-ask",
        permission_mode="ask",
    )
    ask_row = await test_db.get(AgentRunAuthorityModel, narrowed.run_id)
    assert ask_row is not None
    assert ask_row.permission_profile == "read_only"


async def test_event_batch_is_idempotent_and_conflict_does_not_overwrite(
    test_db: AsyncSession,
    test_project_db: object,
    test_user: User,
) -> None:
    del test_project_db, test_user
    conversation = await _conversation(test_db)
    created = await _register(test_db, conversation)
    run = await test_db.get(AgentRunAuthorityModel, created.run_id)
    assert run is not None
    first = await append_local_run_events(
        test_db,
        run=run,
        conversation=conversation,
        user_id=TEST_USER_ID,
        surface="desktop",
        execution_machine_id=_MACHINE,
        events=[{"seq": 1, "kind": "user_message", "payload": {"text": f"at {_ABSOLUTE}"}}],
        raw_size=80,
        artifacts=None,
    )
    assert first.idempotent is False
    assert first.upload_state == "events_accepted"
    assert run.status == "running"
    replay = await append_local_run_events(
        test_db,
        run=run,
        conversation=conversation,
        user_id=TEST_USER_ID,
        surface="desktop",
        execution_machine_id=_MACHINE,
        events=[{"seq": 1, "kind": "user_message", "payload": {"text": f"at {_ABSOLUTE}"}}],
        raw_size=80,
        artifacts=None,
    )
    assert replay.idempotent is True
    with pytest.raises(LocalRunProtocolError) as conflict:
        await append_local_run_events(
            test_db,
            run=run,
            conversation=conversation,
            user_id=TEST_USER_ID,
            surface="desktop",
            execution_machine_id=_MACHINE,
            events=[{"seq": 1, "kind": "user_message", "payload": {"text": "different"}}],
            raw_size=40,
            artifacts=None,
        )
    assert conflict.value.code == "LOCAL_RUN_EVENT_CONFLICT"
    stored = await test_db.get(AgentLocalRunEventModel, (await _only_event(test_db)).id)
    assert stored is not None
    assert stored.payload["text"] == "at <local-root>/main.ts"
    assert stored.payload_sha256
    with pytest.raises(LocalRunProtocolError) as gap:
        await append_local_run_events(
            test_db,
            run=run,
            conversation=conversation,
            user_id=TEST_USER_ID,
            surface="desktop",
            execution_machine_id=_MACHINE,
            events=[{"seq": 3, "kind": "log", "payload": {"text": "skip"}}],
            raw_size=20,
            artifacts=None,
        )
    assert gap.value.code == "LOCAL_RUN_SEQ_GAP"
    with pytest.raises(LocalRunProtocolError) as mismatch:
        await append_local_run_events(
            test_db,
            run=run,
            conversation=conversation,
            user_id=TEST_USER_ID,
            surface="desktop",
            execution_machine_id=_OTHER_MACHINE,
            events=[{"seq": 2, "kind": "log", "payload": {"text": "nope"}}],
            raw_size=20,
            artifacts=None,
        )
    assert mismatch.value.code == "LOCAL_RUN_MACHINE_MISMATCH"
    with pytest.raises(LocalRunProtocolError) as oversized:
        await append_local_run_events(
            test_db,
            run=run,
            conversation=conversation,
            user_id=TEST_USER_ID,
            surface="desktop",
            execution_machine_id=_MACHINE,
            events=[{"seq": 2, "kind": "log", "payload": {"text": "x" * 40}}],
            raw_size=300_000,
            artifacts=None,
        )
    assert oversized.value.code == "LOCAL_RUN_BATCH_TOO_LARGE"


async def test_artifact_uses_artifact_service_and_secrets_are_not_stored(
    test_db: AsyncSession,
    test_project_db: object,
    test_user: User,
) -> None:
    del test_project_db, test_user
    conversation = await _conversation(test_db)
    created = await _register(test_db, conversation)
    run = await test_db.get(AgentRunAuthorityModel, created.run_id)
    assert run is not None
    writer = _Writer()
    content = base64.b64encode(b"hello from the computer").decode("ascii")
    await append_local_run_events(
        test_db,
        run=run,
        conversation=conversation,
        user_id=TEST_USER_ID,
        surface="desktop",
        execution_machine_id=_MACHINE,
        events=[
            {
                "seq": 1,
                "kind": "artifact",
                "payload": {
                    "filename": "note.txt",
                    "content_base64": content,
                    "source_path": _ABSOLUTE,
                    "source_tool": "write",
                },
            }
        ],
        raw_size=200,
        artifacts=writer,
    )
    assert writer.storage.uploads == [b"hello from the computer"]
    replay = await list_local_run_events(
        test_db, run=run, conversation=conversation, user_id=TEST_USER_ID
    )
    assert replay[0]["artifact_id"]
    assert replay[0]["payload"]["source_path"] == "<local-root>/main.ts"
    assert "/Users/alice" not in str(replay)
    secret = base64.b64encode(_SECRET.encode("utf-8")).decode("ascii")
    await append_local_run_events(
        test_db,
        run=run,
        conversation=conversation,
        user_id=TEST_USER_ID,
        surface="desktop",
        execution_machine_id=_MACHINE,
        events=[
            {
                "seq": 2,
                "kind": "artifact",
                "payload": {
                    "filename": "secret.txt",
                    "content_base64": secret,
                    "source_tool": "write",
                },
            }
        ],
        raw_size=200,
        artifacts=writer,
    )
    replay = await list_local_run_events(
        test_db, run=run, conversation=conversation, user_id=TEST_USER_ID
    )
    assert replay[1]["artifact_id"] is None
    assert replay[1]["payload"]["artifact_rejected"] == "secret_like"
    assert _SECRET not in str(replay)
    assert len(writer.storage.uploads) == 1


async def test_stop_beats_a_late_completion_and_revision_conflicts(
    test_db: AsyncSession,
    test_project_db: object,
    test_user: User,
) -> None:
    del test_project_db, test_user
    conversation = await _conversation(test_db)
    created = await _register(test_db, conversation)
    run = await test_db.get(AgentRunAuthorityModel, created.run_id)
    assert run is not None
    stopped = await stop_local_run(
        test_db,
        run=run,
        conversation=conversation,
        user_id=TEST_USER_ID,
        surface="desktop",
        expected_revision=1,
        execution_machine_id=_MACHINE,
    )
    assert stopped.status == "cancel_requested"
    assert stopped.revision == 2
    late = await settle_local_run(
        test_db,
        run=run,
        conversation=conversation,
        user_id=TEST_USER_ID,
        surface="desktop",
        expected_revision=1,
        status="completed",
        execution_machine_id=_MACHINE,
        error=None,
    )
    assert late.late_terminal is True
    assert late.status == "cancelled"
    assert late.upload_state == "synced"
    assert run.status == "cancelled"
    repeated = await settle_local_run(
        test_db,
        run=run,
        conversation=conversation,
        user_id=TEST_USER_ID,
        surface="desktop",
        expected_revision=1,
        status="completed",
        execution_machine_id=_MACHINE,
        error=None,
    )
    assert repeated.status == "cancelled"
    assert repeated.late_terminal is True
    replayed_stop = await stop_local_run(
        test_db,
        run=run,
        conversation=conversation,
        user_id=TEST_USER_ID,
        surface="desktop",
        expected_revision=1,
        execution_machine_id=_MACHINE,
    )
    assert replayed_stop.status == "cancelled"
    assert run.status == "cancelled"


async def test_completion_is_not_replaced_by_a_later_failure(
    test_db: AsyncSession,
    test_project_db: object,
    test_user: User,
) -> None:
    del test_project_db, test_user
    conversation = await _conversation(test_db)
    created = await _register(test_db, conversation)
    run = await test_db.get(AgentRunAuthorityModel, created.run_id)
    assert run is not None
    done = await settle_local_run(
        test_db,
        run=run,
        conversation=conversation,
        user_id=TEST_USER_ID,
        surface="desktop",
        expected_revision=1,
        status="completed",
        execution_machine_id=_MACHINE,
        error=None,
    )
    assert done.upload_state == "synced"
    assert done.late_terminal is False
    replay = await settle_local_run(
        test_db,
        run=run,
        conversation=conversation,
        user_id=TEST_USER_ID,
        surface="desktop",
        expected_revision=1,
        status="completed",
        execution_machine_id=_MACHINE,
        error=None,
    )
    assert replay.revision == 2
    with pytest.raises(LocalRunProtocolError) as conflict:
        await settle_local_run(
            test_db,
            run=run,
            conversation=conversation,
            user_id=TEST_USER_ID,
            surface="desktop",
            expected_revision=1,
            status="failed",
            execution_machine_id=_MACHINE,
            error="nope",
        )
    assert conflict.value.code == "LOCAL_RUN_REVISION_CONFLICT"
    assert run.status == "completed"


async def test_second_active_run_is_rejected(
    test_db: AsyncSession,
    test_project_db: object,
    test_user: User,
) -> None:
    del test_project_db, test_user
    conversation = await _conversation(test_db)
    await _register(test_db, conversation)
    with pytest.raises(LocalRunProtocolError) as active:
        await _register(test_db, conversation, key="local-key-002")
    assert active.value.code == "LOCAL_RUN_ACTIVE_CONFLICT"


async def test_http_register_requires_desktop_surface(
    test_db: AsyncSession,
    test_project_db: object,
    test_user: User,
) -> None:
    del test_project_db
    conversation = await _conversation(test_db)
    body = RegisterLocalRunBody(
        idempotency_key="local-key-http",
        message="hello",
        execution_machine_id=_MACHINE,
        local_root_label=_LABEL,
    )
    with pytest.raises(HTTPException) as web_error:
        await post_local_run(
            conversation.id,
            body,
            current_user=test_user,
            db=test_db,
            x_agi_surface="web",
        )
    assert web_error.value.status_code == 403
    assert web_error.value.detail["code"] == "WEB_LOCAL_RUN_READONLY"
    created = await post_local_run(
        conversation.id,
        body,
        current_user=test_user,
        db=test_db,
        x_agi_surface="desktop",
    )
    assert created["execution_target"] == "local"
    assert created["upload_state"] == "pending"
    assert created["local_root_label"] == _LABEL


async def test_member_who_does_not_own_the_conversation_is_denied(
    test_db: AsyncSession,
    test_project_db: object,
    test_user: User,
    another_user: User,
) -> None:
    del test_project_db, test_user
    test_db.add(
        UserTenant(
            id="ut-other",
            user_id=another_user.id,
            tenant_id=TEST_TENANT_ID,
            role="member",
            permissions={},
        )
    )
    test_db.add(
        UserProject(
            id="up-other",
            user_id=another_user.id,
            project_id=TEST_PROJECT_ID,
            role="member",
        )
    )
    await test_db.commit()
    conversation = await _conversation(test_db)
    with pytest.raises(LocalRunProtocolError) as denied:
        await _register(test_db, conversation, user_id=another_user.id)
    assert denied.value.code == "LOCAL_RUN_FORBIDDEN"


async def _only_event(db: AsyncSession) -> AgentLocalRunEventModel:
    from sqlalchemy import select

    row = await db.scalar(select(AgentLocalRunEventModel))
    assert row is not None
    return row
