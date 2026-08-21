"""V2 Provider/Consumer coverage for workflow runtime composition."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.workflow import AsyncioWorkflowEngine
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.workflow_runtime import (
    WORKFLOW_APPLICATION_MODULE_V2,
    WORKFLOW_APPLICATION_SERVICE_V2,
    WORKFLOW_RUNTIME_MODULE_V2,
    WorkflowApplicationResolverV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _CloseTrackedWorkflowEngine(AsyncioWorkflowEngine):
    def __init__(self) -> None:
        super().__init__()
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


async def test_workflow_resolver_uses_generation_owned_engine() -> None:
    engine = _CloseTrackedWorkflowEngine()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(workflow_runtime_factory=lambda: engine)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=51,
        version=51,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="workflow-application:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            resolver = operation.require(WORKFLOW_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, WorkflowApplicationResolverV2)
            assert resolver.resolve(operation).engine is engine
            assert set(engine._workflow_handlers) == {
                "episode_processing",
                "incremental_refresh",
                "rebuild_communities",
            }
    finally:
        await host.close()

    assert engine.close_calls == 1


async def test_workflow_runtime_disposes_only_after_generation_lease_drains() -> None:
    engines = [_CloseTrackedWorkflowEngine(), _CloseTrackedWorkflowEngine()]
    factory_calls = 0

    def factory() -> AsyncioWorkflowEngine:
        nonlocal factory_calls
        engine = engines[factory_calls]
        factory_calls += 1
        return engine

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(workflow_runtime_factory=factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=52,
        version=52,
    )
    assert first.accepted is True
    lease = await host.acquire()
    _ = await lease.__aenter__()
    try:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=53,
            version=53,
        )

        assert second.accepted is True
        assert engines[0].close_calls == 0
        assert engines[1].close_calls == 0
    finally:
        await lease.__aexit__(None, None, None)

    assert engines[0].close_calls == 1
    await host.close()
    assert engines[1].close_calls == 1


async def test_workflow_application_rejects_missing_runtime_inject_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == WORKFLOW_RUNTIME_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=54)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-workflow-services" in str(error.value)
    assert "service:workflow.runtime@1.0.0" in str(error.value)


def test_workflow_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert WORKFLOW_RUNTIME_MODULE_V2 in enabled_modules
    assert WORKFLOW_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(WORKFLOW_RUNTIME_MODULE_V2) < enabled_modules.index(
        WORKFLOW_APPLICATION_MODULE_V2
    )
    application_entry = next(
        entry for entry in document.entries if entry.module_ref == WORKFLOW_APPLICATION_MODULE_V2
    )
    assert application_entry.inject == {"runtime": "service:workflow.runtime"}
