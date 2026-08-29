"""Generation-owned conversation participant application seam coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    bind_operation_context_v2,
    current_generation_v2,
    current_operation_context_v2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.conversation_participant_services import (
    CONVERSATION_PARTICIPANT_MODULE_V2,
    ConversationParticipantConversationNotFoundV2,
    ConversationParticipantProjectNotFoundV2,
    ConversationParticipantScopeMismatchV2,
    ConversationParticipantServiceV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    FiberPhaseV2,
    LoaderV2,
    OperationContextV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _service(
    *,
    conversation: object | None,
    project: object | None,
) -> tuple[ConversationParticipantServiceV2, SimpleNamespace, SimpleNamespace]:
    access = SimpleNamespace(
        find_by_id=AsyncMock(return_value=conversation),
        repository=SimpleNamespace(save=AsyncMock(return_value=conversation)),
        cache=SimpleNamespace(invalidate=AsyncMock()),
    )
    project_repository = SimpleNamespace(find_by_id=AsyncMock(return_value=project))
    service = ConversationParticipantServiceV2(
        operation=cast(
            Any,
            SimpleNamespace(
                context=SimpleNamespace(
                    scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a")
                )
            ),
        ),
        access=cast(Any, access),
        project_tenant=cast(
            Any,
            SimpleNamespace(project_repository=project_repository),
        ),
        agent_definitions=cast(Any, SimpleNamespace()),
    )
    return service, access, project_repository


async def test_participant_service_loads_conversation_and_project_from_v2_dependencies() -> None:
    conversation = SimpleNamespace(
        id="conversation-a",
        tenant_id="tenant-a",
        project_id="project-a",
    )
    project = SimpleNamespace(id="project-a", tenant_id="tenant-a")
    service, access, project_repository = _service(
        conversation=conversation,
        project=project,
    )

    loaded = await service.load("conversation-a")

    assert loaded.conversation is conversation
    assert loaded.project is project
    access.find_by_id.assert_awaited_once_with("conversation-a")
    project_repository.find_by_id.assert_awaited_once_with("project-a")


async def test_participant_service_distinguishes_missing_conversation_and_project() -> None:
    missing_conversation, _access, project_repository = _service(
        conversation=None,
        project=SimpleNamespace(),
    )
    with pytest.raises(ConversationParticipantConversationNotFoundV2):
        await missing_conversation.load("missing-conversation")
    project_repository.find_by_id.assert_not_awaited()

    conversation = SimpleNamespace(
        id="conversation-a",
        tenant_id="tenant-a",
        project_id="missing-project",
    )
    missing_project, _access, project_repository = _service(
        conversation=conversation,
        project=None,
    )
    with pytest.raises(ConversationParticipantProjectNotFoundV2):
        await missing_project.load("conversation-a")
    project_repository.find_by_id.assert_awaited_once_with("missing-project")


async def test_participant_service_rejects_cross_tenant_load_before_project_lookup() -> None:
    service, _access, project_repository = _service(
        conversation=SimpleNamespace(
            id="conversation-a",
            tenant_id="tenant-b",
            project_id="project-b",
        ),
        project=SimpleNamespace(id="project-b", tenant_id="tenant-b"),
    )

    with pytest.raises(ConversationParticipantConversationNotFoundV2):
        await service.load("conversation-a")

    project_repository.find_by_id.assert_not_awaited()


async def test_participant_service_saves_only_the_exact_tenant_project_scope() -> None:
    conversation = SimpleNamespace(
        id="conversation-a",
        tenant_id="tenant-a",
        project_id="project-a",
    )
    service, access, _project_repository = _service(
        conversation=conversation,
        project=SimpleNamespace(id="project-a"),
    )

    saved = await service.save(
        cast(Any, conversation),
        tenant_id="tenant-a",
        project_id="project-a",
    )

    assert saved is conversation
    access.repository.save.assert_awaited_once_with(conversation)
    await service.after_mutation_committed("project-a")
    access.cache.invalidate.assert_awaited_once_with("project-a")
    with pytest.raises(ConversationParticipantScopeMismatchV2):
        await service.save(
            cast(Any, conversation),
            tenant_id="tenant-other",
            project_id="project-a",
        )


async def test_participant_service_resolves_agent_in_nested_project_operation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=993,
        version=993,
    )
    db = AsyncSession()
    definition = SimpleNamespace(id="agent-a")
    child_operations: list[OperationContextV2] = []

    async def resolve_agent_definition(**kwargs: str) -> object:
        operation = current_operation_context_v2()
        child_operations.append(operation)
        assert operation.context.scope == ScopeV2(
            kind=ScopeKindV2.PROJECT,
            tenant_id="tenant-a",
            project_id="project-a",
        )
        assert operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
        assert kwargs == {
            "agent_id": "agent-a",
            "tenant_id": "tenant-a",
            "project_id": "project-a",
        }
        return definition

    try:
        async with pin_generation_v2(host):
            parent = OperationContextV2(
                generation=current_generation_v2(),
                operation_id="participant-parent",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            )
            async with parent:
                _ = parent.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
                _ = parent.provide(
                    OPERATION_IDENTITY_SERVICE_V2,
                    {"tenant_id": "tenant-a", "user_id": "user-a"},
                )
                service = ConversationParticipantServiceV2(
                    operation=parent,
                    access=cast(Any, SimpleNamespace()),
                    project_tenant=cast(Any, SimpleNamespace()),
                    agent_definitions=cast(
                        Any,
                        SimpleNamespace(resolve=AsyncMock(side_effect=resolve_agent_definition)),
                    ),
                )

                with bind_operation_context_v2(parent):
                    resolved = await service.resolve_agent(
                        agent_id="agent-a",
                        tenant_id="tenant-a",
                        project_id="project-a",
                    )
                    assert current_operation_context_v2() is parent

                assert resolved is definition
                assert child_operations[0].phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


async def test_participant_service_rejects_cross_tenant_agent_scope_before_resolution() -> None:
    service, _access, _project_repository = _service(
        conversation=SimpleNamespace(),
        project=SimpleNamespace(),
    )
    service = replace(
        service,
        operation=cast(
            Any,
            SimpleNamespace(
                context=SimpleNamespace(
                    scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a")
                )
            ),
        ),
        agent_definitions=cast(Any, SimpleNamespace(resolve=AsyncMock())),
    )

    with pytest.raises(ConversationParticipantScopeMismatchV2):
        await service.resolve_agent(
            agent_id="agent-a",
            tenant_id="tenant-b",
            project_id="project-a",
        )

    service.agent_definitions.resolve.assert_not_awaited()


def test_participant_module_is_explicit_in_the_default_profile() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        entry
        for entry in document.entries
        if entry.module_ref == CONVERSATION_PARTICIPANT_MODULE_V2
    )

    assert entry.enabled is True
    assert entry.inject == {
        "agent_definitions": "service:agent-definition-resolver",
        "conversation_access": "service:application.conversation-access",
        "project_tenant": "service:application.project-tenant-services",
    }


async def test_participant_module_rejects_missing_agent_definition_inject_without_fallback() -> (
    None
):
    document = load_profile_document_v2(_PROFILE_PATH)
    participant = next(
        entry
        for entry in document.entries
        if entry.module_ref == CONVERSATION_PARTICIPANT_MODULE_V2
    )
    invalid = replace(
        document,
        entries=tuple(
            replace(
                entry,
                inject={
                    "conversation_access": entry.inject["conversation_access"],
                    "project_tenant": entry.inject["project_tenant"],
                },
            )
            if entry.entry_id == participant.entry_id
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(invalid, {manifest.plugin_id: manifest}, generation=991)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_required_inject"
