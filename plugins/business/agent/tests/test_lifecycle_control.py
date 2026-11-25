"""Exercise original control eligibility and the package's dispatch boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from plugins.business.agent.backend import lifecycle_control as lifecycle
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


def setup(monkeypatch, *, pool_enabled, pool_status, actor_status, permissions):
    instance = {"status": pool_status} if pool_status else None
    http = AsyncMock(
        side_effect=[
            {"enabled": pool_enabled, "instance": instance, "allowed_actions": permissions},
            {"success": True, "action": "terminate"},
        ]
    )
    actor = AsyncMock(return_value="stopping")
    monkeypatch.setattr(lifecycle, "_canonical_http", http)
    monkeypatch.setattr(
        lifecycle,
        "project_lifecycle_snapshot",
        AsyncMock(
            return_value={
                "lifecycle_state": actor_status,
                "tool_count": 8,
                "skill_count": 2,
            }
        ),
    )
    monkeypatch.setattr(lifecycle, "call_actor_control", actor)
    return SimpleNamespace(scope=SimpleNamespace(tenant_id="t", project_id="p")), http, actor


@pytest.mark.parametrize(
    ("managed", "state", "actor", "role_actions", "expected"),
    [
        (False, None, "uninitialized", ["terminate"], []),
        (False, None, "ready", ["view"], []),
        (False, None, "executing", ["terminate"], ["stop", "restart"]),
        (True, "initializing", "ready", ["pause", "terminate"], []),
        (True, None, "ready", ["terminate"], []),
        (
            True,
            "ready",
            "initializing",
            ["pause", "resume", "terminate"],
            ["stop", "restart", "pause"],
        ),
        (True, "paused", "ready", ["pause", "resume", "terminate"], ["stop", "restart", "resume"]),
        (True, "unhealthy", "ready", ["pause", "resume", "terminate"], ["restart"]),
    ],
)
async def test_action_eligibility(monkeypatch, managed, state, actor, role_actions, expected):
    ctx, _, _ = setup(
        monkeypatch,
        pool_enabled=managed,
        pool_status=state,
        actor_status=actor,
        permissions=role_actions,
    )
    assert (await lifecycle.snapshot(ctx))["allowed_actions"] == expected


@pytest.mark.parametrize(
    ("action", "method", "suffix"),
    [
        ("stop", "DELETE", ""),
        ("restart", "DELETE", ""),
        ("pause", "POST", "/pause"),
        ("resume", "POST", "/resume"),
    ],
)
async def test_pool_action_targets_exact_project_and_chat_mode(monkeypatch, action, method, suffix):
    ctx, http, actor = setup(
        monkeypatch,
        pool_enabled=True,
        pool_status="paused" if action == "resume" else "ready",
        actor_status="ready",
        permissions=["view", "terminate", "pause", "resume"],
    )
    await lifecycle.control(ctx, {"action": action}, None)
    assert http.await_args_list[-1].args == (
        ctx,
        method,
        "/api/v1/tenants/t/projects/p/pool/instances/chat" + suffix,
    )
    actor.assert_not_awaited()


async def test_owner_actor_fallback_and_cross_scope_rejection(monkeypatch):
    ctx, http, actor = setup(
        monkeypatch,
        pool_enabled=False,
        pool_status=None,
        actor_status="ready",
        permissions=["terminate"],
    )
    assert (await lifecycle.control(ctx, {"action": "stop"}, None))["status"] == "stopping"
    actor.assert_awaited_once_with(ctx, "stop_agent")
    with pytest.raises(ValidationError):
        await lifecycle.control(ctx, {"action": "stop", "project_id": "foreign"}, None)
    assert http.await_count == 1


async def test_viewer_cannot_invoke_visible_actor_controls(monkeypatch):
    ctx, http, actor = setup(
        monkeypatch,
        pool_enabled=False,
        pool_status=None,
        actor_status="executing",
        permissions=["view"],
    )
    with pytest.raises(OptionalBusinessError) as denied:
        await lifecycle.control(ctx, {"action": "restart"}, None)
    assert denied.value.code == "forbidden"
    assert http.await_count == 1
    actor.assert_not_awaited()
