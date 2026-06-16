from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.models import Project, User


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


@pytest.mark.unit
async def test_list_templates_with_total_filters_before_pagination(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).instance_template_service()

    unpublished = await service.create_template(
        name="Unpublished Template",
        slug=_slug("unpublished-template"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    published_one = await service.create_template(
        name="Published Template One",
        slug=_slug("published-template"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    published_two = await service.create_template(
        name="Published Template Two",
        slug=_slug("published-template"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    await service.publish_template(published_one.id)
    await service.publish_template(published_two.id)
    await service.delete_template(unpublished.id)

    templates, total = await service.list_templates_with_total(
        tenant_id=test_project_db.tenant_id,
        is_published=True,
        limit=1,
        offset=0,
    )

    assert unpublished.is_published is False
    assert total == 2
    assert len(templates) == 1
    assert templates[0].is_published is True

    active_templates, active_total = await service.list_templates_with_total(
        tenant_id=test_project_db.tenant_id,
        limit=10,
        offset=0,
    )
    draft_templates, draft_total = await service.list_templates_with_total(
        tenant_id=test_project_db.tenant_id,
        is_published=False,
        limit=10,
        offset=0,
    )

    assert active_total == 2
    assert {template.id for template in active_templates} == {published_one.id, published_two.id}
    assert draft_total == 0
    assert draft_templates == []
