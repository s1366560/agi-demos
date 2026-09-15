"""No-model canonical admission tests against the real Core policy decoder."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services.chat_permission_admission_v2 import prepare_chat_permission_snapshot
from src.infrastructure.adapters.primary.web import workspace_core_runtime_resolver
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_chat_run_authority,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


@pytest.mark.unit
@pytest.mark.parametrize("ceiling", ["ask", "automatic", "full_access"])
@pytest.mark.parametrize("requested", ["ask", "automatic", "full_access"])
async def test_chat_admission_uses_real_core_policy_without_permission_promotion(
    test_db, test_user, test_project_db, monkeypatch, ceiling, requested
):
    conversation = Conversation(
        id="scoped-chat-policy",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        workspace_id="workspace",
        title="Scoped permission admission",
    )
    test_db.add(conversation)
    await test_db.commit()
    policy = {
        "tenant_id": conversation.tenant_id,
        "project_id": conversation.project_id,
        "workspace_id": "workspace",
        "revision": 19,
        "roles": {},
        "fallbacks": [],
        "reasoning_effort": "medium",
        "permission_mode": ceiling,
        "capability_version": "workspace-agent-policy-v1",
        "updated_at": "2026-09-14T00:00:00Z",
    }

    async def chunks():
        yield json.dumps(policy).encode()

    proxy = AsyncMock(return_value=SimpleNamespace(status_code=200, aiter_raw=chunks))
    monkeypatch.setattr(
        workspace_core_runtime_resolver,
        "workspace_core_runtime_service_v2_from_current_generation",
        lambda: SimpleNamespace(client=SimpleNamespace(proxy_request=proxy)),
    )
    modes = ["ask", "automatic", "full_access"]

    async def admit():
        return await ensure_chat_run_authority(
            test_db,
            conversation=conversation,
            run_id="chat-core-policy-run",
            request_message="No model invoked",
            client_message_id="scoped-chat-turn",
            app_model_context=None,
            permission_mode=requested,
        )

    if modes.index(requested) > modes.index(ceiling):
        with pytest.raises(RuntimeV2Error, match="exceed workspace policy"):
            await admit()
        assert await test_db.get(AgentRunAuthorityModel, "chat-core-policy-run") is None
    else:
        run = await admit()
        assert run.authorization_snapshot["schema_version"] == 1
        assert run.authorization_snapshot["policy"] == policy
        assert run.authorization_snapshot["effective_permission_mode"] == requested
        assert run.authorization_snapshot["requested_permission_mode"] == requested
        assert (
            run.permission_profile
            == {"ask": "read_only", "automatic": "workspace_write", "full_access": "full_access"}[
                requested
            ]
        )
    assert proxy.await_count == 1
    assert proxy.await_args.kwargs["path"] == (
        f"/api/v1/tenants/{conversation.tenant_id}/projects/{conversation.project_id}"
        "/workspaces/workspace/agent-policy"
    )


@pytest.mark.unit
async def test_unbound_chat_requires_confirmation_and_never_reads_workspace_policy(monkeypatch):
    loader = AsyncMock(side_effect=AssertionError("No workspace policy exists"))
    monkeypatch.setattr(
        "src.application.services.chat_permission_admission_v2.load_workspace_policy", loader
    )
    conversation = Conversation(id="unbound", tenant_id="t", project_id="p", user_id="u")
    snapshot = await prepare_chat_permission_snapshot(conversation, None)
    assert snapshot["effective_permission_mode"] == "ask"
    assert snapshot["policy"]["source"] == "unbound_chat_default"
    with pytest.raises(RuntimeV2Error):
        await prepare_chat_permission_snapshot(conversation, "full_access")
    loader.assert_not_awaited()
