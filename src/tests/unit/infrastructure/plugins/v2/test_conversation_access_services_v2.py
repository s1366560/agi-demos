"""V2 persistence and application seams for conversation access."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.repositories.agent_repository import ConversationRepository
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_ACCESS_MODULE_V2,
    CONVERSATION_ACCESS_SERVICE_V2,
    CONVERSATION_CACHE_REDIS_INJECT_V2,
    CONVERSATION_CRUD_REPOSITORIES_INJECT_V2,
    CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2,
    CONVERSATION_CRUD_REPOSITORY_PROVIDER_SERVICE_V2,
    CONVERSATION_REPOSITORY_PROVIDER_MODULE_V2,
    ConversationAccessResolverV2,
    ConversationAccessServiceV2,
    ConversationCrudRepositoriesV2,
    ConversationCrudRepositoryFactoryProtocolV2,
    RedisConversationCacheInvalidatorV2,
    SqlConversationRepositoryFactoryV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.redis_runtime import (
    REDIS_RUNTIME_SERVICE_V2,
    RedisRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _repositories(
    conversation: ConversationRepository,
    *,
    execution: object | None = None,
    execution_event: object | None = None,
    tool_execution_record: object | None = None,
    execution_checkpoint: object | None = None,
) -> ConversationCrudRepositoriesV2:
    return ConversationCrudRepositoriesV2(
        conversation=conversation,
        execution=cast(Any, execution or SimpleNamespace()),
        execution_event=cast(Any, execution_event or SimpleNamespace()),
        tool_execution_record=cast(Any, tool_execution_record or SimpleNamespace()),
        execution_checkpoint=cast(Any, execution_checkpoint or SimpleNamespace()),
    )


def _cache(client: object | None = None) -> RedisConversationCacheInvalidatorV2:
    return RedisConversationCacheInvalidatorV2(
        redis=RedisRuntimeServiceV2(client=client),
    )


async def test_resolver_builds_conversation_access_from_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=944,
        version=944,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="websocket-conversation-access",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(CONVERSATION_ACCESS_SERVICE_V2)

            assert isinstance(resolver, ConversationAccessResolverV2)
            service = resolver.resolve(operation)
            assert isinstance(service, ConversationAccessServiceV2)
            assert cast(Any, service.repositories.conversation)._session is db
            assert cast(Any, service.repositories.execution)._session is db
            assert cast(Any, service.repositories.execution_event)._session is db
            assert cast(Any, service.repositories.tool_execution_record)._session is db
            assert cast(Any, service.repositories.execution_checkpoint)._session is db
    finally:
        await db.close()
        await host.close()


def test_conversation_access_consumer_uses_an_explicit_repository_alias() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[CONVERSATION_ACCESS_MODULE_V2].inject == {
        CONVERSATION_CRUD_REPOSITORIES_INJECT_V2: (
            CONVERSATION_CRUD_REPOSITORY_PROVIDER_SERVICE_V2
        ),
        CONVERSATION_CACHE_REDIS_INJECT_V2: REDIS_RUNTIME_SERVICE_V2,
    }
    assert ordered_modules.index(
        CONVERSATION_REPOSITORY_PROVIDER_MODULE_V2
    ) < ordered_modules.index(CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2)
    assert ordered_modules.index(
        CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2
    ) < ordered_modules.index(CONVERSATION_ACCESS_MODULE_V2)


def test_narrow_repository_factory_cannot_masquerade_as_crud_bundle_provider() -> None:
    provider = SqlConversationRepositoryFactoryV2(strategy="request-async-session")

    assert not isinstance(provider, ConversationCrudRepositoryFactoryProtocolV2)


async def test_missing_conversation_repository_provider_is_rejected_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=945,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-conversation-access" in str(error.value)


async def test_conversation_access_scopes_get_to_exact_project_and_user() -> None:
    conversation = Conversation(
        id="conversation-a",
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="Scoped conversation",
    )
    find_by_id = AsyncMock(return_value=conversation)
    repository = cast(
        ConversationRepository,
        SimpleNamespace(find_by_id=find_by_id),
    )
    service = ConversationAccessServiceV2(
        repositories=_repositories(repository),
        cache=_cache(),
    )

    assert (
        await service.get_conversation(
            conversation_id="conversation-a",
            project_id="project-a",
            user_id="user-a",
        )
        is conversation
    )
    assert (
        await service.get_conversation(
            conversation_id="conversation-a",
            project_id="project-a",
            user_id="user-b",
        )
        is None
    )
    assert find_by_id.await_count == 2


async def test_conversation_access_deletes_only_an_exact_scoped_conversation() -> None:
    conversation = Conversation(
        id="conversation-a",
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="Delete conversation",
    )
    find_by_id = AsyncMock(return_value=conversation)
    cleanup_order: list[str] = []

    def recorder(name: str, *, result: bool | None = None) -> Any:
        async def record(_conversation_id: str) -> bool | None:
            cleanup_order.append(name)
            return result

        return record

    delete = AsyncMock(side_effect=recorder("conversation", result=True))
    execution = SimpleNamespace(delete_by_conversation=AsyncMock(side_effect=recorder("execution")))
    execution_event = SimpleNamespace(
        delete_by_conversation=AsyncMock(side_effect=recorder("execution_event"))
    )
    tool_execution_record = SimpleNamespace(
        delete_by_conversation=AsyncMock(side_effect=recorder("tool_execution_record"))
    )
    execution_checkpoint = SimpleNamespace(
        delete_by_conversation=AsyncMock(side_effect=recorder("execution_checkpoint"))
    )
    repository = cast(
        ConversationRepository,
        SimpleNamespace(find_by_id=find_by_id, delete=delete),
    )
    service = ConversationAccessServiceV2(
        repositories=_repositories(
            repository,
            execution=execution,
            execution_event=execution_event,
            tool_execution_record=tool_execution_record,
            execution_checkpoint=execution_checkpoint,
        ),
        cache=_cache(),
    )

    assert await service.delete_conversation(
        conversation_id="conversation-a",
        project_id="project-a",
        user_id="user-a",
    )
    delete.assert_awaited_once_with("conversation-a")
    assert cleanup_order == [
        "tool_execution_record",
        "execution_event",
        "execution_checkpoint",
        "execution",
        "conversation",
    ]

    delete.reset_mock()
    cleanup_order.clear()
    assert not await service.delete_conversation(
        conversation_id="conversation-a",
        project_id="project-b",
        user_id="user-a",
    )
    delete.assert_not_awaited()
    assert cleanup_order == []


async def test_conversation_access_updates_title_without_owning_the_transaction() -> None:
    conversation = Conversation(
        id="conversation-a",
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="Before",
    )
    save = AsyncMock(return_value=conversation)
    repository = cast(
        ConversationRepository,
        SimpleNamespace(find_by_id=AsyncMock(return_value=conversation), save=save),
    )
    service = ConversationAccessServiceV2(
        repositories=_repositories(repository),
        cache=_cache(),
    )

    result = await service.update_conversation_title(
        conversation_id="conversation-a",
        project_id="project-a",
        user_id="user-a",
        title="After",
    )

    assert result is conversation
    assert conversation.title == "After"
    save.assert_awaited_once_with(conversation)


async def test_conversation_cache_invalidator_scans_only_the_project_namespaces() -> None:
    class TrackedRedis:
        def __init__(self) -> None:
            self.patterns: list[str] = []
            self.deleted: list[tuple[str | bytes, ...]] = []

        async def scan_iter(self, *, match: str, count: int) -> Any:
            assert count == 100
            self.patterns.append(match)
            yield f"{match}one"
            yield f"{match}two".encode()

        async def delete(self, *keys: str | bytes) -> int:
            self.deleted.append(keys)
            return len(keys)

    redis = TrackedRedis()

    await _cache(redis).invalidate("project-a")

    assert redis.patterns == [
        "conv_list:project-a:*",
        "conv_count:project-a:*",
    ]
    assert redis.deleted == [
        ("conv_list:project-a:*one", b"conv_list:project-a:*two"),
        ("conv_count:project-a:*one", b"conv_count:project-a:*two"),
    ]


async def test_invalid_conversation_cache_client_nacks_candidate_and_releases_redis() -> None:
    class InvalidRedis:
        def __init__(self) -> None:
            self.close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1

    redis = InvalidRedis()
    document = load_profile_document_v2(_PROFILE_PATH)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        document,
        {manifest.plugin_id: manifest},
        generation=946,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2(redis_runtime_factory=lambda: redis)).stage(
            snapshot
        )

    assert error.value.code == "invalid_conversation_cache_client"
    assert redis.close_calls == 1
