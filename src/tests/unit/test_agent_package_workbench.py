"""Conversation and payload boundary regressions for signed Agent interactions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from plugins.business.agent.backend import attachment_parts, workbench
from plugins.business.agent.guest.binding import CommandError
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

pytestmark = pytest.mark.unit


def context():
    return SimpleNamespace(
        db=AsyncMock(),
        user=SimpleNamespace(id="owner"),
        scope=SimpleNamespace(project_id="project", tenant_id="tenant"),
    )


@pytest.mark.parametrize(
    "record",
    [
        None,
        SimpleNamespace(user_id="other", request_metadata={}),
        SimpleNamespace(
            user_id=None, request_metadata={"native_binding": {"device_id": "private"}}
        ),
    ],
)
async def test_refuses_foreign_or_device_hitl(monkeypatch, record):
    ctx = context()
    ctx.db.scalar.return_value = record
    monkeypatch.setattr(workbench, "_own_conversation", AsyncMock())
    canonical = AsyncMock()
    monkeypatch.setattr(workbench, "_canonical", canonical)
    with pytest.raises(OptionalBusinessError, match="Request unavailable"):
        await workbench.respond(
            ctx,
            {
                "conversation_id": "chat",
                "request_id": "hitl",
                "hitl_type": "permission",
                "expected_revision": 1,
                "idempotency_key": "turn-1",
                "response_data": {"granted": True},
            },
            None,
        )
    canonical.assert_not_awaited()


async def test_does_not_send_missing_attachment(monkeypatch):
    ctx = context()
    ctx.db.scalars.return_value = []
    monkeypatch.setattr(workbench, "_own_conversation", AsyncMock())
    turn = AsyncMock()
    monkeypatch.setattr(workbench, "_turn", turn)
    with pytest.raises(OptionalBusinessError, match="Attachment unavailable"):
        await workbench.attached_turn(
            ctx,
            {
                "conversation_id": "chat",
                "attachment_ids": ["foreign"],
                "message": "hello",
                "message_id": "turn",
            },
            None,
        )
    turn.assert_not_awaited()


@pytest.mark.parametrize("name", ["../bad", "a/b", "bad\nname", r"a\b"])
def test_rejects_invalid_attachment_names(name):
    with pytest.raises(ValidationError):
        workbench.AttachmentUpload(
            conversation_id="chat", filename=name, mime_type="text/plain", content="Zm9v"
        )


@pytest.mark.parametrize(
    ("number", "offset", "content"), [(1, 0, "dA=="), (2, 0, "YWJj"), (1, 1, "YQ==")]
)
async def test_rejects_invalid_part_coordinates_before_buffering(number, offset, content):
    ctx = context()
    step = attachment_parts.Chunk(
        action="chunk",
        attachment_id="id",
        conversation_id="chat",
        part_number=number,
        offset=offset,
        content=content,
    )
    redis = AsyncMock()
    with pytest.raises((OptionalBusinessError, CommandError), match="Unexpected attachment chunk"):
        await attachment_parts.store_chunk(ctx, SimpleNamespace(size_bytes=3), step, redis, "key")
    redis.hexists.assert_not_awaited()


def test_history_projects_only_public_attachment_metadata():
    public = {"filename": "file.txt", "mime_type": "text/plain", "size_bytes": 4}
    private = {**public, "sandbox_path": "/private/path", "object_key": "private-key"}
    assert workbench.timeline_attachments(
        [
            {
                "id": "u",
                "type": "user_message",
                "metadata": {"fileMetadata": [private, {"filename": "bad"}]},
            },
            {"id": "a", "type": "assistant_message", "metadata": {"fileMetadata": [private]}},
        ]
    ) == {"u": [public]}
