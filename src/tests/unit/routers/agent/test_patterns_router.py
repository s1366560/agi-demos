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


def _pattern_authority(
    repository: object,
    *,
    db: object | None = None,
    current_user: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        db=db if db is not None else SimpleNamespace(),
        current_user=(
            current_user
            if current_user is not None
            else SimpleNamespace(id="user-1", is_admin=False)
        ),
        services=SimpleNamespace(repository=repository),
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
                tenant_id="tenant-1",
                page=1,
                page_size=20,
                min_success_rate=None,
                pattern_application=_pattern_authority(FailingPatternRepository()),
            ),
            "Failed to list patterns",
        ),
        (
            lambda: patterns_router.get_pattern(
                pattern_id="pattern-1",
                tenant_id="tenant-1",
                pattern_application=_pattern_authority(FailingPatternRepository()),
            ),
            "Failed to get pattern",
        ),
        (
            lambda: patterns_router.delete_pattern(
                pattern_id="pattern-1",
                tenant_id="tenant-1",
                pattern_application=_pattern_authority(
                    FailingPatternRepository(),
                    current_user=SimpleNamespace(id="user-1", is_admin=True),
                ),
            ),
            "Failed to delete pattern",
        ),
        (
            lambda: patterns_router.reset_patterns(
                tenant_id="tenant-1",
                pattern_application=_pattern_authority(
                    FailingPatternRepository(),
                    current_user=SimpleNamespace(id="user-1", is_admin=True),
                ),
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
    monkeypatch.setattr(patterns_router, "require_tenant_access", require_access)

    response = await patterns_router.list_patterns(
        tenant_id="tenant-2",
        page=1,
        page_size=20,
        min_success_rate=None,
        pattern_application=_pattern_authority(
            repo,
            db=db,
            current_user=current_user,
        ),
    )

    assert response.total == 1
    assert response.patterns[0].tenant_id == "tenant-2"
    require_access.assert_awaited_once_with(db, current_user, "tenant-2")
    repo.list_by_tenant.assert_awaited_once_with("tenant-2")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_project_patterns_derives_tenant_and_requires_both_memberships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(list_by_tenant=AsyncMock(return_value=[_pattern()]))
    db = AsyncMock()
    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = "tenant-1"
    membership_result = MagicMock()
    membership_result.scalar_one_or_none.return_value = "membership-1"
    db.execute.side_effect = [project_result, membership_result]

    response = await patterns_router.list_project_shared_patterns(
        project_id="project-1",
        page=1,
        page_size=20,
        min_success_rate=None,
        pattern_application=_pattern_authority(
            repo,
            db=db,
            current_user=SimpleNamespace(id="user-1"),
        ),
    )

    assert response.project_id == "project-1"
    assert response.tenant_id == "tenant-1"
    assert response.scope_kind == "tenant_shared"
    assert response.patterns[0].tenant_id == "tenant-1"
    repo.list_by_tenant.assert_awaited_once_with("tenant-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_project_patterns_rejects_missing_project_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(list_by_tenant=AsyncMock())
    db = AsyncMock()
    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = "tenant-1"
    membership_result = MagicMock()
    membership_result.scalar_one_or_none.return_value = None
    db.execute.side_effect = [project_result, membership_result]

    with pytest.raises(HTTPException) as exc_info:
        await patterns_router.list_project_shared_patterns(
            project_id="project-1",
            page=1,
            page_size=20,
            min_success_rate=None,
            pattern_application=_pattern_authority(
                repo,
                db=db,
                current_user=SimpleNamespace(id="user-1"),
            ),
        )

    assert exc_info.value.status_code == 403
    repo.list_by_tenant.assert_not_awaited()


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
    db = SimpleNamespace(commit=AsyncMock())
    current_user = SimpleNamespace(id="user-1")
    monkeypatch.setattr(patterns_router, "require_tenant_access", require_access)

    result = await patterns_router.delete_pattern(
        pattern_id="pattern-1",
        tenant_id="tenant-2",
        pattern_application=_pattern_authority(
            repo,
            db=db,
            current_user=current_user,
        ),
    )

    assert result == {"message": "Pattern deleted successfully", "pattern_id": "pattern-1"}
    require_access.assert_awaited_once_with(
        db,
        current_user,
        "tenant-2",
        require_admin=True,
    )
    repo.delete.assert_awaited_once_with("pattern-1")
    db.commit.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_patterns_commits_all_tenant_deletions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patterns = [
        _pattern(id="pattern-1", tenant_id="tenant-2"),
        _pattern(id="pattern-2", tenant_id="tenant-2"),
    ]
    repo = SimpleNamespace(
        list_by_tenant=AsyncMock(return_value=patterns),
        delete=AsyncMock(return_value=True),
    )
    require_access = AsyncMock()
    db = SimpleNamespace(commit=AsyncMock())
    current_user = SimpleNamespace(id="user-1")
    monkeypatch.setattr(patterns_router, "require_tenant_access", require_access)

    result = await patterns_router.reset_patterns(
        tenant_id="tenant-2",
        pattern_application=_pattern_authority(
            repo,
            db=db,
            current_user=current_user,
        ),
    )

    assert result.deleted_count == 2
    assert result.tenant_id == "tenant-2"
    require_access.assert_awaited_once_with(
        db,
        current_user,
        "tenant-2",
        require_admin=True,
    )
    repo.delete.assert_any_await("pattern-1")
    repo.delete.assert_any_await("pattern-2")
    assert repo.delete.await_count == 2
    db.commit.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_pattern_hides_patterns_outside_requested_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=_pattern(tenant_id="other-tenant")),
        delete=AsyncMock(),
    )
    monkeypatch.setattr(patterns_router, "require_tenant_access", AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await patterns_router.delete_pattern(
            pattern_id="pattern-1",
            tenant_id="tenant-2",
            pattern_application=_pattern_authority(
                repo,
                current_user=SimpleNamespace(id="user-1"),
            ),
        )

    assert exc_info.value.status_code == 404
    repo.delete.assert_not_awaited()
