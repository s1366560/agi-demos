"""Contract tests for the Avernet-backed Cloud task-session saga."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.workspace_core_task_sessions import (
    _complete_platform_saga,
    _new_conversation,
    _stable_id,
    register_task_session_routes,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    TaskSessionCreationReceiptModel,
    Tenant,
    User,
    UserProject,
)
from src.infrastructure.workspace_core.client import WorkspaceCoreClient

TENANT_ID = "tenant-avernet-task-session"
PROJECT_ID = "project-avernet-task-session"
IDEMPOTENCY_KEY = "task-session-key-1"


def _settings() -> WorkspaceCoreSettings:
    return WorkspaceCoreSettings.model_validate(
        {
            "WORKSPACE_CORE_BASE_URL": "http://workspace-core.test",
            "WORKSPACE_CORE_SERVICE_TOKEN": "service-token",
            "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "webhook-token",
            "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "event-token",
            "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "registry-token",
        }
    )


async def _seed_scope(db: AsyncSession, user: User) -> None:
    db.add_all(
        [
            Tenant(
                id=TENANT_ID,
                name="Avernet task-session tenant",
                slug="avernet-task-session-tenant",
                owner_id=user.id,
            ),
            Project(
                id=PROJECT_ID,
                tenant_id=TENANT_ID,
                name="Avernet task-session project",
                owner_id=user.id,
            ),
            UserProject(
                id="avernet-task-session-membership",
                user_id=user.id,
                project_id=PROJECT_ID,
                role="owner",
            ),
        ]
    )
    await db.commit()


def _app(
    db: object,
    user: User,
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
) -> FastAPI:
    app = FastAPI()
    register_task_session_routes(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _settings(),
        transport=httpx.MockTransport(handler),
    )

    async def current_user() -> User:
        return user

    async def session() -> object:
        yield db

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = session
    return app


class _FailingCommitSession:
    def __init__(self, session: AsyncSession, *, fail_on: int) -> None:
        self._session = session
        self._fail_on = fail_on
        self._commits = 0

    def add(self, value: object) -> None:
        self._session.add(value)

    async def execute(self, *args: object, **kwargs: object) -> object:
        return await self._session.execute(*args, **kwargs)

    async def commit(self) -> None:
        self._commits += 1
        if self._commits == self._fail_on:
            raise SQLAlchemyError("injected platform commit failure")
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class _CompetingCommitSession:
    """Deterministically inject a second platform instance at the commit race."""

    def __init__(
        self,
        session: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        competing_conversation: Conversation,
    ) -> None:
        self._session = session
        self._session_factory = session_factory
        self._competing_conversation = competing_conversation
        self._injected = False

    def add(self, value: object) -> None:
        self._session.add(value)

    async def execute(self, *args: object, **kwargs: object) -> object:
        return await self._session.execute(*args, **kwargs)

    async def commit(self) -> None:
        if not self._injected:
            self._injected = True
            await self._session.rollback()
            async with self._session_factory() as competing_session:
                competing_session.add(self._competing_conversation)
                await competing_session.commit()
            raise IntegrityError("INSERT conversations", {}, Exception("duplicate key"))
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


def _body(*, content: str = "Review the release") -> dict[str, object]:
    return {
        "idempotency_key": IDEMPOTENCY_KEY,
        "workspace": {"kind": "existing", "workspace_id": "workspace-core-only"},
        "conversation": {"title": "Release review", "capability_mode": "work"},
        "initial_message": {
            "content": content,
            "context_items": [
                {
                    "kind": "plugin",
                    "resource_id": "plugin-review",
                    "label": "Review plugin",
                }
            ],
        },
    }


@pytest.mark.unit
async def test_task_session_saga_replays_core_and_keeps_one_conversation(
    test_db: AsyncSession,
    test_user: User,
) -> None:
    await _seed_scope(test_db, test_user)
    actor_id = str(test_user.id)
    conversation_id = _stable_id(
        "conversation",
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        actor_id=actor_id,
        idempotency_key=IDEMPOTENCY_KEY,
    )
    message_id = _stable_id(
        "message",
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        actor_id=actor_id,
        idempotency_key=IDEMPOTENCY_KEY,
    )
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == (
            f"/internal/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/task-sessions"
        )
        assert request.headers["authorization"] == "Bearer service-token"
        assert request.headers["x-memstack-user-id"] == actor_id
        assert request.headers["x-memstack-user-email"] == test_user.email
        assert request.headers["x-idempotency-key"] == IDEMPOTENCY_KEY
        payload = json.loads(request.content)
        assert payload["conversation_id"] == conversation_id
        assert payload["initial_message"]["message_id"] == message_id
        return httpx.Response(
            200 if calls > 1 else 201,
            json={
                "receipt_id": "core-receipt-1",
                "replayed": calls > 1,
                "workspace": {
                    "id": "workspace-core-only",
                    "tenant_id": TENANT_ID,
                    "project_id": PROJECT_ID,
                    "name": "Core workspace",
                    "is_archived": False,
                },
                "initial_message": {
                    "id": message_id,
                    "workspace_id": "workspace-core-only",
                    "sender_id": actor_id,
                    "sender_type": "human",
                    "content": "Review the release",
                    "mentions": [],
                    "parent_message_id": None,
                    "metadata": {
                        "source": "task_session",
                        "conversation_id": conversation_id,
                        "context_items": payload["initial_message"]["context_items"],
                    },
                    "created_at": "2026-08-13T00:00:00Z",
                },
                "policy": None,
                "capability_version": "avernet-task-session-v1",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(test_db, test_user, handler)),
        base_url="http://gateway.test",
    ) as client:
        first = await client.post(
            f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/task-sessions",
            json=_body(),
        )
        replay = await client.post(
            f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/task-sessions",
            json=_body(),
        )

    assert first.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["conversation"]["id"] == conversation_id
    count = await test_db.scalar(select(func.count()).select_from(Conversation))
    assert count == 1
    conversation = await test_db.get(Conversation, conversation_id)
    assert conversation is not None
    assert conversation.meta["task_session_saga"] == {
        "status": "committed",
        "receipt_id": "core-receipt-1",
        "payload_hash": conversation.meta["task_session_saga"]["payload_hash"],
        "idempotency_key": IDEMPOTENCY_KEY,
        "initial_message_id": message_id,
    }


@pytest.mark.unit
async def test_task_session_replays_core_after_platform_commit_failure(
    test_db: AsyncSession,
    test_user: User,
) -> None:
    await _seed_scope(test_db, test_user)
    actor_id = str(test_user.id)
    conversation_id = _stable_id(
        "conversation",
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        actor_id=actor_id,
        idempotency_key=IDEMPOTENCY_KEY,
    )
    message_id = _stable_id(
        "message",
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        actor_id=actor_id,
        idempotency_key=IDEMPOTENCY_KEY,
    )
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        return httpx.Response(
            200 if calls > 1 else 201,
            json={
                "receipt_id": "core-receipt-recovery",
                "replayed": calls > 1,
                "workspace": {
                    "id": "workspace-core-only",
                    "tenant_id": TENANT_ID,
                    "project_id": PROJECT_ID,
                    "name": "Core workspace",
                    "is_archived": False,
                },
                "initial_message": {
                    "id": message_id,
                    "workspace_id": "workspace-core-only",
                    "sender_id": actor_id,
                    "sender_type": "human",
                    "content": "Review the release",
                    "mentions": [],
                    "parent_message_id": None,
                    "metadata": {
                        "source": "task_session",
                        "conversation_id": conversation_id,
                        "context_items": payload["initial_message"]["context_items"],
                    },
                    "created_at": "2026-08-13T00:00:00Z",
                },
                "policy": None,
                "capability_version": "avernet-task-session-v1",
            },
        )

    frozen_user = SimpleNamespace(
        id=test_user.id,
        email=test_user.email,
        is_superuser=test_user.is_superuser,
    )
    failing_session = _FailingCommitSession(test_db, fail_on=3)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=_app(failing_session, frozen_user, handler),
            raise_app_exceptions=False,
        ),
        base_url="http://gateway.test",
    ) as client:
        failed = await client.post(
            f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/task-sessions",
            json=_body(),
        )

    assert failed.status_code == 503
    journal = (
        await test_db.execute(select(TaskSessionCreationReceiptModel))
    ).scalar_one()
    assert journal.status == "core_committed"
    assert journal.core_receipt_id == "core-receipt-recovery"
    assert journal.conversation_id is None
    assert await test_db.get(Conversation, conversation_id) is None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(test_db, frozen_user, handler)),
        base_url="http://gateway.test",
    ) as client:
        replay = await client.post(
            f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/task-sessions",
            json=_body(),
        )

    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert calls == 2
    assert await test_db.scalar(select(func.count()).select_from(Conversation)) == 1
    assert (
        await test_db.scalar(select(func.count()).select_from(TaskSessionCreationReceiptModel))
        == 1
    )
    await test_db.refresh(journal)
    assert journal.status == "completed"
    assert journal.conversation_id == conversation_id


@pytest.mark.unit
async def test_task_session_concurrent_platform_commit_finalizes_shared_journal(
    test_db: AsyncSession,
    test_engine: object,
    test_user: User,
) -> None:
    """A losing platform instance adopts the winner without duplicating state."""
    await _seed_scope(test_db, test_user)
    actor_id = str(test_user.id)
    conversation_id = _stable_id(
        "conversation",
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        actor_id=actor_id,
        idempotency_key=IDEMPOTENCY_KEY,
    )
    message_id = _stable_id(
        "message",
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        actor_id=actor_id,
        idempotency_key=IDEMPOTENCY_KEY,
    )
    journal = TaskSessionCreationReceiptModel(
        id="journal-concurrent",
        actor_user_id=actor_id,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        payload_hash="a" * 64,
        workspace_id="workspace-core-only",
        initial_message_id=message_id,
        core_receipt_id="core-receipt-concurrent",
        status="core_committed",
        response_json={"receipt_id": "core-receipt-concurrent"},
    )
    test_db.add(journal)
    await test_db.commit()
    competing_conversation = _new_conversation(
        conversation_id=conversation_id,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        actor_id=actor_id,
        title="Release review",
        capability_mode="work",
        workspace_id="workspace-core-only",
        receipt_id="core-receipt-concurrent",
        message_id=message_id,
        payload_hash="a" * 64,
        idempotency_key=IDEMPOTENCY_KEY,
    )
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    racing_session = _CompetingCommitSession(
        test_db,
        session_factory,
        competing_conversation=competing_conversation,
    )

    conversation = await _complete_platform_saga(
        racing_session,  # type: ignore[arg-type]
        journal=journal,
        conversation_id=conversation_id,
        title="Release review",
        capability_mode="work",
        payload_hash="a" * 64,
        receipt_id="core-receipt-concurrent",
        message_id=message_id,
    )

    assert conversation.id == conversation_id
    assert await test_db.scalar(select(func.count()).select_from(Conversation)) == 1
    await test_db.refresh(journal)
    assert journal.status == "completed"
    assert journal.conversation_id == conversation_id


@pytest.mark.unit
@pytest.mark.parametrize(
    ("core_status", "gateway_status"),
    [(403, 403), (404, 404), (409, 409), (503, 503)],
)
async def test_task_session_maps_core_errors_without_legacy_fallback(
    test_db: AsyncSession,
    test_user: User,
    core_status: int,
    gateway_status: int,
) -> None:
    await _seed_scope(test_db, test_user)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(core_status, json={"detail": "core rejected command"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(test_db, test_user, handler)),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post(
            f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/task-sessions",
            json=_body(),
        )

    assert response.status_code == gateway_status
    count = await test_db.scalar(select(func.count()).select_from(Conversation))
    assert count == 0
