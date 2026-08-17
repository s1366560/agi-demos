from datetime import timedelta

import pytest

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginBackendSelectionModel,
    PlatformPluginHttpRouteModel,
    PlatformPluginPackageModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
    utc_now,
)


@pytest.mark.unit
async def test_permission_credential_and_backend_desired_state_roundtrip(db_session):
    repository = PlatformPluginGovernanceRepository(db_session)

    permission = await repository.grant_permission(
        plugin_id="third-party-tool",
        permission="tools.execute",
        scope_id="tenant-1",
        granted_by="admin-1",
    )
    await repository.grant_permission(
        plugin_id="third-party-tool",
        permission="tools.execute",
        scope_id="tenant-1",
        granted_by="admin-2",
    )
    grant = await repository.grant_credential(
        plugin_id="third-party-tool",
        credential_ref="vault://plugins/third-party/token",
        permission="llm.invoke",
        expires_at=utc_now() + timedelta(minutes=5),
    )
    selection = await repository.set_backend_selection(
        capability_kind="retrieval_backend",
        plugin_id="pgvector-provider",
        capability_id="pgvector",
        scope_id="tenant-1",
    )
    selection = await repository.set_backend_selection(
        capability_kind="retrieval_backend",
        plugin_id="weknora-provider",
        capability_id="weknora",
        scope_id="tenant-1",
    )

    assert permission.revoked_at is None
    assert permission.granted_by == "admin-2"
    assert grant.credential_ref.startswith("vault://")
    assert isinstance(selection, PlatformPluginBackendSelectionModel)
    assert selection.revision == 2
    assert selection.plugin_id == "weknora-provider"
    assert len(await repository.list_permissions("third-party-tool", scope_id="tenant-1")) == 1


@pytest.mark.unit
async def test_http_route_quota_and_package_governance_roundtrip(db_session):
    repository = PlatformPluginGovernanceRepository(db_session)

    route = await repository.upsert_http_route(
        plugin_id="example-plugin",
        method="get",
        path="/api/v1/plugins/example/hello",
        permission="plugin.example.read",
        authorization_mode="tenant_member",
    )
    route = await repository.upsert_http_route(
        plugin_id="example-plugin",
        method="GET",
        path="/api/v1/plugins/example/hello",
        permission="plugin.example.read",
        authorization_mode="tenant_member",
        enabled=False,
    )
    await repository.acquire_quota("example-plugin", output_bytes=128)
    await repository.release_quota("example-plugin")
    package = await repository.upsert_package(
        plugin_id="example-plugin",
        version="1.0.0",
        publisher="memstack",
        artifact_digest="a" * 64,
        signature={"algorithm": "Ed25519"},
        provenance={"predicateType": "https://slsa.dev/provenance/v1"},
        security_scan_status="passed",
    )
    package = await repository.revoke_package(
        "example-plugin",
        "1.0.0",
        "publisher compromised",
    )

    assert isinstance(route, PlatformPluginHttpRouteModel)
    assert route.revision == 2
    assert not route.enabled
    assert isinstance(package, PlatformPluginPackageModel)
    assert package.revoked
    assert package.revocation_reason == "publisher compromised"
