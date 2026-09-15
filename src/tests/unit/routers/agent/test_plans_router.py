"""Tests for plan-mode route hardening."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from inspect import getsource
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.routers.agent.plans import (
    ApprovePlanAndStartRequest,
    SwitchModeRequest,
    approve_plan_and_start,
    get_mode,
    get_tasks,
    switch_mode,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentPlanVersionModel,
    AgentTaskModel,
    Conversation,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.agent_turn_services import AGENT_TURN_MODULE_V2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
    clear_process_generation_host_v2,
    current_operation_context_v2,
    install_process_generation_host_v2,
    pin_generation_v2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_SERVICE_V2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.workspace_core.client import WorkspaceCoreClient

_ROOT = Path(__file__).resolve().parents[5]


@asynccontextmanager
async def _noop_agent_turn_operation(**_kwargs: object) -> AsyncIterator[None]:
    yield None


def _workspace_core_settings() -> WorkspaceCoreSettings:
    return WorkspaceCoreSettings.model_validate(
        {
            "WORKSPACE_CORE_BASE_URL": "http://workspace-core.test",
            "WORKSPACE_CORE_SERVICE_TOKEN": "service-token",
            "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "webhook-token",
            "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "event-token",
            "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "registry-token",
        }
    )


async def _add_conversation_task(
    db: AsyncSession,
    *,
    conversation_id: str,
    project_id: str,
    tenant_id: str,
    user_id: str,
) -> None:
    db.add(
        Conversation(
            id=conversation_id,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title="Scoped plan",
        )
    )
    db.add(
        AgentTaskModel(
            id=f"task-{conversation_id}",
            conversation_id=conversation_id,
            content="Authorized task",
            title="Authorized task",
            status="pending",
            priority="high",
            order_index=0,
        )
    )
    await db.commit()


class FailingDb:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("internal db secret")

    async def commit(self) -> None:
        return None


class AuthorizedDb:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: "conversation-1")


def test_approve_plan_environment_rejects_renderer_authority_fields() -> None:
    request = {
        "conversation_id": "conversation-1",
        "project_id": "project-1",
        "plan_version_id": "plan-version-1",
        "expected_plan_version": 1,
        "permission_profile": "full_access",
        "message": "Implement the approved plan",
        "message_id": "message-1",
        "idempotency_key": "approve-1",
    }

    with pytest.raises(ValidationError):
        ApprovePlanAndStartRequest.model_validate(
            {
                **request,
                "environment": {
                    "kind": "worktree",
                    "id": "renderer-controlled-sandbox",
                    "workspace_path": "/renderer-controlled",
                },
            }
        )


@pytest.mark.unit
async def test_workspace_policy_snapshot_comes_from_core_and_ignores_renderer_profile() -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/workspaces/workspace-1/agent-policy")
        assert request.headers["authorization"] == "Bearer service-token"
        assert request.headers["x-memstack-user-id"] == "user-1"
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "tenant_id": "tenant-1",
                    "project_id": "project-1",
                    "workspace_id": "workspace-1",
                    "revision": 4,
                    "roles": {
                        "default": {"provider_id": "provider-1", "model_id": "model-1"},
                        "fast": None,
                        "coding": None,
                        "vision": None,
                    },
                    "fallbacks": [],
                    "reasoning_effort": "high",
                    "permission_mode": "automatic",
                    "capability_version": "workspace-agent-policy-v1",
                    "updated_at": "2026-08-13T00:00:00Z",
                }
            ).encode(),
            headers={"content-type": "application/json"},
        )

    client = WorkspaceCoreClient(
        _workspace_core_settings(),
        transport=httpx.MockTransport(handler),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(workspace_core_client=client))
    )
    conversation = SimpleNamespace(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
    )

    snapshot, permission_profile = await plans_router._load_workspace_policy_snapshot(
        request,
        conversation=conversation,
        current_user=SimpleNamespace(id="user-1", is_superuser=False),
    )

    assert snapshot["revision"] == 4
    assert snapshot["permission_mode"] == "automatic"
    assert permission_profile == "workspace_write"


@pytest.mark.unit
async def test_workspace_policy_snapshot_fails_closed_without_core() -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    conversation = SimpleNamespace(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
    )

    with pytest.raises(HTTPException) as exc_info:
        await plans_router._load_workspace_policy_snapshot(
            request,
            conversation=conversation,
            current_user=SimpleNamespace(id="user-1", is_superuser=False),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "WORKSPACE_CORE_UNAVAILABLE"


@pytest.mark.unit
async def test_resolve_cloud_run_environment_uses_exact_project_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    class SandboxSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    lifecycle = SimpleNamespace(
        ensure_sandbox_running=AsyncMock(
            return_value=SimpleNamespace(
                project_id="project-1",
                tenant_id="tenant-1",
                sandbox_id="sandbox-server-authority",
                is_healthy=True,
                created_at=datetime(2026, 7, 28, 10),
            )
        )
    )

    class SandboxAuthorityContext:
        async def __aenter__(self) -> SimpleNamespace:
            return SimpleNamespace(
                services=SimpleNamespace(lifecycle_service=lifecycle),
            )

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(plans_router, "async_session_factory", SandboxSessionContext)
    captured: dict[str, object] = {}

    def sandbox_authority(**kwargs: object) -> SandboxAuthorityContext:
        captured.update(kwargs)
        return SandboxAuthorityContext()

    monkeypatch.setattr(plans_router, "sandbox_operation_authority_v2", sandbox_authority)

    environment = await plans_router._resolve_cloud_run_environment(
        project_id="project-1",
        tenant_id="tenant-1",
        kind="worktree",
        bound_at=datetime(2026, 7, 28, 9, tzinfo=UTC),
    )

    assert environment == {
        "id": "sandbox-server-authority",
        "kind": "worktree",
        "label": "sandbox-server-authority",
        "workspace_path": "/workspace",
        "repository_root": None,
        "branch": None,
        "base_commit": None,
        "source_run_id": None,
        "created_at": "2026-07-28T10:00:00+00:00",
    }
    lifecycle.ensure_sandbox_running.assert_awaited_once_with(
        project_id="project-1",
        tenant_id="tenant-1",
    )
    assert captured["scope"] == ScopeV2(
        kind=ScopeKindV2.PROJECT,
        tenant_id="tenant-1",
        project_id="project-1",
    )
    assert captured["identity"] == {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
    }


@pytest.mark.unit
async def test_approve_plan_persists_server_resolved_environment_and_reuses_it_on_retry(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_user: User,
    test_project_db: Project,
) -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    conversation_id = "conversation-approved-environment"
    test_db.add(
        Conversation(
            id=conversation_id,
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
            title="Approved environment",
            current_mode="plan",
        )
    )
    await test_db.commit()
    plan = AgentPlanVersionModel(
        id="plan-version-approved-environment",
        conversation_id=conversation_id,
        version=1,
        status="draft",
        tasks_json=[
            {
                "id": "approved-task",
                "conversation_id": conversation_id,
                "content": "Implement the approved plan",
                "status": "pending",
                "priority": "medium",
                "order_index": 0,
                "created_at": "2026-07-28T10:00:00+00:00",
                "updated_at": None,
            }
        ],
    )
    test_db.add(plan)
    await test_db.commit()

    environment = {
        "id": "sandbox-authoritative",
        "kind": "local",
        "label": "sandbox-authoritative",
        "workspace_path": "/workspace",
        "repository_root": None,
        "branch": None,
        "base_commit": None,
        "source_run_id": None,
        "created_at": "2026-07-28T10:00:00+00:00",
    }
    resolve_environment = AsyncMock(return_value=environment)
    execute_plan = AsyncMock(return_value=None)
    monkeypatch.setattr(plans_router, "_resolve_cloud_run_environment", resolve_environment)
    monkeypatch.setattr(plans_router, "_execute_approved_plan", execute_plan)

    body = ApprovePlanAndStartRequest(
        conversation_id=conversation_id,
        project_id=test_project_db.id,
        plan_version_id=plan.id,
        expected_plan_version=1,
        permission_profile="read_only",
        message="Implement the approved plan",
        message_id="message-approved-environment",
        idempotency_key="approve-environment-1",
        environment={"kind": "local"},
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(container=object())),
    )

    response = await approve_plan_and_start(
        body=body,
        request=request,
        current_user=test_user,
        db=test_db,
    )
    await asyncio.sleep(0)

    run = await test_db.get(AgentPlanRunModel, response["run"]["id"])
    assert run is not None
    assert run.authorization_snapshot["environment"] == environment
    assert response["run"]["environment"] == environment
    assert response["plan_version"]["status"] == "approved"
    assert response["run"]["status"] == "queued"
    assert response["conversation"]["current_mode"] == "build"
    resolve_environment.assert_awaited_once()

    resolve_environment.reset_mock()
    retried = await approve_plan_and_start(
        body=body,
        request=request,
        current_user=test_user,
        db=test_db,
    )

    assert retried["created"] is False
    assert retried["run"]["environment"] == environment
    resolve_environment.assert_not_awaited()


@pytest.mark.unit
async def test_execute_approved_plan_propagates_canonical_run_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    lifecycle: list[str] = []
    run = SimpleNamespace(
        status="queued",
        revision=1,
        updated_at=datetime.now(UTC),
        completed_at=None,
        error=None,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=run),
        refresh=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    class SessionContext:
        async def __aenter__(self) -> object:
            return session

        async def __aexit__(self, *_args: object) -> None:
            return None

    received: dict[str, object] = {}

    class Service:
        async def stream_chat_v2(self, **kwargs: object):
            received.update(kwargs)
            yield {"type": "complete"}

    @asynccontextmanager
    async def operation_context(**_kwargs: object) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            lifecycle.append("operation-generation-release")

    async def publish_status(**_kwargs: object) -> None:
        lifecycle.append("status-publish")

    monkeypatch.setattr(plans_router, "async_session_factory", SessionContext)
    resolve_turn_service = AsyncMock(return_value=Service())
    monkeypatch.setattr(
        plans_router,
        "current_agent_turn_service_v2",
        resolve_turn_service,
    )
    monkeypatch.setattr(
        plans_router,
        "pin_agent_turn_operation_v2",
        operation_context,
    )
    monkeypatch.setattr(plans_router, "settle_agent_plan_run", AsyncMock())
    publish_run_status = AsyncMock(side_effect=publish_status)
    monkeypatch.setattr(
        plans_router,
        "_publish_plan_run_status",
        publish_run_status,
        raising=False,
    )

    await plans_router._execute_approved_plan(
        run_id="plan-run-1",
        conversation_id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        message="Execute",
        message_id="client-message-1",
    )

    assert received["execution_message_id"] == "client-message-1"
    assert received["canonical_run_id"] == "plan-run-1"
    resolve_turn_service.assert_awaited_once_with()
    session.refresh.assert_awaited_once_with(run)
    assert publish_run_status.await_count == 2
    publish_run_status.assert_awaited_with(run=run)
    assert lifecycle.index("status-publish") < lifecycle.index("operation-generation-release")
    assert run.status == "ready_review"
    assert run.revision == 2


@pytest.mark.unit
async def test_execute_approved_plan_replaces_expired_copied_http_generation_with_own_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="approved-plan-http-generation",
    )
    install_process_generation_host_v2(host)
    enter_background = asyncio.Event()
    observed: dict[str, object] = {}
    run = SimpleNamespace(
        status="queued",
        revision=1,
        updated_at=datetime.now(UTC),
        completed_at=None,
        error=None,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=run),
        refresh=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    class SessionContext:
        async def __aenter__(self) -> object:
            await enter_background.wait()
            return session

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Service:
        async def stream_chat_v2(self, **_kwargs: object):
            operation = current_operation_context_v2()
            observed["generation"] = operation.descriptor.generation
            observed["db"] = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
            observed["identity"] = operation.require(OPERATION_IDENTITY_SERVICE_V2)
            observed["metadata"] = operation.require(OPERATION_METADATA_SERVICE_V2)
            observed["distribution"] = operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
            assert operation.generation.resolve(
                RUNTIME_BOUNDARY_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
            yield {"type": "complete"}

    monkeypatch.setattr(plans_router, "async_session_factory", SessionContext)
    resolve_turn_service = AsyncMock(return_value=Service())
    monkeypatch.setattr(
        plans_router,
        "current_agent_turn_service_v2",
        resolve_turn_service,
    )
    monkeypatch.setattr(plans_router, "settle_agent_plan_run", AsyncMock())
    monkeypatch.setattr(plans_router, "_publish_plan_run_status", AsyncMock())
    background_task: asyncio.Task[None] | None = None

    try:
        async with pin_generation_v2(host) as copied_http_generation:
            await host.bootstrap(
                profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
                manifest_paths=(
                    _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",
                ),
                generation=2,
                version=2,
                nonce="approved-plan-background-generation",
            )
            background_task = asyncio.create_task(
                plans_router._execute_approved_plan(
                    run_id="plan-run-1",
                    conversation_id="conversation-1",
                    project_id="project-1",
                    tenant_id="tenant-1",
                    user_id="user-1",
                    message="Execute",
                    message_id="client-message-1",
                )
            )
            await asyncio.sleep(0)

        with pytest.raises(RuntimeV2Error, match="generation is disposed"):
            copied_http_generation.resolve(
                RUNTIME_BOUNDARY_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
        enter_background.set()
        await background_task

        assert observed["generation"] == 2
        assert observed["db"] is session
        assert observed["identity"] == {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "project_id": "project-1",
        }
        assert observed["metadata"] == {
            "kind": "agent-turn",
            "channel": "approved-plan",
            "conversation_id": "conversation-1",
            "run_id": "plan-run-1",
            "message_id": "client-message-1",
        }
        distribution = observed["distribution"]
        assert isinstance(distribution, dict)
        assert distribution["descriptor"]["generation"] == 2
        resolve_turn_service.assert_awaited_once_with()
    finally:
        enter_background.set()
        if background_task is not None and not background_task.done():
            background_task.cancel()
            await asyncio.gather(background_task, return_exceptions=True)
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.unit
async def test_execute_approved_plan_rejects_missing_v2_turn_service_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    def disable_turn_service(document: ProfileDocumentV2) -> ProfileDocumentV2:
        return replace(
            document,
            entries=tuple(
                replace(entry, enabled=False) if entry.module_ref == AGENT_TURN_MODULE_V2 else entry
                for entry in document.entries
            ),
        )

    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=3,
        version=3,
        nonce="approved-plan-turn-missing-service",
        profile_projector=disable_turn_service,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host)
    run = SimpleNamespace(
        status="queued",
        revision=1,
        updated_at=datetime.now(UTC),
        completed_at=None,
        error=None,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=run),
        refresh=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    class SessionContext:
        async def __aenter__(self) -> object:
            return session

        async def __aexit__(self, *_args: object) -> None:
            return None

    settle = AsyncMock()
    monkeypatch.setattr(plans_router, "async_session_factory", SessionContext)
    monkeypatch.setattr(plans_router, "settle_agent_plan_run", settle)
    monkeypatch.setattr(plans_router, "_publish_plan_run_status", AsyncMock())

    try:
        await plans_router._execute_approved_plan(
            run_id="plan-run-1",
            conversation_id="conversation-1",
            project_id="project-1",
            tenant_id="tenant-1",
            user_id="user-1",
            message="Execute",
            message_id="client-message-1",
        )

        assert run.status == "failed"
        assert run.revision == 2
        assert run.error == (
            "service service:agent.turn-service@1.0.0 is unavailable for scope session"
        )
        session.rollback.assert_awaited_once_with()
        settle.assert_awaited_once()
        assert settle.await_args.kwargs["succeeded"] is False
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.unit
async def test_execute_approved_plan_refreshes_authority_after_stream_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    lifecycle: list[str] = []
    run = SimpleNamespace(
        status="queued",
        revision=1,
        updated_at=datetime.now(UTC),
        completed_at=None,
        error=None,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=run),
        refresh=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    class SessionContext:
        async def __aenter__(self) -> object:
            return session

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Service:
        async def stream_chat_v2(self, **_kwargs: object):
            yield {"type": "start"}
            raise RuntimeError("stream failed")

    @asynccontextmanager
    async def operation_context(**_kwargs: object) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            lifecycle.append("operation-generation-release")

    async def publish_status(**_kwargs: object) -> None:
        lifecycle.append("status-publish")

    settle = AsyncMock()
    monkeypatch.setattr(plans_router, "async_session_factory", SessionContext)
    resolve_turn_service = AsyncMock(return_value=Service())
    monkeypatch.setattr(
        plans_router,
        "current_agent_turn_service_v2",
        resolve_turn_service,
    )
    monkeypatch.setattr(
        plans_router,
        "pin_agent_turn_operation_v2",
        operation_context,
    )
    monkeypatch.setattr(plans_router, "settle_agent_plan_run", settle)
    publish_run_status = AsyncMock(side_effect=publish_status)
    monkeypatch.setattr(
        plans_router,
        "_publish_plan_run_status",
        publish_run_status,
        raising=False,
    )

    await plans_router._execute_approved_plan(
        run_id="plan-run-1",
        conversation_id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        message="Execute",
        message_id="client-message-1",
    )

    session.rollback.assert_awaited_once()
    session.refresh.assert_awaited_once_with(run)
    assert run.status == "failed"
    assert run.revision == 2
    settle.assert_awaited_once()
    assert publish_run_status.await_count == 2
    publish_run_status.assert_awaited_with(run=run)
    assert lifecycle.index("status-publish") < lifecycle.index("operation-generation-release")


@pytest.mark.unit
async def test_execute_approved_plan_closes_stream_before_boundary_release_on_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    lifecycle: list[str] = []
    waiting_for_next = asyncio.Event()
    run = SimpleNamespace(
        status="queued",
        revision=1,
        updated_at=datetime.now(UTC),
        completed_at=None,
        error=None,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=run),
        refresh=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    class SessionContext:
        async def __aenter__(self) -> object:
            lifecycle.append("session-enter")
            return session

        async def __aexit__(self, *_args: object) -> None:
            lifecycle.append("session-exit")

    @asynccontextmanager
    async def operation_context(**_kwargs: object) -> AsyncIterator[None]:
        lifecycle.append("operation-enter")
        try:
            yield None
        finally:
            lifecycle.append("operation-generation-release")

    class ClosingStream:
        def __init__(self) -> None:
            self._event_emitted = False

        def __aiter__(self) -> "ClosingStream":
            return self

        async def __anext__(self) -> dict[str, str]:
            if not self._event_emitted:
                self._event_emitted = True
                return {"type": "start"}
            waiting_for_next.set()
            await asyncio.Future()
            raise AssertionError("unreachable")

        async def aclose(self) -> None:
            lifecycle.append("stream-close")

    class Service:
        def stream_chat_v2(self, **_kwargs: object) -> ClosingStream:
            return ClosingStream()

    monkeypatch.setattr(plans_router, "async_session_factory", SessionContext)
    monkeypatch.setattr(
        plans_router,
        "current_agent_turn_service_v2",
        AsyncMock(return_value=Service()),
    )
    monkeypatch.setattr(plans_router, "pin_agent_turn_operation_v2", operation_context)

    monkeypatch.setattr(plans_router, "_publish_plan_run_status", AsyncMock())

    task = asyncio.create_task(
        plans_router._execute_approved_plan(
            run_id="plan-run-1",
            conversation_id="conversation-1",
            project_id="project-1",
            tenant_id="tenant-1",
            user_id="user-1",
            message="Execute",
            message_id="client-message-1",
        )
    )
    await asyncio.wait_for(waiting_for_next.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert lifecycle.index("stream-close") < lifecycle.index("operation-generation-release")
    assert lifecycle.index("operation-generation-release") < lifecycle.index("session-exit")


@pytest.mark.unit
async def test_execute_approved_plan_closes_stream_before_boundary_release_on_stream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    lifecycle: list[str] = []
    run = SimpleNamespace(
        status="queued",
        revision=1,
        updated_at=datetime.now(UTC),
        completed_at=None,
        error=None,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=run),
        refresh=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    class SessionContext:
        async def __aenter__(self) -> object:
            lifecycle.append("session-enter")
            return session

        async def __aexit__(self, *_args: object) -> None:
            lifecycle.append("session-exit")

    @asynccontextmanager
    async def operation_context(**_kwargs: object) -> AsyncIterator[None]:
        lifecycle.append("operation-enter")
        try:
            yield None
        finally:
            lifecycle.append("operation-generation-release")

    class FailingClosingStream:
        def __init__(self) -> None:
            self._event_emitted = False

        def __aiter__(self) -> "FailingClosingStream":
            return self

        async def __anext__(self) -> dict[str, str]:
            if not self._event_emitted:
                self._event_emitted = True
                return {"type": "start"}
            raise RuntimeError("stream failed")

        async def aclose(self) -> None:
            lifecycle.append("stream-close")

    class Service:
        def stream_chat_v2(self, **_kwargs: object) -> FailingClosingStream:
            return FailingClosingStream()

    monkeypatch.setattr(plans_router, "async_session_factory", SessionContext)
    monkeypatch.setattr(
        plans_router,
        "current_agent_turn_service_v2",
        AsyncMock(return_value=Service()),
    )
    monkeypatch.setattr(plans_router, "pin_agent_turn_operation_v2", operation_context)
    monkeypatch.setattr(plans_router, "settle_agent_plan_run", AsyncMock())
    monkeypatch.setattr(plans_router, "_publish_plan_run_status", AsyncMock())

    await plans_router._execute_approved_plan(
        run_id="plan-run-1",
        conversation_id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        message="Execute",
        message_id="client-message-1",
    )

    assert lifecycle.index("stream-close") < lifecycle.index("operation-generation-release")
    assert lifecycle.index("operation-generation-release") < lifecycle.index("session-exit")


def test_execute_approved_plan_has_no_static_llm_or_di_composition() -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    source = getsource(plans_router._execute_approved_plan)

    assert "create_llm_client" not in source
    assert "DIContainer" not in source
    assert ".agent_service(" not in source


@pytest.mark.unit
async def test_publish_plan_run_status_persists_and_broadcasts_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.primary.web.routers.agent.plans as plans_router

    published: list[tuple[str, dict[str, Any]]] = []

    class TrackedRedis:
        def __init__(self, name: str) -> None:
            self.name = name
            self.close_calls = 0

        async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str]:
            for key in ():
                yield key

        async def delete(self, *_keys: str | bytes) -> int:
            return 0

        async def xadd(self, _stream: str, _fields: dict[str, object], **_options: object) -> bytes:
            return b"1-0"

        async def aclose(self) -> None:
            self.close_calls += 1

    first_redis = TrackedRedis("first")
    second_redis = TrackedRedis("second")
    redis_clients = iter((first_redis, second_redis))

    async def redis_factory() -> TrackedRedis:
        return next(redis_clients)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=901,
        version=901,
    )
    assert first.accepted is True

    class EventBus:
        def __init__(self, redis_client: object) -> None:
            assert redis_client is first_redis

        async def publish_to_stream(
            self,
            conversation_id: str,
            event: dict[str, Any],
        ) -> str:
            published.append((conversation_id, event))
            second = await host.bootstrap(
                profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
                manifest_paths=(
                    _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",
                ),
                generation=902,
                version=902,
            )
            assert second.accepted is True
            assert first_redis.close_calls == 0
            return "1-0"

    manager = SimpleNamespace(broadcast_to_conversation=AsyncMock(return_value=1))
    monkeypatch.setattr(plans_router, "RedisEventBusAdapter", EventBus, raising=False)
    monkeypatch.setattr(
        plans_router,
        "get_connection_manager",
        lambda: manager,
        raising=False,
    )
    run = SimpleNamespace(
        id="plan-run-1",
        conversation_id="conversation-1",
        project_id="project-1",
        plan_version_id="plan-version-1",
        idempotency_key="plan-approval-1",
        message_id="message-1",
        request_message="Execute",
        status="ready_review",
        revision=2,
        created_at=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 4, 12, 1, tzinfo=UTC),
        completed_at=datetime(2026, 8, 4, 12, 1, tzinfo=UTC),
        error=None,
        permission_profile="read_only",
        authorization_snapshot={
            "conversation_id": "conversation-1",
            "project_id": "project-1",
            "plan_version_id": "plan-version-1",
            "permission_profile": "read_only",
            "environment": None,
        },
    )

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="plan-status-publication",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            await plans_router._publish_plan_run_status(run=run)
            assert first_redis.close_calls == 0
            assert second_redis.close_calls == 0

        assert first_redis.close_calls == 1
        assert second_redis.close_calls == 0
    finally:
        await host.close()

    assert second_redis.close_calls == 1

    assert len(published) == 1
    conversation_id, event = published[0]
    assert conversation_id == "conversation-1"
    assert event["type"] == "run_status"
    assert event["conversation_id"] == "conversation-1"
    assert event["payload"] == event["data"]
    assert event["payload"]["id"] == "plan-run-1"
    assert event["payload"]["status"] == "ready_review"
    assert event["payload"]["revision"] == 2
    assert event["payload"]["completed_at"] == "2026-08-04T12:01:00+00:00"
    assert isinstance(event["event_time_us"], int)
    manager.broadcast_to_conversation.assert_awaited_once_with(
        "conversation-1",
        event,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_switch_mode_sanitizes_internal_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await switch_mode(
            request_body=SwitchModeRequest(conversation_id="conversation-1", mode="plan"),
            current_user=SimpleNamespace(id="user-1"),
            db=FailingDb(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to switch mode"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_mode_sanitizes_internal_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_mode(
            conversation_id="conversation-1",
            current_user=SimpleNamespace(id="user-1"),
            db=FailingDb(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get mode"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.parametrize(
    ("operation", "revoked_membership"),
    [
        ("switch", "project"),
        ("switch", "tenant"),
        ("get", "project"),
        ("get", "tenant"),
    ],
)
async def test_plan_mode_rejects_owned_conversation_after_scope_membership_revoked(
    test_db: AsyncSession,
    test_user: User,
    test_project_db: Project,
    operation: str,
    revoked_membership: str,
) -> None:
    conversation_id = f"conversation-{operation}-{revoked_membership}-revoked"
    await _add_conversation_task(
        test_db,
        conversation_id=conversation_id,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )

    if revoked_membership == "project":
        statement = delete(UserProject).where(
            UserProject.user_id == test_user.id,
            UserProject.project_id == test_project_db.id,
        )
    else:
        statement = delete(UserTenant).where(
            UserTenant.user_id == test_user.id,
            UserTenant.tenant_id == test_project_db.tenant_id,
        )
    await test_db.execute(statement)
    await test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        if operation == "switch":
            await switch_mode(
                request_body=SwitchModeRequest(conversation_id=conversation_id, mode="build"),
                current_user=test_user,
                db=test_db,
            )
        else:
            await get_mode(
                conversation_id=conversation_id,
                current_user=test_user,
                db=test_db,
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tasks_sanitizes_internal_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingTaskRepository:
        def __init__(self, db: Any) -> None:
            self.db = db

        find_by_conversation = AsyncMock(side_effect=RuntimeError("internal task secret"))

    import src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository as task_repo

    monkeypatch.setattr(task_repo, "SqlAgentTaskRepository", FailingTaskRepository)

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-1",
            current_user=SimpleNamespace(id="user-1"),
            db=AuthorizedDb(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get tasks"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
async def test_get_tasks_returns_tasks_for_owned_tenant_project_conversation(
    test_db: AsyncSession,
    test_user: User,
    test_project_db: Project,
) -> None:
    await _add_conversation_task(
        test_db,
        conversation_id="conversation-owned",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )

    response = await get_tasks(
        conversation_id="conversation-owned",
        status=None,
        current_user=test_user,
        db=test_db,
    )

    assert response.conversation_id == "conversation-owned"
    assert response.total_count == 1
    assert response.tasks[0].id == "task-conversation-owned"
    payload = response.model_dump()
    assert payload["approval"] == {"kind": "legacy_mode_switch"}
    assert payload["plan_version"] is None


@pytest.mark.unit
async def test_get_tasks_rejects_another_users_conversation(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    another_user: User,
) -> None:
    await _add_conversation_task(
        test_db,
        conversation_id="conversation-other-user",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=another_user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-other-user",
            status=None,
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.unit
async def test_get_tasks_rejects_owned_conversation_without_project_membership(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_user: User,
    another_user: User,
) -> None:
    project = Project(
        id="project-without-membership",
        tenant_id=test_tenant_db.id,
        name="Restricted project",
        owner_id=another_user.id,
    )
    test_db.add(project)
    await test_db.commit()
    await _add_conversation_task(
        test_db,
        conversation_id="conversation-restricted-project",
        project_id=project.id,
        tenant_id=test_tenant_db.id,
        user_id=test_user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-restricted-project",
            status=None,
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.unit
async def test_get_tasks_rejects_owned_conversation_without_tenant_membership(
    test_db: AsyncSession,
    test_user: User,
    another_user: User,
) -> None:
    tenant = Tenant(
        id="tenant-without-membership",
        name="Restricted tenant",
        slug="restricted-tenant",
        owner_id=another_user.id,
    )
    project = Project(
        id="project-in-restricted-tenant",
        tenant_id=tenant.id,
        name="Restricted tenant project",
        owner_id=another_user.id,
    )
    test_db.add_all(
        [
            tenant,
            project,
            UserProject(
                id="stale-project-membership",
                user_id=test_user.id,
                project_id=project.id,
                role="member",
            ),
        ]
    )
    await test_db.commit()
    await _add_conversation_task(
        test_db,
        conversation_id="conversation-restricted-tenant",
        project_id=project.id,
        tenant_id=tenant.id,
        user_id=test_user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-restricted-tenant",
            status=None,
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.unit
async def test_get_tasks_rejects_conversation_whose_project_belongs_to_another_tenant(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    tenant = Tenant(
        id="tenant-mismatched-with-project",
        name="Mismatched tenant",
        slug="mismatched-tenant",
        owner_id=test_user.id,
    )
    test_db.add_all(
        [
            tenant,
            UserTenant(
                id="mismatched-tenant-membership",
                user_id=test_user.id,
                tenant_id=tenant.id,
                role="owner",
            ),
        ]
    )
    await test_db.commit()
    await _add_conversation_task(
        test_db,
        conversation_id="conversation-cross-tenant-project",
        project_id=test_project_db.id,
        tenant_id=tenant.id,
        user_id=test_user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-cross-tenant-project",
            status=None,
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"
