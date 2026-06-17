from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.application.schemas.instance_template_schemas import (
    InstanceTemplateCreate,
    InstanceTemplateUpdate,
    TemplateItemCreate,
)
from src.infrastructure.adapters.primary.web.routers import instance_templates as router


class _FailingTemplateService:
    async def create_template(self, **_kwargs: object) -> object:
        raise ValueError("internal unique constraint secret")

    async def list_templates(self, **_kwargs: object) -> list[object]:
        raise ValueError("internal list secret")

    async def list_templates_with_total(self, **_kwargs: object) -> tuple[list[object], int]:
        raise ValueError("internal list secret")

    async def update_template(self, **_kwargs: object) -> object:
        raise ValueError("Template tmpl-secret not found")

    async def delete_template(self, *_args: object) -> None:
        raise ValueError("Template tmpl-secret not found")

    async def publish_template(self, *_args: object) -> object:
        raise ValueError("Template tmpl-secret not found")

    async def unpublish_template(self, *_args: object) -> object:
        raise ValueError("Template tmpl-secret not found")

    async def get_template(self, *_args: object) -> object | None:
        return SimpleNamespace(
            id="tmpl-source",
            tenant_id="tenant-1",
            description=None,
            icon=None,
            image_version=None,
            default_config={},
            deleted_at=None,
        )

    async def list_template_items(self, *_args: object) -> list[object]:
        return []

    async def add_template_item(self, **_kwargs: object) -> object:
        raise ValueError("Template tmpl-secret not found")

    async def remove_template_item(self, *_args: object, **_kwargs: object) -> None:
        raise ValueError("Template item item-secret not found")


class _Container:
    def __init__(self) -> None:
        self.service = _FailingTemplateService()

    def instance_template_service(self) -> _FailingTemplateService:
        return self.service


@pytest.fixture(autouse=True)
def failing_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _Container())


@pytest.fixture
def db() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock())


@pytest.fixture
def user() -> SimpleNamespace:
    return SimpleNamespace(id="user-1")


@pytest.mark.unit
async def test_create_template_sanitizes_validation_errors(
    db: SimpleNamespace,
    user: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await router.create_template(
            request=SimpleNamespace(),
            data=InstanceTemplateCreate(name="Template", slug="template"),
            tenant_id="tenant-1",
            current_user=user,
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid template request"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
async def test_list_templates_sanitizes_validation_errors(db: SimpleNamespace) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await router.list_templates(
            request=SimpleNamespace(),
            page=1,
            page_size=20,
            is_published=None,
            tenant_id="tenant-1",
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid template request"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.parametrize(
    ("call_name", "call_args"),
    [
        (
            "update_template",
            {
                "request": SimpleNamespace(),
                "template_id": "tmpl-secret",
                "data": InstanceTemplateUpdate(name="Updated"),
                "tenant_id": "tenant-1",
            },
        ),
        (
            "delete_template",
            {
                "request": SimpleNamespace(),
                "template_id": "tmpl-secret",
                "tenant_id": "tenant-1",
            },
        ),
        (
            "publish_template",
            {
                "request": SimpleNamespace(),
                "template_id": "tmpl-secret",
                "tenant_id": "tenant-1",
            },
        ),
        (
            "unpublish_template",
            {
                "request": SimpleNamespace(),
                "template_id": "tmpl-secret",
                "tenant_id": "tenant-1",
            },
        ),
        (
            "add_template_item",
            {
                "request": SimpleNamespace(),
                "template_id": "tmpl-secret",
                "data": TemplateItemCreate(
                    template_id="tmpl-secret",
                    item_slug="gene-a",
                ),
                "tenant_id": "tenant-1",
            },
        ),
        (
            "remove_template_item",
            {
                "request": SimpleNamespace(),
                "template_id": "tmpl-secret",
                "item_id": "item-secret",
                "tenant_id": "tenant-1",
            },
        ),
    ],
)
async def test_template_routes_sanitize_not_found_value_errors(
    call_name: str,
    call_args: dict[str, object],
    db: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await getattr(router, call_name)(**call_args, db=db)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Template not found"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_clone_template_sanitizes_create_value_errors(
    db: SimpleNamespace,
    user: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await router.clone_template(
            request=SimpleNamespace(),
            template_id="tmpl-source",
            data=router.CloneTemplateRequest(new_name="Clone"),
            tenant_id="tenant-1",
            current_user=user,
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid template request"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
async def test_list_template_items_rejects_cross_tenant_template(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    class CrossTenantService:
        list_template_items = AsyncMock()

        async def get_template(self, *_args: object) -> object:
            return SimpleNamespace(id="tmpl-other", tenant_id="tenant-2", deleted_at=None)

    service = CrossTenantService()

    class Container:
        def instance_template_service(self) -> CrossTenantService:
            return service

    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: Container())

    with pytest.raises(HTTPException) as exc_info:
        await router.list_template_items(
            request=SimpleNamespace(),
            template_id="tmpl-other",
            tenant_id="tenant-1",
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Template not found"
    service.list_template_items.assert_not_called()


@pytest.mark.unit
async def test_remove_template_item_passes_route_template_scope(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    class ScopedService:
        def __init__(self) -> None:
            self.remove_template_item = AsyncMock()

        async def get_template(self, *_args: object) -> object:
            return SimpleNamespace(id="tmpl-owned", tenant_id="tenant-1", deleted_at=None)

    service = ScopedService()

    class Container:
        def instance_template_service(self) -> ScopedService:
            return service

    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: Container())

    await router.remove_template_item(
        request=SimpleNamespace(),
        template_id="tmpl-owned",
        item_id="item-owned",
        tenant_id="tenant-1",
        db=db,
    )

    service.remove_template_item.assert_awaited_once_with("item-owned", template_id="tmpl-owned")
