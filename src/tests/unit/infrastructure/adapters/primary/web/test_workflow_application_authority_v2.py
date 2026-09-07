"""Request-boundary coverage for the workflow application V2 authority."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.primary.web.routers import (
    episodes,
    graph,
    maintenance,
    memories,
    tasks,
)
from src.infrastructure.adapters.primary.web.workflow_application_authority_v2 import (
    workflow_engine_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.background_tasks import TaskManager
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.workflow import AsyncioWorkflowEngine
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]
_WORKFLOW_ENDPOINTS = (
    episodes.create_episode,
    graph.rebuild_communities,
    maintenance.incremental_refresh,
    maintenance.deduplicate_entities,
    maintenance.optimize_graph,
    memories.create_memory,
    memories.reprocess_memory,
    memories.update_memory,
    tasks.retry_pending_tasks_endpoint,
    tasks.retry_task_endpoint,
)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "POST",
            "path": "/api/v1/memories/",
            "path_params": {},
            "query_string": b"tenant_id=tenant-a&project_id=project-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


@pytest.mark.parametrize("endpoint", _WORKFLOW_ENDPOINTS)
def test_workflow_routes_require_v2_authority(endpoint: Any) -> None:
    parameter = signature(endpoint).parameters["workflow_engine"]

    assert parameter.default.dependency is workflow_engine_authority_dependency_v2
    assert parameter.annotation in {"WorkflowEnginePort", WorkflowEnginePort}


def test_workflow_routes_remove_static_dependency() -> None:
    for module in (episodes, graph, maintenance, memories, tasks):
        assert "get_workflow_engine" not in vars(module)


async def test_authority_resolves_engine_from_pinned_generation() -> None:
    engine = AsyncioWorkflowEngine(manager=TaskManager())
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(workflow_runtime_factory=lambda: engine)
    )
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=61,
        version=61,
    )
    assert publication.accepted is True
    dependency = None
    try:
        async with pin_generation_v2(host):
            dependency = workflow_engine_authority_dependency_v2(
                request=_request(),
                current_user=cast(User, SimpleNamespace(id="user-a")),
            )

            assert await anext(dependency) is engine
            await dependency.aclose()
    finally:
        if dependency is not None:
            await dependency.aclose()
        await host.close()


async def test_authority_propagates_generation_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.workflow_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    dependency = workflow_engine_authority_dependency_v2(
        request=_request(),
        current_user=cast(User, SimpleNamespace(id="user-a")),
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()

    assert error.value.code == "generation_not_pinned"
