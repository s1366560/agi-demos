"""Production cutover coverage for generation-owned Artifact lifecycle access."""

from __future__ import annotations

from inspect import getsource
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.core.project_react_agent import (
    ProjectAgentConfig,
    ProjectReActAgent,
)
from src.infrastructure.plugins.v2.artifact_lifecycle_projection import (
    current_artifact_lifecycle_application_service_v2,
)
from src.infrastructure.plugins.v2.artifact_lifecycle_services import (
    ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2,
    ArtifactLifecycleApplicationServiceV2,
)
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_WORKER_STATE_MODULE = "src.infrastructure.agent.state.agent_worker_state"
_WORKER_RUNTIME_MODULE = "src.infrastructure.plugins.v2.agent_worker_runtime"


def _worker_runtime_services(graph_service: object, redis_client: object) -> SimpleNamespace:
    return SimpleNamespace(
        graph_runtime=SimpleNamespace(
            graph_service=graph_service,
            unavailable_code=None,
        ),
        redis_runtime=SimpleNamespace(client=redis_client),
    )


async def test_projection_returns_the_exact_pinned_generation_service() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=167,
        version=167,
    )
    assert publication.accepted is True
    try:
        async with pin_generation_v2(host) as generation:
            projected = current_artifact_lifecycle_application_service_v2()
            direct = generation.resolve(
                ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )

            assert projected is direct
            assert isinstance(projected, ArtifactLifecycleApplicationServiceV2)
    finally:
        await host.close()


def test_projection_fails_closed_without_a_pinned_generation() -> None:
    with pytest.raises(RuntimeV2Error) as error:
        current_artifact_lifecycle_application_service_v2()

    assert error.value.code == "generation_not_pinned"


async def test_project_agent_resolves_artifacts_only_from_the_pinned_generation() -> None:
    artifact_service = object()
    lifecycle = SimpleNamespace(artifact=artifact_service)
    agent = ProjectReActAgent(
        ProjectAgentConfig(
            tenant_id="tenant-a",
            project_id="project-a",
            agent_mode="default",
        )
    )

    with (
        patch(
            f"{_WORKER_RUNTIME_MODULE}.current_agent_worker_runtime_services_v2",
            return_value=_worker_runtime_services(MagicMock(), AsyncMock()),
        ),
        patch(
            f"{_WORKER_STATE_MODULE}.get_or_create_provider_config",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch(
            f"{_WORKER_STATE_MODULE}.get_or_create_llm_client",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch(
            "src.infrastructure.agent.core.project_react_agent."
            "current_artifact_lifecycle_application_service_v2",
            return_value=lifecycle,
        ),
    ):
        services = await agent._init_core_services(force_refresh=False)

    assert services[2] is artifact_service


async def test_project_agent_propagates_missing_required_artifact_service() -> None:
    agent = ProjectReActAgent(
        ProjectAgentConfig(
            tenant_id="tenant-a",
            project_id="project-a",
            agent_mode="default",
        )
    )
    missing = RuntimeV2Error("service_not_found", "artifact lifecycle unavailable")

    with (
        patch(
            f"{_WORKER_RUNTIME_MODULE}.current_agent_worker_runtime_services_v2",
            return_value=_worker_runtime_services(MagicMock(), AsyncMock()),
        ),
        patch(
            "src.infrastructure.agent.core.project_react_agent."
            "current_artifact_lifecycle_application_service_v2",
            side_effect=missing,
        ),
        pytest.raises(RuntimeV2Error) as error,
    ):
        await agent._init_core_services(force_refresh=False)

    assert error.value is missing


def test_production_callers_do_not_reach_back_into_static_artifact_di() -> None:
    project_source = getsource(ProjectReActAgent._init_core_services)
    channel_source = (
        _ROOT / "src/application/services/channels/channel_message_router.py"
    ).read_text(encoding="utf-8")

    assert "current_artifact_lifecycle_application_service_v2" in project_source
    assert "DIContainer" not in project_source
    assert "container.artifact_service" not in project_source
    assert "app_container.artifact_service" not in channel_source
