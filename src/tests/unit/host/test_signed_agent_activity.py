from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from plugins.business.agent.backend import activity_operations as operations
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

pytestmark = pytest.mark.unit


@pytest.fixture
def ctx():
    return SimpleNamespace(
        scope=SimpleNamespace(project_id="project", tenant_id="tenant"),
        user=SimpleNamespace(id="reader"),
        db=SimpleNamespace(scalar=AsyncMock()),
    )


@pytest.mark.parametrize(
    ("view", "path"), [("items", "my-work"), ("receipts", "activity/read-state")]
)
async def test_reader_bound_to_installed_scope(ctx, monkeypatch, view, path):
    authority = AsyncMock(return_value={"items": []})
    monkeypatch.setattr(operations, "_canonical", authority)
    assert (await operations.activity(ctx, {"view": view}, None))["principal_id"] == "reader"
    authority.assert_awaited_once_with(ctx, "GET", path, project_route=True)
    with pytest.raises(ValidationError):
        await operations.activity(ctx, {"view": view, "project_id": "other"}, None)


async def test_receipts_require_revision_and_pass_authority_conflict(ctx, monkeypatch):
    request = {"expected_authority_revision": 4, "entries": []}
    authority = AsyncMock(side_effect=OptionalBusinessError("conflict", "stale"))
    monkeypatch.setattr(operations, "_canonical", authority)
    with pytest.raises(ValidationError):
        await operations.mark_read(ctx, {"entries": []}, None)
    with pytest.raises(OptionalBusinessError):
        await operations.mark_read(ctx, request, None)
    authority.assert_awaited_once_with(
        ctx, "PUT", "activity/read-state", project_route=True, body=request
    )


@pytest.mark.parametrize("values", [[None], ["other-conversation", None]])
async def test_run_detail_rejects_foreign_project_or_owner(ctx, monkeypatch, values):
    authority = AsyncMock()
    monkeypatch.setattr(operations, "_canonical", authority)

    async def missing(_run_id):
        return values[0]

    monkeypatch.setattr(operations, "_run_conversation", missing)
    monkeypatch.setattr(operations, "_own_conversation", AsyncMock(side_effect=OptionalBusinessError("forbidden", "owned")))
    with pytest.raises(OptionalBusinessError):
        await operations.run_detail(ctx, {"run_id": "run", "view": "summary"}, None)
    authority.assert_not_awaited()


async def test_scoped_turn_changes_are_revision_bound(ctx, monkeypatch):
    authority = AsyncMock(return_value={"status": "ready"})
    monkeypatch.setattr(operations, "_canonical", authority)
    monkeypatch.setattr(operations, "_run_conversation", AsyncMock(return_value="conversation"))
    monkeypatch.setattr(operations, "_own_conversation", AsyncMock())
    data = {
        "run_id": "run",
        "view": "changes",
        "scope": "turn",
        "turn_id": "turn",
        "expected_revision": 5,
    }
    assert await operations.run_detail(ctx, data, None) == {"status": "ready"}
    authority.assert_awaited_once_with(
        ctx,
        "GET",
        "runs/run/changes",
        query={"turn_id": "turn", "expected_revision": 5, "scope": "turn"},
    )


async def test_latest_run_checks_owner_and_handles_empty_history(ctx, monkeypatch):
    authority = AsyncMock(return_value={"latest_run": None})
    monkeypatch.setattr(operations, "_canonical", authority)
    owned = AsyncMock(side_effect=[OptionalBusinessError("forbidden", "owned"), None])
    monkeypatch.setattr(operations, "_own_conversation", owned)
    with pytest.raises(OptionalBusinessError):
        await operations.latest_run(ctx, {"conversation_id": "conversation"}, None)
    assert await operations.latest_run(ctx, {"conversation_id": "conversation"}, None) == {
        "latest_run": None
    }
    authority.assert_awaited_once_with(ctx, "GET", "conversations/conversation/latest-run")
