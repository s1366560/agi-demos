from __future__ import annotations

from datetime import UTC, datetime
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


def _authority(
    *,
    service: object,
    db: object,
    user: object,
    tenant_id: str = "tenant-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        db=db,
        current_user=user,
        tenant_id=tenant_id,
        services=SimpleNamespace(templates=service),
    )


@pytest.fixture(autouse=True)
def allow_template_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    async def require_access(
        db: object,
        user: object,
        tenant_id: str,
        *,
        require_admin: bool = False,
    ) -> None:
        return None

    monkeypatch.setattr(router, "require_tenant_access", require_access)


@pytest.fixture
def db() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock())


@pytest.fixture
def user() -> SimpleNamespace:
    return SimpleNamespace(id="user-1")


@pytest.fixture
def authority(db: SimpleNamespace, user: SimpleNamespace) -> SimpleNamespace:
    return _authority(service=_FailingTemplateService(), db=db, user=user)


@pytest.mark.unit
async def test_create_template_sanitizes_validation_errors(
    authority: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await router.create_template(
            data=InstanceTemplateCreate(name="Template", slug="template"),
            authority=authority,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid template request"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
async def test_create_template_requires_tenant_admin_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    authority: SimpleNamespace,
) -> None:
    async def deny_admin(
        *_args: object,
        **_kwargs: object,
    ) -> None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    monkeypatch.setattr(router, "require_tenant_access", deny_admin)

    with pytest.raises(HTTPException) as exc_info:
        await router.create_template(
            data=InstanceTemplateCreate(name="Template", slug="template"),
            authority=authority,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Admin access required"
    authority.db.commit.assert_not_awaited()


@pytest.mark.unit
async def test_create_template_rejects_payload_tenant_mismatch(
    authority: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await router.create_template(
            data=InstanceTemplateCreate(
                name="Template",
                slug="template",
                tenant_id="tenant-2",
            ),
            authority=authority,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Access denied"
    authority.db.commit.assert_not_awaited()


@pytest.mark.unit
async def test_create_template_uses_authenticated_tenant_scope(
    db: SimpleNamespace,
    user: SimpleNamespace,
) -> None:
    class Service:
        def __init__(self) -> None:
            self.create_template = AsyncMock(
                return_value=SimpleNamespace(
                    id="tmpl-1",
                    name="Template",
                    slug="template",
                    tenant_id="tenant-1",
                    description=None,
                    icon=None,
                    image_version=None,
                    default_config={},
                    is_published=False,
                    is_featured=False,
                    install_count=0,
                    created_by="user-1",
                    created_at=datetime.now(UTC),
                    updated_at=None,
                )
            )

    service = Service()

    response = await router.create_template(
        data=InstanceTemplateCreate(
            name="Template",
            slug="template",
            tenant_id="tenant-1",
        ),
        authority=_authority(service=service, db=db, user=user),
    )

    assert response.tenant_id == "tenant-1"
    service.create_template.assert_awaited_once()
    assert service.create_template.await_args.kwargs["tenant_id"] == "tenant-1"


@pytest.mark.unit
async def test_list_templates_sanitizes_validation_errors(
    authority: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await router.list_templates(
            page=1,
            page_size=20,
            is_published=None,
            authority=authority,
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
                "template_id": "tmpl-secret",
                "data": InstanceTemplateUpdate(name="Updated"),
            },
        ),
        (
            "delete_template",
            {
                "template_id": "tmpl-secret",
            },
        ),
        (
            "publish_template",
            {
                "template_id": "tmpl-secret",
            },
        ),
        (
            "unpublish_template",
            {
                "template_id": "tmpl-secret",
            },
        ),
        (
            "add_template_item",
            {
                "template_id": "tmpl-secret",
                "data": TemplateItemCreate(
                    template_id="tmpl-secret",
                    item_slug="gene-a",
                ),
            },
        ),
        (
            "remove_template_item",
            {
                "template_id": "tmpl-secret",
                "item_id": "item-secret",
            },
        ),
    ],
)
async def test_template_routes_sanitize_not_found_value_errors(
    call_name: str,
    call_args: dict[str, object],
    authority: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await getattr(router, call_name)(**call_args, authority=authority)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Template not found"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_clone_template_sanitizes_create_value_errors(
    authority: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await router.clone_template(
            template_id="tmpl-source",
            data=router.CloneTemplateRequest(new_name="Clone"),
            authority=authority,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid template request"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
async def test_list_template_items_rejects_cross_tenant_template(
    db: SimpleNamespace,
) -> None:
    class CrossTenantService:
        list_template_items = AsyncMock()

        async def get_template(self, *_args: object) -> object:
            return SimpleNamespace(id="tmpl-other", tenant_id="tenant-2", deleted_at=None)

    service = CrossTenantService()

    with pytest.raises(HTTPException) as exc_info:
        await router.list_template_items(
            template_id="tmpl-other",
            authority=_authority(
                service=service,
                db=db,
                user=SimpleNamespace(id="user-1"),
            ),
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Template not found"
    service.list_template_items.assert_not_called()


@pytest.mark.unit
async def test_remove_template_item_passes_route_template_scope(
    db: SimpleNamespace,
) -> None:
    class ScopedService:
        def __init__(self) -> None:
            self.remove_template_item = AsyncMock()

        async def get_template(self, *_args: object) -> object:
            return SimpleNamespace(id="tmpl-owned", tenant_id="tenant-1", deleted_at=None)

    service = ScopedService()

    await router.remove_template_item(
        template_id="tmpl-owned",
        item_id="item-owned",
        authority=_authority(
            service=service,
            db=db,
            user=SimpleNamespace(id="user-1"),
        ),
    )

    service.remove_template_item.assert_awaited_once_with("item-owned", template_id="tmpl-owned")
