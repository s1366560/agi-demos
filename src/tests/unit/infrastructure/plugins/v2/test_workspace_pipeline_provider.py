"""V2-only Workspace pipeline provider composition coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.workspace_plan import pipeline_provider_registry
from src.infrastructure.agent.workspace_plan.pipeline_provider_registry import (
    require_pipeline_provider,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.workspace_pipeline import (
    WORKSPACE_DRONE_PIPELINE_PROVIDER_MODULE_V2,
    WORKSPACE_DRONE_PIPELINE_PROVIDER_SERVICE_V2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_pipeline_provider_resolves_from_pinned_v2_generation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    assert publication.accepted is True

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="pipeline-provider:test",
            scope=ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id="tenant-1",
                project_id="project-1",
                session_id="session-1",
            ),
        ):
            provider = await require_pipeline_provider("drone")

        assert provider.__class__.__name__ == "DronePipelineProvider"
        assert callable(provider.run)
    finally:
        await host.close()


def test_pipeline_provider_resolver_has_no_v1_registry_authority() -> None:
    assert not hasattr(pipeline_provider_registry, "get_plugin_registry")
    assert not hasattr(pipeline_provider_registry, "get_plugin_runtime_manager")


async def test_disabling_pipeline_provider_entry_removes_service_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == WORKSPACE_DRONE_PIPELINE_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=2,
    )
    generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    try:
        with pytest.raises(RuntimeV2Error) as error:
            _ = generation.resolve(
                WORKSPACE_DRONE_PIPELINE_PROVIDER_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
    finally:
        await generation.dispose()

    assert error.value.code == "missing_service"


async def test_pipeline_provider_config_is_rejected_before_activation() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    invalid = replace(
        document,
        entries=tuple(
            replace(entry, config={"provider": "jenkins"})
            if entry.module_ref == WORKSPACE_DRONE_PIPELINE_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        invalid,
        {manifest.plugin_id: manifest},
        generation=3,
    )

    with pytest.raises(RuntimeV2Error) as error:
        _ = await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "invalid_module_config"
