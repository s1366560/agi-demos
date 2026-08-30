"""Producer-side V2 lifecycle tests for automatic conversation titles."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    AsyncSessionFactoryServiceV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
)
from src.infrastructure.plugins.v2.conversation_generation_services import (
    ConversationGenerationServiceV2,
)
from src.infrastructure.plugins.v2.conversation_title_lifecycle import (
    CONVERSATION_TITLE_LIFECYCLE_GENERATION_INJECT_V2,
    CONVERSATION_TITLE_LIFECYCLE_MODULE_V2,
    CONVERSATION_TITLE_LIFECYCLE_SESSIONS_INJECT_V2,
    ConversationTitleLifecycleV2,
)
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error

pytestmark = pytest.mark.unit


def _descriptor() -> PluginGenerationDescriptorV2:
    return PluginGenerationDescriptorV2(
        profile_id="memstack-default-v2",
        generation=901,
        digest="a" * 64,
    )


def _parent_operation() -> Any:
    scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id="tenant-a",
        project_id="project-a",
        session_id="conversation-a",
    )
    identity = {"tenant_id": "tenant-a", "user_id": "user-a"}
    return SimpleNamespace(
        operation_id="ray-turn:message-a",
        generation=SimpleNamespace(descriptor=_descriptor()),
        descriptor=_descriptor(),
        context=SimpleNamespace(scope=scope),
        require=MagicMock(
            side_effect=lambda service: identity
            if service == OPERATION_IDENTITY_SERVICE_V2
            else None
        ),
    )


def _session_factory(session: Any) -> AsyncSessionFactoryServiceV2:
    @asynccontextmanager
    async def factory():
        yield session

    return AsyncSessionFactoryServiceV2(factory=cast(Any, factory))


def _child_operation(parent: Any) -> Any:
    child = MagicMock()
    child.phase = FiberPhaseV2.PENDING
    child.descriptor = parent.descriptor
    child.provide = MagicMock()

    async def enter() -> Any:
        child.phase = FiberPhaseV2.ACTIVE
        return child

    async def exit(*_args: object) -> None:
        child.phase = FiberPhaseV2.DISPOSED

    child.__aenter__ = AsyncMock(side_effect=enter)
    child.__aexit__ = AsyncMock(side_effect=exit)
    return child


def _conversation() -> Conversation:
    return Conversation(
        id="conversation-a",
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="Lifecycle title",
        message_count=2,
    )


def _generation_service(
    *,
    generated: Conversation | None = None,
    error: BaseException | None = None,
) -> ConversationGenerationServiceV2:
    service = create_autospec(ConversationGenerationServiceV2, instance=True)
    if error is not None:
        service.generate_initial_title.side_effect = error
    else:
        service.generate_initial_title.return_value = generated
    return cast(ConversationGenerationServiceV2, service)


async def test_successful_turn_commits_before_cache_and_emits_typed_title_event() -> None:
    trace: list[str] = []
    parent = _parent_operation()
    child = _child_operation(parent)
    db = AsyncMock(spec=AsyncSession)
    db.commit.side_effect = lambda: trace.append("commit")
    service = _generation_service(generated=_conversation())
    cast(Any, service).generate_initial_title.side_effect = lambda **_kwargs: (
        trace.append("generate"),
        _conversation(),
    )[1]
    cast(Any, service).after_update_committed.side_effect = lambda: trace.append("invalidate")
    resolver = SimpleNamespace(resolve=MagicMock(return_value=service))
    lifecycle = ConversationTitleLifecycleV2(
        sessions=_session_factory(db),
        conversation_generation=cast(Any, resolver),
    )

    async def next_(payload: object) -> object:
        trace.append("next")
        return payload

    with (
        patch(
            "src.infrastructure.plugins.v2.conversation_title_lifecycle.current_operation_context_v2",
            return_value=parent,
        ),
        patch(
            "src.infrastructure.plugins.v2.conversation_title_lifecycle.OperationContextV2",
            return_value=child,
        ) as child_factory,
    ):
        result = await lifecycle.handle(
            {
                "conversation_id": "conversation-a",
                "success": True,
                "generation_digest": parent.descriptor.digest,
                "operation_id": parent.operation_id,
            },
            next_,
        )

    assert trace == ["generate", "commit", "invalidate", "next"]
    service.generate_initial_title.assert_awaited_once_with(conversation_id="conversation-a")
    child_factory.assert_called_once()
    assert child_factory.call_args.kwargs["generation"] is parent.generation
    assert child_factory.call_args.kwargs["scope"] == parent.context.scope
    child_operation_id = child_factory.call_args.kwargs["operation_id"]
    assert child_operation_id.startswith(f"{parent.operation_id}:conversation-title:")
    child.provide.assert_any_call(OPERATION_DB_SESSION_SERVICE_V2, db)
    child.provide.assert_any_call(
        OPERATION_IDENTITY_SERVICE_V2,
        {
            "tenant_id": "tenant-a",
            "project_id": "project-a",
            "user_id": "user-a",
        },
    )
    child.provide.assert_any_call(
        OPERATION_METADATA_SERVICE_V2,
        {
            "kind": "conversation-title-lifecycle",
            "parent_operation_id": parent.operation_id,
        },
    )
    emitted = cast(dict[str, Any], result)["emitted_events"]
    assert len(emitted) == 1
    assert emitted[0]["type"] == "title_generated"
    assert emitted[0]["data"] == {
        "conversation_id": "conversation-a",
        "title": "Lifecycle title",
        "message_id": None,
        "generated_by": "llm",
        "plugin_generation": parent.descriptor.to_payload(),
        "operation_id": child_operation_id,
        "parent_operation_id": parent.operation_id,
    }


async def test_cache_failure_after_commit_still_emits_durable_title_event() -> None:
    parent = _parent_operation()
    child = _child_operation(parent)
    db = AsyncMock(spec=AsyncSession)
    service = _generation_service(generated=_conversation())
    service.after_update_committed.side_effect = RuntimeError("cache unavailable")
    lifecycle = ConversationTitleLifecycleV2(
        sessions=_session_factory(db),
        conversation_generation=cast(
            Any,
            SimpleNamespace(resolve=MagicMock(return_value=service)),
        ),
    )
    next_ = AsyncMock(side_effect=lambda payload: payload)

    with (
        patch(
            "src.infrastructure.plugins.v2.conversation_title_lifecycle.current_operation_context_v2",
            return_value=parent,
        ),
        patch(
            "src.infrastructure.plugins.v2.conversation_title_lifecycle.OperationContextV2",
            return_value=child,
        ),
    ):
        result = await lifecycle.handle(
            {"conversation_id": "conversation-a", "success": True},
            next_,
        )

    db.commit.assert_awaited_once_with()
    db.rollback.assert_not_awaited()
    service.after_update_committed.assert_awaited_once_with()
    emitted = cast(dict[str, Any], result)["emitted_events"]
    assert emitted[0]["type"] == "title_generated"
    next_.assert_awaited_once()


@pytest.mark.parametrize("success", [False, None, 1, "true"])
async def test_only_literal_success_triggers_title_lifecycle(success: object) -> None:
    service = _generation_service()
    lifecycle = ConversationTitleLifecycleV2(
        sessions=_session_factory(AsyncMock(spec=AsyncSession)),
        conversation_generation=cast(Any, SimpleNamespace(resolve=MagicMock(return_value=service))),
    )
    next_ = AsyncMock(side_effect=lambda payload: payload)

    result = await lifecycle.handle(
        {"conversation_id": "conversation-a", "success": success},
        next_,
    )

    assert result == {"conversation_id": "conversation-a", "success": success}
    service.generate_initial_title.assert_not_awaited()
    next_.assert_awaited_once()


async def test_ineligible_conversation_does_not_commit_invalidate_or_emit() -> None:
    parent = _parent_operation()
    child = _child_operation(parent)
    db = AsyncMock(spec=AsyncSession)
    service = _generation_service()
    lifecycle = ConversationTitleLifecycleV2(
        sessions=_session_factory(db),
        conversation_generation=cast(
            Any,
            SimpleNamespace(resolve=MagicMock(return_value=service)),
        ),
    )
    next_phases: list[FiberPhaseV2] = []

    async def next_(payload: object) -> object:
        next_phases.append(child.phase)
        return payload

    with (
        patch(
            "src.infrastructure.plugins.v2.conversation_title_lifecycle.current_operation_context_v2",
            return_value=parent,
        ),
        patch(
            "src.infrastructure.plugins.v2.conversation_title_lifecycle.OperationContextV2",
            return_value=child,
        ),
    ):
        result = await lifecycle.handle(
            {"conversation_id": "conversation-a", "success": True},
            next_,
        )

    db.commit.assert_not_awaited()
    service.after_update_committed.assert_not_awaited()
    assert "emitted_events" not in cast(dict[str, Any], result)
    assert next_phases == [FiberPhaseV2.DISPOSED]


async def test_missing_parent_identity_skips_optional_enrichment_without_fallback() -> None:
    parent = _parent_operation()
    parent.require = MagicMock(return_value=None)
    db = AsyncMock(spec=AsyncSession)
    service = _generation_service(generated=_conversation())
    resolver = SimpleNamespace(resolve=MagicMock(return_value=service))
    lifecycle = ConversationTitleLifecycleV2(
        sessions=_session_factory(db),
        conversation_generation=cast(Any, resolver),
    )
    next_ = AsyncMock(side_effect=lambda payload: payload)

    with patch(
        "src.infrastructure.plugins.v2.conversation_title_lifecycle.current_operation_context_v2",
        return_value=parent,
    ):
        result = await lifecycle.handle(
            {"conversation_id": "conversation-a", "success": True},
            next_,
        )

    assert result == {"conversation_id": "conversation-a", "success": True}
    resolver.resolve.assert_not_called()
    service.generate_initial_title.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()
    next_.assert_awaited_once()


async def test_failure_rolls_back_without_event_or_fallback() -> None:
    parent = _parent_operation()
    child = _child_operation(parent)
    db = AsyncMock(spec=AsyncSession)
    service = _generation_service(error=RuntimeV2Error("judge_failed", "structured judge failed"))
    lifecycle = ConversationTitleLifecycleV2(
        sessions=_session_factory(db),
        conversation_generation=cast(
            Any,
            SimpleNamespace(resolve=MagicMock(return_value=service)),
        ),
    )
    next_ = AsyncMock(side_effect=lambda payload: payload)

    with (
        patch(
            "src.infrastructure.plugins.v2.conversation_title_lifecycle.current_operation_context_v2",
            return_value=parent,
        ),
        patch(
            "src.infrastructure.plugins.v2.conversation_title_lifecycle.OperationContextV2",
            return_value=child,
        ),
    ):
        result = await lifecycle.handle(
            {"conversation_id": "conversation-a", "success": True},
            next_,
        )

    db.rollback.assert_awaited_once_with()
    db.commit.assert_not_awaited()
    service.after_update_committed.assert_not_awaited()
    assert "emitted_events" not in cast(dict[str, Any], result)
    next_.assert_awaited_once()


async def test_cancellation_rolls_back_propagates_and_disposes_child_operation() -> None:
    parent = _parent_operation()
    child = _child_operation(parent)
    db = AsyncMock(spec=AsyncSession)
    service = _generation_service(error=asyncio.CancelledError())
    lifecycle = ConversationTitleLifecycleV2(
        sessions=_session_factory(db),
        conversation_generation=cast(
            Any,
            SimpleNamespace(resolve=MagicMock(return_value=service)),
        ),
    )
    next_ = AsyncMock()

    with (
        patch(
            "src.infrastructure.plugins.v2.conversation_title_lifecycle.current_operation_context_v2",
            return_value=parent,
        ),
        patch(
            "src.infrastructure.plugins.v2.conversation_title_lifecycle.OperationContextV2",
            return_value=child,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await lifecycle.handle(
            {"conversation_id": "conversation-a", "success": True},
            next_,
        )

    db.rollback.assert_awaited_once_with()
    child.__aexit__.assert_awaited_once()
    assert child.phase is FiberPhaseV2.DISPOSED
    next_.assert_not_awaited()


def test_lifecycle_is_an_optional_profile_module_with_declared_aliases() -> None:
    from pathlib import Path

    from src.infrastructure.plugins.v2.composer import load_profile_document_v2

    root = Path(__file__).resolve().parents[6]
    document = load_profile_document_v2(root / "config/plugin-profiles/memstack-default.v2.yaml")
    entries = {entry.module_ref: entry for entry in document.entries}

    assert entries[CONVERSATION_TITLE_LIFECYCLE_MODULE_V2].inject == {
        CONVERSATION_TITLE_LIFECYCLE_SESSIONS_INJECT_V2: (
            "service:persistence.async-session-factory"
        ),
        CONVERSATION_TITLE_LIFECYCLE_GENERATION_INJECT_V2: (
            "service:application.conversation-generation"
        ),
    }
