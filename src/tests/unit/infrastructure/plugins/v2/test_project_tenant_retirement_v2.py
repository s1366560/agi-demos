"""Zero-reference gates for the retired project/tenant shadow and legacy DI seam."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.configuration.containers.auth_container import AuthContainer
from src.configuration.containers.project_container import ProjectContainer
from src.configuration.di_container import DIContainer
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.project_tenant_services import (
    PROJECT_TENANT_APPLICATION_MODULE_V2,
    PROJECT_TENANT_PROVIDER_MODULE_V2,
    project_tenant_service_definitions_v2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_SHADOW_MODULE_V2 = "builtin://memstack/persistence/project-tenant-shadow"


def test_project_tenant_runtime_definitions_only_keep_authoritative_modules() -> None:
    module_refs = tuple(
        definition.module_ref for definition in project_tenant_service_definitions_v2()
    )

    assert module_refs == (
        PROJECT_TENANT_PROVIDER_MODULE_V2,
        PROJECT_TENANT_APPLICATION_MODULE_V2,
    )


def test_project_tenant_profile_and_manifest_do_not_publish_shadow_module() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))

    enabled_modules = {entry.module_ref for entry in profile.entries if entry.enabled}
    manifest_modules = {module.module_ref for module in manifest.modules}

    assert _SHADOW_MODULE_V2 not in enabled_modules
    assert _SHADOW_MODULE_V2 not in manifest_modules


def test_project_tenant_legacy_di_accessors_and_shadow_adapter_are_removed() -> None:
    retired_accessors = {
        "tenant_repository",
        "project_repository",
        "project_service",
        "tenant_service",
    }
    assert not retired_accessors.intersection(vars(DIContainer))
    assert "tenant_repository" not in vars(AuthContainer)
    assert not {"project_repository", "project_service", "tenant_service"}.intersection(
        vars(ProjectContainer)
    )
    assert not (
        _ROOT / "src/infrastructure/adapters/primary/web/project_tenant_shadow_v2.py"
    ).exists()
