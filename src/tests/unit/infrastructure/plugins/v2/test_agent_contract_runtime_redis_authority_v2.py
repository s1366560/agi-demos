"""Pinned-generation authority coverage for workspace contract-agent turns."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import src.infrastructure.agent.workspace.contract_agent_runtime as contract_agent_runtime
import src.infrastructure.plugins.v2.artifact_content_gc_runtime as persistence_runtime
from src.infrastructure.agent.workspace.contract_agent_runtime import (
    workspace_contract_agent_turn_authority_v2,
    workspace_contract_operation_id_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    clear_process_generation_host_v2,
    current_operation_context_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.workspace_core_runtime import WorkspaceCoreRuntimeServiceV2
from src.infrastructure.plugins.v2.workspace_core_shadow import activate_workspace_core_shadow_v2
from src.infrastructure.workspace_core.client import (
    WorkspaceContractActorResolveRequest,
    WorkspaceContractActorResolveResponse,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TurnService:
    def stream_chat_v2(self, **_kwargs: Any) -> Any:
        async def _events() -> Any:
            if False:
                yield None

        return _events()


class _SessionContext:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def __aenter__(self) -> AsyncSession:
        return self.db

    async def __aexit__(self, *_args: object) -> None:
        return None


class _ActorClient:
    def __init__(self, actor_user_id: str) -> None:
        self.actor_user_id = actor_user_id
        self.requests: list[WorkspaceContractActorResolveRequest] = []

    async def resolve_contract_actor(
        self,
        request: WorkspaceContractActorResolveRequest,
    ) -> WorkspaceContractActorResolveResponse:
        self.requests.append(request)
        return WorkspaceContractActorResolveResponse(
            contract_version="2.0.0",
            actor_user_id=self.actor_user_id,
            participant_actor_id=f"human:{self.actor_user_id}",
            authority_revision=17,
            policy_version="workspace-contract-actor-owner.v1",
            duplicate=False,
        )


class _ProviderAdapter:
    def __init__(self) -> None:
        self.wait_calls = 0

    async def wait_until_idle(self) -> None:
        self.wait_calls += 1


def _workspace_runtime(
    client: _ActorClient,
    adapter: _ProviderAdapter,
) -> WorkspaceCoreRuntimeServiceV2:
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


def test_contract_agent_turn_operation_id_is_stable_and_scope_bound() -> None:
    kwargs = {
        "purpose": "planner_turn",
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "conversation_id": "conversation-1",
    }

    first = workspace_contract_operation_id_v2(**kwargs)

    assert first == workspace_contract_operation_id_v2(**kwargs)
    assert first.startswith("workspace-contract-turn:planner_turn:")
    assert len(first) <= 256
    assert first != workspace_contract_operation_id_v2(**{**kwargs, "workspace_id": "workspace-2"})


async def test_contract_agent_turn_holds_exact_generation_and_operation_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = [_ActorClient("owner-old"), _ActorClient("owner-new")]
    adapters = [_ProviderAdapter(), _ProviderAdapter()]
    runtime_calls = 0

    async def workspace_runtime_factory() -> WorkspaceCoreRuntimeServiceV2:
        nonlocal runtime_calls
        runtime = _workspace_runtime(clients[runtime_calls], adapters[runtime_calls])
        runtime_calls += 1
        return runtime

    db = AsyncSession()
    monkeypatch.setattr(persistence_runtime, "async_session_factory", lambda: _SessionContext(db))
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            workspace_core_runtime_factory=workspace_runtime_factory,
        )
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=721,
        version=721,
        profile_projector=activate_workspace_core_shadow_v2,
    )
    assert first.accepted is True
    install_process_generation_host_v2(host)

    service = _TurnService()
    observed_generations: list[int] = []

    async def resolve_turn_service() -> _TurnService:
        operation = current_operation_context_v2()
        observed_generations.append(operation.descriptor.generation)
        return service

    monkeypatch.setattr(
        contract_agent_runtime,
        "current_agent_turn_service_v2",
        resolve_turn_service,
    )

    authority = None
    try:
        async with workspace_contract_agent_turn_authority_v2(
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conversation-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
            contract_kind="verifier",
            actor_purpose="verifier_turn",
        ) as current:
            authority = current
            assert current.actor.actor_user_id == "owner-old"
            assert current.service is service
            assert current.operation.phase is FiberPhaseV2.ACTIVE
            assert current.operation.descriptor.generation == 721
            assert current.operation.operation_id.startswith(
                "workspace-contract-turn:verifier_turn:"
            )
            assert current.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert current.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-1",
                "project_id": "project-1",
                "user_id": "owner-old",
            }
            assert current.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "workspace-contract-agent-turn",
                "contract_kind": "verifier",
                "actor_purpose": "verifier_turn",
                "workspace_id": "workspace-1",
                "conversation_id": "conversation-1",
                "agent_id": "agent-1",
                "actor_participant_id": "human:owner-old",
                "actor_authority_revision": 17,
                "actor_policy_version": "workspace-contract-actor-owner.v1",
                "actor_resolution_duplicate": False,
            }
            assert clients[0].requests == [
                WorkspaceContractActorResolveRequest(
                    tenant_id="tenant-1",
                    project_id="project-1",
                    workspace_id="workspace-1",
                    purpose="verifier_turn",
                    operation_id=current.operation.operation_id,
                )
            ]

            second = await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=722,
                version=722,
                profile_projector=activate_workspace_core_shadow_v2,
            )
            assert second.accepted is True
            assert current.operation.descriptor.generation == 721

        assert authority is not None
        assert authority.operation.phase is FiberPhaseV2.DISPOSED
        assert observed_generations == [721]
        assert adapters[0].wait_calls == 1
    finally:
        await db.close()
        clear_process_generation_host_v2(host)
        await host.close()


async def test_contract_agent_turn_requires_v2_actor_resolver_without_fallback() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=723,
        version=723,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host)

    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with workspace_contract_agent_turn_authority_v2(
                tenant_id="tenant-1",
                project_id="project-1",
                conversation_id="conversation-1",
                workspace_id="workspace-1",
                agent_id="agent-1",
                contract_kind="planner",
                actor_purpose="planner_turn",
            ):
                raise AssertionError("missing actor resolver must fail before yielding authority")
    finally:
        clear_process_generation_host_v2(host)
        await host.close()

    assert error.value.code == "missing_service"


def test_contract_agent_runtime_does_not_read_static_agent_composition() -> None:
    source = (_ROOT / "src/infrastructure/agent/workspace/contract_agent_runtime.py").read_text(
        encoding="utf-8"
    )
    for retired_composition in (
        "create_llm_client",
        "get_app_container",
        "DIContainer",
        "current_agent_worker_redis_client_v2",
        "create_workspace_contract_agent_service",
        "legacy_workspace_runtime_retired",
        "resolve_workspace_actor_user_id",
    ):
        assert retired_composition not in source
