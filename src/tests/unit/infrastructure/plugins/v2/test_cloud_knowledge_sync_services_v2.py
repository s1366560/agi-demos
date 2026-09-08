"""Generation, identity and default-publication boundaries for cloud sync."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncScope
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
    SqlKnowledgeSyncRepository,
)
from src.infrastructure.plugins.v2.builtin_cloud_knowledge_sync_http_routes import (
    CLOUD_KNOWLEDGE_SYNC_HTTP_MODULE_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.cloud_knowledge_sync_services import (
    CLOUD_KNOWLEDGE_SYNC_APPLICATION_MODULE_V2,
    CLOUD_KNOWLEDGE_SYNC_APPLICATION_SERVICE_V2,
    CLOUD_KNOWLEDGE_SYNC_REPOSITORY_MODULE_V2,
    CLOUD_KNOWLEDGE_SYNC_REPOSITORY_SERVICE_V2,
    cloud_knowledge_sync_service_definitions_v2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    LoaderV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[6]


def test_cloud_sync_modules_are_registered_but_default_profile_keeps_them_closed() -> None:
    refs = {item.module_ref for item in cloud_knowledge_sync_service_definitions_v2()}
    assert refs == {
        CLOUD_KNOWLEDGE_SYNC_REPOSITORY_MODULE_V2,
        CLOUD_KNOWLEDGE_SYNC_APPLICATION_MODULE_V2,
    }
    entries = load_profile_document_v2(ROOT / "config/plugin-profiles/memstack-default.v2.yaml")
    matching = [
        entry
        for entry in entries.entries
        if entry.module_ref in refs | {CLOUD_KNOWLEDGE_SYNC_HTTP_MODULE_V2}
    ]
    assert len(matching) == 3
    assert all(not entry.enabled for entry in matching)


@pytest.fixture
async def sync_host():
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=83,
        version=83,
        profile_projector=lambda document: replace(
            document,
            entries=tuple(
                replace(entry, enabled=True)
                if entry.module_ref
                in {
                    CLOUD_KNOWLEDGE_SYNC_APPLICATION_MODULE_V2,
                    CLOUD_KNOWLEDGE_SYNC_REPOSITORY_MODULE_V2,
                }
                else entry
                for entry in document.entries
            ),
        ),
    )
    assert publication.accepted
    try:
        yield host
    finally:
        await host.close()


def provide(operation, db, identity):
    operation.provide("service:operation.db-session", db)
    operation.provide("service:operation.identity", identity)
    return operation.require(CLOUD_KNOWLEDGE_SYNC_APPLICATION_SERVICE_V2)


async def test_retained_sync_enrollment_and_commit_cannot_outlive_operation(sync_host):
    async with await sync_host.acquire() as generation, AsyncSession() as db:
        async with OperationContextV2(
            generation=generation,
            operation_id="retained-sync",
            scope=ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="tenant", project_id="project"),
        ) as operation:
            resolver = provide(operation, db, {"user_id": "actor", "tenant_id": "tenant"})
            services = resolver.resolve(operation)
        for action in (
            services.enrollment.status,
            services.enrollment.bootstrap,
            services.sync.commit,
        ):
            with pytest.raises(RuntimeV2Error, match="inactive plugin operation"):
                await action()


@pytest.mark.parametrize("field", ["user_id", "tenant_id"])
async def test_identity_change_revokes_retained_service_before_database_access(sync_host, field):
    async with (
        await sync_host.acquire() as generation,
        AsyncSession() as db,
        OperationContextV2(
            generation=generation,
            operation_id="changed-sync-identity",
            scope=ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="tenant", project_id="project"),
        ) as operation,
    ):
        identity = {"user_id": "actor", "tenant_id": "tenant"}
        services = provide(operation, db, identity).resolve(operation)
        identity[field] = "other"
        with pytest.raises(RuntimeV2Error) as error:
            await services.enrollment.status()
        assert error.value.code == "invalid_operation_identity"


async def test_root_scope_cannot_build_a_project_sync_application(sync_host):
    async with (
        await sync_host.acquire() as generation,
        AsyncSession() as db,
        OperationContextV2(
            generation=generation,
            operation_id="invalid-sync-scope",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as operation,
    ):
        resolver = provide(operation, db, {"user_id": "actor", "tenant_id": "tenant"})
        with pytest.raises(RuntimeV2Error) as error:
            resolver.resolve(operation)
        assert error.value.code == "invalid_operation_scope"


def cloud_snapshot(enabled_modules):
    document = load_profile_document_v2(ROOT / "config/plugin-profiles/memstack-default.v2.yaml")
    document = replace(
        document,
        entries=tuple(
            replace(entry, enabled=True) if entry.module_ref in enabled_modules else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(
        json.loads(
            (ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json").read_text()
        )
    )
    return compose_profile_v2(document, {manifest.plugin_id: manifest}, generation=84)


@pytest.mark.parametrize(
    "consumer", [CLOUD_KNOWLEDGE_SYNC_APPLICATION_MODULE_V2, CLOUD_KNOWLEDGE_SYNC_HTTP_MODULE_V2]
)
async def test_missing_cloud_sync_provider_rejects_candidate_without_fallback(consumer):
    snapshot = cloud_snapshot({consumer})
    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)
    assert error.value.code == "missing_inject_provider"


@pytest.mark.parametrize(
    ("module_ref", "service", "code"),
    [
        (
            CLOUD_KNOWLEDGE_SYNC_REPOSITORY_MODULE_V2,
            CLOUD_KNOWLEDGE_SYNC_REPOSITORY_SERVICE_V2,
            "invalid_cloud_sync_provider",
        ),
        (
            CLOUD_KNOWLEDGE_SYNC_APPLICATION_MODULE_V2,
            CLOUD_KNOWLEDGE_SYNC_APPLICATION_SERVICE_V2,
            "invalid_cloud_sync_resolver",
        ),
    ],
)
async def test_invalid_cloud_sync_provider_rejects_candidate_without_routes(
    module_ref, service, code
):
    snapshot = cloud_snapshot(
        {
            CLOUD_KNOWLEDGE_SYNC_REPOSITORY_MODULE_V2,
            CLOUD_KNOWLEDGE_SYNC_APPLICATION_MODULE_V2,
            CLOUD_KNOWLEDGE_SYNC_HTTP_MODULE_V2,
        }
    )

    def invalid_provider(context, _config):
        context.provide(service, object())

    definitions = tuple(
        PluginDefinitionV2(
            module_ref=definition.module_ref,
            contract_digest=definition.contract_digest,
            apply=invalid_provider,
        )
        if definition.module_ref == module_ref
        else definition
        for definition in builtin_runtime_definitions_v2()
    )
    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions).stage(snapshot)
    assert error.value.code == code


@pytest.mark.parametrize("identity", [None, {}, {"user_id": " actor "}, {"user_id": 17}])
async def test_noncanonical_actor_cannot_build_cloud_sync_application(sync_host, identity):
    async with (
        await sync_host.acquire() as generation,
        AsyncSession() as db,
        OperationContextV2(
            generation=generation,
            operation_id="malformed-sync-identity",
            scope=ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="tenant", project_id="project"),
        ) as operation,
    ):
        resolver = provide(operation, db, identity)
        with pytest.raises(RuntimeV2Error) as error:
            resolver.resolve(operation)
        assert error.value.code == "invalid_operation_identity"


async def test_invalid_database_session_cannot_build_cloud_sync_application(sync_host):
    async with (
        await sync_host.acquire() as generation,
        OperationContextV2(
            generation=generation,
            operation_id="malformed-sync-database",
            scope=ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="tenant", project_id="project"),
        ) as operation,
    ):
        resolver = provide(operation, object(), {"user_id": "actor", "tenant_id": "tenant"})
        with pytest.raises(RuntimeV2Error) as error:
            resolver.resolve(operation)
        assert error.value.code == "invalid_operation_db_session"


@pytest.mark.parametrize("revocation", ["actor", "operation"])
async def test_scope_discovery_rechecks_operation_after_database_await(
    sync_host, monkeypatch, revocation
):
    async with (
        await sync_host.acquire() as generation,
        AsyncSession() as db,
        OperationContextV2(
            generation=generation,
            operation_id="scope-discovery-revoked-in-flight",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as operation,
    ):
        identity = {"user_id": "actor", "tenant_id": None}
        resolver = provide(operation, db, identity)

        async def discover(_repository, actor_id, project_id):
            if revocation == "actor":
                identity["user_id"] = "other"
            else:
                await operation.dispose()
            return KnowledgeSyncScope(tenant_id="tenant", project_id=project_id, actor_id=actor_id)

        monkeypatch.setattr(SqlKnowledgeSyncRepository, "resolve_scope", discover)
        with pytest.raises(RuntimeV2Error) as error:
            await resolver.discover_scope(operation, "project")
        assert error.value.code == (
            "invalid_operation_identity" if revocation == "actor" else "inactive_operation"
        )


async def test_commit_completion_cannot_be_used_after_operation_retirement(sync_host, monkeypatch):
    async with (
        await sync_host.acquire() as generation,
        AsyncSession() as db,
        OperationContextV2(
            generation=generation,
            operation_id="commit-operation-retired-in-flight",
            scope=ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="tenant", project_id="project"),
        ) as operation,
    ):
        services = provide(operation, db, {"user_id": "actor", "tenant_id": "tenant"}).resolve(
            operation
        )

        async def commit():
            await operation.dispose()

        monkeypatch.setattr(db, "commit", commit)
        with pytest.raises(RuntimeV2Error, match="inactive plugin operation"):
            await services.sync.commit()
