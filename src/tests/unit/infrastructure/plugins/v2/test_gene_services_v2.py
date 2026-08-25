"""V2 Provider/Consumer coverage for Gene marketplace services."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.containers.instance_container import InstanceContainer
from src.configuration.di_container import DIContainer
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    GeneMarketModel,
    InstanceModel,
    Project,
    User,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.gene_services import (
    GENE_APPLICATION_MODULE_V2,
    GENE_APPLICATION_SERVICE_V2,
    GENE_PROVIDER_MODULE_V2,
    GeneApplicationResolverV2,
    GeneResourceDirectoryV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_application_resolver_builds_gene_services_from_operation_db() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=51,
        version=51,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-genes:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(GENE_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, GeneApplicationResolverV2)

            services = resolver.resolve(operation)

            assert services.genes._gene_repo._session is db
            assert services.genes._genome_repo._session is db
            assert services.genes._instance_gene_repo._session is db
            assert services.genes._gene_rating_repo._session is db
            assert services.genes._evolution_event_repo._session is db
            assert services.genes._gene_review_repo._session is db
            assert services.resources._db is db
    finally:
        await db.close()
        await host.close()


def test_provider_and_consumer_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert GENE_PROVIDER_MODULE_V2 in enabled_modules
    assert GENE_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(GENE_PROVIDER_MODULE_V2) < enabled_modules.index(
        GENE_APPLICATION_MODULE_V2
    )


async def test_application_resolver_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref == GENE_PROVIDER_MODULE_V2 else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=52,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-gene-services" in str(error.value)


async def test_application_resolver_requires_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=53,
        version=53,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-genes:no-db",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            resolver = operation.require(GENE_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "missing_service"
    finally:
        await host.close()


def test_static_gene_accessors_are_retired_after_v2_cutover() -> None:
    for accessor in (
        "gene_repository",
        "genome_repository",
        "instance_gene_repository",
        "gene_rating_repository",
        "evolution_event_repository",
        "gene_review_repository",
        "gene_service",
    ):
        assert not hasattr(InstanceContainer, accessor)
        assert not hasattr(DIContainer, accessor)


async def test_resource_directory_enforces_tenant_deleted_and_global_visibility(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    active_instance = InstanceModel(
        id="gene-v2-active-instance",
        name="Active Gene Instance",
        slug="gene-v2-active-instance",
        tenant_id=test_project_db.tenant_id,
        service_type="ClusterIP",
        created_by=test_user.id,
    )
    deleted_instance = InstanceModel(
        id="gene-v2-deleted-instance",
        name="Deleted Gene Instance",
        slug="gene-v2-deleted-instance",
        tenant_id=test_project_db.tenant_id,
        service_type="ClusterIP",
        created_by=test_user.id,
        deleted_at=datetime.now(UTC),
    )
    genes = [
        GeneMarketModel(
            id="gene-v2-tenant",
            name="Tenant Gene",
            slug="gene-v2-tenant",
            tenant_id=test_project_db.tenant_id,
            description="Tenant metadata",
            category="tenant",
        ),
        GeneMarketModel(
            id="gene-v2-global",
            name="Global Gene",
            slug="gene-v2-global",
            tenant_id=None,
            description="Global metadata",
            category="global",
        ),
        GeneMarketModel(
            id="gene-v2-foreign",
            name="Foreign Gene",
            slug="gene-v2-foreign",
            tenant_id="foreign-tenant",
        ),
        GeneMarketModel(
            id="gene-v2-deleted",
            name="Deleted Gene",
            slug="gene-v2-deleted",
            tenant_id=test_project_db.tenant_id,
            deleted_at=datetime.now(UTC),
        ),
    ]
    test_db.add_all([active_instance, deleted_instance, *genes])
    await test_db.commit()
    resources = GeneResourceDirectoryV2(_db=test_db)

    assert await resources.contains_instance(
        instance_id=active_instance.id,
        tenant_id=test_project_db.tenant_id,
    )
    assert not await resources.contains_instance(
        instance_id=active_instance.id,
        tenant_id="foreign-tenant",
    )
    assert not await resources.contains_instance(
        instance_id=deleted_instance.id,
        tenant_id=test_project_db.tenant_id,
    )

    metadata = await resources.get_gene_metadata(
        gene_ids={gene.id for gene in genes},
        tenant_id=test_project_db.tenant_id,
    )

    assert metadata == {
        "gene-v2-tenant": {
            "name": "Tenant Gene",
            "description": "Tenant metadata",
            "category": "tenant",
        },
        "gene-v2-global": {
            "name": "Global Gene",
            "description": "Global metadata",
            "category": "global",
        },
    }
