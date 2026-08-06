from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.routers.auth import router
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.security.oauth_login import (
    OAuthAuthorization,
    OAuthCallbackResult,
    OAuthIdentity,
    OAuthProviderDescriptor,
    OAuthStateInvalidError,
    OAuthStateStoreUnavailableError,
)


class FakeOAuthService:
    def __init__(self) -> None:
        self.begin_authorization = AsyncMock(
            return_value=OAuthAuthorization(
                provider_id="google",
                authorization_url="https://accounts.google.example/auth?state=opaque",
                expires_in=600,
            )
        )
        self.exchange_callback = AsyncMock(
            return_value=OAuthCallbackResult(
                identity=OAuthIdentity(
                    provider_id="google",
                    subject="subject-1",
                    email="user@example.com",
                    email_verified=True,
                    display_name="OAuth User",
                    avatar_url=None,
                ),
                redirect_to="/tenant/t-1/overview",
            )
        )

    def list_providers(self) -> tuple[OAuthProviderDescriptor, ...]:
        return (OAuthProviderDescriptor(id="google", display_name="Google"),)


@pytest.fixture
def oauth_service() -> FakeOAuthService:
    return FakeOAuthService()


@pytest.fixture
def db() -> AsyncMock:
    database = AsyncMock()
    database.add = MagicMock()
    database.commit = AsyncMock()
    return database


@pytest.fixture
def client(oauth_service: FakeOAuthService, db: AsyncMock) -> TestClient:
    app = FastAPI()
    app.state.container = SimpleNamespace(redis=lambda: SimpleNamespace())
    app.dependency_overrides[get_db] = lambda: db
    app.include_router(router, prefix="/api/v1")

    with patch(
        "src.infrastructure.adapters.primary.web.routers.auth.get_oauth_login_service",
        return_value=oauth_service,
    ):
        yield TestClient(app)


