"""Unit tests for admin DLQ router access control."""

from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.admin_dlq import require_admin
from src.infrastructure.adapters.secondary.persistence.models import User


def _user(**attrs: object) -> User:
    return cast(User, SimpleNamespace(**attrs))


@pytest.mark.unit
def test_require_admin_allows_superuser() -> None:
    current_user = _user(is_superuser=True, roles=[])

    assert require_admin(current_user) is current_user


@pytest.mark.unit
def test_require_admin_allows_admin_role_relationship() -> None:
    current_user = _user(
        is_superuser=False,
        roles=[SimpleNamespace(role=SimpleNamespace(name="admin"))],
    )

    assert require_admin(current_user) is current_user


@pytest.mark.unit
def test_require_admin_preserves_legacy_role_attribute() -> None:
    current_user = _user(is_superuser=False, role="admin", roles=[])

    assert require_admin(current_user) is current_user


@pytest.mark.unit
def test_require_admin_rejects_non_admin() -> None:
    current_user = _user(
        is_superuser=False,
        roles=[SimpleNamespace(role=SimpleNamespace(name="user"))],
    )

    with pytest.raises(HTTPException) as exc_info:
        require_admin(current_user)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
