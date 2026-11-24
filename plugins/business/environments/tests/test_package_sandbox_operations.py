"""Named sandbox calls delegate to the project authority and return only page-facing data."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from plugins.business.environments.backend import package_sandbox_operations as ops
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


@pytest.fixture
def authority(monkeypatch):
    app = FastAPI()
    state = {
        "project_id": "p",
        "tenant_id": "t",
        "status": "running",
        "is_healthy": True,
        "sandbox_id": "sandbox",
        "terminal_url": "private",
        "run_revision": 7,
        "run_id": "run",
        "expires_at": "2030-01-01T00:00:00Z",
        "contract_version": 2,
        "resume_token": "private",
        "cwd": "private",
    }
    calls = []
    capability = {"contract_version": 2, "availability": "available", "reason_code": None}

    @app.api_route("/api/v1/projects/p/sandbox{suffix:path}", methods=["GET", "POST"])
    async def dispatch(suffix: str, request: Request):
        assert request.headers["authorization"] == "Bearer test"
        calls.append((suffix, request.method))
        if suffix == "/capabilities":
            return {
                "terminal_resume": capability,
                "terminal_interactive": {"availability": "available", "contract_version": 1},
            }
        if suffix == "/terminal/sessions":
            body = await request.json()
            if body != {"run_id": "run", "expected_run_revision": 7}:
                return JSONResponse({}, status_code=403)
        return state

    monkeypatch.setattr(
        ops, "get_settings", lambda: SimpleNamespace(project_sandbox_authority_url=None)
    )
    ctx = SimpleNamespace(
        request=SimpleNamespace(app=app, headers={"Authorization": "Bearer test"}),
        scope=SimpleNamespace(tenant_id="t", project_id="p"),
    )
    return ctx, state, capability, calls


@pytest.mark.unit
async def test_read_prepare_and_grant_project_scoped_without_private_handles(authority):
    ctx, _, _, calls = authority
    state = await ops.read_sandbox(ctx, {}, None)
    assert state["sandbox"] == {"sandbox_id": "sandbox", "is_healthy": True, "status": "running"}
    assert await ops.prepare_sandbox(ctx, {"profile": "lite"}, None) == {
        "sandbox": state["sandbox"]
    }
    grant = await ops.authorize_terminal(ctx, {"run_id": "run", "expected_run_revision": 7}, None)
    assert set(grant) == {"project_id", "run_id", "run_revision", "expires_at", "contract_version"}
    assert calls == [
        ("/capabilities", "GET"),
        ("", "GET"),
        ("", "POST"),
        ("/capabilities", "GET"),
        ("/terminal/sessions", "POST"),
    ]


@pytest.mark.unit
async def test_unauthorized_or_mismatched_terminal_never_escapes_scope(authority):
    ctx, state, capability, calls = authority
    with pytest.raises(ValidationError):
        await ops.authorize_terminal(
            ctx, {"project_id": "other", "run_id": "run", "expected_run_revision": 7}, None
        )
    assert not calls
    with pytest.raises(OptionalBusinessError, match="403"):
        await ops.authorize_terminal(ctx, {"run_id": "run", "expected_run_revision": 6}, None)
    state["tenant_id"] = "foreign"
    with pytest.raises(OptionalBusinessError, match="scope mismatch"):
        await ops.read_sandbox(ctx, {}, None)
    state["project_id"] = "foreign"
    with pytest.raises(OptionalBusinessError, match="scope mismatch"):
        await ops.authorize_terminal(ctx, {"run_id": "run", "expected_run_revision": 7}, None)
    calls.clear()
    capability.update(availability="degraded", reason_code="run_authority_unavailable")
    with pytest.raises(OptionalBusinessError, match="run_authority_unavailable"):
        await ops.authorize_terminal(ctx, {"run_id": "run", "expected_run_revision": 7}, None)
    assert calls == [("/capabilities", "GET")]


@pytest.mark.unit
async def test_unavailable_upstream_returns_scoped_failure(authority, monkeypatch):
    ctx, *_ = authority
    monkeypatch.setattr(
        ops.httpx.AsyncClient, "request", AsyncMock(side_effect=ops.httpx.ConnectError("offline"))
    )
    with pytest.raises(OptionalBusinessError, match="authority unavailable"):
        await ops.read_sandbox(ctx, {}, None)


@pytest.mark.unit
async def test_metrics_are_bound_to_the_current_project_and_sandbox(authority):
    ctx, state, _, calls = authority
    state.update(
        cpu_percent=42.5,
        memory_usage=1024,
        memory_limit=4096,
        pids=3,
        collected_at="2026-11-24T07:00:00Z",
    )
    result = await ops.read_sandbox(ctx, {"metrics_for": "sandbox"}, None)
    assert result["metrics"] == {
        "cpu_percent": 42.5,
        "memory_usage": 1024,
        "memory_limit": 4096,
        "pids": 3,
        "collected_at": "2026-11-24T07:00:00Z",
    }
    assert calls == [("", "GET"), ("/stats", "GET")]
    calls.clear()
    with pytest.raises(OptionalBusinessError, match="selected sandbox has changed"):
        await ops.read_sandbox(ctx, {"metrics_for": "retired"}, None)
    assert calls == [("", "GET")]
