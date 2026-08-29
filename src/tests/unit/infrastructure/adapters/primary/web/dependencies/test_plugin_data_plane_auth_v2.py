"""Fail-closed HTTP authentication for protocol-v2 data planes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies.plugin_data_plane_auth_v2 import (
    PlatformPluginDataPlanePrincipalV2,
    get_plugin_data_plane_principal_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.platform_plugin_data_plane_credential_repository_v2 import (
    PlatformPluginDataPlaneCredentialRepositoryV2,
)

pytestmark = pytest.mark.unit


def _client(db: AsyncSession) -> TestClient:
    app = FastAPI()

    async def override_db() -> AsyncSession:
        return db

    @app.get("/workload-only")
    async def workload_only(
        principal: PlatformPluginDataPlanePrincipalV2 = Depends(get_plugin_data_plane_principal_v2),
    ) -> dict[str, str]:
        return {
            "credential_id": principal.credential_id,
            "data_plane_id": principal.data_plane_id,
        }

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


async def test_data_plane_auth_accepts_only_active_bound_workload_credential(
    db_session: AsyncSession,
) -> None:
    repository = PlatformPluginDataPlaneCredentialRepositoryV2(db_session)
    issued = await repository.issue(
        data_plane_id="rust-server",
        actor_id="platform-admin",
    )
    await db_session.commit()

    response = _client(db_session).get(
        "/workload-only",
        headers={"Authorization": f"Bearer {issued.secret}"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "credential_id": issued.credential.id,
        "data_plane_id": "rust-server",
    }


@pytest.mark.parametrize(
    "authorization",
    (
        None,
        "Bearer ms_sk_user-controlled-key",
        "Bearer ms_dp_invalid",
        "Token ms_dp_invalid",
    ),
)
async def test_data_plane_auth_has_no_user_or_admin_fallback(
    db_session: AsyncSession,
    authorization: str | None,
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}

    response = _client(db_session).get("/workload-only", headers=headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"] == "Invalid plugin data-plane credential"


async def test_data_plane_auth_rejects_expired_and_revoked_credentials(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    repository = PlatformPluginDataPlaneCredentialRepositoryV2(db_session)
    expired = await repository.issue(
        data_plane_id="rust-server",
        actor_id="platform-admin",
        expires_at=now + timedelta(microseconds=1),
        now=now,
    )
    revoked = await repository.issue(
        data_plane_id="desktop-sidecar",
        actor_id="platform-admin",
    )
    _ = await repository.revoke(revoked.credential.id, actor_id="platform-admin")
    await db_session.commit()
    client = _client(db_session)

    expired_response = client.get(
        "/workload-only",
        headers={"Authorization": f"Bearer {expired.secret}"},
    )
    revoked_response = client.get(
        "/workload-only",
        headers={"Authorization": f"Bearer {revoked.secret}"},
    )

    assert expired_response.status_code == status.HTTP_401_UNAUTHORIZED
    assert revoked_response.status_code == status.HTTP_401_UNAUTHORIZED
