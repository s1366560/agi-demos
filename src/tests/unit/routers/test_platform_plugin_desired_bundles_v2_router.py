"""Protocol-v2 DesiredBundleSet management transport tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import DesiredBundleSetV2, ProfileLayerKindV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.protocol import desired_bundle_set_v2_to_payload
from src.tests.unit.infrastructure.plugins.v2.layer_composer_test_support import (
    _bundle,
    _desired,
    _entry,
    _layer,
    _scope,
    _source,
)

pytestmark = pytest.mark.unit


def _desired_set(*, revision: int = 3) -> DesiredBundleSetV2:
    root = _scope()
    bundle = _bundle(
        "base-runtime",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("provider", scope=root),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("consumer", scope=root),),
            ),
        )
    )
    desired = _desired((bundle,), source)
    desired = replace(desired, revision=revision, digest=f"sha256:{'0' * 64}")
    return replace(desired, digest=desired_bundle_set_digest_v2(desired))


def _client(db: AsyncSession, *, superuser: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(platform_plugins.router)

    async def override_db() -> AsyncSession:
        return db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: User(
        id="plugin-v2-admin",
        email="plugin-v2-admin@example.com",
        hashed_password="hashed",
        full_name="Plugin V2 Admin",
        is_active=True,
        is_superuser=superuser,
    )
    return TestClient(app)


def _request(desired: DesiredBundleSetV2, *, expected_revision: int | None) -> dict:
    return {
        "schema_version": 2,
        "scope": {"kind": "tenant", "tenant_id": "tenant-a"},
        "expected_revision": expected_revision,
        "desired_bundle_set": desired_bundle_set_v2_to_payload(desired),
    }


async def test_put_and_get_current_desired_bundle_set(db_session: AsyncSession) -> None:
    desired = _desired_set()
    client = _client(db_session)

    response = client.put(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/current",
        json=_request(desired, expected_revision=None),
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["schema_version"] == 2
    assert payload["scope"] == {"kind": "tenant", "tenant_id": "tenant-a"}
    assert payload["desired_bundle_set"] == desired_bundle_set_v2_to_payload(desired)
    assert payload["actor_id"] == "plugin-v2-admin"

    current = client.get(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/current",
        params={"scope_kind": "tenant", "tenant_id": "tenant-a"},
    )
    assert current.status_code == status.HTTP_200_OK
    assert current.json() == payload


async def test_desired_bundle_history_is_scope_private_and_revision_ordered(
    db_session: AsyncSession,
) -> None:
    first = _desired_set()
    second = replace(first, revision=first.revision + 1, digest=f"sha256:{'0' * 64}")
    second = replace(second, digest=desired_bundle_set_digest_v2(second))
    client = _client(db_session)
    first_response = client.put(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/current",
        json=_request(first, expected_revision=None),
    )
    assert first_response.status_code == status.HTTP_200_OK
    second_response = client.put(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/current",
        json=_request(second, expected_revision=first.revision),
    )
    assert second_response.status_code == status.HTTP_200_OK

    history = client.get(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/history",
        params={"scope_kind": "tenant", "tenant_id": "tenant-a"},
    )

    assert history.status_code == status.HTTP_200_OK
    assert [row["desired_bundle_set"]["revision"] for row in history.json()] == [4, 3]
    other = client.get(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/current",
        params={"scope_kind": "tenant", "tenant_id": "tenant-b"},
    )
    assert other.status_code == status.HTTP_404_NOT_FOUND


async def test_desired_bundle_set_rejects_stale_writer_and_v1_payload(
    db_session: AsyncSession,
) -> None:
    desired = _desired_set()
    client = _client(db_session)
    initial = client.put(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/current",
        json=_request(desired, expected_revision=None),
    )
    assert initial.status_code == status.HTTP_200_OK
    changed = replace(desired, revision=desired.revision + 1, digest=f"sha256:{'0' * 64}")
    changed = replace(changed, digest=desired_bundle_set_digest_v2(changed))

    stale = client.put(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/current",
        json=_request(changed, expected_revision=desired.revision - 1),
    )
    assert stale.status_code == status.HTTP_409_CONFLICT
    assert stale.json()["detail"]["code"] == "plugin_desired_bundle_set_conflict"

    legacy = _request(changed, expected_revision=desired.revision)
    legacy["schema_version"] = 1
    incompatible = client.put(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/current",
        json=legacy,
    )
    assert incompatible.status_code == status.HTTP_409_CONFLICT
    assert incompatible.json()["detail"]["code"] == "plugin_protocol_incompatible"


async def test_desired_bundle_set_management_requires_platform_admin(
    db_session: AsyncSession,
) -> None:
    response = _client(db_session, superuser=False).put(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/current",
        json=_request(_desired_set(), expected_revision=None),
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
