"""Unit tests for marketplace catalog governance endpoints."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.plugin_marketplace_install_service import (
    MarketplaceInstallDecision,
)
from src.domain.model.plugins import parse_plugin_manifest
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import plugin_marketplace
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginApplyStateModel,
    Tenant,
    User,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.plugins.llm_adapters import LlmAdapterProviderRegistry
from src.infrastructure.plugins.runtime_host import (
    PlatformPluginRuntimeHost,
    set_platform_plugin_runtime_host,
)

MANIFEST = {
    "schemaVersion": 1,
    "id": "third-party-tool",
    "version": "1.0.0",
    "runtime": "wasm",
    "trust": "signed",
    "provides": [{"kind": "tool", "id": "demo", "permissions": ["tools.execute"]}],
}


async def seed_package(db: AsyncSession) -> None:
    repository = PlatformPluginGovernanceRepository(db)
    await repository.upsert_package(
        plugin_id="third-party-tool",
        version="1.0.0",
        publisher="memstack",
        artifact_digest="a" * 64,
        manifest=MANIFEST,
        signature={"algorithm": "Ed25519", "public_key_sha256": "b" * 64},
        provenance={"predicateType": "https://slsa.dev/provenance/v1"},
        security_scan_status="passed",
    )
    await db.commit()


def make_client(
    db: AsyncSession,
    current_user: User,
) -> TestClient:
    app = FastAPI()
    app.include_router(plugin_marketplace.router)

    async def override_db() -> AsyncSession:
        return db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_runtime_host() -> Any:
    """Give every marketplace mutation an isolated local data plane."""
    host = PlatformPluginRuntimeHost(adapter_registry=LlmAdapterProviderRegistry())
    set_platform_plugin_runtime_host(host)
    try:
        yield host
    finally:
        set_platform_plugin_runtime_host(None)


@pytest.mark.unit
async def test_marketplace_list_and_detail_hide_revoked_by_default(
    db_session: AsyncSession,
) -> None:
    await seed_package(db_session)
    user = User(
        id="marketplace-reader",
        email="reader@example.com",
        hashed_password="hashed",
        full_name="Reader",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    client = make_client(db_session, user)

    listing = client.get("/api/v1/plugin-marketplace/packages")
    detail = client.get("/api/v1/plugin-marketplace/packages/third-party-tool")

    assert listing.status_code == status.HTTP_200_OK
    assert listing.json()[0]["plugin_id"] == "third-party-tool"
    assert "public_key_pem" not in listing.json()[0]["signature"]
    assert detail.status_code == status.HTTP_200_OK
    assert detail.json()["versions"][0]["manifest"] == MANIFEST


@pytest.mark.unit
async def test_marketplace_approval_requires_tenant_admin_and_persists_grant(
    db_session: AsyncSession,
) -> None:
    await seed_package(db_session)
    tenant = Tenant(
        id="marketplace-tenant",
        name="Marketplace Tenant",
        slug="marketplace-tenant",
        owner_id="marketplace-admin",
    )
    user = User(
        id="marketplace-admin",
        email="admin@example.com",
        hashed_password="hashed",
        full_name="Admin",
        is_active=True,
    )
    db_session.add_all(
        [
            tenant,
            user,
            UserTenant(
                id="marketplace-membership",
                user_id=user.id,
                tenant_id=tenant.id,
                role="admin",
            ),
        ]
    )
    await db_session.commit()
    client = make_client(db_session, user)

    response = client.post(
        "/api/v1/plugin-marketplace/packages/third-party-tool/approve",
        json={
            "version": "1.0.0",
            "tenant_id": tenant.id,
            "approved_permissions": ["tools.execute"],
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["granted_permissions"] == ["tools.execute"]
    repository = PlatformPluginGovernanceRepository(db_session)
    assert [
        row.permission
        for row in await repository.list_permissions(
            "third-party-tool",
            scope_id=tenant.id,
        )
    ] == ["tools.execute"]


@pytest.mark.unit
async def test_marketplace_revocation_requires_superuser_and_fails_closed(
    db_session: AsyncSession,
) -> None:
    await seed_package(db_session)
    non_admin = User(
        id="marketplace-member",
        email="member@example.com",
        hashed_password="hashed",
        full_name="Member",
        is_active=True,
    )
    superuser = User(
        id="marketplace-superuser",
        email="superuser@example.com",
        hashed_password="hashed",
        full_name="Superuser",
        is_active=True,
        is_superuser=True,
    )
    db_session.add_all([non_admin, superuser])
    await db_session.commit()

    forbidden = make_client(db_session, non_admin).post(
        "/api/v1/plugin-marketplace/packages/third-party-tool/revoke",
        json={"reason": "publisher compromised"},
    )
    revoked = make_client(db_session, superuser).post(
        "/api/v1/plugin-marketplace/packages/third-party-tool/revoke",
        json={"reason": "publisher compromised"},
    )
    listing = make_client(db_session, superuser).get(
        "/api/v1/plugin-marketplace/packages",
        params={"include_revoked": True},
    )

    assert forbidden.status_code == status.HTTP_403_FORBIDDEN
    assert revoked.status_code == status.HTTP_200_OK
    assert revoked.json()["revoked_versions"] == ["1.0.0"]
    assert listing.json()[0]["revoked"] is True


@pytest.mark.unit
async def test_marketplace_uninstall_removes_desired_state(
    db_session: AsyncSession,
) -> None:
    await seed_package(db_session)
    tenant = Tenant(
        id="marketplace-uninstall-tenant",
        name="Uninstall Tenant",
        slug="marketplace-uninstall-tenant",
        owner_id="marketplace-uninstaller",
    )
    user = User(
        id="marketplace-uninstaller",
        email="uninstaller@example.com",
        hashed_password="hashed",
        full_name="Uninstaller",
        is_active=True,
    )
    db_session.add_all(
        [
            tenant,
            user,
            UserTenant(
                id="marketplace-uninstall-membership",
                user_id=user.id,
                tenant_id=tenant.id,
                role="admin",
            ),
        ]
    )
    await PlatformPluginRepository(db_session).set_desired_state(
        plugin_id="third-party-tool",
        enabled=True,
        config={},
    )
    await db_session.commit()
    await db_session.commit()

    response = make_client(db_session, user).post(
        "/api/v1/plugin-marketplace/packages/third-party-tool/uninstall",
        json={"version": "1.0.0", "tenant_id": tenant.id},
    )
    desired = await PlatformPluginRepository(db_session).get_desired_state("third-party-tool")
    package = await PlatformPluginGovernanceRepository(db_session).get_package_version(
        "third-party-tool",
        "1.0.0",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "plugin_id": "third-party-tool",
        "version": "1.0.0",
        "status": "uninstalled",
        "desired_removed": True,
        "revoked_permissions": 0,
    }
    assert desired is None
    assert package is not None
    assert package.install_status == "uninstalled"


class _ApprovedInstallService:
    """Fake install service persisting the same rows as an approved install."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def request_install(self, *, request: Any) -> MarketplaceInstallDecision:
        governance = PlatformPluginGovernanceRepository(self._db)
        plugins = PlatformPluginRepository(self._db)
        await governance.upsert_package(
            plugin_id=request.plugin_id,
            version=request.version,
            publisher=request.publisher,
            artifact_digest=request.artifact_sha256,
            manifest=request.manifest,
            signature={"algorithm": "Ed25519", "public_key_sha256": "b" * 64},
            provenance={"predicateType": request.provenance.predicate_type},
            security_scan_status="passed",
        )
        await plugins.upsert_catalog_manifest(parse_plugin_manifest(request.manifest))
        await plugins.set_desired_state(
            plugin_id=request.plugin_id,
            enabled=True,
            config={},
        )
        return MarketplaceInstallDecision(
            status="approved",
            plugin_id=request.plugin_id,
            version=request.version,
            reason="verified",
            desired_revision=1,
        )


