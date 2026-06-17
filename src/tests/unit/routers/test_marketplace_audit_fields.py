"""Unit tests for creator audit fields in marketplace-style routes."""

from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.cluster_schemas import ClusterCreate
from src.application.schemas.gene_schemas import (
    GeneCreate,
    GeneRatingCreate,
    GeneReviewCreate,
    GenomeCreate,
    GenomeRatingCreate,
)
from src.application.schemas.instance_template_schemas import InstanceTemplateCreate
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.routers.clusters import create_cluster
from src.infrastructure.adapters.primary.web.routers.genes import (
    create_gene,
    create_gene_review,
    create_genome,
    delete_gene_review,
    rate_gene,
    rate_genome,
)
from src.infrastructure.adapters.primary.web.routers.instance_templates import create_template
from src.infrastructure.adapters.secondary.persistence.models import Project, User


def _request() -> Request:
    return cast(
        Request,
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=DIContainer()))),
    )


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


@pytest.mark.unit
class TestMarketplaceAuditFields:
    @pytest.mark.asyncio
    async def test_create_cluster_records_authenticated_user(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        response = await create_cluster(
            _request(),
            ClusterCreate(name=f"Cluster {_slug('audit')}"),
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        assert response.created_by == test_user.id

    @pytest.mark.asyncio
    async def test_create_template_records_authenticated_user(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        response = await create_template(
            _request(),
            InstanceTemplateCreate(name="Audit Template", slug=_slug("template")),
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        assert response.created_by == test_user.id

    @pytest.mark.asyncio
    async def test_create_gene_records_authenticated_user(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        response = await create_gene(
            _request(),
            GeneCreate(
                name="Audit Gene",
                slug=_slug("gene"),
                source_ref="github:org/repo/gene",
                parent_gene_id="parent-gene-1",
            ),
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        assert response.created_by == test_user.id
        assert response.source_ref == "github:org/repo/gene"
        assert response.parent_gene_id == "parent-gene-1"

    @pytest.mark.asyncio
    async def test_create_genome_records_authenticated_user(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        response = await create_genome(
            _request(),
            GenomeCreate(name="Audit Genome", slug=_slug("genome")),
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        assert response.created_by == test_user.id

    @pytest.mark.asyncio
    async def test_rate_gene_records_authenticated_user(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        gene = await create_gene(
            _request(),
            GeneCreate(name="Rated Gene", slug=_slug("rated-gene")),
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        response = await rate_gene(
            _request(),
            gene.id,
            GeneRatingCreate(rating=5, comment="Useful"),
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        assert response.user_id == test_user.id
        assert response.user_id != test_project_db.tenant_id

    @pytest.mark.asyncio
    async def test_rate_genome_records_authenticated_user(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        genome = await create_genome(
            _request(),
            GenomeCreate(name="Rated Genome", slug=_slug("rated-genome")),
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        response = await rate_genome(
            _request(),
            genome.id,
            GenomeRatingCreate(rating=4, comment="Works"),
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        assert response.user_id == test_user.id
        assert response.user_id != test_project_db.tenant_id

    @pytest.mark.asyncio
    async def test_gene_reviews_use_authenticated_user_for_create_and_delete(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        gene = await create_gene(
            _request(),
            GeneCreate(name="Reviewed Gene", slug=_slug("reviewed-gene")),
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        review = await create_gene_review(
            _request(),
            gene.id,
            GeneReviewCreate(rating=5, content="Solid capability."),
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        assert review.user_id == test_user.id
        assert review.user_id != test_project_db.tenant_id

        await delete_gene_review(
            _request(),
            gene.id,
            review.id,
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
            db=test_db,
        )
