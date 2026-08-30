"""Workspace prompt context resolution through one pinned V2 generation."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.domain.model.agent import Conversation
from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2 import workspace_prompt_context_services
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    agent_worker_workspace_core_runtime_factory_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_ACCESS_MODULE_V2,
    CONVERSATION_ACCESS_SERVICE_V2,
)
from src.infrastructure.plugins.v2.protocol import (
    parse_plugin_manifest_v2,
    plugin_contract_digest_v2,
)
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_contracts import generated_target_catalog_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.workspace_core_runtime import (
    WORKSPACE_CORE_RUNTIME_SERVICE_V2,
    WorkspaceCoreRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.workspace_core_shadow import (
    WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2,
    activate_workspace_core_shadow_v2,
)
from src.infrastructure.plugins.v2.workspace_prompt_context_services import (
    WORKSPACE_PROMPT_CONTEXT_CONVERSATIONS_INJECT_V2,
    WORKSPACE_PROMPT_CONTEXT_MODULE_V2,
    WORKSPACE_PROMPT_CONTEXT_RUNTIME_INJECT_V2,
    WORKSPACE_PROMPT_CONTEXT_SERVICE_V2,
    WorkspacePromptContextProtocolV2,
    WorkspacePromptContextServiceV2,
)
from src.infrastructure.workspace_core.client import (
    WorkspaceCoreAgent,
    WorkspaceCoreBlackboardPost,
    WorkspaceCoreCyberObjective,
    WorkspaceCoreMember,
    WorkspaceCoreMessage,
    WorkspaceCoreProfile,
    WorkspaceCoreTask,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)
_NOW = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)


class _ProviderAdapter:
    def __init__(self) -> None:
        self.wait_calls = 0

    async def wait_until_idle(self) -> None:
        self.wait_calls += 1


def _runtime(client: object, adapter: _ProviderAdapter) -> WorkspaceCoreRuntimeServiceV2:
    marker = object()
    return WorkspaceCoreRuntimeServiceV2(
        settings=cast(Any, marker),
        client=cast(Any, client),
        authority=cast(Any, marker),
        context_judge=cast(Any, marker),
        plan_judge=cast(Any, marker),
        autonomy_judge=cast(Any, marker),
        access_verifier=cast(Any, marker),
        event_sink=cast(Any, marker),
        agent_runtime_provider=cast(Any, marker),
        provider_adapter=cast(Any, adapter),
    )


class _ConversationAccess:
    def __init__(self, conversation: Conversation | None) -> None:
        self.conversation = conversation
        self.requests: list[dict[str, str]] = []

    async def get_conversation(
        self,
        *,
        conversation_id: str,
        project_id: str,
        user_id: str,
    ) -> Conversation | None:
        self.requests.append(
            {
                "conversation_id": conversation_id,
                "project_id": project_id,
                "user_id": user_id,
            }
        )
        return self.conversation


class _ConversationResolver:
    def __init__(self, access: _ConversationAccess) -> None:
        self.access = access
        self.operations: list[OperationContextV2] = []

    def resolve(self, operation: OperationContextV2) -> Any:
        self.operations.append(operation)
        return self.access


class _Operation:
    def __init__(
        self,
        *,
        tenant_id: str = "tenant-1",
        project_id: str = "project-1",
        session_id: str = "conversation-1",
        identity: object | None = None,
    ) -> None:
        self.context = SimpleNamespace(
            scope=ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id=tenant_id,
                project_id=project_id,
                session_id=session_id,
            )
        )
        self.identity = identity or {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "user_id": "user-1",
        }

    def require(self, service: str) -> object:
        assert service == OPERATION_IDENTITY_SERVICE_V2
        return self.identity


class _WorkspaceClient:
    def __init__(self) -> None:
        self.workspace_ids: list[str] = []

    def _record(self, workspace_id: str) -> None:
        self.workspace_ids.append(workspace_id)

    async def read_workspace_profile(self, **kwargs: object) -> WorkspaceCoreProfile:
        self._record(cast(str, kwargs["workspace_id"]))
        return WorkspaceCoreProfile(
            id="workspace-exact",
            tenant_id="tenant-1",
            project_id="project-1",
            name="Release Room",
            created_by="user-1",
            is_archived=False,
            metadata={},
        )

    async def list_workspace_members(self, **kwargs: object) -> list[WorkspaceCoreMember]:
        self._record(cast(str, kwargs["workspace_id"]))
        return [
            WorkspaceCoreMember(
                workspace_id="workspace-exact",
                user_id="user-1",
                role="owner",
            )
        ]

    async def list_workspace_agents(self, **kwargs: object) -> list[WorkspaceCoreAgent]:
        self._record(cast(str, kwargs["workspace_id"]))
        return [
            WorkspaceCoreAgent(
                id="binding-1",
                workspace_id="workspace-exact",
                agent_id="agent-1",
                display_name="Verifier",
                description="Checks release evidence",
                status="busy",
                is_active=True,
            )
        ]

    async def list_workspace_messages(self, **kwargs: object) -> list[WorkspaceCoreMessage]:
        self._record(cast(str, kwargs["workspace_id"]))
        return [
            WorkspaceCoreMessage(
                id="message-1",
                workspace_id="workspace-exact",
                sender_id="user-1",
                sender_type="human",
                content="Verify the release",
                mentions=["agent-1"],
                parent_message_id=None,
                metadata={},
                created_at=_NOW,
            )
        ]

    async def list_workspace_blackboard_posts(
        self,
        **kwargs: object,
    ) -> list[WorkspaceCoreBlackboardPost]:
        self._record(cast(str, kwargs["workspace_id"]))
        return [
            WorkspaceCoreBlackboardPost(
                id="post-1",
                workspace_id="workspace-exact",
                author_id="user-1",
                title="Release gate",
                content="All required evidence must be attached",
                status="open",
                is_pinned=True,
                metadata={},
                created_at=_NOW,
                updated_at=None,
            )
        ]

    async def list_workspace_tasks(self, **kwargs: object) -> list[WorkspaceCoreTask]:
        self._record(cast(str, kwargs["workspace_id"]))
        return [
            WorkspaceCoreTask(
                id="task-1",
                workspace_id="workspace-exact",
                title="Verify release",
                description="Run every release gate",
                created_by="user-1",
                status="todo",
                priority="P1",
                metadata={"task_role": "goal_root"},
                created_at=_NOW,
                updated_at=_NOW,
            )
        ]

    async def list_workspace_objectives(
        self,
        **kwargs: object,
    ) -> list[WorkspaceCoreCyberObjective]:
        self._record(cast(str, kwargs["workspace_id"]))
        return [
            WorkspaceCoreCyberObjective(
                id="objective-1",
                workspace_id="workspace-exact",
                title="Ship safely",
                description="Preserve rollback evidence",
                obj_type="objective",
                parent_id=None,
                progress=0.5,
                created_by="user-1",
                created_at=_NOW,
                updated_at=None,
            )
        ]


def _conversation(*, workspace_id: str | None = "workspace-exact") -> Conversation:
    return Conversation(
        id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        user_id="user-1",
        title="Release",
        workspace_id=workspace_id,
    )


def test_prompt_context_contract_profile_catalog_and_definition_are_exact() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    module = next(
        item for item in manifest.modules if item.module_ref == WORKSPACE_PROMPT_CONTEXT_MODULE_V2
    )
    entry = next(
        item
        for item in load_profile_document_v2(_PROFILE_PATH).entries
        if item.entry_id == WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2
    )
    definition = next(
        item
        for item in builtin_runtime_definitions_v2()
        if item.module_ref == WORKSPACE_PROMPT_CONTEXT_MODULE_V2
    )
    catalog = generated_target_catalog_v2("python")[WORKSPACE_PROMPT_CONTEXT_MODULE_V2]
    artifact_path = _ROOT / module.artifact.source.removeprefix("repo+python://")
    expected_digest = plugin_contract_digest_v2(module.contract)

    assert module.contract_digest == expected_digest
    assert definition.contract_digest == expected_digest
    assert catalog.contract_digest == expected_digest
    assert module.artifact.digest == artifact_digest_v2(artifact_path.read_bytes())
    assert catalog.artifact_digest == module.artifact.digest
    assert tuple(
        (provided.service, provided.version) for provided in module.contract.services.provides
    ) == ((WORKSPACE_PROMPT_CONTEXT_SERVICE_V2, "1.0.0"),)
    assert tuple(
        (required.alias, required.service, required.version)
        for required in module.contract.services.requires
    ) == (
        (
            WORKSPACE_PROMPT_CONTEXT_RUNTIME_INJECT_V2,
            WORKSPACE_CORE_RUNTIME_SERVICE_V2,
            "1.0.0",
        ),
        (
            WORKSPACE_PROMPT_CONTEXT_CONVERSATIONS_INJECT_V2,
            CONVERSATION_ACCESS_SERVICE_V2,
            "1.0.0",
        ),
    )
    assert entry.parent_entry_id == "runtime-generation-boundary"
    assert entry.enabled is False
    assert entry.inject == {
        WORKSPACE_PROMPT_CONTEXT_RUNTIME_INJECT_V2: WORKSPACE_CORE_RUNTIME_SERVICE_V2,
        WORKSPACE_PROMPT_CONTEXT_CONVERSATIONS_INJECT_V2: CONVERSATION_ACCESS_SERVICE_V2,
    }
    assert entry.config == {"strategy": "workspace-core-read-model"}


async def test_prompt_context_uses_exact_conversation_workspace_and_formats_all_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = cast("OperationContextV2", _Operation())
    access = _ConversationAccess(_conversation())
    conversations = _ConversationResolver(access)
    client = _WorkspaceClient()
    service = WorkspacePromptContextServiceV2(
        runtime=_runtime(client, _ProviderAdapter()),
        conversations=cast(Any, conversations),
    )
    attempts_seen: list[object] = []
    original_experience_builder = (
        workspace_prompt_context_services.build_workspace_task_experience_summary
    )

    def build_experience(task: object, *, attempts: object = None) -> dict[str, Any]:
        attempts_seen.append(attempts)
        return original_experience_builder(cast(Any, task), attempts=cast(Any, attempts))

    monkeypatch.setattr(
        workspace_prompt_context_services,
        "build_workspace_task_experience_summary",
        build_experience,
    )

    result = await service.build(
        operation,
        project_id="project-1",
        tenant_id="tenant-1",
    )

    assert access.requests == [
        {
            "conversation_id": "conversation-1",
            "project_id": "project-1",
            "user_id": "user-1",
        }
    ]
    assert conversations.operations == [operation]
    assert client.workspace_ids == ["workspace-exact"] * 7
    assert result is not None
    assert '<cyber-workspace name="Release Room" id="workspace-exact">' in result
    assert "<members>" in result
    assert "<agents>" in result
    assert "<recent-messages>" in result
    assert "<blackboard>" in result
    assert "<objectives>" in result
    assert "<tasks>" in result
    assert "<goal-candidates>" in result
    assert attempts_seen == [[]]


async def test_prompt_context_rejects_operation_scope_drift_before_reading_conversation() -> None:
    operation = cast("OperationContextV2", _Operation(project_id="project-other"))
    access = _ConversationAccess(_conversation())
    service = WorkspacePromptContextServiceV2(
        runtime=_runtime(_WorkspaceClient(), _ProviderAdapter()),
        conversations=cast(Any, _ConversationResolver(access)),
    )

    with pytest.raises(RuntimeV2Error) as error:
        await service.build(operation, project_id="project-1", tenant_id="tenant-1")

    assert error.value.code == "workspace_prompt_context_scope_mismatch"
    assert access.requests == []


@pytest.mark.parametrize(
    ("conversation", "expected_code"),
    [
        (None, "workspace_prompt_context_conversation_missing"),
        (_conversation(workspace_id=None), "workspace_prompt_context_workspace_missing"),
    ],
)
async def test_prompt_context_fails_closed_without_exact_workspace(
    conversation: Conversation | None,
    expected_code: str,
) -> None:
    operation = cast("OperationContextV2", _Operation())
    service = WorkspacePromptContextServiceV2(
        runtime=_runtime(_WorkspaceClient(), _ProviderAdapter()),
        conversations=cast(Any, _ConversationResolver(_ConversationAccess(conversation))),
    )

    with pytest.raises(RuntimeV2Error) as error:
        await service.build(operation, project_id="project-1", tenant_id="tenant-1")

    assert error.value.code == expected_code


async def test_prompt_context_keeps_the_exact_pinned_generation_during_reload() -> None:
    clients = [object(), object()]
    adapters = [_ProviderAdapter(), _ProviderAdapter()]
    calls = 0

    async def factory() -> WorkspaceCoreRuntimeServiceV2:
        nonlocal calls
        runtime = _runtime(clients[calls], adapters[calls])
        calls += 1
        return runtime

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(workspace_core_runtime_factory=factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=821,
        version=821,
        profile_projector=activate_workspace_core_shadow_v2,
    )
    assert first.accepted is True

    async with pin_generation_v2(host) as pinned:
        old_service = pinned.resolve(WORKSPACE_PROMPT_CONTEXT_SERVICE_V2, _ROOT_SCOPE)
        assert isinstance(old_service, WorkspacePromptContextProtocolV2)
        assert cast(WorkspacePromptContextServiceV2, old_service).runtime.client is clients[0]

        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=822,
            version=822,
            profile_projector=activate_workspace_core_shadow_v2,
        )
        assert second.accepted is True
        assert cast(WorkspacePromptContextServiceV2, old_service).runtime.client is clients[0]
        assert adapters[0].wait_calls == 0

    assert adapters[0].wait_calls == 1
    current = host.manager.current
    assert current is not None
    current_service = current.resolve(WORKSPACE_PROMPT_CONTEXT_SERVICE_V2, _ROOT_SCOPE)
    assert cast(WorkspacePromptContextServiceV2, current_service).runtime.client is clients[1]

    await host.close()
    assert adapters[1].wait_calls == 1


async def test_enabled_prompt_context_rejects_missing_conversation_provider() -> None:
    document = activate_workspace_core_shadow_v2(load_profile_document_v2(_PROFILE_PATH))
    document = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == CONVERSATION_ACCESS_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(document, {manifest.plugin_id: manifest}, generation=823)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert CONVERSATION_ACCESS_SERVICE_V2 in str(error.value)


async def test_agent_worker_workspace_factory_uses_health_checked_runtime_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.configuration import workspace_core as workspace_core_config
    from src.infrastructure.adapters.primary.web import workspace_core_runtime

    settings = object()
    runtime = object()
    calls: list[object] = []

    async def create(candidate: object) -> object:
        calls.append(candidate)
        return runtime

    monkeypatch.setattr(workspace_core_config, "get_workspace_core_settings", lambda: settings)
    monkeypatch.setattr(workspace_core_runtime, "create_workspace_core_runtime_service_v2", create)

    result = await agent_worker_workspace_core_runtime_factory_v2()

    assert result is runtime
    assert calls == [settings]


@pytest.mark.parametrize(
    "relative_path",
    [
        "src/infrastructure/agent/actor/project_agent_actor.py",
        "src/infrastructure/agent/actor/local_chat_worker.py",
        "src/infrastructure/agent/hitl/generation_recovery_v2.py",
    ],
)
def test_agent_worker_data_planes_supply_workspace_core_generation_factory(
    relative_path: str,
) -> None:
    source = (_ROOT / relative_path).read_text(encoding="utf-8")

    assert "workspace_core_runtime_factory=agent_worker_workspace_core_runtime_factory_v2" in source
    assert '"project_id":' in source
