"""V2 application resolver coverage for attachment services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.attachment_service import AttachmentService
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    OBJECT_STORAGE_PROVIDER_MODULE_V2,
    OBJECT_STORAGE_SERVICE_V2,
    ObjectStorageServiceV2,
)
from src.infrastructure.plugins.v2.attachment_services import (
    ATTACHMENT_APPLICATION_MODULE_V2,
    ATTACHMENT_APPLICATION_SERVICE_V2,
    ATTACHMENT_STORAGE_INJECT_V2,
    AttachmentApplicationResolverV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_resolver_builds_attachment_service_from_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=151,
        version=151,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-attachment-application",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(ATTACHMENT_APPLICATION_SERVICE_V2)
            storage = generation.resolve(
                OBJECT_STORAGE_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )

            assert isinstance(resolver, AttachmentApplicationResolverV2)
            assert isinstance(storage, ObjectStorageServiceV2)
            service = resolver.resolve(operation)
            assert isinstance(service, AttachmentService)
            assert service._storage is storage.storage_service
            assert getattr(service._repo, "_session", None) is db
    finally:
        await db.close()
        await host.close()


def test_attachment_consumer_is_an_explicit_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[ATTACHMENT_APPLICATION_MODULE_V2].inject == {
        ATTACHMENT_STORAGE_INJECT_V2: OBJECT_STORAGE_SERVICE_V2,
    }
    assert ordered_modules.index(OBJECT_STORAGE_PROVIDER_MODULE_V2) < ordered_modules.index(
        ATTACHMENT_APPLICATION_MODULE_V2
    )


async def test_missing_storage_provider_is_rejected_without_di_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == OBJECT_STORAGE_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=152,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-attachment-services" in str(error.value)
