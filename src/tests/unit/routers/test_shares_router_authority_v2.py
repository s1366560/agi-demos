"""Unit coverage for Shares handlers' V2 authority transaction boundary."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.infrastructure.adapters.primary.web.routers import shares as shares_router
from src.infrastructure.adapters.primary.web.shares_application_authority_v2 import (
    SharesApplicationAuthorityV2,
)
from src.infrastructure.plugins.v2.shares_services import (
    SharedMemoryAccessV2,
    SharesDuplicateTargetV2,
    SharesLinkNotFoundV2,
)

pytestmark = pytest.mark.unit


class _SharesService:
    async def create_share(
        self,
        *,
        memory_id: str,
        user_id: str,
        share_data: dict[str, Any],
    ) -> dict[str, Any]:
        return {"id": "share-1", "memory_id": memory_id, "user_id": user_id, **share_data}

    async def list_shares(self, *, memory_id: str, user_id: str) -> dict[str, Any]:
        return {"shares": [{"memory_id": memory_id, "user_id": user_id}]}

    async def delete_share(self, *, memory_id: str, share_id: str, user_id: str) -> None:
        _ = (memory_id, share_id, user_id)

    async def get_shared_memory(self, *, share_token: str) -> SharedMemoryAccessV2:
        return SharedMemoryAccessV2(
            payload={"memory": {"id": "memory-1"}, "share": {"permissions": {"view": True}}},
            memory_id="memory-1",
            share_id=f"share-for-{share_token}",
        )


def _authority(
    service: object, *, db: object, authenticated: bool = True
) -> SharesApplicationAuthorityV2:
    return cast(
        SharesApplicationAuthorityV2,
        SimpleNamespace(
            operation=object(),
            db=db,
            current_user=SimpleNamespace(id="user-1") if authenticated else None,
            services=SimpleNamespace(shares=service),
        ),
    )


def _request(*, user_agent: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"user-agent", user_agent.encode())],
            "method": "DELETE",
            "path": "/api/v1/memories/memory-1/shares/share-1",
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_share_reads_do_not_commit_but_mutations_commit_once() -> None:
    db = SimpleNamespace(commit=AsyncMock())
    authority = _authority(_SharesService(), db=db)

    listed = await shares_router.list_shares("memory-1", authority)

    assert listed["shares"][0]["user_id"] == "user-1"
    db.commit.assert_not_awaited()

    created = await shares_router.create_share(
        "memory-1", {"permissions": {"view": True}}, authority
    )

    assert created["memory_id"] == "memory-1"
    db.commit.assert_awaited_once_with()

    db.commit.reset_mock()
    deleted = await shares_router.delete_share(
        "memory-1",
        "share-1",
        _request(user_agent="testclient"),
        authority,
    )

    assert deleted == {"success": True}
    db.commit.assert_awaited_once_with()


async def test_public_share_read_commits_access_count_once() -> None:
    db = SimpleNamespace(commit=AsyncMock())
    authority = _authority(_SharesService(), db=db, authenticated=False)

    result = await shares_router.get_shared_memory("secret-token", authority)

    assert result["memory"]["id"] == "memory-1"
    db.commit.assert_awaited_once_with()


async def test_share_failures_do_not_commit_authority_session() -> None:
    class FailingSharesService(_SharesService):
        async def create_share(
            self,
            *,
            memory_id: str,
            user_id: str,
            share_data: dict[str, Any],
        ) -> dict[str, Any]:
            _ = (memory_id, user_id, share_data)
            raise SharesDuplicateTargetV2

        async def get_shared_memory(self, *, share_token: str) -> SharedMemoryAccessV2:
            _ = share_token
            raise SharesLinkNotFoundV2

    db = SimpleNamespace(commit=AsyncMock())
    authenticated = _authority(FailingSharesService(), db=db)
    public = _authority(FailingSharesService(), db=db, authenticated=False)

    with pytest.raises(HTTPException) as duplicate:
        await shares_router.create_share("memory-1", {}, authenticated)
    with pytest.raises(HTTPException) as missing:
        await shares_router.get_shared_memory("missing-token", public)

    assert duplicate.value.status_code == 400
    assert missing.value.status_code == 404
    db.commit.assert_not_awaited()
