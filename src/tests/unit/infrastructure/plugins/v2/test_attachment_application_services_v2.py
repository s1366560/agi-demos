"""V2 Provider/Consumer coverage for attachment services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.attachment_service import AttachmentService
from src.configuration.containers.agent_container import AgentContainer
from src.configuration.di_container import DIContainer
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import Project, User
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    OBJECT_STORAGE_PROVIDER_MODULE_V2,
    OBJECT_STORAGE_SERVICE_V2,
    ObjectStorageServiceV2,
)
from src.infrastructure.plugins.v2.attachment_services import (
    ATTACHMENT_APPLICATION_MODULE_V2,
    ATTACHMENT_APPLICATION_SERVICE_V2,
    ATTACHMENT_PROVIDER_INJECT_V2,
    ATTACHMENT_PROVIDER_MODULE_V2,
    ATTACHMENT_PROVIDER_SERVICE_V2,
    ATTACHMENT_STORAGE_INJECT_V2,
    AttachmentApplicationResolverV2,
    AttachmentApplicationServicesV2,
    SqlAttachmentProjectAccessV2,
    attachment_service_definitions_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_resolver_builds_attachment_services_from_operation_identity_and_session() -> None:
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
            _ = operation.provide(
                OPERATION_IDENTITY_SERVICE_V2,
                {"user_id": "user-1", "is_superuser": False},
            )
            resolver = operation.require(ATTACHMENT_APPLICATION_SERVICE_V2)
            storage = generation.resolve(
                OBJECT_STORAGE_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )

            assert isinstance(resolver, AttachmentApplicationResolverV2)
            assert isinstance(storage, ObjectStorageServiceV2)
            services = resolver.resolve(operation)
            assert isinstance(services, AttachmentApplicationServicesV2)
            assert isinstance(services.attachments.service, AttachmentService)
            assert services.attachments.service._storage is storage.storage_service
            assert getattr(services.attachments.service._repo, "_session", None) is db
            assert getattr(services.attachments.access, "_session", None) is db
            assert services.attachments.user_id == "user-1"
            assert services.attachments.is_superuser is False
    finally:
        await db.close()
        await host.close()


def test_attachment_provider_precedes_consumer_in_definitions_and_profile() -> None:
    definitions = attachment_service_definitions_v2()
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert tuple(definition.module_ref for definition in definitions) == (
        ATTACHMENT_PROVIDER_MODULE_V2,
        ATTACHMENT_APPLICATION_MODULE_V2,
    )
    assert entries[ATTACHMENT_PROVIDER_MODULE_V2].inject == {}
    assert entries[ATTACHMENT_APPLICATION_MODULE_V2].inject == {
        ATTACHMENT_PROVIDER_INJECT_V2: ATTACHMENT_PROVIDER_SERVICE_V2,
        ATTACHMENT_STORAGE_INJECT_V2: OBJECT_STORAGE_SERVICE_V2,
    }
    assert ordered_modules.index(ATTACHMENT_PROVIDER_MODULE_V2) < ordered_modules.index(
        ATTACHMENT_APPLICATION_MODULE_V2
    )
    assert ordered_modules.index(OBJECT_STORAGE_PROVIDER_MODULE_V2) < ordered_modules.index(
        ATTACHMENT_APPLICATION_MODULE_V2
    )


def test_static_attachment_constructors_are_retired_after_v2_cutover() -> None:
    retired_constructors = {"attachment_repository", "attachment_service"}

    assert retired_constructors.isdisjoint(vars(AgentContainer))
    assert retired_constructors.isdisjoint(vars(DIContainer))


@pytest.mark.parametrize(
    ("disabled_module", "missing_entry"),
    (
        (OBJECT_STORAGE_PROVIDER_MODULE_V2, "builtin-attachment-services"),
        (ATTACHMENT_PROVIDER_MODULE_V2, "builtin-attachment-services"),
    ),
)
async def test_missing_provider_is_rejected_without_static_fallback(
    disabled_module: str,
    missing_entry: str,
) -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref == disabled_module else entry
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
    assert missing_entry in str(error.value)


async def test_sql_access_returns_authoritative_tenant_for_member_and_superuser(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    another_user: User,
) -> None:
    access = SqlAttachmentProjectAccessV2(_session=test_db)
    project_ids = frozenset({str(test_project_db.id)})

    member = await access.accessible_project_tenants(
        project_ids=project_ids,
        user_id=str(test_user.id),
        is_superuser=False,
    )
    denied = await access.accessible_project_tenants(
        project_ids=project_ids,
        user_id=str(another_user.id),
        is_superuser=False,
    )
    superuser = await access.accessible_project_tenants(
        project_ids=project_ids,
        user_id="unrelated-superuser",
        is_superuser=True,
    )

    expected = {str(test_project_db.id): str(test_project_db.tenant_id)}
    assert member == expected
    assert denied == {}
    assert superuser == expected


async def test_sql_access_empty_roster_performs_no_query() -> None:
    class _FailingSession:
        async def execute(self, _statement: object) -> object:
            raise AssertionError("empty project roster must not query SQL")

    access = SqlAttachmentProjectAccessV2(_session=cast(AsyncSession, _FailingSession()))

    assert (
        await access.accessible_project_tenants(
            project_ids=frozenset(),
            user_id="user-1",
            is_superuser=False,
        )
        == {}
    )


async def test_invalid_identity_is_rejected_before_provider_build() -> None:
    class _Provider:
        def __init__(self) -> None:
            self.calls = 0

        def build(self, _operation: OperationContextV2) -> object:
            self.calls += 1
            raise AssertionError("invalid identity must fail before persistence resolution")

    provider = _Provider()
    resolver = AttachmentApplicationResolverV2(
        provider=cast(Any, provider),
        storage=cast(ObjectStorageServiceV2, SimpleNamespace(storage_service=object())),
        upload_max_size_llm_mb=10,
        upload_max_size_sandbox_mb=100,
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=153,
        version=153,
    )
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="invalid-attachment-identity",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(
                OPERATION_IDENTITY_SERVICE_V2,
                {"user_id": "user-1"},
            )
            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)
    finally:
        await host.close()

    assert error.value.code == "invalid_operation_identity"
    assert provider.calls == 0
