"""V2 collection authority for creating and listing conversations."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.conversation_collection_repository import (
    CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_MODULE_V2,
    CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_SERVICE_V2,
    SqlConversationCollectionRepositoryV2,
)
from src.infrastructure.plugins.v2.conversation_collection_services import (
    CONVERSATION_COLLECTION_AGENT_DEFINITIONS_INJECT_V2,
    CONVERSATION_COLLECTION_MODULE_V2,
    CONVERSATION_COLLECTION_REDIS_INJECT_V2,
    CONVERSATION_COLLECTION_REPOSITORY_INJECT_V2,
    CONVERSATION_COLLECTION_SERVICE_V2,
    CONVERSATION_CREATED_EVENT_V2,
    CONVERSATION_CREATED_REDIS_PUBLISHER_MODULE_V2,
    CONVERSATION_CREATED_REDIS_PUBLISHER_REDIS_INJECT_V2,
    ConversationCollectionResolverV2,
    ConversationCollectionServiceV2,
    InvalidConversationAgentSelectionV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _conversation() -> Conversation:
    return Conversation(
        id="conversation-a",
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="V2 collection",
        status=ConversationStatus.ACTIVE,
        created_at=datetime(2026, 8, 29, 1, 2, 3, tzinfo=UTC),
    )


def _service(
    *,
    repository: object,
    definition: object | None = None,
    dispatch: AsyncMock | None = None,
) -> ConversationCollectionServiceV2:
    resolver = SimpleNamespace(
        resolve=AsyncMock(return_value=definition or SimpleNamespace(id="a"))
    )
    return ConversationCollectionServiceV2(
        repository=cast(Any, repository),
        agent_definitions=cast(Any, resolver),
        cache=cast(Any, SimpleNamespace(invalidate=AsyncMock())),
        dispatch_created=dispatch or AsyncMock(),
    )


async def test_runtime_resolves_collection_repository_from_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=948,
        version=948,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-conversation-collection",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(CONVERSATION_COLLECTION_SERVICE_V2)

            assert isinstance(resolver, ConversationCollectionResolverV2)
            service = resolver.resolve(operation)
            assert isinstance(service, ConversationCollectionServiceV2)
            assert isinstance(service.repository, SqlConversationCollectionRepositoryV2)
            assert cast(Any, service.repository).session is db
    finally:
        await db.close()
        await host.close()


def test_collection_profile_declares_provider_consumer_and_optional_event_handler() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered = tuple(entry.module_ref for entry in document.entries)

    assert entries[CONVERSATION_COLLECTION_MODULE_V2].inject == {
        CONVERSATION_COLLECTION_REPOSITORY_INJECT_V2: (
            CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_SERVICE_V2
        ),
        CONVERSATION_COLLECTION_AGENT_DEFINITIONS_INJECT_V2: ("service:agent-definition-resolver"),
        CONVERSATION_COLLECTION_REDIS_INJECT_V2: "service:runtime.redis-client",
    }
    assert entries[CONVERSATION_CREATED_REDIS_PUBLISHER_MODULE_V2].inject == {
        CONVERSATION_CREATED_REDIS_PUBLISHER_REDIS_INJECT_V2: "service:runtime.redis-client"
    }
    assert ordered.index(CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_MODULE_V2) < ordered.index(
        CONVERSATION_COLLECTION_MODULE_V2
    )


async def test_missing_collection_repository_provider_is_rejected_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == CONVERSATION_COLLECTION_REPOSITORY_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=949)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-conversation-collection" in str(error.value)


async def test_create_validates_selected_agent_through_v2_and_does_not_commit() -> None:
    saved: list[Conversation] = []

    async def save(conversation: Conversation) -> Conversation:
        saved.append(conversation)
        return conversation

    repository = SimpleNamespace(save=AsyncMock(side_effect=save))
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=SimpleNamespace(id="agent-a")))
    service = ConversationCollectionServiceV2(
        repository=cast(Any, repository),
        agent_definitions=cast(Any, resolver),
        cache=cast(Any, SimpleNamespace(invalidate=AsyncMock())),
        dispatch_created=AsyncMock(),
    )

    conversation = await service.create_conversation(
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="Created through V2",
        agent_config={"selected_agent_id": "agent-a"},
        workspace_id="workspace-a",
    )

    resolver.resolve.assert_awaited_once_with(
        agent_id="agent-a",
        tenant_id="tenant-a",
        project_id="project-a",
    )
    assert saved == [conversation]
    assert conversation.project_id == "project-a"
    assert conversation.tenant_id == "tenant-a"
    assert conversation.user_id == "user-a"
    assert conversation.workspace_id == "workspace-a"


async def test_create_fails_closed_when_selected_agent_is_not_contributed() -> None:
    repository = SimpleNamespace(save=AsyncMock())
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=None))
    service = ConversationCollectionServiceV2(
        repository=cast(Any, repository),
        agent_definitions=cast(Any, resolver),
        cache=cast(Any, SimpleNamespace(invalidate=AsyncMock())),
        dispatch_created=AsyncMock(),
    )

    with pytest.raises(InvalidConversationAgentSelectionV2):
        await service.create_conversation(
            project_id="project-a",
            tenant_id="tenant-a",
            user_id="user-a",
            agent_config={"selected_agent_id": "agent-missing"},
        )

    repository.save.assert_not_awaited()


async def test_collection_service_proxies_all_scoped_query_shapes() -> None:
    conversation = _conversation()
    repository = SimpleNamespace(
        list_default=AsyncMock(return_value=[conversation]),
        count_default=AsyncMock(return_value=1),
        list_workspace=AsyncMock(return_value=[conversation]),
        count_workspace=AsyncMock(return_value=1),
        list_unbound=AsyncMock(return_value=[conversation]),
        count_unbound=AsyncMock(return_value=1),
    )
    service = _service(repository=repository)

    assert await service.list_conversations(
        project_id="project-a",
        tenant_id="tenant-a",
        status=ConversationStatus.ACTIVE,
        limit=10,
        offset=2,
    ) == [conversation]
    assert (
        await service.count_conversations(
            project_id="project-a",
            tenant_id="tenant-a",
            status=ConversationStatus.ACTIVE,
        )
        == 1
    )
    assert await service.list_workspace_conversations(
        project_id="project-a",
        tenant_id="tenant-a",
        workspace_ids={"workspace-a"},
        status=None,
        limit=5,
        offset=1,
    ) == [conversation]
    assert (
        await service.count_workspace_conversations(
            project_id="project-a",
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            status=None,
        )
        == 1
    )
    assert await service.list_unbound_conversations(
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        status=None,
        limit=5,
        offset=1,
    ) == [conversation]
    assert (
        await service.count_unbound_conversations(
            project_id="project-a",
            tenant_id="tenant-a",
            user_id="user-a",
            status=None,
        )
        == 1
    )

    repository.list_default.assert_awaited_once_with(
        project_id="project-a",
        tenant_id="tenant-a",
        status=ConversationStatus.ACTIVE,
        limit=10,
        offset=2,
    )
    repository.list_workspace.assert_awaited_once_with(
        project_id="project-a",
        tenant_id="tenant-a",
        workspace_ids={"workspace-a"},
        status=None,
        limit=5,
        offset=1,
    )
    repository.list_unbound.assert_awaited_once_with(
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        status=None,
        limit=5,
        offset=1,
    )


async def test_after_commit_invalidates_then_dispatches_typed_created_event() -> None:
    order: list[str] = []

    async def invalidate(_project_id: str) -> None:
        order.append("invalidate")

    async def dispatch(_conversation: Conversation) -> None:
        order.append("dispatch")

    service = ConversationCollectionServiceV2(
        repository=cast(Any, SimpleNamespace()),
        agent_definitions=cast(Any, SimpleNamespace()),
        cache=cast(Any, SimpleNamespace(invalidate=invalidate)),
        dispatch_created=dispatch,
    )

    await service.after_create_committed(_conversation())

    assert order == ["invalidate", "dispatch"]


async def test_typed_conversation_created_event_keeps_existing_redis_wire_payload() -> None:
    class TrackedRedis:
        def __init__(self) -> None:
            self.xadd_calls: list[tuple[str, dict[str, object], int, bool]] = []

        async def scan_iter(self, *, match: str, count: int) -> Any:
            if False:
                yield match, count

        async def delete(self, *_keys: str | bytes) -> int:
            return 0

        async def xadd(
            self,
            stream: str,
            fields: dict[str, object],
            *,
            maxlen: int,
            approximate: bool,
        ) -> bytes:
            self.xadd_calls.append((stream, fields, maxlen, approximate))
            return b"1-0"

        async def aclose(self) -> None:
            return None

    redis = TrackedRedis()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=lambda: redis)
    )
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=950,
        version=950,
    )
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="conversation-created-event",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(CONVERSATION_COLLECTION_SERVICE_V2)
            assert isinstance(resolver, ConversationCollectionResolverV2)

            await resolver.resolve(operation).after_create_committed(_conversation())

        assert len(redis.xadd_calls) == 1
        stream, fields, maxlen, approximate = redis.xadd_calls[0]
        assert stream == "events:project:project-a:conversation_created"
        assert fields["event_type"] == "conversation_created"
        assert fields["routing_key"] == "project:project-a:conversation_created"
        wire_event = json.loads(str(fields["data"]))
        assert wire_event["payload"]["conversation_id"] == "conversation-a"
        assert maxlen == 10_000
        assert approximate is True
    finally:
        await db.close()
        await host.close()


def test_manifest_declares_serial_conversation_created_event_on_both_modules() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    modules = {module["module_ref"]: module for module in manifest["modules"]}
    emitter = modules[CONVERSATION_COLLECTION_MODULE_V2]["contract"]["events"]["emits"]
    handler = modules[CONVERSATION_CREATED_REDIS_PUBLISHER_MODULE_V2]["contract"]["events"][
        "handles"
    ]

    assert emitter == handler
    assert emitter[0]["event"] == CONVERSATION_CREATED_EVENT_V2
    assert emitter[0]["mode"] == "serial"
    assert emitter[0]["result_schema"]["type"] == "null"
