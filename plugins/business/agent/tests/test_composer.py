"""The signed controls submit single preferences without forwarding arbitrary configuration."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from plugins.business.agent.backend import composer
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


@pytest.mark.parametrize(
    "change",
    [
        {"project_id": "foreign", "mode": "plan"},
        {"mode": "plan", "approval_mode": "ask"},
        {"llm_overrides": {"approval_mode": "full_access"}},
        {"llm_overrides": {"max_tokens": 0}},
        {"llm_overrides": {"top_p": 1.2}},
        {"approval_mode": None},
        {},
        {"mode": "execute"},
    ],
)
def test_disallow_ambiguous_or_out_of_scope_changes(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        composer.SavePreference.model_validate({"conversation_id": "owned", **change})


@pytest.mark.parametrize(
    ("change", "canonical"),
    [
        (
            {"reasoning_effort": "high"},
            {"llm_overrides": {"temperature": 0.3, "reasoning_effort": "high"}},
        ),
        ({"reasoning_effort": "default"}, {"llm_overrides": {"temperature": 0.3}}),
        ({"llm_overrides": {}}, {"llm_overrides": {"reasoning_effort": "low"}}),
        (
            {"llm_overrides": {"frequency_penalty": 1}},
            {"llm_overrides": {"frequency_penalty": 1.0, "reasoning_effort": "low"}},
        ),
        ({"approval_mode": "auto_edit"}, {"approval_mode": "auto_edit"}),
        (
            {"llm_model_override": "model-A"},
            {
                "llm_model_override": "model-A",
                "llm_route_override": {"provider_id": "provider-A", "model_id": "model-A"},
            },
        ),
        ({"llm_model_override": None}, {"llm_model_override": None}),
    ],
)
async def test_single_field_uses_owned_canonical_mutation(monkeypatch, change, canonical) -> None:
    row = {"agent_config": {"llm_overrides": {"temperature": 0.3, "reasoning_effort": "low"}}}
    owned = AsyncMock()
    http = AsyncMock(side_effect=[row, row, {"mode": "build"}])
    monkeypatch.setattr(composer, "_own_conversation", owned)
    monkeypatch.setattr(composer, "_canonical", http)
    monkeypatch.setattr(
        composer, "_routes", AsyncMock(return_value=("model-A", {"model-A": "provider-A"}))
    )
    ctx = object()
    await composer.save(ctx, {"conversation_id": "owned", **change}, None)
    owned.assert_awaited_once_with(ctx, "owned")
    assert http.await_args_list[1].args == (ctx, "PATCH", "conversations/owned/config")
    assert http.await_args_list[1].kwargs["body"] == canonical


async def test_cross_project_conversation_cannot_change_preferences(monkeypatch) -> None:
    http = AsyncMock()
    monkeypatch.setattr(composer, "_canonical", http)
    monkeypatch.setattr(
        composer,
        "_own_conversation",
        AsyncMock(side_effect=OptionalBusinessError("forbidden", "denied")),
    )
    with pytest.raises(OptionalBusinessError):
        await composer.save(
            object(), {"conversation_id": "other", "approval_mode": "full_access"}, None
        )
    http.assert_not_awaited()


@pytest.mark.parametrize(
    ("row", "change"),
    [
        ({"execution_target": "local"}, {"mode": "plan"}),
        ({"metadata": {"execution_target": "local"}}, {"reasoning_effort": "high"}),
        ({"execution_target": "cloud"}, {"llm_model_override": "other-tenant-model"}),
    ],
)
async def test_reject_device_mutation_and_foreign_model(monkeypatch, row, change) -> None:
    http = AsyncMock(return_value=row)
    monkeypatch.setattr(composer, "_canonical", http)
    monkeypatch.setattr(composer, "_own_conversation", AsyncMock())
    monkeypatch.setattr(composer, "_routes", AsyncMock(return_value=(None, {})))
    with pytest.raises(OptionalBusinessError) as denied:
        await composer.save(object(), {"conversation_id": "owned", **change}, None)
    assert denied.value.code == "forbidden"
    assert http.await_count == 1


async def test_roster_applies_provider_filters_and_tenant_priority() -> None:
    from src.host.operations.agent_package.model_routes import routes_for
    from src.infrastructure.persistence.llm_providers_models import LLMProvider

    blocked = LLMProvider(
        name="first",
        id="a",
        llm_model="model-blocked",
        allowed_models='["model"]',
        blocked_models='["model-blocked"]',
        secondary_models=["model-shared", "foreign"],
    )
    eligible = LLMProvider(
        name="second", id="b", llm_model="model-chat", secondary_models=["model-shared"]
    )
    default, routes = routes_for([blocked, eligible])
    assert default == "model-chat"
    assert routes["model-shared"] == "a"
    assert routes["model-chat"] == "b"
    assert "model-blocked" not in routes and "foreign" not in routes


async def test_workbench_resume_uses_unbound_order_and_stable_ids(monkeypatch) -> None:
    from plugins.business.agent.backend import chat_operations as chat

    queries = AsyncMock(
        side_effect=[
            {"items": [{"id": "u", "title": "unbound original"}, {"id": "v"}]},
            {
                "items": [
                    {"id": "w"},
                    {"id": "u", "title": "group surrogate"},
                    {"id": "w"},
                    {"id": "z"},
                ]
            },
        ]
    )
    monkeypatch.setattr(chat, "_canonical", queries)
    ctx = object()
    page = await chat._conversation_page(ctx, chat.WorkbenchList(workbench=True))
    assert [row["id"] for row in page] == ["u", "v", "w", "z"]
    assert page[0]["title"] == "unbound original"
    assert [call.kwargs["query"] for call in queries.await_args_list] == [
        {"unbound_only": "true", "limit": 10},
        {"group_by_workspace": "true", "limit": 10},
    ]


@pytest.mark.parametrize(
    ("options", "queries"),
    [
        ({}, [{}]),
        (
            {"workbench": True, "workspace_id": "ws", "limit": 20},
            [{"workspace_id": "ws", "limit": 20}],
        ),
        (
            {"workbench": True, "limit": 20},
            [{"unbound_only": "true", "limit": 20}, {"group_by_workspace": "true", "limit": 20}],
        ),
    ],
)
async def test_sidebar_and_filtered_list_keep_their_scope(monkeypatch, options, queries) -> None:
    from plugins.business.agent.backend import chat_operations as chat

    fetch = AsyncMock(return_value={"items": []})
    monkeypatch.setattr(chat, "_canonical", fetch)
    assert await chat._conversation_page(object(), chat.WorkbenchList(**options)) == []
    assert [call.kwargs["query"] for call in fetch.await_args_list] == queries


async def test_skill_picker_only_exposes_enabled_scope_and_refuses_forged_turn(monkeypatch):
    from types import SimpleNamespace

    from plugins.business.agent.backend import chat_operations as chat

    ctx = SimpleNamespace(
        scope=SimpleNamespace(tenant_id="t", project_id="p"),
        db=SimpleNamespace(scalar=AsyncMock(return_value={})),
    )
    base = {
        "id": "one",
        "name": "chosen",
        "description": "enabled",
        "status": "active",
        "scope": "project",
        "project_id": "p",
        "tenant_id": "t",
    }
    monkeypatch.setattr(
        chat,
        "_canonical_http",
        AsyncMock(
            return_value={
                "skills": [
                    base,
                    {**base, "name": "foreign", "project_id": "q"},
                    {**base, "name": "inactive", "status": "disabled"},
                    {**base, "name": "other", "tenant_id": "other"},
                ]
            }
        ),
    )
    listed = await chat.visible_skills(ctx, limit=50)
    assert listed == [{"id": "one", "name": "chosen", "description": "enabled", "scope": "project"}]
    monkeypatch.setattr(chat, "_own_conversation", AsyncMock())
    monkeypatch.setattr(chat, "latest_execution_placements", AsyncMock(return_value={}))
    socket = AsyncMock(return_value={"status": "completed"})
    monkeypatch.setattr(chat, "stream_turn", socket)
    payload = {"conversation_id": "owned", "message_id": "id", "message": "hello"}
    for rejected in ("foreign", "inactive", "other", "unknown"):
        with pytest.raises(OptionalBusinessError):
            await chat.turn(ctx, {**payload, "forced_skill_name": rejected}, None)
    socket.assert_not_awaited()
    await chat.turn(ctx, {**payload, "forced_skill_name": "chosen"}, None)
    socket.assert_awaited_once_with(ctx, {**payload, "forced_skill_name": "chosen"}, None)


async def test_voice_checks_selected_principal_project_and_conversation(monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(composer, "voice_ticket", lambda **kwargs: "fixture-ticket")
    guard = AsyncMock(return_value=None)
    monkeypatch.setattr(composer, "voice_conversation_tenant", guard)
    ctx = SimpleNamespace(
        db=object(),
        user=SimpleNamespace(id="owner"),
        scope=SimpleNamespace(tenant_id="t", project_id="p"),
    )
    with pytest.raises(OptionalBusinessError, match="cloud conversation"):
        await composer.authorize_voice(ctx, {"conversation_id": "owned"}, None)
    guard.assert_awaited_once_with(
        ctx.db, user_id="owner", tenant_id="t", project_id="p", conversation_id="owned"
    )
    guard.return_value = "t"
    assert await composer.authorize_voice(ctx, {"conversation_id": "owned"}, None) == {
        "conversation_id": "owned",
        "principal_id": "owner",
        "ticket": "fixture-ticket",
    }
