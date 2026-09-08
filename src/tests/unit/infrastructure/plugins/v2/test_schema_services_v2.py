"""V2 provider and application coverage for project schema services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.schema import EntityTypeCreate
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.project_schema.commands import ProjectSchemaScope
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.schema_services import (
    SCHEMA_APPLICATION_MODULE_V2,
    SCHEMA_APPLICATION_SERVICE_V2,
    SCHEMA_PROVIDER_MODULE_V2,
    SchemaAccessDeniedV2,
    SchemaApplicationResolverV2,
    SchemaApplicationServicesV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_schema_application_resolver_builds_operation_owned_services() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=21,
        version=21,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="schema:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            _ = operation.provide(
                "service:operation.identity",
                {
                    "user_id": "user-a",
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                },
            )
            resolver = operation.require(SCHEMA_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, SchemaApplicationResolverV2)

            services = resolver.resolve(operation)

            assert getattr(services.persistence, "_session", None) is db
    finally:
        await db.close()
        await host.close()


def test_schema_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert SCHEMA_PROVIDER_MODULE_V2 in enabled_modules
    assert SCHEMA_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(SCHEMA_PROVIDER_MODULE_V2) < enabled_modules.index(
        SCHEMA_APPLICATION_MODULE_V2
    )


async def test_schema_application_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == SCHEMA_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=22)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-schema-services" in str(error.value)


async def test_viewer_write_is_rejected_before_schema_persistence_mutation() -> None:
    persistence = SimpleNamespace(
        find_membership=AsyncMock(return_value=SimpleNamespace(role="viewer")),
        create_entity_type=AsyncMock(),
    )
    services = SchemaApplicationServicesV2(
        persistence=persistence,
        authorization=SimpleNamespace(
            authorize=AsyncMock(side_effect=ProjectSchemaError("project_schema_access_denied"))
        ),
        scope=ProjectSchemaScope(tenant_id="tenant-a", project_id="project-a", actor_id="user-a"),
    )

    with pytest.raises(SchemaAccessDeniedV2):
        await services.create_entity_type(
            user_id="user-a",
            project_id="project-a",
            data=EntityTypeCreate(name="Person", schema={"fields": []}),
        )

    persistence.create_entity_type.assert_not_awaited()
