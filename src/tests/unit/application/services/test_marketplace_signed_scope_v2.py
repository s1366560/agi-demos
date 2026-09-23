"""Exact tenant/project signed lifecycle, grant isolation and failed publication rollback."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.installed_verified_bundle_loader_v2 import (
    InstalledVerifiedBundleLoaderV2,
)
from src.application.services.marketplace_signed_scope_v2 import (
    SignedMarketplaceScopeV2,
    signed_installations,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.tests.unit.application.services.test_plugin_marketplace_install_service import (
    FakeArtifactClient,
    _public_key_pem,
    _request,
    _signed_bundle,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def setup(db_session):
    production = production_bundle_sources_v2()
    repo = PlatformPluginDesiredBundleSetRepositoryV2(db_session)
    await repo.record_desired_set(
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        desired_set=production.desired_set,
        expected_revision=None,
        actor_id="setup",
    )
    await db_session.commit()
    runtime = SimpleNamespace(
        publish_current=AsyncMock(
            return_value=SimpleNamespace(
                publication=SimpleNamespace(
                    accepted=True,
                    envelope=SimpleNamespace(version=2),
                    snapshot=SimpleNamespace(
                        manifests=(SimpleNamespace(plugin_id="third-party-tool"),)
                    ),
                )
            )
        )
    )
    first = SignedMarketplaceScopeV2(db_session, runtime, "tenant-a", "project-a")
    other = SignedMarketplaceScopeV2(db_session, runtime, "tenant-b", "project-b")
    await first.initialize("admin")
    await other.initialize("admin")
    signer = Ed25519PrivateKey.generate()
    key = _public_key_pem(signer)
    bundle, archive = _signed_bundle(signer)
    request = _request(bundle, archive, key).model_copy(
        update={"tenant_id": "tenant-a", "project_id": "project-a"}
    )
    return first, other, runtime, request, key, archive


async def install(lifecycle, request, key, archive):
    previous, old = await lifecycle.begin(request.plugin_id, request.version)
    service = PluginMarketplaceInstallService(
        lifecycle.governance,
        lifecycle.mutations,
        FakeArtifactClient(archive),
        trusted_public_keys=(key,),
    )
    decision = await service.request_install(request=request, actor_id="admin")
    assert decision.status == "approved", decision.reason
    return await lifecycle.publish(request.plugin_id, previous=previous, old=old, actor_id="admin")


async def test_signed_install_disable_enable_uninstall_is_scope_isolated(setup, db_session):
    first, other, runtime, request, key, archive = setup
    result = await install(first, request, key, archive)
    assert result["status"] == "enabled" and result["install_strategy"] == "signed-v2"
    assert await signed_installations(db_session, "tenant-b", "project-b") == []
    assert len((await other.desired.current_desired_set(other.scope)).desired_set.bundles) == 1
    grants = await first.governance.list_permissions(
        request.plugin_id, scope_type="project", scope_id="project-a"
    )
    assert [grant.permission for grant in grants] == ["tools.execute"]
    other_request = request.model_copy(update={"tenant_id": "tenant-b", "project_id": "project-b"})
    await install(other, other_request, key, archive)
    disabled = await first.toggle(request.plugin_id, "disable", "admin")
    assert disabled["status"] == "disabled"
    assert len((await other.desired.current_desired_set(other.scope)).desired_set.bundles) == 2
    assert (await first.toggle(request.plugin_id, "enable", "admin"))["status"] == "enabled"
    assert (await first.toggle(request.plugin_id, "uninstall", "admin"))["status"] == "uninstalled"
    assert (
        await first.governance.list_permissions(
            request.plugin_id, scope_type="project", scope_id="project-a"
        )
        == []
    )
    assert await other.governance.list_permissions(
        request.plugin_id, scope_type="project", scope_id="project-b"
    )
    assert (
        await first.governance.get_package_version(request.plugin_id, request.version)
    ).install_status == "installed"
    assert all(
        call.args[0].kind is ScopeKindV2.PROJECT for call in runtime.publish_current.call_args_list
    )


async def test_failed_update_preserves_previous_desired_and_enabled_record(setup):
    first, _other, runtime, request, key, archive = setup
    initial = await install(first, request, key, archive)
    before = await first.desired.current_desired_set(first.scope)
    previous, old = await first.begin(request.plugin_id, "2.0.0")
    reference = replace(before.desired_set.bundles[-1], version="2.0.0")
    await first.mutations.install(scope=first.scope, bundle=reference, actor_id="admin")
    runtime.publish_current.side_effect = ValueError("candidate fails")
    with pytest.raises(ValueError, match="candidate fails"):
        await first.publish(request.plugin_id, previous=previous, old=old, actor_id="admin")
    current = await first.desired.current_desired_set(first.scope)
    assert current.desired_set.bundles == before.desired_set.bundles
    row = await first.record(request.plugin_id)
    assert row.payload["version"] == initial["version"] and row.payload["status"] == "enabled"


async def test_scoped_loader_cannot_borrow_other_tenant_grants(setup):
    first, other, _runtime, request, key, archive = setup
    await install(first, request, key, archive)
    reference = (await first.desired.current_desired_set(first.scope)).desired_set.bundles[-1]
    loader = InstalledVerifiedBundleLoaderV2(
        governance_repository=first.governance,
        artifact_client=FakeArtifactClient(archive),
        production_sources=production_bundle_sources_v2(),
        trusted_public_keys=(key,),
        scope=other.scope,
    )
    with pytest.raises(ValueError):
        await loader.load(reference)
    allowed = InstalledVerifiedBundleLoaderV2(
        governance_repository=first.governance,
        artifact_client=FakeArtifactClient(archive),
        production_sources=production_bundle_sources_v2(),
        trusted_public_keys=(key,),
        scope=first.scope,
    )
    assert (await allowed.load(reference)).manifest.bundle_id == request.plugin_id


async def test_signed_job_replay_and_conflicting_request(setup, db_session):
    first, _other, _runtime, request, key, archive = setup
    await install(first, request, key, archive)
    data = {"idempotency_key": "disable-once"}
    result = await first.mutate(request.plugin_id, "disable", "admin", data)
    assert result == await first.mutate(request.plugin_id, "disable", "admin", data)
    with pytest.raises(ValueError, match="different request"):
        await first.mutate(request.plugin_id, "enable", "admin", data)
    async with async_sessionmaker(db_session.bind, expire_on_commit=False)() as fresh:
        records = await signed_installations(fresh, "tenant-a", "project-a")
        assert records[0]["status"] == "disabled"


async def test_actual_signed_python_service_drains_disappears_and_recovers(  # noqa: PLR0915
    setup, db_session, monkeypatch
):
    import json
    import zipfile
    from pathlib import Path

    from fastapi import FastAPI

    from src.application.services import scoped_installed_bundle_loader_v2
    from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
        initialize_plugin_runtime_v2,
        shutdown_plugin_runtime_v2,
    )
    from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
        initialize_scoped_profile_runtime_v2,
    )
    from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
    from src.infrastructure.plugins.v2.protocol import parse_bundle_manifest_v2
    from src.infrastructure.plugins.v2.tool_set import TOOL_SET_CATALOG_SERVICE_V2
    from src.infrastructure.plugins.v2.wasm_tool_runtime import prepare_wasm_operation_tools_v2

    fixture = Path("src/tests/unit/infrastructure/plugins/v2/fixtures/signed_wasm_marker")
    archive_bytes = (fixture / "marker.mspkg").read_bytes()
    key = (fixture / "signer-public.pem").read_text()
    with zipfile.ZipFile(fixture / "marker.mspkg") as archive:
        bundle = parse_bundle_manifest_v2(json.loads(archive.read("bundle.json")))
    client = FakeArtifactClient(archive_bytes)
    app = FastAPI()
    app.state.plugin_marketplace_trusted_public_keys_v2 = (key,)
    app.state.plugin_marketplace_allowed_registries_v2 = frozenset(
        {"https://registry.memstack.test"}
    )
    monkeypatch.setattr(
        scoped_installed_bundle_loader_v2, "OciPluginArtifactClient", lambda _client: client
    )
    host = await initialize_plugin_runtime_v2(app)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    runtime = initialize_scoped_profile_runtime_v2(app, session_factory=factory, redis_client=None)
    lifecycle = SignedMarketplaceScopeV2(db_session, runtime, "tenant-a", "project-a")
    request = _request(bundle, archive_bytes, key).model_copy(
        update={"tenant_id": "tenant-a", "project_id": "project-a"}
    )
    session_scope = ScopeV2(
        kind=ScopeKindV2.SESSION, tenant_id="tenant-a", project_id="project-a", session_id="test"
    )
    authority = SimpleNamespace(authorize=AsyncMock(return_value=True))
    try:
        result = await install(lifecycle, request, key, archive_bytes)
        assert result["status"] == "enabled"
        reserved = await runtime.acquire(lifecycle.scope)
        async with pin_operation_context_v2(
            reserved.host, scope=session_scope, operation_id="signed-use"
        ) as operation:
            assert await prepare_wasm_operation_tools_v2(operation, authority) == 1
            catalog = operation.require(TOOL_SET_CATALOG_SERVICE_V2)
            source_id = f"wasm:{bundle.manifests[0].modules[0].module_ref}:{bundle.layers[0].entries[0].entry_id}"
            contribution = dict(catalog.contributions())[source_id]
            (tool,) = contribution().definitions
            assert json.loads(await tool.execute(input="hello"))["score"] == 20260914
            await lifecycle.toggle(bundle.bundle_id, "disable", "admin")
            assert json.loads(await tool.execute(input="in-flight"))["score"] == 20260914
        await reserved.lease.release()
        newer = await runtime.acquire(lifecycle.scope)
        async with pin_operation_context_v2(
            newer.host, scope=session_scope, operation_id="disabled"
        ) as operation:
            assert await prepare_wasm_operation_tools_v2(operation, authority) == 0
        await newer.lease.release()
        await lifecycle.toggle(bundle.bundle_id, "enable", "admin")
        await runtime.close()
        app.state.scoped_profile_runtime_v2 = None
        runtime = initialize_scoped_profile_runtime_v2(
            app, session_factory=factory, redis_client=None
        )
        restored = await runtime.acquire(lifecycle.scope)
        async with pin_operation_context_v2(
            restored.host, scope=session_scope, operation_id="restart"
        ) as operation:
            assert await prepare_wasm_operation_tools_v2(operation, authority) == 1
            catalog = operation.require(TOOL_SET_CATALOG_SERVICE_V2)
            source_id = f"wasm:{bundle.manifests[0].modules[0].module_ref}:{bundle.layers[0].entries[0].entry_id}"
            contribution = dict(catalog.contributions())[source_id]
            (tool,) = contribution().definitions
            assert json.loads(await tool.execute(input="restart"))["score"] == 20260914
        await restored.lease.release()
        lifecycle.runtime = runtime
        await lifecycle.toggle(bundle.bundle_id, "uninstall", "admin")
        final = await runtime.acquire(lifecycle.scope)
        async with pin_operation_context_v2(
            final.host, scope=session_scope, operation_id="uninstalled"
        ) as operation:
            assert await prepare_wasm_operation_tools_v2(operation, authority) == 0
        await final.lease.release()
        assert host.current_distribution.snapshot.generation == 1
    finally:
        await runtime.close()
        await shutdown_plugin_runtime_v2(app)
