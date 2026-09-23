"""Real PostgreSQL, signed Wasmtime and SQL authorization across private scopes."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from src.application.services.agent.conversation_manager import ConversationManager
from src.application.services.marketplace_legacy_retirement_v2 import maintenance_scoped_runtime
from src.application.services.marketplace_signed_scope_v2 import (
    SignedMarketplaceScopeV2,
    signed_installations,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.application.services.wasm_operation_authority_v2 import SqlWasmOperationAuthorityV2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    Base,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAgentExecutionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.plugins.v2.agent_turn_requirements_v2 import AGENT_TURN_REQUIRED_SERVICES_V2
from src.infrastructure.plugins.v2.boundary import OPERATION_IDENTITY_SERVICE_V2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import parse_bundle_manifest_v2
from src.infrastructure.plugins.v2.scoped_boundary import pin_scoped_agent_turn_operation_v2
from src.infrastructure.plugins.v2.tool_set import TOOL_SET_CATALOG_SERVICE_V2
from src.infrastructure.plugins.v2.wasm_tool_runtime import prepare_wasm_operation_tools_v2
from src.tests.integration.test_marketplace_v3_jobs_postgres import migrate
from src.tests.unit.application.services.test_plugin_marketplace_install_service import (
    FakeArtifactClient,
    _request,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(loop_scope="function")
async def sessions():
    url = os.environ.get("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("requires the owned PostgreSQL runner")
    schema = f"signed_marketplace_{uuid4().hex}"
    admin = create_async_engine(url)
    engine = create_async_engine(
        url,
        connect_args={
            "server_settings": {
                "search_path": schema,
                "lock_timeout": "10s",
                "statement_timeout": "20s",
            }
        },
    )
    selected = {
        table
        for name, table in Base.metadata.tables.items()
        if name.startswith("platform_plugin_v2_")
        or name
        in {
            "platform_plugin_packages",
            "platform_plugin_permissions",
            "users",
            "tenants",
            "projects",
            "user_projects",
            "user_tenants",
            "conversations",
        }
    }
    while True:
        parents = {fk.column.table for table in selected for fk in table.foreign_keys}
        if parents <= selected:
            break
        selected |= parents
    try:
        async with admin.begin() as connection:
            await connection.execute(CreateSchema(schema))
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda connection: Base.metadata.create_all(connection, tables=list(selected))
            )
            await connection.run_sync(migrate)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def test_two_tenants_projects_real_signed_wasm_restart_and_disappearance(  # noqa: PLR0915
    sessions, monkeypatch
):
    from fastapi import FastAPI

    from src.application.services import scoped_installed_bundle_loader_v2
    from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
        initialize_scoped_profile_runtime_v2,
    )

    fixture = Path("src/tests/unit/infrastructure/plugins/v2/fixtures/signed_wasm_marker")
    archive = (fixture / "marker.mspkg").read_bytes()
    key = (fixture / "signer-public.pem").read_text()
    with zipfile.ZipFile(fixture / "marker.mspkg") as package:
        bundle = parse_bundle_manifest_v2(json.loads(package.read("bundle.json")))
    monkeypatch.setattr(
        scoped_installed_bundle_loader_v2,
        "OciPluginArtifactClient",
        lambda _client: FakeArtifactClient(archive),
    )
    contexts = []
    async with sessions() as db:
        user = User(
            id=str(uuid4()),
            email="scoped-marketplace@example.test",
            hashed_password="test",
            full_name="test",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        for tenant_label in ("a", "b"):
            tenant = Tenant(
                id=str(uuid4()), name=tenant_label, slug=f"scope-{tenant_label}", owner_id=user.id
            )
            db.add(tenant)
            await db.flush()
            db.add(UserTenant(id=str(uuid4()), user_id=user.id, tenant_id=tenant.id, role="admin"))
            for project_label in ("one", "two"):
                project = Project(
                    id=str(uuid4()), tenant_id=tenant.id, name=project_label, owner_id=user.id
                )
                db.add(project)
                await db.flush()
                db.add(
                    UserProject(
                        id=str(uuid4()), user_id=user.id, project_id=project.id, role="admin"
                    )
                )
                conversation = await ConversationManager(
                    SqlConversationRepository(db), SqlAgentExecutionRepository(db)
                ).create_conversation(project_id=project.id, tenant_id=tenant.id, user_id=user.id)
                contexts.append((tenant.id, project.id, conversation.id))
        await PlatformPluginDesiredBundleSetRepositoryV2(db).record_desired_set(
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
            desired_set=production_bundle_sources_v2().desired_set,
            expected_revision=None,
            actor_id=user.id,
        )
        await db.commit()
        _unused, host = await maintenance_scoped_runtime(db)
        await _unused.close()
        app = FastAPI()
        app.state.platform_plugin_runtime_v2 = host
        app.state.plugin_marketplace_trusted_public_keys_v2 = (key,)
        app.state.plugin_marketplace_allowed_registries_v2 = frozenset(
            {"https://registry.memstack.test"}
        )
        runtime = initialize_scoped_profile_runtime_v2(
            app, session_factory=sessions, redis_client=None
        )
        authority = SqlWasmOperationAuthorityV2(session_factory=sessions)
        lifecycles = [
            SignedMarketplaceScopeV2(db, runtime, tenant, project)
            for tenant, project, _ in contexts
        ]
        for lifecycle in lifecycles:
            await lifecycle.initialize(user.id)
        try:
            for index in (0, 2):
                lifecycle = lifecycles[index]
                request = _request(bundle, archive, key).model_copy(
                    update={
                        "tenant_id": lifecycle.scope.tenant_id,
                        "project_id": lifecycle.scope.project_id,
                    }
                )
                previous, old = await lifecycle.begin(bundle.bundle_id, bundle.version)
                decision = await PluginMarketplaceInstallService(
                    lifecycle.governance,
                    lifecycle.mutations,
                    FakeArtifactClient(archive),
                    trusted_public_keys=(key,),
                ).request_install(request=request, actor_id=user.id)
                assert decision.status == "approved", decision.reason
                result = await lifecycle.publish(
                    bundle.bundle_id, previous=previous, old=old, actor_id=user.id
                )
                assert result["status"] == "enabled"
            assert len(await signed_installations(db, *contexts[0][:2])) == 1
            assert await signed_installations(db, *contexts[1][:2]) == []

            async def call(index, expected):
                tenant, project, conversation = contexts[index]
                scope = ScopeV2(
                    kind=ScopeKindV2.SESSION,
                    tenant_id=tenant,
                    project_id=project,
                    session_id=conversation,
                )
                publication = await runtime.prepare_current(
                    scope, actor_id=user.id, required_services=AGENT_TURN_REQUIRED_SERVICES_V2
                )
                assert publication.publication.accepted
                reservation = await runtime.acquire(scope)
                async with pin_scoped_agent_turn_operation_v2(
                    reservation,
                    operation_id=str(uuid4()),
                    tenant_id=tenant,
                    project_id=project,
                    session_id=conversation,
                    services={
                        OPERATION_IDENTITY_SERVICE_V2: {
                            "tenant_id": tenant,
                            "project_id": project,
                            "user_id": user.id,
                        }
                    },
                ) as operation:
                    assert await prepare_wasm_operation_tools_v2(operation, authority) == int(
                        expected
                    )
                    if expected:
                        catalog = operation.require(TOOL_SET_CATALOG_SERVICE_V2)
                        source_id = f"wasm:{bundle.manifests[0].modules[0].module_ref}:{bundle.layers[0].entries[0].entry_id}"
                        (tool,) = dict(catalog.contributions())[source_id]().definitions
                        assert (
                            json.loads(await tool.execute(input="PostgreSQL scoped WASM"))["score"]
                            == 20260914
                        )

            for index in range(4):
                await call(index, index in (0, 2))
            await lifecycles[0].toggle(bundle.bundle_id, "disable", user.id)
            await call(0, False)
            await call(2, True)
            await lifecycles[0].toggle(bundle.bundle_id, "enable", user.id)
            await call(0, True)
            await runtime.close()
            app.state.scoped_profile_runtime_v2 = None
            runtime = initialize_scoped_profile_runtime_v2(
                app, session_factory=sessions, redis_client=None
            )
            for lifecycle in lifecycles:
                lifecycle.runtime = runtime
            await call(0, True)
            await call(2, True)
            await lifecycles[0].toggle(bundle.bundle_id, "uninstall", user.id)
            await call(0, False)
            await call(2, True)
            await lifecycles[2].toggle(bundle.bundle_id, "uninstall", user.id)
            await call(2, False)
            assert host.current_distribution.snapshot.generation == 1
        finally:
            await runtime.close()
            await host.close()
