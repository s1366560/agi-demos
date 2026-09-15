"""Fresh SQL governance controls real signed, leased Wasmtime tools."""

from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.agent.conversation_manager import ConversationManager
from src.application.services.wasm_operation_authority_v2 import SqlWasmOperationAuthorityV2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAgentExecutionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.protocol import (
    build_profile_snapshot_v2,
    bundle_manifest_v2_to_payload,
    control_envelope_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.wasm_tool_runtime import prepare_wasm_operation_tools_v2
from src.tests.unit.infrastructure.plugins.v2.test_wasm_tool_runtime import (  # noqa: F401
    resolve,
    staged,
)


@pytest.fixture
async def setup_authority(test_engine, test_db, test_project_db, test_user, staged, verified):  # noqa: F811
    manager, catalog = staged
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    conversations = ConversationManager(
        SqlConversationRepository(test_db), SqlAgentExecutionRepository(test_db)
    )
    conversation = await conversations.create_conversation(
        project_id=test_project_db.id, tenant_id=test_project_db.tenant_id, user_id=test_user.id
    )
    governance = PlatformPluginGovernanceRepository(test_db)
    await governance.upsert_package(
        plugin_id=verified.manifest.bundle_id,
        version=verified.manifest.version,
        publisher="fixture",
        artifact_digest="a" * 64,
        manifest=bundle_manifest_v2_to_payload(verified.manifest),
        signature={},
        provenance={},
        security_scan_status="passed",
    )
    await governance.grant_permission(
        plugin_id=verified.manifest.bundle_id,
        permission="tools.execute",
        scope_id=test_project_db.tenant_id,
    )
    async with await manager.acquire() as generation:
        snapshot = generation.snapshot
    await PlatformPluginRepositoryV2(test_db).record_requested_distribution(
        snapshot, control_envelope_v2(snapshot, version=1, nonce="wasm-authority-1")
    )
    await test_db.commit()
    scope = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        session_id=conversation.id,
    )
    identity = {
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "user_id": test_user.id,
    }
    return (
        manager,
        catalog,
        SqlWasmOperationAuthorityV2(session_factory=sessions),
        scope,
        identity,
        governance,
        snapshot,
    )


async def test_real_sql_grant_and_fresh_revocation_on_retained_wasm_callable(
    setup_authority, test_db, verified
):
    manager, catalog, authority, scope, identity, governance, _ = setup_authority
    async with pin_operation_context_v2(
        manager,
        operation_id="sql-authority",
        scope=scope,
        services={OPERATION_IDENTITY_SERVICE_V2: identity},
    ) as operation:
        assert await prepare_wasm_operation_tools_v2(operation, authority) == 1
        (definition,) = resolve(catalog).definitions
        assert "20260914" in await definition.execute(input="SQL grant")
        await governance.revoke_permissions(verified.manifest.bundle_id)
        await test_db.commit()
        with pytest.raises(RuntimeV2Error, match="permission"):
            await definition.execute(input="revoked")


@pytest.mark.parametrize("field", ["tenant_id", "project_id", "user_id"])
async def test_wrong_operation_identity_hides_tools(setup_authority, field):
    manager, catalog, authority, scope, identity, _, _ = setup_authority
    async with pin_operation_context_v2(
        manager,
        operation_id="wrong",
        scope=scope,
        services={OPERATION_IDENTITY_SERVICE_V2: identity | {field: "other"}},
    ) as operation:
        assert await prepare_wasm_operation_tools_v2(operation, authority) == 0
        assert not resolve(catalog).definitions


async def test_unrelated_generation_change_allowed_but_disabled_entry_denies_old_lease(
    setup_authority, test_db, verified
):
    manager, catalog, authority, scope, identity, _, snapshot = setup_authority
    async with pin_operation_context_v2(
        manager,
        operation_id="publication",
        scope=scope,
        services={OPERATION_IDENTITY_SERVICE_V2: identity},
    ) as operation:
        await prepare_wasm_operation_tools_v2(operation, authority)
        (definition,) = resolve(catalog).definitions
        for version, enabled in [(2, True), (3, False)]:
            entries = tuple(
                replace(entry, enabled=enabled)
                if entry.plugin_ref == verified.manifest.manifests[0].plugin_id
                else entry
                for entry in snapshot.entries
            )
            latest = build_profile_snapshot_v2(
                profile_id=snapshot.profile_id,
                generation=version,
                manifests=snapshot.manifests,
                entries=entries,
            )
            await PlatformPluginRepositoryV2(test_db).record_requested_distribution(
                latest,
                control_envelope_v2(latest, version=version, nonce=f"wasm-authority-{version}"),
            )
            await test_db.commit()
            if enabled:
                assert "20260914" in await definition.execute(input="unrelated publication")
            else:
                with pytest.raises(RuntimeV2Error, match="permission"):
                    await definition.execute(input="disabled")


@pytest.fixture
def verified():
    from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
    from src.tests.unit.infrastructure.plugins.v2.test_external_wasm_admission import FIXTURE

    return parse_bundle_archive_v2(
        (FIXTURE / "marker.mspkg").read_bytes(),
        source="marketplace://qa-marketplace-marker-bundle/1.0.0",
        trusted_public_keys=((FIXTURE / "signer-public.pem").read_text(),),
        approved_permissions=frozenset({"tools.execute"}),
        require_signature=True,
        require_provenance=True,
    )


@pytest.mark.parametrize("action", ["revoke", "uninstall", "other_tenant_grant"])
async def test_package_and_exact_tenant_grant_changes_deny_cached_callable(
    setup_authority, test_db, verified, action
):
    manager, catalog, authority, scope, identity, governance, _ = setup_authority
    async with pin_operation_context_v2(
        manager,
        operation_id="package-state",
        scope=scope,
        services={OPERATION_IDENTITY_SERVICE_V2: identity},
    ) as operation:
        await prepare_wasm_operation_tools_v2(operation, authority)
        (definition,) = resolve(catalog).definitions
        package_id, version = verified.manifest.bundle_id, verified.manifest.version
        if action == "revoke":
            await governance.revoke_package(package_id, version, "test")
        elif action == "uninstall":
            await governance.uninstall_package(package_id, version)
        else:
            await governance.revoke_permissions(package_id)
            await governance.grant_permission(
                plugin_id=package_id, permission="tools.execute", scope_id="other-tenant"
            )
        await test_db.commit()
        with pytest.raises(RuntimeV2Error, match="permission"):
            await definition.execute(input="stale lease")


async def test_production_preparation_uses_real_sql_authority_and_signed_runtime(
    setup_authority, test_engine, monkeypatch
):
    from src.application.services.wasm_operation_authority_v2 import prepare_agent_wasm_tools_v2
    from src.infrastructure.adapters.secondary.persistence import database

    monkeypatch.setattr(
        database, "async_session_factory", async_sessionmaker(test_engine, expire_on_commit=False)
    )
    manager, catalog, _, scope, identity, _, _ = setup_authority
    async with pin_operation_context_v2(
        manager,
        operation_id="production-preparation",
        scope=scope,
        services={OPERATION_IDENTITY_SERVICE_V2: identity},
    ) as operation:
        assert await prepare_agent_wasm_tools_v2(operation) == 1
        (definition,) = resolve(catalog).definitions
        assert "20260914" in await definition.execute(input="production SQL adapter")
