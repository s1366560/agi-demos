"""V2 generation authority coverage for Workspace LLM session persistence."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.ports.repositories.agent_repository import ConversationRepository
from src.infrastructure.agent.workspace import session_conversations as session_module
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ASYNC_SESSION_FACTORY_SERVICE_V2,
    AsyncSessionFactoryServiceV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_ACCESS_SERVICE_V2,
    ConversationAccessResolverProtocolV2,
    ConversationAccessServiceV2,
    ConversationCrudRepositoriesV2,
    SqlConversationCrudRepositoryFactoryV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedDb:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1
        self.order.append("commit")


class _SessionContext:
    def __init__(self, db: object) -> None:
        self.db = db

    async def __aenter__(self) -> object:
        return self.db

    async def __aexit__(self, *_args: object) -> None:
        return None


class _TrackedCache:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.projects: list[str] = []

    async def invalidate(self, project_id: str) -> None:
        self.projects.append(project_id)
        self.order.append("cache")


@dataclass(frozen=True, kw_only=True)
class _Resolver:
    service: ConversationAccessServiceV2

    def resolve(self, _operation: object) -> ConversationAccessServiceV2:
        return self.service


class _Operation:
    def __init__(self, services: Mapping[str, object]) -> None:
        self.services = dict(services)
        self.provided: list[tuple[str, object, str | None]] = []

    def require(self, service: str) -> object:
        try:
            return self.services[service]
        except KeyError as exc:
            raise RuntimeV2Error("service_not_found", f"missing {service}") from exc

    def provide(self, service: str, value: object, *, label: str | None = None) -> object:
        self.services[service] = value
        self.provided.append((service, value, label))
        return value


class _TrackedRedisClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.close_calls = 0
        self.patterns: list[str] = []
        self.deleted: list[tuple[str | bytes, ...]] = []
        self.on_first_scan: Callable[[], Awaitable[None]] | None = None

    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str]:
        assert count == 100
        self.patterns.append(match)
        callback = self.on_first_scan
        self.on_first_scan = None
        if callback is not None:
            await callback()
        yield f"{match}cached"

    async def delete(self, *keys: str | bytes) -> int:
        self.deleted.append(keys)
        return len(keys)

    async def xadd(self, *_args: object, **_kwargs: object) -> str:
        return "1-0"

    async def aclose(self) -> None:
        self.close_calls += 1


def _repositories(repository: ConversationRepository) -> ConversationCrudRepositoriesV2:
    return ConversationCrudRepositoriesV2(
        conversation=repository,
        execution=cast(Any, SimpleNamespace()),
        execution_event=cast(Any, SimpleNamespace()),
        tool_execution_record=cast(Any, SimpleNamespace()),
        execution_checkpoint=cast(Any, SimpleNamespace()),
    )


def _session_factory(db: object) -> AsyncSessionFactoryServiceV2:
    def factory() -> _SessionContext:
        return _SessionContext(db)

    return AsyncSessionFactoryServiceV2(factory=cast(Any, factory))


def _call_kwargs(*, actor_user_id: str | None = "user-a") -> dict[str, Any]:
    return {
        "conversation_id": "conversation-a",
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "workspace_id": "workspace-a",
        "agent_id": "planner-a",
        "title": "Workspace planning",
        "stage": "planning",
        "actor_user_id": actor_user_id,
        "linked_workspace_task_id": "task-a",
        "metadata": {"input_fingerprint": "fingerprint-a"},
    }


def _install_fake_operation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sessions: object,
    resolver: object,
) -> tuple[_Operation, list[dict[str, object]]]:
    operation = _Operation(
        {
            ASYNC_SESSION_FACTORY_SERVICE_V2: sessions,
            CONVERSATION_ACCESS_SERVICE_V2: resolver,
        }
    )
    calls: list[dict[str, object]] = []

    @asynccontextmanager
    async def pin_operation(**kwargs: object) -> AsyncIterator[_Operation]:
        calls.append(dict(kwargs))
        yield operation

    monkeypatch.setattr(
        session_module,
        "pin_agent_turn_operation_v2",
        pin_operation,
        raising=False,
    )
    return operation, calls


async def test_workspace_session_creates_exact_scoped_conversation_through_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    db = _TrackedDb(order)
    saved: list[Conversation] = []

    async def save(conversation: Conversation) -> Conversation:
        order.append("save")
        saved.append(conversation)
        return conversation

    repository = cast(
        ConversationRepository,
        SimpleNamespace(find_by_id=AsyncMock(return_value=None), save=AsyncMock(side_effect=save)),
    )
    cache = _TrackedCache(order)
    service = ConversationAccessServiceV2(
        repositories=_repositories(repository),
        cache=cache,
    )
    resolver = _Resolver(service=service)
    assert isinstance(resolver, ConversationAccessResolverProtocolV2)
    operation, pin_calls = _install_fake_operation(
        monkeypatch,
        sessions=_session_factory(db),
        resolver=resolver,
    )

    assert await session_module.ensure_workspace_llm_conversation(
        **_call_kwargs(actor_user_id="  user-a  ")
    )

    assert len(pin_calls) == 1
    assert pin_calls[0] == {
        "operation_id": pin_calls[0]["operation_id"],
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "session_id": "conversation-a",
        "services": {
            OPERATION_IDENTITY_SERVICE_V2: {
                "tenant_id": "tenant-a",
                "project_id": "project-a",
                "user_id": "user-a",
            },
            OPERATION_METADATA_SERVICE_V2: {
                "kind": "workspace-llm-session",
                "conversation_id": "conversation-a",
                "workspace_id": "workspace-a",
                "agent_id": "planner-a",
                "stage": "planning",
            },
        },
        "force_process_host_lease": True,
    }
    assert str(pin_calls[0]["operation_id"]).startswith("workspace-llm-session:")
    assert operation.provided == [
        (OPERATION_DB_SESSION_SERVICE_V2, db, "workspace-llm-session-db"),
    ]
    assert len(saved) == 1
    conversation = saved[0]
    assert conversation.id == "conversation-a"
    assert conversation.tenant_id == "tenant-a"
    assert conversation.project_id == "project-a"
    assert conversation.user_id == "user-a"
    assert conversation.workspace_id == "workspace-a"
    assert conversation.linked_workspace_task_id == "task-a"
    assert conversation.status is ConversationStatus.ACTIVE
    assert conversation.agent_config == {"selected_agent_id": "planner-a"}
    assert conversation.metadata["workspace_llm_stage"] == "planning"
    assert conversation.metadata["input_fingerprint"] == "fingerprint-a"
    assert order == ["save", "commit", "cache"]
    assert cache.projects == ["project-a"]


async def test_workspace_session_updates_existing_conversation_without_scope_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    db = _TrackedDb(order)
    existing = Conversation(
        id="conversation-a",
        tenant_id="tenant-a",
        project_id="project-a",
        user_id="user-a",
        title="Existing",
        workspace_id="workspace-old",
        linked_workspace_task_id="task-old",
        agent_config={"keep": True, "selected_agent_id": "agent-old"},
        metadata={"keep": "value"},
    )
    repository = cast(
        ConversationRepository,
        SimpleNamespace(
            find_by_id=AsyncMock(return_value=existing),
            save=AsyncMock(side_effect=lambda conversation: conversation),
        ),
    )
    service = ConversationAccessServiceV2(
        repositories=_repositories(repository),
        cache=_TrackedCache(order),
    )
    _install_fake_operation(
        monkeypatch,
        sessions=_session_factory(db),
        resolver=_Resolver(service=service),
    )

    assert await session_module.ensure_workspace_llm_conversation(**_call_kwargs())

    assert existing.workspace_id == "workspace-a"
    assert existing.linked_workspace_task_id == "task-a"
    assert existing.agent_config == {"keep": True, "selected_agent_id": "planner-a"}
    assert existing.metadata["keep"] == "value"
    assert existing.metadata["input_fingerprint"] == "fingerprint-a"
    assert existing.updated_at is not None
    cast(Any, repository).save.assert_awaited_once_with(existing)
    assert db.commit_calls == 1


@pytest.mark.parametrize(
    ("field", "value"),
    (("tenant_id", "tenant-b"), ("project_id", "project-b"), ("user_id", "user-b")),
)
async def test_workspace_session_rejects_existing_scope_mismatch_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    order: list[str] = []
    db = _TrackedDb(order)
    existing_values = {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "user_id": "user-a",
    }
    existing_values[field] = value
    existing = Conversation(
        id="conversation-a",
        title="Existing",
        workspace_id="workspace-old",
        **existing_values,
    )
    repository = cast(
        ConversationRepository,
        SimpleNamespace(find_by_id=AsyncMock(return_value=existing), save=AsyncMock()),
    )
    cache = _TrackedCache(order)
    service = ConversationAccessServiceV2(
        repositories=_repositories(repository),
        cache=cache,
    )
    _install_fake_operation(
        monkeypatch,
        sessions=_session_factory(db),
        resolver=_Resolver(service=service),
    )

    assert not await session_module.ensure_workspace_llm_conversation(**_call_kwargs())

    assert existing.workspace_id == "workspace-old"
    cast(Any, repository).save.assert_not_awaited()
    assert db.commit_calls == 0
    assert cache.projects == []


async def test_workspace_session_requires_explicit_actor_before_provider_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_calls = 0

    @asynccontextmanager
    async def reject_pin(**_kwargs: object) -> AsyncIterator[object]:
        nonlocal pin_calls
        pin_calls += 1
        raise AssertionError("missing actor must not activate a V2 Provider")
        yield object()

    monkeypatch.setattr(
        session_module,
        "pin_agent_turn_operation_v2",
        reject_pin,
        raising=False,
    )

    assert not await session_module.ensure_workspace_llm_conversation(
        **_call_kwargs(actor_user_id="  ")
    )
    assert pin_calls == 0


@pytest.mark.parametrize(
    ("sessions", "resolver", "code"),
    (
        (object(), _Resolver, "invalid_workspace_session_factory"),
        (None, object(), "invalid_workspace_conversation_access"),
    ),
)
async def test_workspace_session_rejects_invalid_v2_services_without_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
    sessions: object | None,
    resolver: object,
    code: str,
) -> None:
    db = _TrackedDb([])
    valid_service = ConversationAccessServiceV2(
        repositories=_repositories(
            cast(
                ConversationRepository,
                SimpleNamespace(find_by_id=AsyncMock(return_value=None), save=AsyncMock()),
            )
        ),
        cache=_TrackedCache([]),
    )
    resolved_sessions = _session_factory(db) if sessions is None else sessions
    resolved_resolver = _Resolver(service=valid_service) if resolver is _Resolver else resolver
    _install_fake_operation(
        monkeypatch,
        sessions=resolved_sessions,
        resolver=resolved_resolver,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await session_module.ensure_workspace_llm_conversation(**_call_kwargs())

    assert error.value.code == code


async def test_workspace_session_propagates_missing_v2_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _Operation({})

    @asynccontextmanager
    async def pin_operation(**_kwargs: object) -> AsyncIterator[_Operation]:
        yield operation

    monkeypatch.setattr(
        session_module,
        "pin_agent_turn_operation_v2",
        pin_operation,
        raising=False,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await session_module.ensure_workspace_llm_conversation(**_call_kwargs())

    assert error.value.code == "service_not_found"


async def test_workspace_session_keeps_exact_generation_until_cache_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.plugins.v2 import artifact_content_gc_runtime as persistence_runtime

    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    clients = iter((first_client, second_client))
    order: list[str] = []
    db = _TrackedDb(order)
    repository = cast(
        ConversationRepository,
        SimpleNamespace(find_by_id=AsyncMock(return_value=None), save=AsyncMock()),
    )

    async def redis_factory() -> _TrackedRedisClient:
        return next(clients)

    def session_factory() -> _SessionContext:
        return _SessionContext(db)

    def build_crud(
        _factory: SqlConversationCrudRepositoryFactoryV2,
        operation: object,
    ) -> ConversationCrudRepositoriesV2:
        assert cast(Any, operation).require(OPERATION_DB_SESSION_SERVICE_V2) is db
        return _repositories(repository)

    monkeypatch.setattr(persistence_runtime, "async_session_factory", session_factory)
    monkeypatch.setattr(SqlConversationCrudRepositoryFactoryV2, "build_crud", build_crud)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=711,
        version=711,
    )
    assert first.accepted is True
    install_process_generation_host_v2(host)

    async def reload_generation() -> None:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=712,
            version=712,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0

    first_client.on_first_scan = reload_generation

    try:
        assert await session_module.ensure_workspace_llm_conversation(**_call_kwargs())
        assert first_client.patterns == [
            "conv_list:project-a:*",
            "conv_count:project-a:*",
        ]
        assert second_client.patterns == []
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        clear_process_generation_host_v2(host)
        await host.close()

    assert second_client.close_calls == 1


def test_workspace_session_has_no_static_persistence_or_redis_authority() -> None:
    source = (_ROOT / "src/infrastructure/agent/workspace/session_conversations.py").read_text(
        encoding="utf-8"
    )

    for retired_reference in (
        "async_session_factory",
        "SqlConversationRepository",
        "legacy_workspace_runtime_retired",
        "current_agent_worker_redis_client_v2",
        ".keys(",
        "_invalidate_conversation_list_cache",
    ):
        assert retired_reference not in source
    for required_reference in (
        "ASYNC_SESSION_FACTORY_SERVICE_V2",
        "CONVERSATION_ACCESS_SERVICE_V2",
        "pin_agent_turn_operation_v2",
        "force_process_host_lease=True",
    ):
        assert required_reference in source
