from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.gene.enums import EvolutionEventType
from src.domain.model.gene.instance_gene import EvolutionEvent
from src.infrastructure.adapters.secondary.persistence.models import (
    InstanceModel,
    Project,
    Tenant,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_evolution_event_repository import (
    SqlEvolutionEventRepository,
)


def _event(
    *,
    event_id: str,
    instance_id: str = "instance-1",
    gene_id: str | None = "gene-1",
    created_at: datetime,
) -> EvolutionEvent:
    return EvolutionEvent(
        id=event_id,
        instance_id=instance_id,
        gene_id=gene_id,
        event_type=EvolutionEventType.learned,
        gene_name=event_id,
        created_at=created_at,
    )


@pytest.mark.unit
async def test_evolution_event_repository_orders_timelines_by_newest_then_id(
    test_db: AsyncSession,
) -> None:
    repo = SqlEvolutionEventRepository(test_db)
    base_time = datetime(2026, 1, 1, tzinfo=UTC)

    for event in [
        _event(event_id="tie-b", created_at=base_time + timedelta(minutes=1)),
        _event(event_id="oldest", created_at=base_time),
        _event(event_id="newest", created_at=base_time + timedelta(minutes=2)),
        _event(event_id="tie-a", created_at=base_time + timedelta(minutes=1)),
    ]:
        await repo.save(event)
    await test_db.flush()

    by_instance = await repo.find_by_instance("instance-1", limit=4)
    by_gene = await repo.find_by_gene("gene-1", limit=4)
    by_filters = await repo.find_by_filters(instance_id="instance-1", limit=4)
    second_page = await repo.find_by_filters(instance_id="instance-1", limit=2, offset=2)

    assert [event.id for event in by_instance] == ["newest", "tie-a", "tie-b", "oldest"]
    assert [event.id for event in by_gene] == ["newest", "tie-a", "tie-b", "oldest"]
    assert [event.id for event in by_filters] == ["newest", "tie-a", "tie-b", "oldest"]
    assert [event.id for event in second_page] == ["tie-b", "oldest"]


@pytest.mark.unit
async def test_evolution_event_repository_filters_gene_events_by_instance_tenant(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    foreign_tenant = Tenant(
        id="foreign-event-tenant",
        name="Foreign Event Tenant",
        slug="foreign-event-tenant",
        owner_id=test_user.id,
    )
    test_db.add(foreign_tenant)
    test_db.add_all(
        [
            InstanceModel(
                id="tenant-instance",
                name="Tenant Instance",
                slug="tenant-instance",
                tenant_id=test_project_db.tenant_id,
                service_type="ClusterIP",
                status="running",
                created_by=test_user.id,
            ),
            InstanceModel(
                id="foreign-instance",
                name="Foreign Instance",
                slug="foreign-instance",
                tenant_id=foreign_tenant.id,
                service_type="ClusterIP",
                status="running",
                created_by=test_user.id,
            ),
        ]
    )
    await test_db.flush()

    repo = SqlEvolutionEventRepository(test_db)
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    await repo.save(
        _event(
            event_id="tenant-event",
            instance_id="tenant-instance",
            gene_id="shared-gene",
            created_at=base_time,
        )
    )
    await repo.save(
        _event(
            event_id="foreign-event",
            instance_id="foreign-instance",
            gene_id="shared-gene",
            created_at=base_time + timedelta(minutes=1),
        )
    )
    await test_db.flush()

    events = await repo.find_by_filters(
        tenant_id=test_project_db.tenant_id,
        gene_id="shared-gene",
        limit=10,
    )
    total = await repo.count_by_filters(
        tenant_id=test_project_db.tenant_id,
        gene_id="shared-gene",
    )

    assert [event.id for event in events] == ["tenant-event"]
    assert total == 1
