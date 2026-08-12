"""Avernet Provider webhook authentication and dispatch contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web import workspace_core_provider
from src.infrastructure.adapters.primary.web.workspace_core_runtime import (
    install_workspace_core_runtime,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.workspace_core.autonomy_judge import (
    WorkspaceAutonomyCandidate,
    WorkspaceAutonomyJudgeRequest,
    WorkspaceAutonomyJudgeUnavailable,
    WorkspaceAutonomyJudgeVerdict,
)
from src.infrastructure.workspace_core.context_judge import (
    WorkspaceContextCandidate,
    WorkspaceContextJudgeRequest,
    WorkspaceContextJudgeUnavailable,
    WorkspaceContextJudgeVerdict,
)
from src.infrastructure.workspace_core.plan_judge import (
    WorkspacePlanJudgeRequest,
    WorkspacePlanJudgeUnavailable,
    WorkspacePlanJudgeVerdict,
)
from src.infrastructure.workspace_core.provider import (
    AvernetProviderAdapter,
    ProviderAbortResult,
    ProviderHistoryResult,
    ProviderRuntimeEvent,
    ProviderWebhookRequest,
)


def _settings() -> WorkspaceCoreSettings:
    return WorkspaceCoreSettings.model_validate(
        {
            "WORKSPACE_CORE_BACKEND": "avernet",
            "WORKSPACE_CORE_BASE_URL": "http://workspace-core.test",
            "WORKSPACE_CORE_SERVICE_TOKEN": "service-token",
            "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "webhook-token",
            "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "event-token",
            "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "registry-token",
        }
    )


def _payload(method: str = "chat.history") -> dict[str, object]:
    return {
        "type": "req",
        "id": "run-1",
        "method": method,
        "session_id": "session-1",
        "bcn_group_id": "group-1",
        "to_bot": {
            "provider_id": "provider-1",
            "provider_bot_ref": "agent-1",
        },
        "message": {"content": [{"type": "text", "text": "hello"}]},
        "timeout_ms": 30_000,
        "extensions": {
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "workspace_id": "workspace-1",
            "user_id": "user-1",
            "conversation_id": "conversation-1",
        },
    }


class FakeRuntime:
    def stream_send(
        self,
        _request: ProviderWebhookRequest,
    ) -> AsyncIterator[ProviderRuntimeEvent]:
        raise AssertionError("send is not expected")

    async def inject(self, _request: ProviderWebhookRequest) -> None:
        return None

    async def abort(self, _request: ProviderWebhookRequest) -> ProviderAbortResult:
        return ProviderAbortResult(ray_cancelled=True, local_worker_cancelled=True)

    async def history(self, _request: ProviderWebhookRequest) -> ProviderHistoryResult:
        return ProviderHistoryResult(messages=[{"role": "assistant", "content": "persisted"}])


class FakeSink:
    async def publish(
        self,
        _request: ProviderWebhookRequest,
        _event: ProviderRuntimeEvent,
    ) -> None:
        return None


class FakeContextJudge:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.requests: list[WorkspaceContextJudgeRequest] = []

    async def select(
        self,
        request: WorkspaceContextJudgeRequest,
    ) -> WorkspaceContextJudgeVerdict:
        self.requests.append(request)
        if self.unavailable:
            raise WorkspaceContextJudgeUnavailable("judge unavailable")
        selected = request.candidates[1]
        return WorkspaceContextJudgeVerdict(
            selected=selected,
            rationale="The structured evidence supports candidate index 1.",
            evidence=["candidate index 1 is available"],
            agent_id="provider-judge:model-judge",
            tool_name="select_workspace_context",
            input_json={"candidates": [candidate.model_dump() for candidate in request.candidates]},
            output_json={
                "candidate_index": 1,
                "rationale": "The structured evidence supports candidate index 1.",
                "evidence": ["candidate index 1 is available"],
            },
            latency_ms=7,
        )


class FakePlanJudge:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.requests: list[WorkspacePlanJudgeRequest] = []

    async def judge(self, request: WorkspacePlanJudgeRequest) -> WorkspacePlanJudgeVerdict:
        self.requests.append(request)
        if self.unavailable:
            raise WorkspacePlanJudgeUnavailable("judge unavailable")
        return WorkspacePlanJudgeVerdict(
            proceed=True,
            selected_node_id="node-2",
            rationale="The structured evidence supports node-2.",
            agent_id="provider-judge:model-judge",
            tool_name="judge_workspace_plan",
            input_json=request.model_dump(mode="json"),
            output_json={
                "proceed": True,
                "selected_node_id": "node-2",
                "rationale": "The structured evidence supports node-2.",
            },
            latency_ms=9,
        )


class FakeAutonomyJudge:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.requests: list[WorkspaceAutonomyJudgeRequest] = []

    async def judge(self, request: WorkspaceAutonomyJudgeRequest) -> WorkspaceAutonomyJudgeVerdict:
        self.requests.append(request)
        if self.unavailable:
            raise WorkspaceAutonomyJudgeUnavailable("judge unavailable")
        return WorkspaceAutonomyJudgeVerdict(
            verdict="continue",
            selected_root_task_id="task-2",
            rationale="The structured evidence supports task-2.",
            agent_id="provider-judge:model-judge",
            tool_name="judge_workspace_autonomy",
            input_json=request.model_dump(mode="json"),
            output_json={
                "verdict": "continue",
                "selected_root_task_id": "task-2",
                "rationale": "The structured evidence supports task-2.",
            },
            latency_ms=11,
        )


class RecordingProviderAdapter(AvernetProviderAdapter):
    def __init__(self) -> None:
        self.requests: list[ProviderWebhookRequest] = []

    async def handle(self, request: ProviderWebhookRequest) -> dict[str, Any]:
        self.requests.append(request)
        return {"ok": True}


def _app() -> FastAPI:
    app = FastAPI()
    install_workspace_core_runtime(app, _settings())
    app.state.workspace_core_provider_adapter = AvernetProviderAdapter(
        FakeRuntime(),
        FakeSink(),
        app.state.workspace_core_client,
    )
    return app


def _registry_app(monkeypatch: pytest.MonkeyPatch, agent: object | None) -> FastAPI:
    app = _app()

    async def override_db() -> AsyncIterator[Any]:
        yield object()

    class FakeRegistry:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(
            self,
            agent_id: str,
            *,
            tenant_id: str | None = None,
            project_id: str | None = None,
        ) -> object | None:
            assert (agent_id, tenant_id, project_id) == (
                "agent-1",
                "tenant-1",
                "project-1",
            )
            return agent

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(workspace_core_provider, "SqlAgentRegistryRepository", FakeRegistry)
    return app


def _provider_registry_app(provider: object | None) -> FastAPI:
    app = _app()

    class FakeResult:
        def scalar_one_or_none(self) -> object | None:
            return provider

    class FakeDb:
        async def execute(self, _statement: object) -> FakeResult:
            return FakeResult()

    async def override_db() -> AsyncIterator[Any]:
        yield FakeDb()

    app.dependency_overrides[get_db] = override_db
    return app


@pytest.mark.unit
async def test_provider_webhook_requires_dedicated_bearer_token() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://api.test",
    ) as client:
        missing = await client.post(
            "/internal/v1/workspace-core/provider",
            json=_payload(),
        )
        service_token = await client.post(
            "/internal/v1/workspace-core/provider",
            json=_payload(),
            headers={"Authorization": "Bearer service-token"},
        )

    assert missing.status_code == 401
    assert service_token.status_code == 401


@pytest.mark.unit
async def test_provider_webhook_dispatches_authenticated_history() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/provider",
            json=_payload(),
            headers={"Authorization": "Bearer webhook-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "session_id": "session-1",
        "messages": [{"role": "assistant", "content": "persisted"}],
        "has_more": False,
        "next_before": None,
        "next_after": None,
    }


@pytest.mark.unit
async def test_agent_registry_requires_dedicated_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _registry_app(monkeypatch, None)
    payload = {"tenant_id": "tenant-1", "project_id": "project-1", "agent_id": "agent-1"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/agent-registry/resolve",
            json=payload,
            headers={"Authorization": "Bearer service-token"},
        )

    assert response.status_code == 401


@pytest.mark.unit
async def test_agent_registry_returns_structured_scoped_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SimpleNamespace(
        id="agent-1",
        name="planner",
        display_name="Planner",
        enabled=True,
    )
    app = _registry_app(monkeypatch, agent)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/agent-registry/resolve",
            json={
                "tenant_id": "tenant-1",
                "project_id": "project-1",
                "agent_id": "agent-1",
            },
            headers={"Authorization": "Bearer registry-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "agent_id": "agent-1",
        "name": "planner",
        "display_name": "Planner",
        "enabled": True,
    }


@pytest.mark.unit
async def test_provider_registry_requires_dedicated_registry_token() -> None:
    app = _provider_registry_app(None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/provider-registry/resolve",
            json={
                "tenant_id": "tenant-1",
                "provider_id": "00000000-0000-0000-0000-000000000001",
                "model_id": "model-1",
            },
            headers={"Authorization": "Bearer service-token"},
        )

    assert response.status_code == 401


@pytest.mark.unit
async def test_provider_registry_validates_model_and_returns_tenant_default() -> None:
    provider = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        llm_model="model-default",
        allowed_models='["model-1"]',
        secondary_models=["model-2"],
    )
    app = _provider_registry_app(provider)
    headers = {"Authorization": "Bearer registry-token"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        resolved = await client.post(
            "/internal/v1/workspace-core/provider-registry/resolve",
            json={
                "tenant_id": "tenant-1",
                "provider_id": "00000000-0000-0000-0000-000000000001",
                "model_id": "model-1",
            },
            headers=headers,
        )
        default = await client.post(
            "/internal/v1/workspace-core/provider-registry/default",
            json={"tenant_id": "tenant-1"},
            headers=headers,
        )

    assert resolved.status_code == 200
    assert resolved.json() == {
        "available": True,
        "provider_id": "00000000-0000-0000-0000-000000000001",
        "model_id": "model-1",
    }
    assert default.status_code == 200
    assert default.json() == {
        "available": True,
        "provider_id": "00000000-0000-0000-0000-000000000001",
        "model_id": "model-default",
    }


def _context_judge_payload() -> dict[str, object]:
    return {
        "user_id": "user-1",
        "current": None,
        "candidates": [
            {
                "tenant_id": "tenant-1",
                "project_id": "project-1",
                "membership_role": "member",
            },
            {
                "tenant_id": "tenant-2",
                "project_id": "project-2",
                "membership_role": "owner",
            },
        ],
    }


@pytest.mark.unit
async def test_context_judge_requires_dedicated_registry_token() -> None:
    app = _app()
    app.state.workspace_core_context_judge = FakeContextJudge()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/context-judge",
            json=_context_judge_payload(),
            headers={"Authorization": "Bearer service-token"},
        )

    assert response.status_code == 401


@pytest.mark.unit
async def test_context_judge_returns_only_structured_auditable_verdict() -> None:
    app = _app()
    judge = FakeContextJudge()
    app.state.workspace_core_context_judge = judge
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/context-judge",
            json=_context_judge_payload(),
            headers={"Authorization": "Bearer registry-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "selected": {
            "tenant_id": "tenant-2",
            "project_id": "project-2",
            "membership_role": "owner",
        },
        "rationale": "The structured evidence supports candidate index 1.",
        "evidence": ["candidate index 1 is available"],
        "agent_id": "provider-judge:model-judge",
        "tool_name": "select_workspace_context",
        "input_json": {
            "candidates": [
                WorkspaceContextCandidate(**candidate).model_dump()
                for candidate in _context_judge_payload()["candidates"]
            ]
        },
        "output_json": {
            "candidate_index": 1,
            "rationale": "The structured evidence supports candidate index 1.",
            "evidence": ["candidate index 1 is available"],
        },
        "latency_ms": 7,
    }
    assert len(judge.requests) == 1


@pytest.mark.unit
async def test_context_judge_fails_closed_when_agent_verdict_is_unavailable() -> None:
    app = _app()
    app.state.workspace_core_context_judge = FakeContextJudge(unavailable=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/context-judge",
            json=_context_judge_payload(),
            headers={"Authorization": "Bearer registry-token"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Workspace Context judge is unavailable"}


def _plan_judge_payload() -> dict[str, object]:
    return {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "actor_id": "user-1",
        "plan_id": "plan-1",
        "plan_revision": 3,
        "kind": "select_pipeline_target",
        "candidate_node_ids": ["node-1", "node-2"],
        "evidence": {"nodes": ["node-1", "node-2"]},
    }


@pytest.mark.unit
async def test_plan_judge_requires_dedicated_registry_token() -> None:
    app = _app()
    app.state.workspace_core_plan_judge = FakePlanJudge()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/plan-judge",
            json=_plan_judge_payload(),
            headers={"Authorization": "Bearer service-token"},
        )

    assert response.status_code == 401


@pytest.mark.unit
async def test_plan_judge_returns_only_structured_auditable_verdict() -> None:
    app = _app()
    judge = FakePlanJudge()
    app.state.workspace_core_plan_judge = judge
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/plan-judge",
            json=_plan_judge_payload(),
            headers={"Authorization": "Bearer registry-token"},
        )

    assert response.status_code == 200
    assert response.json()["proceed"] is True
    assert response.json()["selected_node_id"] == "node-2"
    assert response.json()["tool_name"] == "judge_workspace_plan"
    assert response.json()["input_json"]["plan_revision"] == 3
    assert len(judge.requests) == 1


@pytest.mark.unit
async def test_plan_judge_fails_closed_when_agent_verdict_is_unavailable() -> None:
    app = _app()
    app.state.workspace_core_plan_judge = FakePlanJudge(unavailable=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/plan-judge",
            json=_plan_judge_payload(),
            headers={"Authorization": "Bearer registry-token"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Workspace Plan judge is unavailable"}


def _autonomy_judge_payload() -> dict[str, object]:
    return {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "actor_id": "user-1",
        "workspace_revision": 7,
        "force": False,
        "candidates": [
            {
                "root_task_id": "task-1",
                "title": "First task",
                "description": None,
                "status": "pending",
                "metadata": {},
            },
            {
                "root_task_id": "task-2",
                "title": "Second task",
                "description": "Ready for execution",
                "status": "pending",
                "metadata": {},
            },
        ],
    }


@pytest.mark.unit
async def test_autonomy_judge_requires_dedicated_registry_token() -> None:
    app = _app()
    app.state.workspace_core_autonomy_judge = FakeAutonomyJudge()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/autonomy-judge",
            json=_autonomy_judge_payload(),
            headers={"Authorization": "Bearer service-token"},
        )

    assert response.status_code == 401


@pytest.mark.unit
async def test_autonomy_judge_returns_only_structured_auditable_verdict() -> None:
    app = _app()
    judge = FakeAutonomyJudge()
    app.state.workspace_core_autonomy_judge = judge
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/autonomy-judge",
            json=_autonomy_judge_payload(),
            headers={"Authorization": "Bearer registry-token"},
        )

    assert response.status_code == 200
    assert response.json()["verdict"] == "continue"
    assert response.json()["selected_root_task_id"] == "task-2"
    assert response.json()["tool_name"] == "judge_workspace_autonomy"
    assert len(judge.requests) == 1
    assert judge.requests[0].candidates[1] == WorkspaceAutonomyCandidate(
        root_task_id="task-2",
        title="Second task",
        description="Ready for execution",
        status="pending",
        metadata={},
    )


@pytest.mark.unit
async def test_autonomy_judge_fails_closed_when_agent_verdict_is_unavailable() -> None:
    app = _app()
    app.state.workspace_core_autonomy_judge = FakeAutonomyJudge(unavailable=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        response = await client.post(
            "/internal/v1/workspace-core/autonomy-judge",
            json=_autonomy_judge_payload(),
            headers={"Authorization": "Bearer registry-token"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Workspace Autonomy judge is unavailable"}


def _plan_dispatch_payload() -> dict[str, object]:
    return {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "plan_id": "plan-1",
        "plan_node_id": "node-1",
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "agent_id": "agent-1",
        "action": "run_pipeline",
        "outbox_id": "outbox-1",
        "correlation_id": "correlation-1",
        "conversation_id": "conversation-1",
        "payload": {"actor_id": "user-1", "reason": "contract"},
    }


@pytest.mark.unit
async def test_plan_dispatch_requires_provider_token_and_starts_one_scoped_send() -> None:
    app = _app()
    adapter = RecordingProviderAdapter()
    app.state.workspace_core_provider_adapter = adapter
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://api.test",
    ) as client:
        unauthorized = await client.post(
            "/internal/v1/workspace-core/plan-dispatch",
            json=_plan_dispatch_payload(),
            headers={"Authorization": "Bearer registry-token"},
        )
        response = await client.post(
            "/internal/v1/workspace-core/plan-dispatch",
            json=_plan_dispatch_payload(),
            headers={"Authorization": "Bearer webhook-token"},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "provider_id": "memstack-agent-runtime",
        "provider_bot_ref": "agent-1",
        "provider_run_id": "52f088e0-5a71-56fe-9519-74ff42ce0a62",
    }
    assert len(adapter.requests) == 1
    provider_request = adapter.requests[0]
    assert provider_request.id == "outbox-1"
    assert provider_request.method == "chat.send"
    assert provider_request.to_bot.provider_id == "memstack-workspace-agent-runtime"
    assert provider_request.extensions["user_id"] == "user-1"
    assert provider_request.extensions["correlation_id"] == "correlation-1"