@pytest.mark.unit
class TestOAuthLoginRoutes:
    def test_lists_configured_oauth_providers(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/oauth/providers")

        assert response.status_code == 200
        assert response.json() == {"providers": [{"id": "google", "display_name": "Google"}]}

    def test_begins_oauth_authorization_with_server_state(
        self,
        client: TestClient,
        oauth_service: FakeOAuthService,
    ) -> None:
        response = client.post(
            "/api/v1/auth/oauth/google/authorize",
            json={"redirect_to": "/tenant/t-1/overview"},
        )

        assert response.status_code == 200
        assert response.json()["authorization_url"].startswith("https://accounts.google.example")
        oauth_service.begin_authorization.assert_awaited_once_with(
            ANY,
            provider_id="google",
            redirect_to="/tenant/t-1/overview",
        )

    def test_callback_issues_memstack_session_for_preprovisioned_verified_identity(
        self,
        client: TestClient,
        oauth_service: FakeOAuthService,
        db: AsyncMock,
    ) -> None:
        user = SimpleNamespace(
            id="user-1",
            email="user@example.com",
            full_name="Existing User",
            is_active=True,
            is_superuser=False,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            profile={},
            preferred_language="en-US",
            roles=[
                SimpleNamespace(
                    role=SimpleNamespace(name="member"),
                    tenant_id="tenant-1",
                    project_id=None,
                )
            ],
        )
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        db.execute.return_value = result

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.auth.create_api_key",
                new=AsyncMock(return_value=("ms_sk_oauth", MagicMock())),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.auth._ensure_default_project",
                new=AsyncMock(),
            ),
        ):
            response = client.post(
                "/api/v1/auth/oauth/google/callback",
                json={"code": "provider-code", "state": "opaque-state"},
            )

        assert response.status_code == 200
        assert response.json()["access_token"] == "ms_sk_oauth"
        assert response.json()["redirect_to"] == "/tenant/t-1/overview"
        assert response.json()["user"]["user_id"] == "user-1"
        assert user.profile["oauth_identities"]["google"]["subject"] == "subject-1"
        assert "provider-code" not in repr(user.profile)
        assert "ms_sk_oauth" not in repr(user.profile)
        assert db.execute.await_count == 4
        db.commit.assert_awaited_once()
        oauth_service.exchange_callback.assert_awaited_once_with(
            ANY,
            provider_id="google",
            code="provider-code",
            state="opaque-state",
        )

    def test_callback_returns_stable_reason_for_invalid_state(
        self,
        client: TestClient,
        oauth_service: FakeOAuthService,
    ) -> None:
        oauth_service.exchange_callback.side_effect = OAuthStateInvalidError()

        response = client.post(
            "/api/v1/auth/oauth/google/callback",
            json={"code": "provider-code", "state": "expired-state"},
        )

        assert response.status_code == 400
        assert response.json()["detail"]["reason_code"] == "oauth_callback_state_invalid"

    def test_callback_rejects_unverified_identity_before_account_lookup(
        self,
        client: TestClient,
        oauth_service: FakeOAuthService,
        db: AsyncMock,
    ) -> None:
        oauth_service.exchange_callback.return_value = OAuthCallbackResult(
            identity=OAuthIdentity(
                provider_id="google",
                subject="subject-1",
                email="user@example.com",
                email_verified=False,
                display_name="OAuth User",
                avatar_url=None,
            ),
            redirect_to="/",
        )

        response = client.post(
            "/api/v1/auth/oauth/google/callback",
            json={"code": "provider-code", "state": "opaque-state"},
        )

        assert response.status_code == 403
        assert response.json()["detail"]["reason_code"] == "oauth_identity_email_unverified"
        db.execute.assert_not_awaited()

    def test_callback_rejects_identity_without_preprovisioned_account(
        self,
        client: TestClient,
        db: AsyncMock,
    ) -> None:
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        response = client.post(
            "/api/v1/auth/oauth/google/callback",
            json={"code": "provider-code", "state": "opaque-state"},
        )

        assert response.status_code == 403
        assert response.json()["detail"]["reason_code"] == "oauth_account_not_preprovisioned"
        db.commit.assert_not_awaited()

    def test_callback_rejects_different_subject_already_bound_to_same_user(
        self,
        client: TestClient,
        db: AsyncMock,
    ) -> None:
        user = _oauth_user(
            profile={"oauth_identities": {"google": {"subject": "different-subject"}}}
        )
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        db.execute.return_value = result

        response = client.post(
            "/api/v1/auth/oauth/google/callback",
            json={"code": "provider-code", "state": "opaque-state"},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["reason_code"] == "oauth_identity_subject_conflict"
        db.commit.assert_not_awaited()

    def test_callback_rejects_subject_bound_to_another_user(
        self,
        client: TestClient,
        db: AsyncMock,
    ) -> None:
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = _oauth_user()
        owner_result = MagicMock()
        owner_result.scalar_one_or_none.return_value = _oauth_user(user_id="user-2")
        db.execute.side_effect = [MagicMock(), MagicMock(), account_result, owner_result]

        response = client.post(
            "/api/v1/auth/oauth/google/callback",
            json={"code": "provider-code", "state": "opaque-state"},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["reason_code"] == "oauth_identity_link_conflict"
        db.commit.assert_not_awaited()

    def test_callback_reports_unavailable_one_time_state_store(
        self,
        client: TestClient,
        oauth_service: FakeOAuthService,
    ) -> None:
        oauth_service.exchange_callback.side_effect = OAuthStateStoreUnavailableError()

        response = client.post(
            "/api/v1/auth/oauth/google/callback",
            json={"code": "provider-code", "state": "opaque-state"},
        )

        assert response.status_code == 503
        assert response.json()["detail"]["reason_code"] == "oauth_state_store_unavailable"

    def test_authorize_rejects_cross_origin_redirect(
        self,
        client: TestClient,
        oauth_service: FakeOAuthService,
    ) -> None:
        oauth_service.begin_authorization.side_effect = ValueError("unsafe redirect")

        response = client.post(
            "/api/v1/auth/oauth/google/authorize",
            json={"redirect_to": "https://attacker.example"},
        )

        assert response.status_code == 400
        assert response.json()["detail"]["reason_code"] == "oauth_redirect_invalid"


def _oauth_user(
    *,
    user_id: str = "user-1",
    profile: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        email="user@example.com",
        full_name="Existing User",
        is_active=True,
        is_superuser=False,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        profile=profile or {},
        preferred_language="en-US",
        roles=[
            SimpleNamespace(
                role=SimpleNamespace(name="member"),
                tenant_id="tenant-1",
                project_id=None,
            )
        ],
    )
