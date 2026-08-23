"""V2 Provider coverage for the generation-owned engine catalog."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.engine_services import (
    ENGINE_CATALOG_MODULE_V2,
    ENGINE_CATALOG_SERVICE_V2,
    EngineCatalogV2,
    EngineDescriptorV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_engine_catalog_is_built_from_the_explicit_profile_entry() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=91,
        version=91,
    )
    assert publication.accepted is True
    try:
        async with await host.acquire() as generation:
            catalog = generation.resolve(
                ENGINE_CATALOG_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )

            assert isinstance(catalog, EngineCatalogV2)
            assert [engine.runtime_id for engine in catalog.list_engines()] == [
                "python-3.12",
                "node-22",
                "sandbox-base",
            ]
    finally:
        await host.close()


def test_engine_catalog_is_an_explicit_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entry = next(item for item in document.entries if item.module_ref == ENGINE_CATALOG_MODULE_V2)

    assert entry.enabled is True
    assert entry.config["strategy"] == "declared-engines"
    assert [engine["runtime_id"] for engine in entry.config["engines"]] == [
        "python-3.12",
        "node-22",
        "sandbox-base",
    ]


async def test_engines_route_rejects_missing_catalog_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref == ENGINE_CATALOG_MODULE_V2 else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=92)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-engines-http-routes" in str(error.value)
    assert "service:application.engine-catalog@1.0.0" in str(error.value)


def test_engine_catalog_rejects_duplicate_runtime_ids() -> None:
    descriptor = EngineDescriptorV2(
        runtime_id="duplicate-runtime",
        display_name="Duplicate",
        display_description="Duplicate engine fixture",
        display_tags=("test",),
        display_powered_by="Test",
        order=1,
        image_registry_key="duplicate",
        default_registry_url="example.invalid/duplicate:latest",
    )

    with pytest.raises(RuntimeV2Error) as error:
        EngineCatalogV2(engines=(descriptor, descriptor))

    assert error.value.code == "duplicate_engine_runtime_id"