def _install_payload(tenant_id: str) -> dict[str, Any]:
    return {
        "plugin_id": "third-party-tool",
        "version": "1.0.0",
        "publisher": "memstack",
        "tenant_id": tenant_id,
        "artifact": {
            "registry": "https://registry.example.test",
            "repository": "memstack/third-party-tool",
            "manifest_sha256": "c" * 64,
        },
        "artifact_sha256": "a" * 64,
        "manifest": MANIFEST,
        "signature": {
            "algorithm": "Ed25519",
            "public_key_pem": "pem",
            "signature_base64": "c2ln",
        },
        "provenance": {
            "predicate_type": "https://slsa.dev/provenance/v1",
            "builder_id": "test-builder",
            "subject_name": "third-party-tool",
        },
        "approved_permissions": ["tools.execute"],
        "tenant_admin_approved": True,
        "security_scan_passed": True,
    }


@pytest.mark.unit
async def test_install_and_uninstall_close_the_snapshot_distribution_loop(
    db_session: AsyncSession,
    isolated_runtime_host: PlatformPluginRuntimeHost,
) -> None:
    tenant = Tenant(
        id="marketplace-loop-tenant",
        name="Loop Tenant",
        slug="marketplace-loop-tenant",
        owner_id="marketplace-loop-admin",
    )
    user = User(
        id="marketplace-loop-admin",
        email="loop-admin@example.com",
        hashed_password="hashed",
        full_name="Loop Admin",
        is_active=True,
    )
    db_session.add_all(
        [
            tenant,
            user,
            UserTenant(
                id="marketplace-loop-membership",
                user_id=user.id,
                tenant_id=tenant.id,
                role="admin",
            ),
        ]
    )
    await db_session.commit()
    client = make_client(db_session, user)

    async def override_service() -> Any:
        yield _ApprovedInstallService(db_session)

    client.app.dependency_overrides[plugin_marketplace._service] = override_service

    installed = client.post(
        "/api/v1/plugin-marketplace/packages/third-party-tool/install",
        json=_install_payload(tenant.id),
    )

    assert installed.status_code == status.HTTP_202_ACCEPTED
    assert installed.json()["status"] == "approved"

    plugins = PlatformPluginRepository(db_session)
    first_snapshot = await plugins.latest_snapshot()
    assert first_snapshot is not None
    assert first_snapshot.version == 1
    installed_ids = [row["id"] for row in first_snapshot.payload["plugins"]]
    assert "third-party-tool" in installed_ids
    assert isolated_runtime_host.capabilities.list_capabilities("third-party-tool")

    apply_state = await db_session.execute(
        select(PlatformPluginApplyStateModel).where(
            PlatformPluginApplyStateModel.data_plane_id == "python-backend"
        )
    )
    assert apply_state.scalar_one().status == "ack"

    uninstalled = client.post(
        "/api/v1/plugin-marketplace/packages/third-party-tool/uninstall",
        json={"version": "1.0.0", "tenant_id": tenant.id},
    )

    assert uninstalled.status_code == status.HTTP_200_OK
    second_snapshot = await plugins.latest_snapshot()
    assert second_snapshot is not None
    assert second_snapshot.version == 2
    remaining_ids = [row["id"] for row in second_snapshot.payload["plugins"]]
    assert "third-party-tool" not in remaining_ids
    assert isolated_runtime_host.capabilities.list_capabilities("third-party-tool") == ()
