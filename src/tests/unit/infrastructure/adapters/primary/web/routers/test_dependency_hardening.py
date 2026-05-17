from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.configuration import features
from src.infrastructure.adapters.primary.web.dependencies import auth_dependencies, authorization


class _DisabledFeatureGate:
    edition = "secret-enterprise"

    def is_enabled(self, _feature_id: str) -> bool:
        return False


class _FailingAuthService:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def verify_api_key(self, _api_key: str) -> None:
        raise ValueError("secret api key backend reason")

    async def get_user_by_id(self, _user_id: str) -> None:
        raise ValueError("secret user lookup reason")


@pytest.mark.unit
def test_require_feature_sanitizes_feature_and_edition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(features, "get_feature_gate", lambda: _DisabledFeatureGate())
    dependency = features.require_feature("secret-feature-id").dependency

    with pytest.raises(HTTPException) as exc_info:
        dependency()

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Feature is not available"
    assert "secret-feature-id" not in exc_info.value.detail
    assert "secret-enterprise" not in exc_info.value.detail


@pytest.mark.unit
async def test_verify_api_key_dependency_sanitizes_service_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_dependencies, "AuthService", _FailingAuthService)

    with pytest.raises(HTTPException) as exc_info:
        await auth_dependencies.verify_api_key_dependency(
            api_key="ms_sk_secret",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid API key"
    assert "secret api key backend reason" not in exc_info.value.detail


@pytest.mark.unit
async def test_get_current_user_sanitizes_service_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_dependencies, "AuthService", _FailingAuthService)

    with pytest.raises(HTTPException) as exc_info:
        await auth_dependencies.get_current_user(
            api_key=SimpleNamespace(user_id="user-secret"),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Access denied"
    assert "secret user lookup reason" not in exc_info.value.detail


@pytest.mark.unit
async def test_permission_decorators_sanitize_required_permission_names() -> None:
    async def endpoint(**_kwargs: object) -> str:
        return "ok"

    auth_service = SimpleNamespace(check_permission=AsyncMock(return_value=False))
    wrapped = authorization.require_permission("secret:permission")(endpoint)

    with pytest.raises(HTTPException) as exc_info:
        await wrapped(current_user=SimpleNamespace(id="user-1"), auth_service=auth_service)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Permission required"
    assert "secret:permission" not in exc_info.value.detail


@pytest.mark.unit
async def test_role_decorator_sanitizes_required_role_name() -> None:
    async def endpoint(**_kwargs: object) -> str:
        return "ok"

    auth_service = SimpleNamespace(get_user_roles=AsyncMock(return_value=[]))
    wrapped = authorization.require_role("secret-admin-role")(endpoint)

    with pytest.raises(HTTPException) as exc_info:
        await wrapped(current_user=SimpleNamespace(id="user-1"), auth_service=auth_service)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Role required"
    assert "secret-admin-role" not in exc_info.value.detail
