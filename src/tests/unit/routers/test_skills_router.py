from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers import skills as router


class _SkillRepository:
    async def create(self, _skill: object) -> object:
        raise ValueError("Skill name 'Bad Name' must be lowercase with hyphens only")


class _Container:
    def skill_repository(self) -> _SkillRepository:
        return _SkillRepository()


@pytest.mark.unit
async def test_create_skill_sanitizes_domain_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _Container())

    with pytest.raises(HTTPException) as exc_info:
        await router.create_skill(
            request=SimpleNamespace(),
            data=router.SkillCreate(
                name="Bad Name",
                description="Test skill",
                tools=["read"],
            ),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid skill request"
    assert "Bad Name" not in exc_info.value.detail


@pytest.mark.unit
async def test_get_skill_version_sanitizes_missing_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _VersionRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_version(self, _skill_id: str, _version_number: int) -> object | None:
            return None

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _VersionRepository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await router.get_skill_version(
            skill_id="skill-secret",
            version_number=42,
            db=SimpleNamespace(),
            tenant={"id": "tenant-1"},
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Skill version not found"
    assert "secret" not in exc_info.value.detail
    assert "42" not in exc_info.value.detail
