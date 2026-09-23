"""Protocol-v2 marketplace router authority and publication tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
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
    PlatformPluginPackageModel,
    PlatformPluginPermissionModel,
    PlatformPluginV2DesiredBundleSetModel,
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
from src.infrastructure.plugins.v2.production_bundle import PRODUCTION_BASE_BUNDLE_ID_V2
from src.infrastructure.plugins.v2.protocol import (
    bundle_manifest_v2_to_payload,
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


async def _prepare_scoped(app, db, artifact_client, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.application.services import scoped_installed_bundle_loader_v2
    from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
        initialize_scoped_profile_runtime_v2,
    )
    from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

    await PlatformPluginDesiredBundleSetRepositoryV2(db).record_desired_set(
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        desired_set=production_bundle_sources_v2().desired_set,
        expected_revision=None,
        actor_id="fixture",
    )
    await db.commit()
    app.state.plugin_marketplace_allowed_registries_v2 = frozenset(
        {"https://registry.memstack.test"}
    )
    monkeypatch.setattr(
        scoped_installed_bundle_loader_v2, "OciPluginArtifactClient", lambda client: artifact_client
    )
    return initialize_scoped_profile_runtime_v2(
        app, session_factory=async_sessionmaker(db.bind, expire_on_commit=False), redis_client=None
    )


async def _seed_package(
    db: AsyncSession,
    *,
    signer: Ed25519PrivateKey,
) -> tuple[Any, bytes, str]:
    bundle, archive = _signed_bundle(signer)
    public_key = _public_key_pem(signer)
    signature = bundle.signature
    assert signature is not None
    # Fingerprint convention must match the install service: sha256 over the
    # raw Ed25519 public-key bytes, not over the PEM text.
    raw_public_key = signer.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
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
            "public_key_sha256": hashlib.sha256(raw_public_key).hexdigest(),
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
    user.is_superuser = True
    await db_session.commit()

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
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert desired is None
    assert package is None
    assert await _legacy_row_counts(db_session) == (0, 0)


async def test_marketplace_install_without_signature_material_resolves_from_catalog(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desktop/web installs omit PEM secrets the catalog redacts by contract."""
    signer = Ed25519PrivateKey.generate()
    bundle, archive = _signed_bundle(signer)
    public_key = _public_key_pem(signer)
    _ = await _seed_package(db_session, signer=signer)
    user, tenant = await _tenant_admin(
        db_session,
        user_id="marketplace-resolve-admin",
        tenant_id="marketplace-resolve-tenant",
    )
    user.is_superuser = True
    await db_session.commit()

    request_body = (
        _request(bundle, archive, public_key)
        .model_copy(update={"tenant_id": tenant.id, "signature": None, "provenance": None})
        .model_dump(mode="json", exclude={"signature", "provenance"})
    )
    app = _app(db_session, user)
    app.state.plugin_marketplace_trusted_public_keys_v2 = (public_key,)
    monkeypatch.setattr(
        plugin_marketplace,
        "OciPluginArtifactClient",
        lambda _client: FakeArtifactClient(archive),
    )
    host = await initialize_plugin_runtime_v2(app)
    scoped = await _prepare_scoped(app, db_session, FakeArtifactClient(archive), monkeypatch)

    try:
        async with _client(app) as client:
            response = await client.post(
                f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/install",
                json=request_body,
            )
    finally:
        await scoped.close()
        await shutdown_plugin_runtime_v2(app)
    _ = host

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json()["status"] == "approved", response.json()["reason"]
    assert response.json()["reason"] == "protocol v2 Bundle verified and desired"
    package = await PlatformPluginGovernanceRepository(db_session).get_package_version(
        bundle.bundle_id,
        bundle.version,
    )
    assert package is not None
    assert package.install_status == "installed"
    desired = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant.id)
    )
    assert desired is not None
    assert any(
        bundle_ref.bundle_id == bundle.bundle_id for bundle_ref in desired.desired_set.bundles
    )


async def test_marketplace_v2_publication_is_idempotent_retains_last_good_and_uninstalls(
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
    user.is_superuser = True
    await db_session.commit()
    app = _app(db_session, user)
    app.state.plugin_marketplace_trusted_public_keys_v2 = (public_key,)
    monkeypatch.setattr(
        plugin_marketplace,
        "OciPluginArtifactClient",
        lambda _client: artifact_client,
    )
    host = await initialize_plugin_runtime_v2(app)
    scoped = await _prepare_scoped(app, db_session, artifact_client, monkeypatch)
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

            # Failed scoped candidate never publishes into the ROOT host.
            assert host.current_distribution.snapshot.generation == 1
            artifact_client.archive = archive
            artifact_client.layer_digest = hashlib.sha256(archive).hexdigest()

            uninstalled = await client.post(
                f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/uninstall",
                json={"version": bundle.version, "tenant_id": tenant.id},
            )

        desired = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(
            ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant.id)
        )
        assert installed.status_code == status.HTTP_202_ACCEPTED, installed.text
        assert repeated.status_code == status.HTTP_202_ACCEPTED, repeated.text
        assert nacked.status_code == status.HTTP_409_CONFLICT, nacked.text
        assert uninstalled.status_code == status.HTTP_200_OK, uninstalled.text
        assert [ref.bundle_id for ref in desired.desired_set.bundles] == [
            PRODUCTION_BASE_BUNDLE_ID_V2
        ]
        assert host.current_distribution.snapshot.generation == 1
        assert await _legacy_row_counts(db_session) == (0, 0)
    finally:
        await scoped.close()
        await shutdown_plugin_runtime_v2(app)


@pytest.mark.parametrize("operation", ["install", "uninstall"])
async def test_tenant_admin_cannot_mutate_root_marketplace_state(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    signer = Ed25519PrivateKey.generate()
    public_key = _public_key_pem(signer)
    bundle, archive = _signed_bundle(signer)
    user, tenant = await _tenant_admin(
        db_session, user_id="root-denied-admin", tenant_id="root-denied-tenant"
    )
    assert user.is_superuser is False
    app = _app(db_session, user)
    app.state.plugin_marketplace_trusted_public_keys_v2 = (public_key,)
    monkeypatch.setattr(
        plugin_marketplace, "OciPluginArtifactClient", lambda _client: FakeArtifactClient(archive)
    )
    payload = (
        _request(bundle, archive, public_key)
        .model_copy(update={"tenant_id": tenant.id})
        .model_dump(mode="json")
        if operation == "install"
        else {"version": bundle.version, "tenant_id": tenant.id}
    )
    async with _client(app) as client:
        response = await client.post(
            f"/api/v1/plugin-marketplace/packages/{bundle.bundle_id}/{operation}", json=payload
        )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    for model in (
        PlatformPluginV2DesiredBundleSetModel,
        PlatformPluginV2PublicationModel,
        PlatformPluginPackageModel,
        PlatformPluginPermissionModel,
    ):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    assert await _legacy_row_counts(db_session) == (0, 0)
