"""V2 application seam coverage for Agent workflow status."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_workflow_status_services import (
    AGENT_WORKFLOW_STATUS_MODULE_V2,
    AGENT_WORKFLOW_STATUS_SERVICE_V2,
    RayAgentWorkflowStatusServiceV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.runtime import OperationContextV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/agent/events.py"


async def test_workflow_status_service_uses_generation_owned_ray_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_reference = object()
    actor = SimpleNamespace(status=SimpleNamespace(remote=MagicMock(return_value=status_reference)))
    get_actor = AsyncMock(return_value=actor)
    await_status = AsyncMock(
        return_value=SimpleNamespace(
            actor_id="actor-a",
            is_executing=True,
            is_initialized=True,
            created_at="2026-08-29T07:30:00+00:00",
        )
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.actor.actor_manager.get_actor_if_exists",
        get_actor,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.ray.client.await_ray",
        await_status,
    )

    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1004,
        version=1004,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-workflow-status",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            service = operation.require(AGENT_WORKFLOW_STATUS_SERVICE_V2)

            assert isinstance(service, RayAgentWorkflowStatusServiceV2)
            result = await service.get_status(
                tenant_id="tenant-a",
                project_id="project-a",
                agent_mode="default",
            )

        get_actor.assert_awaited_once_with(
            tenant_id="tenant-a",
            project_id="project-a",
            agent_mode="default",
        )
        actor.status.remote.assert_called_once_with()
        await_status.assert_awaited_once_with(status_reference)
        assert result is not None
        assert result.workflow_id == "actor-a"
        assert result.status == "RUNNING"
        assert result.started_at == datetime.fromisoformat("2026-08-29T07:30:00+00:00")
    finally:
        await host.close()


async def test_workflow_status_service_returns_none_when_actor_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_actor = AsyncMock(return_value=None)
    await_status = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.agent.actor.actor_manager.get_actor_if_exists",
        get_actor,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.ray.client.await_ray",
        await_status,
    )
    service = RayAgentWorkflowStatusServiceV2()

    result = await service.get_status(
        tenant_id="tenant-a",
        project_id="project-a",
        agent_mode="default",
    )

    assert result is None
    await_status.assert_not_awaited()


def test_workflow_status_module_is_an_explicit_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        entry for entry in document.entries if entry.module_ref == AGENT_WORKFLOW_STATUS_MODULE_V2
    )

    assert entry.enabled is True
    assert entry.config == {"strategy": "ray-actor-status"}
    assert entry.inject == {}


def test_workflow_status_route_has_no_static_ray_lookup() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")

    assert "actor_manager import get_actor_if_exists" not in source
    assert "secondary.ray.client import await_ray" not in source
