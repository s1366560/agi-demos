from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    InstanceTemplateModel,
    Project,
    TemplateItemModel,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_instance_template_repository import (
    SqlInstanceTemplateRepository,
)


def _template(
    *,
    template_id: str,
    slug: str,
    tenant_id: str,
    created_by: str,
) -> InstanceTemplateModel:
    return InstanceTemplateModel(
        id=template_id,
        name=template_id,
        slug=slug,
        tenant_id=tenant_id,
        created_by=created_by,
    )


def _template_item(
    *,
    item_id: str,
    template_id: str,
    item_slug: str,
    display_order: int = 0,
    deleted_at: datetime | None = None,
) -> TemplateItemModel:
    return TemplateItemModel(
        id=item_id,
        template_id=template_id,
        item_type="gene",
        item_slug=item_slug,
        display_order=display_order,
        deleted_at=deleted_at,
    )


@pytest.mark.unit
async def test_template_item_repository_filters_deleted_and_deletes_with_parent_scope(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    deleted_at = datetime.now(UTC)
    test_db.add_all(
        [
            _template(
                template_id="owned-template",
                slug="owned-template",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
            ),
            _template(
                template_id="other-template",
                slug="other-template",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
            ),
            _template_item(
                item_id="active-item",
                template_id="owned-template",
                item_slug="active-gene",
                display_order=1,
            ),
            _template_item(
                item_id="deleted-item",
                template_id="owned-template",
                item_slug="deleted-gene",
                display_order=2,
                deleted_at=deleted_at,
            ),
            _template_item(
                item_id="other-template-item",
                template_id="other-template",
                item_slug="other-gene",
            ),
        ]
    )
    await test_db.flush()

    repo = SqlInstanceTemplateRepository(test_db)

    listed = await repo.find_items_by_template("owned-template")
    wrong_parent_deleted = await repo.delete_item(
        "other-template-item",
        template_id="owned-template",
    )
    scoped_deleted = await repo.delete_item("active-item", template_id="owned-template")
    remaining = await repo.find_items_by_template("owned-template")

    assert [item.id for item in listed] == ["active-item"]
    assert wrong_parent_deleted is False
    assert scoped_deleted is True
    assert remaining == []
