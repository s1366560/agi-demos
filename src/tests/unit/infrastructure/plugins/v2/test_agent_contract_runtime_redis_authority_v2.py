"""Pinned-generation authority coverage for workspace contract-agent turns."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import src.infrastructure.agent.workspace.contract_agent_runtime as contract_agent_runtime
from src.infrastructure.agent.workspace.contract_agent_runtime import (
    workspace_contract_agent_turn_authority_v2,
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
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

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


async def test_contract_agent_turn_holds_exact_generation_and_operation_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=721,
        version=721,
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

    db = AsyncSession()
    authority = None
    try:
        async with workspace_contract_agent_turn_authority_v2(
            db=db,
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
            conversation_id="conversation-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
            contract_kind="verifier",
        ) as current:
            authority = current
            assert current.service is service
            assert current.operation.phase is FiberPhaseV2.ACTIVE
            assert current.operation.descriptor.generation == 721
            assert current.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert current.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "project_id": "project-1",
            }
            assert current.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "workspace-contract-agent-turn",
                "contract_kind": "verifier",
                "workspace_id": "workspace-1",
                "conversation_id": "conversation-1",
                "agent_id": "agent-1",
            }

            second = await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=722,
                version=722,
            )
            assert second.accepted is True
            assert current.operation.descriptor.generation == 721

        assert authority is not None
        assert authority.operation.phase is FiberPhaseV2.DISPOSED
        assert observed_generations == [721]
    finally:
        await db.close()
        clear_process_generation_host_v2(host)
        await host.close()


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
    ):
        assert retired_composition not in source
