from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.gene.enums import EvolutionEventType
from src.infrastructure.adapters.secondary.persistence.models import Project, User


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


@pytest.mark.unit
async def test_list_genes_with_total_filters_before_pagination(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()

    await service.create_gene(
        name="Other Gene",
        slug=_slug("other-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        category="other",
    )
    await service.create_gene(
        name="Target Gene One",
        slug=_slug("target-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        category="target",
    )
    await service.create_gene(
        name="Target Gene Two",
        slug=_slug("target-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        category="target",
    )

    genes, total = await service.list_genes_with_total(
        tenant_id=test_project_db.tenant_id,
        category="target",
        limit=1,
        offset=0,
    )

    assert total == 2
    assert len(genes) == 1
    assert genes[0].category == "target"


@pytest.mark.unit
async def test_list_genomes_with_total_filters_before_pagination(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()

    unpublished = await service.create_genome(
        name="Unpublished Genome",
        slug=_slug("unpublished-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    published_one = await service.create_genome(
        name="Published Genome One",
        slug=_slug("published-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    published_two = await service.create_genome(
        name="Published Genome Two",
        slug=_slug("published-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    await service.publish_genome(published_one.id)
    await service.publish_genome(published_two.id)

    genomes, total = await service.list_genomes_with_total(
        tenant_id=test_project_db.tenant_id,
        is_published=True,
        limit=1,
        offset=0,
    )

    assert unpublished.is_published is False
    assert total == 2
    assert len(genomes) == 1
    assert genomes[0].is_published is True


@pytest.mark.unit
async def test_list_evolution_events_with_total_filters_before_pagination(
    test_db: AsyncSession,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()

    await service.create_evolution_event(
        "instance-1",
        event_type=EvolutionEventType.forgot,
        gene_name="Forgot",
    )
    await service.create_evolution_event(
        "instance-1",
        event_type=EvolutionEventType.learned,
        gene_name="Learned One",
    )
    await service.create_evolution_event(
        "instance-1",
        event_type=EvolutionEventType.learned,
        gene_name="Learned Two",
    )

    events, total = await service.list_evolution_events_with_total(
        instance_id="instance-1",
        event_type=EvolutionEventType.learned,
        limit=1,
        offset=0,
    )

    assert total == 2
    assert len(events) == 1
    assert events[0].event_type == EvolutionEventType.learned
