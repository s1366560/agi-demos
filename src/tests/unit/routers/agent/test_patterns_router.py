"""Tests for workflow pattern route hardening."""

from collections.abc import Awaitable, Callable
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
    request.app.state.container.with_db.return_value = SimpleNamespace(
        workflow_pattern_repository=lambda: FailingPatternRepository()
    )
    return request


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
                user_tenant_id="tenant-1",
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
                user_tenant_id="tenant-1",
                db=SimpleNamespace(),
            ),
            "Failed to get pattern",
        ),
        (
            lambda: patterns_router.delete_pattern(
                pattern_id="pattern-1",
                request=_request_with_pattern_repo(),
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
    call: Callable[[], Awaitable[Any]],
    expected_detail: str,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await call()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == expected_detail
    assert "internal" not in exc_info.value.detail
