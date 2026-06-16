"""Tests for prompt template router tenant authorization."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.domain.model.agent.prompt_template import PromptTemplate
from src.infrastructure.adapters.primary.web.routers.agent import templates


def _make_db() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())


def _make_user(user_id: str = "user-1") -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def _make_template(**overrides: Any) -> PromptTemplate:
    values = {
        "id": "template-1",
        "tenant_id": "tenant-1",
        "project_id": None,
        "created_by": "user-1",
        "title": "Template",
        "content": "Use {{ input }}",
        "category": "general",
        "is_system": False,
    }
    values.update(overrides)
    return PromptTemplate(**values)


def _patch_repo(monkeypatch: pytest.MonkeyPatch, repo: SimpleNamespace) -> None:
    monkeypatch.setattr(templates, "SqlPromptTemplateRepository", lambda _db: repo)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_template_requires_selected_tenant_access_and_project_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(save=AsyncMock(side_effect=lambda template: template))
    db = _make_db()
    require_access = AsyncMock()
    require_project_scope = AsyncMock()
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(templates, "require_tenant_access", require_access)
    monkeypatch.setattr(templates, "_require_project_scope", require_project_scope)

    response = await templates.create_template(
        data=templates.TemplateCreateRequest(
            title="Project template",
            content="Project {{ input }}",
            project_id="project-1",
        ),
        tenant_id="selected-tenant",
        current_user=_make_user(),
        db=db,
    )

    saved_template = repo.save.await_args.args[0]
    assert response.tenant_id == "selected-tenant"
    assert saved_template.tenant_id == "selected-tenant"
    require_access.assert_awaited_once_with(
        db,
        _make_user(),
        "selected-tenant",
        require_admin=False,
    )
    require_project_scope.assert_awaited_once_with(db, "selected-tenant", "project-1")
    db.commit.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_system_template_requires_admin_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(save=AsyncMock())
    db = _make_db()
    _patch_repo(monkeypatch, repo)

    async def require_access(
        _db: object,
        _current_user: object,
        _tenant_id: str,
        *,
        require_admin: bool = False,
    ) -> None:
        if require_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

    monkeypatch.setattr(templates, "require_tenant_access", require_access)

    with pytest.raises(HTTPException) as exc_info:
        await templates.create_template(
            data=templates.TemplateCreateRequest(
                title="System template",
                content="System {{ input }}",
                is_system=True,
            ),
            tenant_id="tenant-1",
            current_user=_make_user(),
            db=db,
        )

    assert exc_info.value.status_code == 403
    repo.save.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_templates_validates_project_scope_before_project_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = _make_template(project_id="project-1")
    repo = SimpleNamespace(list_by_project=AsyncMock(return_value=[template]))
    db = _make_db()
    require_access = AsyncMock()
    require_project_scope = AsyncMock()
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(templates, "require_tenant_access", require_access)
    monkeypatch.setattr(templates, "_require_project_scope", require_project_scope)

    response = await templates.list_templates(
        tenant_id="tenant-1",
        project_id="project-1",
        limit=50,
        offset=0,
        current_user=_make_user(),
        db=db,
    )

    assert [item.id for item in response] == ["template-1"]
    require_access.assert_awaited_once_with(db, _make_user(), "tenant-1")
    require_project_scope.assert_awaited_once_with(db, "tenant-1", "project-1")
    repo.list_by_project.assert_awaited_once_with("project-1", limit=50, offset=0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_template_requires_access_to_template_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(find_by_id=AsyncMock(return_value=_make_template(tenant_id="other-tenant")))
    db = _make_db()
    _patch_repo(monkeypatch, repo)

    async def deny_access(
        _db: object,
        _current_user: object,
        tenant_id: str,
        *,
        require_admin: bool = False,
    ) -> None:
        assert tenant_id == "other-tenant"
        assert require_admin is False
        raise HTTPException(status_code=403, detail="Tenant access required")

    monkeypatch.setattr(templates, "require_tenant_access", deny_access)

    with pytest.raises(HTTPException) as exc_info:
        await templates.get_template(
            template_id="template-1",
            current_user=_make_user(),
            db=db,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_system_template_requires_tenant_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(
        find_by_id=AsyncMock(return_value=_make_template(created_by="other-user", is_system=True)),
        save=AsyncMock(),
    )
    db = _make_db()
    _patch_repo(monkeypatch, repo)
    access_calls: list[bool] = []

    async def require_access(
        _db: object,
        _current_user: object,
        _tenant_id: str,
        *,
        require_admin: bool = False,
    ) -> None:
        access_calls.append(require_admin)
        if require_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

    monkeypatch.setattr(templates, "require_tenant_access", require_access)

    with pytest.raises(HTTPException) as exc_info:
        await templates.update_template(
            template_id="template-1",
            data=templates.TemplateUpdateRequest(title="Updated"),
            current_user=_make_user(),
            db=db,
        )

    assert exc_info.value.status_code == 403
    assert access_calls == [True]
    repo.save.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_non_system_template_rejects_non_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(
        find_by_id=AsyncMock(return_value=_make_template(created_by="other-user")),
        delete=AsyncMock(return_value=True),
    )
    db = _make_db()
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(templates, "require_tenant_access", AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await templates.delete_template(
            template_id="template-1",
            current_user=_make_user(),
            db=db,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Not authorized to modify this template"
    repo.delete.assert_not_awaited()
