"""Drone tool PluginConfig Consumer coverage."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
    pin_agent_turn_operation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.cicd_pipeline_repository_services import (
    CICD_PIPELINE_REPOSITORY_PROVIDER_SERVICE_V2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.plugin_config_services import (
    PLUGIN_CONFIG_APPLICATION_SERVICE_V2,
    PluginConfigApplicationServicesV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_DRONE_PLUGIN_CONFIGS_INJECT_V2 = "plugin_configs"
_DRONE_PIPELINE_REPOSITORY_INJECT_V2 = "pipeline_repository"
_DRONE_TOOL_MODULE_V2 = "builtin://memstack/agent/tool/drone"


class _Repository:
    async def get_by_tenant_and_plugin(self, tenant_id: str, plugin_name: str) -> None:
        del tenant_id, plugin_name
        return None

    async def upsert(self, **_kwargs: object) -> None:
        return None


class _Resolver:
    def __init__(self) -> None:
        self.operation = None
        self.repository = _Repository()

    def resolve(self, operation):
        self.operation = operation
        return PluginConfigApplicationServicesV2(repository=self.repository)


class _PipelineRepository:
    pass


class _PipelineRepositoryProvider:
    def __init__(self) -> None:
        self.operation = None
        self.repository = _PipelineRepository()

    def build(self, operation):
        self.operation = operation
        return self.repository


async def test_bound_drone_tool_injects_repository_from_parent_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1022,
        version=1022,
    )
    assert publication.accepted is True, publication.receipt
    drone_module = import_module("src.infrastructure.plugins.v2.drone_capabilities")
    db = AsyncSession()
    resolver = _Resolver()
    pipeline_repository_provider = _PipelineRepositoryProvider()
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def session_factory():
        yield db

    class _Service:
        def __init__(
            self,
            session,
            *,
            pipeline_repository,
            plugin_config_repository,
        ) -> None:
            captured["session"] = session
            captured["pipeline_repository"] = pipeline_repository
            captured["repository"] = plugin_config_repository

        async def run_pipeline(self, request):
            captured["request"] = request
            return SimpleNamespace(
                status="success",
                to_json=lambda: {
                    "provider": "drone",
                    "repository": request.repository,
                    "run_id": "run-a",
                    "status": "success",
                },
            )

    monkeypatch.setattr(drone_module, "async_session_factory", session_factory)
    monkeypatch.setattr(drone_module, "CicdPipelineService", _Service)
    install_process_generation_host_v2(host)
    try:
        async with pin_agent_turn_operation_v2(
            operation_id="turn-drone-1",
            tenant_id="tenant-a",
            project_id="project-a",
            session_id="session-a",
            services={
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "user_id": "user-a",
                }
            },
        ):
            bound = drone_module._bind_drone_tool_v2(
                drone_module.cicd_run_pipeline_tool,
                resolver,
                pipeline_repository_provider,
            )
            result = await bound.execute(
                SimpleNamespace(
                    conversation_id="session-a",
                    project_id="project-a",
                    tenant_id="tenant-a",
                    user_id="user-a",
                ),
                repository="owner/repo",
            )

        assert result.is_error is False
        assert captured["session"] is db
        assert captured["pipeline_repository"] is pipeline_repository_provider.repository
        assert captured["repository"] is resolver.repository
        assert resolver.operation is not None
        assert pipeline_repository_provider.operation is resolver.operation
        assert resolver.operation.descriptor.generation == 1022
        assert resolver.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        clear_process_generation_host_v2(host)
        await db.close()
        await host.close()


async def test_drone_rejects_wrong_plugin_config_alias_before_loading() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    broken = replace(
        document,
        entries=tuple(
            replace(
                entry,
                inject={
                    **entry.inject,
                    _DRONE_PLUGIN_CONFIGS_INJECT_V2: (
                        "service:persistence.skill-repository-provider"
                    ),
                },
            )
            if entry.module_ref == _DRONE_TOOL_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(broken, {manifest.plugin_id: manifest}, generation=1023)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "inject_service_mismatch"
    assert "builtin-drone-tool" in str(error.value)


async def test_drone_rejects_wrong_pipeline_repository_alias_before_loading() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    broken = replace(
        document,
        entries=tuple(
            replace(
                entry,
                inject={
                    **entry.inject,
                    _DRONE_PIPELINE_REPOSITORY_INJECT_V2: (
                        "service:persistence.skill-repository-provider"
                    ),
                },
            )
            if entry.module_ref == _DRONE_TOOL_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(broken, {manifest.plugin_id: manifest}, generation=1024)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "inject_service_mismatch"
    assert "builtin-drone-tool" in str(error.value)


def test_drone_profile_declares_required_consumer_aliases() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entry = next(item for item in document.entries if item.module_ref == _DRONE_TOOL_MODULE_V2)

    assert entry.inject == {
        "catalog": "service:tool-set-catalog",
        _DRONE_PLUGIN_CONFIGS_INJECT_V2: PLUGIN_CONFIG_APPLICATION_SERVICE_V2,
        _DRONE_PIPELINE_REPOSITORY_INJECT_V2: CICD_PIPELINE_REPOSITORY_PROVIDER_SERVICE_V2,
    }
