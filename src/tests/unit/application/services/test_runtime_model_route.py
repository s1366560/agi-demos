"""Workspace model selection is frozen across ordinary and approved turns."""

from unittest.mock import AsyncMock

import pytest

from src.application.services.agent import runtime_model_route as routes
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["chat", "plan"])
@pytest.mark.parametrize("mode", ["work", "code"])
async def test_run_freezes_authoritative_role_and_replays(
    monkeypatch, test_db, test_user, test_project_db, kind, mode
):
    conversation = Conversation(
        id="route-conversation",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Route",
        workspace_id="workspace-1",
        agent_config={"capability_mode": mode},
    )
    test_db.add(conversation)
    await test_db.flush()
    policy = {
        "revision": 3,
        "roles": {
            "default": {"provider_id": "provider-a", "model_id": "model-a"},
            "coding": {"provider_id": "provider-b", "model_id": "model-b"},
        },
    }
    run = AgentRunAuthorityModel(
        id="route-run",
        tenant_id=conversation.tenant_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        run_kind=kind,
        idempotency_key="route",
        message_id="route",
        request_message="Execute",
        status="running",
        permission_profile="read_only",
        authorization_snapshot={"policy": policy} if kind == "plan" else {},
    )
    test_db.add(run)
    await test_db.commit()
    load = AsyncMock(return_value=policy)
    monkeypatch.setattr(routes, "load_workspace_policy", load)
    kwargs = {
        "tenant_id": conversation.tenant_id,
        "project_id": conversation.project_id,
        "conversation_id": conversation.id,
        "run_id": run.id,
    }
    route = await routes.freeze_run_model_route(test_db, **kwargs)
    expected = policy["roles"]["coding" if mode == "code" else "default"]
    assert route.provider_id == expected["provider_id"]
    assert route.model_id == expected["model_id"]
    assert run.authorization_snapshot["model_route"] == expected
    assert load.await_count == (1 if kind == "chat" else 0)
    load.reset_mock()
    load.side_effect = AssertionError("Frozen run must not resolve a different provider")
    assert await routes.freeze_run_model_route(test_db, **kwargs) == route
    load.assert_not_awaited()

    for field in ("tenant_id", "project_id", "conversation_id", "run_id"):
        with pytest.raises(RuntimeV2Error):
            await routes.freeze_run_model_route(test_db, **{**kwargs, field: "different-scope"})
    if kind == "chat":
        load.side_effect = None
        load.return_value = {
            "revision": 4,
            "roles": {
                "default": {"provider_id": "next-provider", "model_id": "next-model"},
                "coding": {"provider_id": "next-provider", "model_id": "next-model"},
            },
        }
        next_run = AgentRunAuthorityModel(
            id="next-route-run",
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            conversation_id=conversation.id,
            run_kind="chat",
            idempotency_key="next",
            message_id="next",
            request_message="Follow up",
            status="running",
            permission_profile="read_only",
            authorization_snapshot={},
        )
        test_db.add(next_run)
        await test_db.commit()
        next_route = await routes.freeze_run_model_route(
            test_db, **{**kwargs, "run_id": next_run.id}
        )
        assert next_route.provider_id == "next-provider"
        assert run.authorization_snapshot["model_route"] == expected
    run.status = "completed"
    await test_db.commit()
    with pytest.raises(RuntimeV2Error):
        await routes.freeze_run_model_route(test_db, **kwargs)


@pytest.mark.unit
@pytest.mark.parametrize(
    "policy", [{}, {"roles": {"default": None}}, {"roles": {"default": {"provider_id": "p"}}}]
)
def test_missing_policy_never_silently_uses_a_pool(policy):
    with pytest.raises(RuntimeV2Error):
        routes.route_from_policy(policy, "work")


@pytest.mark.unit
@pytest.mark.parametrize(
    "mismatch", [None, "tenant_id", "project_id", "workspace_id", "unavailable"]
)
async def test_policy_read_checks_exact_core_scope(monkeypatch, mismatch):
    import json
    from types import SimpleNamespace

    from src.infrastructure.adapters.primary.web import workspace_core_runtime_resolver

    conversation = Conversation(
        id="c", tenant_id="tenant", project_id="project", user_id="user", workspace_id="workspace"
    )
    policy = {
        "tenant_id": "tenant",
        "project_id": "project",
        "workspace_id": "workspace",
        "revision": 3,
        "roles": {"default": {"provider_id": "selected", "model_id": "model"}},
        "fallbacks": [],
        "reasoning_effort": "medium",
        "permission_mode": "ask",
        "capability_version": "workspace-agent-policy-v1",
        "updated_at": "2026-09-14T00:00:00Z",
    }
    if mismatch in {"tenant_id", "project_id", "workspace_id"}:
        policy[mismatch] = "other"

    async def chunks():
        yield json.dumps(policy).encode()

    proxy = AsyncMock(
        return_value=SimpleNamespace(
            status_code=503 if mismatch == "unavailable" else 200, aiter_raw=chunks
        )
    )
    monkeypatch.setattr(
        workspace_core_runtime_resolver,
        "workspace_core_runtime_service_v2_from_current_generation",
        lambda: SimpleNamespace(client=SimpleNamespace(proxy_request=proxy)),
    )
    if mismatch:
        with pytest.raises(RuntimeV2Error):
            await routes.load_workspace_policy(conversation)
    else:
        assert (await routes.load_workspace_policy(conversation))["revision"] == 3
    assert (
        proxy.await_args.kwargs["path"]
        == "/api/v1/tenants/tenant/projects/project/workspaces/workspace/agent-policy"
    )
    assert ("X-MemStack-User-ID", "user") in proxy.await_args.kwargs["headers"]
