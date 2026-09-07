"""Administrative lifecycle for dedicated protocol-v2 workload credentials."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.platform_plugin_data_plane_credential_repository_v2 import (
    PLUGIN_DATA_PLANE_CREDENTIAL_PREFIX_V2,
    PlatformPluginDataPlaneCredentialRepositoryV2,
)

pytestmark = pytest.mark.unit


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


async def test_admin_can_issue_list_rotate_and_revoke_data_plane_credential(
    db_session: AsyncSession,
) -> None:
    client = _client(db_session)
    expires_at = datetime.now(UTC) + timedelta(days=30)

    issued_response = client.post(
        "/api/v1/platform-plugins/v2/data-plane-credentials",
        json={"data_plane_id": "rust-server", "expires_at": expires_at.isoformat()},
    )

    assert issued_response.status_code == status.HTTP_201_CREATED
    issued = issued_response.json()
    assert issued["schema_version"] == 2
    assert issued["data_plane_id"] == "rust-server"
    assert issued["secret"].startswith(PLUGIN_DATA_PLANE_CREDENTIAL_PREFIX_V2)
    assert issued["created_by_user_id"] == "plugin-v2-admin"
    assert issued["revoked_at"] is None

    listed_response = client.get(
        "/api/v1/platform-plugins/v2/data-plane-credentials",
        params={"data_plane_id": "rust-server"},
    )
    assert listed_response.status_code == status.HTTP_200_OK
    listed = listed_response.json()
    assert len(listed) == 1
    assert listed[0]["credential_id"] == issued["credential_id"]
    assert "secret" not in listed[0]

    rotated_response = client.post(
        f"/api/v1/platform-plugins/v2/data-plane-credentials/{issued['credential_id']}/rotate",
        json={"expires_at": (expires_at + timedelta(days=30)).isoformat()},
    )
    assert rotated_response.status_code == status.HTTP_201_CREATED
    rotated = rotated_response.json()
    assert rotated["credential_id"] != issued["credential_id"]
    assert rotated["rotated_from_id"] == issued["credential_id"]
    assert rotated["secret"] != issued["secret"]

    repository = PlatformPluginDataPlaneCredentialRepositoryV2(db_session)
    assert await repository.authenticate(issued["secret"]) is None
    assert await repository.authenticate(rotated["secret"]) is not None

    revoked_response = client.delete(
        f"/api/v1/platform-plugins/v2/data-plane-credentials/{rotated['credential_id']}"
    )
    assert revoked_response.status_code == status.HTTP_200_OK
    revoked = revoked_response.json()
    assert revoked["credential_id"] == rotated["credential_id"]
    assert revoked["revoked_at"] is not None
    assert revoked["revoked_by_user_id"] == "plugin-v2-admin"
    assert await repository.authenticate(rotated["secret"]) is None


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    (
        (
            "POST",
            "/api/v1/platform-plugins/v2/data-plane-credentials",
            {"data_plane_id": "rust-server"},
        ),
        ("GET", "/api/v1/platform-plugins/v2/data-plane-credentials", None),
        (
            "POST",
            "/api/v1/platform-plugins/v2/data-plane-credentials/unknown/rotate",
            {},
        ),
        ("DELETE", "/api/v1/platform-plugins/v2/data-plane-credentials/unknown", None),
    ),
)
async def test_data_plane_credential_management_requires_platform_admin(
    db_session: AsyncSession,
    method: str,
    path: str,
    json_body: dict[str, str] | None,
) -> None:
    response = _client(db_session, superuser=False).request(method, path, json=json_body)

    assert response.status_code == status.HTTP_403_FORBIDDEN


async def test_data_plane_credential_cannot_access_management_endpoints(
    db_session: AsyncSession,
) -> None:
    issued = await PlatformPluginDataPlaneCredentialRepositoryV2(db_session).issue(
        data_plane_id="rust-server",
        actor_id="plugin-v2-admin",
    )
    await db_session.commit()
    app = FastAPI()
    app.include_router(platform_plugins.router)

    async def override_db() -> AsyncSession:
        return db_session

    app.dependency_overrides[get_db] = override_db
    response = TestClient(app).get(
        "/api/v1/platform-plugins/v2/data-plane-credentials",
        headers={"Authorization": f"Bearer {issued.secret}"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == (
        "Invalid API key format. API keys should start with 'ms_sk_'"
    )


async def test_data_plane_credential_management_returns_stable_not_found(
    db_session: AsyncSession,
) -> None:
    response = _client(db_session).post(
        "/api/v1/platform-plugins/v2/data-plane-credentials/unknown/rotate",
        json={},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"]["code"] == "plugin_data_plane_credential_not_found"
