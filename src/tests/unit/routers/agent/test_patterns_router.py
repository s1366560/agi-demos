"""Tests for workflow pattern route hardening."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.agent import patterns as patterns_router


class FailingPatternRepository:
    list_by_tenant = AsyncMock(side_effect=RuntimeError("internal pattern list secret"))
    get_by_id = AsyncMock(side_effect=RuntimeError("internal pattern get secret"))
    delete = AsyncMock(side_effect=RuntimeError("internal pattern delete secret"))


def _request_with_pattern_repo() -> MagicMock:
    request = MagicMock()
    return request


def _patch_pattern_repo(monkeypatch: pytest.MonkeyPatch, repo: object) -> None:
    monkeypatch.setattr(
        patterns_router,
        "get_container_with_db",
        lambda _request, _db: SimpleNamespace(
            workflow_pattern_repository=lambda: repo
        ),
    )


def _pattern(**overrides: Any) -> SimpleNamespace:
    values = {
        "id": "pattern-1",
        "tenant_id": "tenant-1",
        "name": "Pattern",
        "description": "Useful workflow",
        "steps": [],
        "success_rate": 0.9,
        "usage_count": 3,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "metadata": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call", "expected_detail"),
    [
        (
            lambda: patterns_router.list_patterns(
                request=_request_with_pattern_repo(),
                tenant_id="tenant-1",
                page=1,
                page_size=20,
                min_success_rate=None,
                current_user=SimpleNamespace(id="user-1", is_admin=False),
                db=SimpleNamespace(),
            ),
            "Failed to list patterns",
        ),
        (
            lambda: patterns_router.get_pattern(
                pattern_id="pattern-1",
                request=_request_with_pattern_repo(),
                tenant_id="tenant-1",
                current_user=SimpleNamespace(id="user-1", is_admin=False),
                db=SimpleNamespace(),
            ),
            "Failed to get pattern",
        ),
        (
            lambda: patterns_router.delete_pattern(
                pattern_id="pattern-1",
                request=_request_with_pattern_repo(),
                tenant_id="tenant-1",
                current_user=SimpleNamespace(id="user-1", is_admin=True),
                db=SimpleNamespace(),
            ),
            "Failed to delete pattern",
        ),
        (
            lambda: patterns_router.reset_patterns(
                request=_request_with_pattern_repo(),
                tenant_id="tenant-1",
                current_user=SimpleNamespace(id="user-1", is_admin=True),
                db=SimpleNamespace(),
            ),
            "Failed to reset patterns",
        ),
    ],
)
async def test_pattern_routes_sanitize_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
    call: Callable[[], Awaitable[Any]],
    expected_detail: str,
) -> None:
    monkeypatch.setattr(patterns_router, "require_tenant_access", AsyncMock())
    _patch_pattern_repo(monkeypatch, FailingPatternRepository())

    with pytest.raises(HTTPException) as exc_info:
        await call()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == expected_detail
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_patterns_uses_requested_tenant_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(list_by_tenant=AsyncMock(return_value=[_pattern(tenant_id="tenant-2")]))
    require_access = AsyncMock()
    db = SimpleNamespace()
    current_user = SimpleNamespace(id="user-1")
    _patch_pattern_repo(monkeypatch, repo)
    monkeypatch.setattr(patterns_router, "require_tenant_access", require_access)

    response = await patterns_router.list_patterns(
        request=_request_with_pattern_repo(),
        tenant_id="tenant-2",
        page=1,
        page_size=20,
        min_success_rate=None,
        current_user=current_user,
        db=db,
    )

    assert response.total == 1
    assert response.patterns[0].tenant_id == "tenant-2"
    require_access.assert_awaited_once_with(db, current_user, "tenant-2")
    repo.list_by_tenant.assert_awaited_once_with("tenant-2")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_pattern_requires_admin_for_requested_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=_pattern(tenant_id="tenant-2")),
        delete=AsyncMock(),
    )
    require_access = AsyncMock()
    db = SimpleNamespace()
    current_user = SimpleNamespace(id="user-1")
    _patch_pattern_repo(monkeypatch, repo)
    monkeypatch.setattr(patterns_router, "require_tenant_access", require_access)

    result = await patterns_router.delete_pattern(
        pattern_id="pattern-1",
        request=_request_with_pattern_repo(),
        tenant_id="tenant-2",
        current_user=current_user,
        db=db,
    )

    assert result == {"message": "Pattern deleted successfully", "pattern_id": "pattern-1"}
    require_access.assert_awaited_once_with(
        db,
        current_user,
        "tenant-2",
        require_admin=True,
    )
    repo.delete.assert_awaited_once_with("pattern-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_pattern_hides_patterns_outside_requested_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=_pattern(tenant_id="other-tenant")),
        delete=AsyncMock(),
    )
    _patch_pattern_repo(monkeypatch, repo)
    monkeypatch.setattr(patterns_router, "require_tenant_access", AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await patterns_router.delete_pattern(
            pattern_id="pattern-1",
            request=_request_with_pattern_repo(),
            tenant_id="tenant-2",
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    repo.delete.assert_not_awaited()
