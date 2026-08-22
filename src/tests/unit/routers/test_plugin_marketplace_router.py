"""Protocol-v2 marketplace router authority and publication tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import DataPlaneTargetV2, ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import plugin_marketplace
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginCatalogModel,
    PlatformPluginDesiredStateModel,
    PlatformPluginV2PublicationModel,
    Tenant,
    User,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import PRODUCTION_BASE_BUNDLE_ID_V2
from src.infrastructure.plugins.v2.protocol import (
    bundle_manifest_v2_to_payload,
    parse_profile_snapshot_v2,
)
from src.tests.unit.application.services.test_plugin_marketplace_install_service import (
    FakeArtifactClient,
    _public_key_pem,
    _request,
    _signed_bundle,
)

pytestmark = pytest.mark.unit


def _app(db: AsyncSession, current_user: User) -> FastAPI:
    app = FastAPI()
    app.include_router(plugin_marketplace.router)

    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://marketplace.test",
    )


async def _tenant_admin(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
) -> tuple[User, Tenant]:
    tenant = Tenant(
        id=tenant_id,
        name=f"Tenant {tenant_id}",
        slug=tenant_id,
        owner_id=user_id,
    )
    user = User(
        id=user_id,
        email=f"{user_id}@example.com",
        hashed_password="hashed",
        full_name=user_id,
        is_active=True,
    )
    db.add_all(
        [
            tenant,
            user,
            UserTenant(
                id=f"membership-{tenant_id}",
                user_id=user.id,
                tenant_id=tenant.id,
                role="admin",
            ),
        ]
    )
    await db.commit()
    return user, tenant


async def _seed_package(
    db: AsyncSession,
    *,
    signer: Ed25519PrivateKey,
) -> tuple[Any, bytes, str]:
    bundle, archive = _signed_bundle(signer)
    public_key = _public_key_pem(signer)
    signature = bundle.signature
    assert signature is not None
    _ = await PlatformPluginGovernanceRepository(db).upsert_package(
        plugin_id=bundle.bundle_id,
        version=bundle.version,
        publisher="memstack",
        artifact_digest=hashlib.sha256(archive).hexdigest(),
        artifact_registry="https://registry.memstack.test",
        artifact_repository="memstack/plugins/third-party-tools",
        oci_manifest_digest="1" * 64,
        manifest=bundle_manifest_v2_to_payload(bundle),
        signature={
            "algorithm": "Ed25519",
            "public_key_sha256": hashlib.sha256(public_key.encode("utf-8")).hexdigest(),
            "signature_sha256": hashlib.sha256(signature.encode("ascii")).hexdigest(),
        },
        provenance={"predicateType": "https://slsa.dev/provenance/v1"},
        security_scan_status="passed",
    )
    await db.commit()
    return bundle, archive, public_key


async def _legacy_row_counts(db: AsyncSession) -> tuple[int, int]:
    catalog = await db.scalar(select(func.count()).select_from(PlatformPluginCatalogModel))
    desired = await db.scalar(select(func.count()).select_from(PlatformPluginDesiredStateModel))
    return int(catalog or 0), int(desired or 0)


async def test_marketplace_list_and_detail_expose_only_v2_bundle_metadata(
    db_session: AsyncSession,
) -> None:
    bundle, _archive, _public_key = await _seed_package(
        db_session,
        signer=Ed25519PrivateKey.generate(),
    )
    user = User(
        id="marketplace-reader",
        email="reader@example.com",
        hashed_password="hashed",
        full_name="Reader",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    async with _client(_app(db_session, user)) as client:
        listing = await client.get("/api/v1/plugin-marketplace/packages")
        detail = await client.get(f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}")

    assert listing.status_code == status.HTTP_200_OK
    assert listing.json()[0]["plugin_id"] == bundle.bundle_id
    assert "public_key_pem" not in listing.json()[0]["signature"]
    assert detail.status_code == status.HTTP_200_OK
    assert detail.json()["versions"][0]["manifest"]["schema_version"] == 2
    assert await _legacy_row_counts(db_session) == (0, 0)


async def test_marketplace_approval_requires_tenant_admin_and_persists_scoped_grant(
    db_session: AsyncSession,
) -> None:
    bundle, _archive, _public_key = await _seed_package(
        db_session,
        signer=Ed25519PrivateKey.generate(),
    )
    user, tenant = await _tenant_admin(
        db_session,
        user_id="marketplace-admin",
        tenant_id="marketplace-tenant",
    )

    async with _client(_app(db_session, user)) as client:
        response = await client.post(
            f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/approve",
            json={
                "version": bundle.version,
                "tenant_id": tenant.id,
                "approved_permissions": ["tools.execute"],
            },
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["granted_permissions"] == ["tools.execute"]
    repository = PlatformPluginGovernanceRepository(db_session)
    assert [
        row.permission
        for row in await repository.list_permissions(bundle.bundle_id, scope_id=tenant.id)
    ] == ["tools.execute"]


async def test_marketplace_revocation_requires_superuser_and_never_writes_v1(
    db_session: AsyncSession,
) -> None:
    bundle, _archive, _public_key = await _seed_package(
        db_session,
        signer=Ed25519PrivateKey.generate(),
    )
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

    async with _client(_app(db_session, non_admin)) as client:
        forbidden = await client.post(
            f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/revoke",
            json={"reason": "publisher compromised"},
        )
    async with _client(_app(db_session, superuser)) as client:
        revoked = await client.post(
            f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/revoke",
            json={"reason": "publisher compromised"},
        )
        listing = await client.get(
            "/api/v1/plugin-marketplace/packages",
            params={"include_revoked": True},
        )

    assert forbidden.status_code == status.HTTP_403_FORBIDDEN
    assert revoked.status_code == status.HTTP_200_OK
    assert revoked.json()["revoked_versions"] == [bundle.version]
    assert listing.json()[0]["revoked"] is True
    assert await _legacy_row_counts(db_session) == (0, 0)


async def test_marketplace_install_with_empty_trust_store_fails_closed(
    db_session: AsyncSession,
) -> None:
    signer = Ed25519PrivateKey.generate()
    bundle, archive = _signed_bundle(signer)
    public_key = _public_key_pem(signer)
    user, tenant = await _tenant_admin(
        db_session,
        user_id="marketplace-empty-trust-admin",
        tenant_id="marketplace-empty-trust-tenant",
    )

    async with _client(_app(db_session, user)) as client:
        response = await client.post(
            f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/install",
            json=_request(bundle, archive, public_key)
            .model_copy(update={"tenant_id": tenant.id})
            .model_dump(mode="json"),
        )

    desired = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(
        ScopeV2(kind=ScopeKindV2.ROOT)
    )
    package = await PlatformPluginGovernanceRepository(db_session).get_package_version(
        bundle.bundle_id,
        bundle.version,
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json()["status"] == "quarantined"
    assert "trust store is empty" in response.json()["reason"]
    assert desired is None
    assert package is None
    assert await _legacy_row_counts(db_session) == (0, 0)


async def test_marketplace_v2_publication_is_idempotent_retains_last_good_and_uninstalls(  # noqa: PLR0915
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signer = Ed25519PrivateKey.generate()
    public_key = _public_key_pem(signer)
    bundle, archive = _signed_bundle(signer)
    artifact_client = FakeArtifactClient(archive)
    user, tenant = await _tenant_admin(
        db_session,
        user_id="marketplace-loop-admin",
        tenant_id="marketplace-loop-tenant",
    )
    app = _app(db_session, user)
    app.state.plugin_marketplace_trusted_public_keys_v2 = (public_key,)
    monkeypatch.setattr(
        plugin_marketplace,
        "OciPluginArtifactClient",
        lambda _client: artifact_client,
    )
    host = await initialize_plugin_runtime_v2(app)
    payload = (
        _request(bundle, archive, public_key)
        .model_copy(update={"tenant_id": tenant.id})
        .model_dump(mode="json")
    )

    try:
        async with _client(app) as client:
            installed = await client.post(
                f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/install",
                json=payload,
            )
            repeated = await client.post(
                f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/install",
                json=payload,
            )

            bad_bundle, bad_archive = _signed_bundle(
                signer,
                version="2.0.0",
                module_ref="marketplace://unknown/runtime-v2",
                target=DataPlaneTargetV2.PYTHON,
            )
            artifact_client.archive = bad_archive
            artifact_client.layer_digest = hashlib.sha256(bad_archive).hexdigest()
            bad_payload = (
                _request(bad_bundle, bad_archive, public_key)
                .model_copy(update={"tenant_id": tenant.id})
                .model_dump(mode="json")
            )
            nacked = await client.post(
                f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/install",
                json=bad_payload,
            )

            host_after_nack = host.current_distribution
            assert host_after_nack is not None
            assert host_after_nack.snapshot.generation == 2
            repository = PlatformPluginRepositoryV2(db_session)
            degraded = await repository.latest_publication_readiness()
            assert degraded is not None
            assert degraded.status.value == "degraded"
            last_good = await repository.last_good_distribution(PYTHON_API_DATA_PLANE_ID_V2)
            assert last_good is not None
            assert parse_profile_snapshot_v2(last_good["snapshot"]).generation == 2

            uninstalled = await client.post(
                f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/uninstall",
                json={"version": bad_bundle.version, "tenant_id": tenant.id},
            )

        desired = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(
            ScopeV2(kind=ScopeKindV2.ROOT)
        )
        readiness = await PlatformPluginRepositoryV2(db_session).latest_publication_readiness()
        publication_count = await db_session.scalar(
            select(func.count()).select_from(PlatformPluginV2PublicationModel)
        )
        current = host.current_distribution

        assert installed.status_code == status.HTTP_202_ACCEPTED
        assert installed.json()["status"] == "approved"
        assert repeated.status_code == status.HTTP_202_ACCEPTED
        assert repeated.json()["status"] == "approved"
        assert nacked.status_code == status.HTTP_202_ACCEPTED
        assert nacked.json()["status"] == "approved"
        assert uninstalled.status_code == status.HTTP_200_OK
        assert uninstalled.json()["desired_removed"] is True
        assert desired is not None
        assert desired.desired_set.revision == 4
        assert [reference.bundle_id for reference in desired.desired_set.bundles] == [
            PRODUCTION_BASE_BUNDLE_ID_V2
        ]
        assert readiness is not None
        assert readiness.status.value == "ready"
        assert publication_count == 3
        assert current is not None
        assert current.snapshot.generation == 4
        assert all(
            manifest.plugin_id != "third-party-tool" for manifest in current.snapshot.manifests
        )
        assert await _legacy_row_counts(db_session) == (0, 0)
    finally:
        await shutdown_plugin_runtime_v2(app)
