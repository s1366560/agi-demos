from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.gene.enums import EvolutionEventType, InstanceGeneStatus
from src.infrastructure.adapters.secondary.persistence.models import (
    InstanceModel,
    Project,
    Tenant,
    User,
)


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


async def _create_instance(
    test_db: AsyncSession,
    *,
    instance_id: str,
    tenant_id: str,
    created_by: str,
) -> None:
    test_db.add(
        InstanceModel(
            id=instance_id,
            name=instance_id,
            slug=instance_id,
            tenant_id=tenant_id,
            service_type="ClusterIP",
            status="running",
            created_by=created_by,
        )
    )
    await test_db.flush()


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
async def test_list_genes_with_total_filters_by_search_and_visibility(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()

    await service.create_gene(
        name="Needle Public Gene",
        slug=_slug("needle-public"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        description="Matches the marketplace search",
        visibility="public",
    )
    await service.create_gene(
        name="Needle Private Gene",
        slug=_slug("needle-private"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        description="Matches the marketplace search",
        visibility="org_private",
    )
    await service.create_gene(
        name="Other Public Gene",
        slug=_slug("other-public"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        description="Does not match",
        visibility="public",
    )

    genes, total = await service.list_genes_with_total(
        tenant_id=test_project_db.tenant_id,
        search="needle",
        visibility="public",
        limit=10,
        offset=0,
    )

    assert total == 1
    assert [gene.name for gene in genes] == ["Needle Public Gene"]


@pytest.mark.unit
async def test_list_genes_with_total_filters_by_exact_slugs_before_pagination(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()

    first = await service.create_gene(
        name="First Included Gene",
        slug=_slug("included-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    second = await service.create_gene(
        name="Second Included Gene",
        slug=_slug("included-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    await service.create_gene(
        name="Other Gene",
        slug=_slug("other-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    genes, total = await service.list_genes_with_total(
        tenant_id=test_project_db.tenant_id,
        slugs=[first.slug, second.slug],
        limit=1,
        offset=0,
    )

    assert total == 2
    assert len(genes) == 1
    assert genes[0].slug in {first.slug, second.slug}


@pytest.mark.unit
async def test_list_genes_with_total_excludes_installed_instance_genes_before_pagination(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    await _create_instance(
        test_db,
        instance_id="instance-installable",
        tenant_id=test_project_db.tenant_id,
        created_by=test_user.id,
    )
    installed_gene = await service.create_gene(
        name="Already Installed",
        slug=_slug("already-installed"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    available_gene = await service.create_gene(
        name="Still Available",
        slug=_slug("still-available"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    await service.install_gene("instance-installable", installed_gene.id)

    genes, total = await service.list_genes_with_total(
        tenant_id=test_project_db.tenant_id,
        exclude_installed_instance_id="instance-installable",
        limit=1,
        offset=0,
    )

    assert total == 1
    assert [gene.id for gene in genes] == [available_gene.id]


@pytest.mark.unit
async def test_list_genes_with_total_defaults_to_global_scope(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()

    global_gene = await service.create_gene(
        name="Global Listed Gene",
        slug=_slug("global-listed"),
        created_by=test_user.id,
        tenant_id=None,
    )
    global_gene = await service.publish_gene(global_gene.id)
    tenant_gene = await service.create_gene(
        name="Tenant Hidden Gene",
        slug=_slug("tenant-hidden"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    await service.publish_gene(tenant_gene.id)

    genes, total = await service.list_genes_with_total(limit=10, offset=0)

    assert [gene.id for gene in genes] == [global_gene.id]
    assert total == 1


@pytest.mark.unit
async def test_list_genes_with_total_can_include_public_globals_for_tenant_scope(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()

    tenant_gene = await service.create_gene(
        name="Tenant Listed Gene",
        slug=_slug("tenant-listed"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    global_gene = await service.create_gene(
        name="Global Listed Gene",
        slug=_slug("global-listed"),
        created_by=test_user.id,
        tenant_id=None,
    )
    global_gene = await service.publish_gene(global_gene.id)
    global_draft = await service.create_gene(
        name="Global Draft Gene",
        slug=_slug("global-draft"),
        created_by=test_user.id,
        tenant_id=None,
    )

    genes, total = await service.list_genes_with_total(
        tenant_id=test_project_db.tenant_id,
        include_global=True,
        limit=10,
        offset=0,
    )

    assert {gene.id for gene in genes} == {tenant_gene.id, global_gene.id}
    assert global_draft.id not in {gene.id for gene in genes}
    assert total == 2


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
async def test_unpublish_genome_removes_it_from_published_results(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    genome = await service.create_genome(
        name="Publish Toggle Genome",
        slug=_slug("publish-toggle-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    published = await service.publish_genome(genome.id)
    assert published.is_published is True

    unpublished = await service.unpublish_genome(genome.id)
    published_genomes, published_total = await service.list_genomes_with_total(
        tenant_id=test_project_db.tenant_id,
        is_published=True,
        limit=10,
        offset=0,
    )
    unpublished_genomes, unpublished_total = await service.list_genomes_with_total(
        tenant_id=test_project_db.tenant_id,
        is_published=False,
        limit=10,
        offset=0,
    )

    assert unpublished.is_published is False
    assert genome.id not in {item.id for item in published_genomes}
    assert published_total == 0
    assert genome.id in {item.id for item in unpublished_genomes}
    assert unpublished_total == 1


@pytest.mark.unit
async def test_list_genomes_with_total_can_include_public_globals_for_tenant_scope(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()

    tenant_genome = await service.create_genome(
        name="Tenant Listed Genome",
        slug=_slug("tenant-listed-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    global_genome = await service.create_genome(
        name="Global Listed Genome",
        slug=_slug("global-listed-genome"),
        created_by=test_user.id,
        tenant_id=None,
    )
    global_genome = await service.publish_genome(global_genome.id)
    global_draft = await service.create_genome(
        name="Global Draft Genome",
        slug=_slug("global-draft-genome"),
        created_by=test_user.id,
        tenant_id=None,
    )

    genomes, total = await service.list_genomes_with_total(
        tenant_id=test_project_db.tenant_id,
        include_global=True,
        limit=10,
        offset=0,
    )

    assert {genome.id for genome in genomes} == {tenant_genome.id, global_genome.id}
    assert global_draft.id not in {genome.id for genome in genomes}
    assert total == 2


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


@pytest.mark.unit
async def test_list_evolution_events_with_total_filters_by_tenant_scope(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    foreign_tenant = Tenant(
        id="foreign-service-event-tenant",
        name="Foreign Service Event Tenant",
        slug="foreign-service-event-tenant",
        owner_id=test_user.id,
    )
    test_db.add(foreign_tenant)
    await test_db.flush()
    await _create_instance(
        test_db,
        instance_id="service-tenant-instance",
        tenant_id=test_project_db.tenant_id,
        created_by=test_user.id,
    )
    await _create_instance(
        test_db,
        instance_id="service-foreign-instance",
        tenant_id=foreign_tenant.id,
        created_by=test_user.id,
    )

    tenant_event = await service.create_evolution_event(
        "service-tenant-instance",
        gene_id="shared-service-gene",
        event_type=EvolutionEventType.learned,
        gene_name="Tenant Event",
    )
    await service.create_evolution_event(
        "service-foreign-instance",
        gene_id="shared-service-gene",
        event_type=EvolutionEventType.learned,
        gene_name="Foreign Event",
    )

    events, total = await service.list_evolution_events_with_total(
        tenant_id=test_project_db.tenant_id,
        gene_id="shared-service-gene",
        limit=10,
        offset=0,
    )

    assert [event.id for event in events] == [tenant_event.id]
    assert total == 1


@pytest.mark.unit
async def test_install_gene_reactivates_soft_deleted_instance_gene(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    await _create_instance(
        test_db,
        instance_id="instance-reinstall",
        tenant_id=test_project_db.tenant_id,
        created_by=test_user.id,
    )
    gene = await service.create_gene(
        name="Reusable Gene",
        slug=_slug("reusable-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        version="1.2.3",
    )

    first_install = await service.install_gene("instance-reinstall", gene.id)
    installed_gene = await service.get_gene(gene.id)
    assert installed_gene is not None
    assert installed_gene.install_count == 1

    with pytest.raises(ValueError):
        await service.install_gene("instance-reinstall", gene.id)
    duplicate_rejected_gene = await service.get_gene(gene.id)
    assert duplicate_rejected_gene is not None
    assert duplicate_rejected_gene.install_count == 1

    await service.uninstall_gene(first_install.id)
    uninstalled_gene = await service.get_gene(gene.id)
    assert uninstalled_gene is not None
    assert uninstalled_gene.install_count == 0

    second_install = await service.install_gene(
        "instance-reinstall",
        gene.id,
        config_snapshot={"mode": "strict"},
    )
    reinstalled_gene = await service.get_gene(gene.id)
    assert reinstalled_gene is not None
    assert reinstalled_gene.install_count == 1

    assert second_install.id == first_install.id
    assert second_install.deleted_at is None
    assert second_install.status == InstanceGeneStatus.installed
    assert second_install.installed_version == "1.2.3"
    assert second_install.config_snapshot == {"mode": "strict"}


@pytest.mark.unit
async def test_list_instance_genes_with_summary_filters_deleted_before_pagination(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    await _create_instance(
        test_db,
        instance_id="instance-list",
        tenant_id=test_project_db.tenant_id,
        created_by=test_user.id,
    )
    genes = [
        await service.create_gene(
            name=f"Installed Gene {index}",
            slug=_slug(f"installed-gene-{index}"),
            created_by=test_user.id,
            tenant_id=test_project_db.tenant_id,
        )
        for index in range(4)
    ]
    installed = [await service.install_gene("instance-list", gene.id) for gene in genes]
    instance_gene_repo = DIContainer().with_db(test_db).instance_gene_repository()
    installed[1].usage_count = 5
    installed[2].usage_count = 7
    await instance_gene_repo.save(installed[1])
    await instance_gene_repo.save(installed[2])
    await service.uninstall_gene(installed[3].id)

    page, total, active_total, usage_total = await service.list_instance_genes_with_summary(
        "instance-list",
        limit=2,
        offset=0,
    )

    assert total == 3
    assert active_total == 3
    assert usage_total == 12
    assert len(page) == 2
    assert all(gene.deleted_at is None for gene in page)


@pytest.mark.unit
async def test_list_instance_genes_with_summary_searches_metadata_before_pagination(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    await _create_instance(
        test_db,
        instance_id="instance-search-installed",
        tenant_id=test_project_db.tenant_id,
        created_by=test_user.id,
    )
    matching_gene = await service.create_gene(
        name="Contract Reviewer",
        slug=_slug("contract-reviewer"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        category="review",
    )
    other_gene = await service.create_gene(
        name="Load Tester",
        slug=_slug("load-tester"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        category="testing",
    )
    await service.install_gene("instance-search-installed", other_gene.id)
    await service.install_gene("instance-search-installed", matching_gene.id)

    page, total, active_total, usage_total = await service.list_instance_genes_with_summary(
        "instance-search-installed",
        limit=1,
        offset=0,
        search="contract",
        tenant_id=test_project_db.tenant_id,
    )

    assert total == 1
    assert active_total == 1
    assert usage_total == 0
    assert [gene.gene_id for gene in page] == [matching_gene.id]
