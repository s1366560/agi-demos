"""Conversation and payload boundary regressions for signed Agent interactions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from plugins.business.agent.backend import attachment_parts, workbench
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
    with pytest.raises(OptionalBusinessError, match="Unexpected attachment chunk"):
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


async def test_answers_an_environment_variable_request_with_its_values(monkeypatch):
    """The original workbench answers with plain values on the authenticated channel."""
    ctx = context()
    ctx.db.scalar.return_value = SimpleNamespace(user_id="owner", request_metadata={})
    monkeypatch.setattr(workbench, "_own_conversation", AsyncMock())
    canonical = AsyncMock(return_value={"success": True, "authority_revision": 4})
    monkeypatch.setattr(workbench, "_canonical", canonical)

    result = await workbench.respond(
        ctx,
        {
            "conversation_id": "chat",
            "request_id": "env",
            "hitl_type": "env_var",
            "expected_revision": 3,
            "idempotency_key": "key-1",
            "response_data": {"values": {"GITHUB_TOKEN": "fixture"}},
        },
        None,
    )

    assert result == {"success": True, "authority_revision": 4}
    canonical.assert_awaited_once_with(
        ctx,
        "POST",
        "hitl/respond",
        body={
            "request_id": "env",
            "hitl_type": "env_var",
            "expected_revision": 3,
            "idempotency_key": "key-1",
            "response_data": {"values": {"GITHUB_TOKEN": "fixture"}},
            "contract_version": 2,
        },
    )


async def test_saves_an_answer_as_a_prompt_template_of_the_project(monkeypatch):
    """The original workbench keeps an answer as a template of its project."""
    from plugins.business.agent.backend import composer_context

    ctx = context()
    canonical = AsyncMock(
        return_value={
            "id": "tpl-1",
            "title": "Summary",
            "category": "writing",
            "content": "Answer text",
            "created_by": "owner",
        }
    )
    monkeypatch.setattr(composer_context, "_canonical", canonical)

    result = await composer_context.save_template(
        ctx, {"title": "Summary", "content": "Answer text", "category": "writing"}, None
    )

    assert result == {"id": "tpl-1", "title": "Summary", "category": "writing"}
    canonical.assert_awaited_once_with(
        ctx,
        "POST",
        "templates",
        query={"tenant_id": "tenant"},
        body={
            "title": "Summary",
            "content": "Answer text",
            "category": "writing",
            "project_id": "project",
        },
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "", "content": "text"},
        {"title": "x" * 201, "content": "text"},
        {"title": "Title", "content": ""},
        {"title": "Title", "content": "text", "category": "other"},
    ],
)
def test_rejects_an_empty_or_unclassified_template(payload):
    from plugins.business.agent.backend import composer_context

    with pytest.raises(ValidationError):
        composer_context.TemplateSave.model_validate(payload)


@pytest.mark.parametrize(
    ("sandbox", "expected"),
    [
        (
            {
                "sandbox_id": "sandbox-1",
                "project_id": "project",
                "tenant_id": "tenant",
                "status": "running",
                "is_healthy": True,
                "endpoint": "ws://sandbox.internal",
                "error_message": None,
            },
            {"sandbox": {"status": "running", "is_healthy": True}},
        ),
        ({"sandbox_id": "sandbox-1", "status": "creating"}, {"sandbox": {"status": "creating"}}),
    ],
)
async def test_reads_the_sandbox_of_the_project_for_the_status_bar(monkeypatch, sandbox, expected):
    """The original status bar shows whether the project sandbox is connected."""
    from plugins.business.agent.backend import composer_context

    ctx = context()
    canonical = AsyncMock(return_value=sandbox)
    monkeypatch.setattr(composer_context, "_canonical", canonical)

    result = await composer_context.project_context(ctx, {"view": "sandbox"}, None)

    assert result == expected
    canonical.assert_awaited_once_with(ctx, "GET", "sandbox", project_route=True)


async def test_reports_no_sandbox_when_the_project_has_none(monkeypatch):
    from plugins.business.agent.backend import composer_context
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

    ctx = context()
    canonical = AsyncMock(side_effect=OptionalBusinessError("page_not_found", "HTTP 404"))
    monkeypatch.setattr(composer_context, "_canonical", canonical)

    assert await composer_context.project_context(ctx, {"view": "sandbox"}, None) == {
        "sandbox": None
    }


async def test_passes_a_sandbox_that_cannot_be_read_to_the_page(monkeypatch):
    from plugins.business.agent.backend import composer_context
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

    ctx = context()
    canonical = AsyncMock(side_effect=OptionalBusinessError("forbidden", "HTTP 403"))
    monkeypatch.setattr(composer_context, "_canonical", canonical)

    with pytest.raises(OptionalBusinessError, match="HTTP 403"):
        await composer_context.project_context(ctx, {"view": "sandbox"}, None)
