"""Unit tests for creator audit fields in marketplace-style routes."""

from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
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
from src.application.services.cluster_service import ClusterService
from src.application.services.instance_template_service import InstanceTemplateService
from src.infrastructure.adapters.primary.web.gene_application_authority_v2 import (
    GeneApplicationAuthorityV2,
)
from src.infrastructure.adapters.primary.web.routers import clusters, instance_templates
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
from src.infrastructure.adapters.secondary.persistence.sql_cluster_repository import (
    SqlClusterRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_instance_template_repository import (
    SqlInstanceTemplateRepository,
)
from src.infrastructure.plugins.v2.gene_services import SqlGeneServiceFactoryV2
from src.infrastructure.plugins.v2.runtime import OperationContextV2


def _gene_authority(
    *,
    db: AsyncSession,
    tenant_id: str,
    current_user: User,
) -> GeneApplicationAuthorityV2:
    operation = cast(
        OperationContextV2,
        SimpleNamespace(require=lambda _service: db),
    )
    return cast(
        GeneApplicationAuthorityV2,
        SimpleNamespace(
            db=db,
            current_user=current_user,
            tenant_id=tenant_id,
            services=SqlGeneServiceFactoryV2().build(operation),
        ),
    )


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


@pytest.mark.unit
class TestMarketplaceAuditFields:
    @pytest.mark.asyncio
    async def test_create_cluster_records_authenticated_user(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        async def allow_access(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(clusters, "require_tenant_access", allow_access)

        authority = SimpleNamespace(
            db=test_db,
            current_user=test_user,
            tenant_id=test_project_db.tenant_id,
            services=SimpleNamespace(
                clusters=ClusterService(
                    cluster_repo=SqlClusterRepository(test_db),
                )
            ),
        )
        response = await create_cluster(
            ClusterCreate(name=f"Cluster {_slug('audit')}"),
            authority=authority,
        )

        assert response.created_by == test_user.id

    @pytest.mark.asyncio
    async def test_create_template_records_authenticated_user(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        async def allow_access(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(instance_templates, "require_tenant_access", allow_access)

        authority = SimpleNamespace(
            db=test_db,
            current_user=test_user,
            tenant_id=test_project_db.tenant_id,
            services=SimpleNamespace(
                templates=InstanceTemplateService(
                    template_repo=SqlInstanceTemplateRepository(test_db),
                )
            ),
        )
        response = await create_template(
            InstanceTemplateCreate(name="Audit Template", slug=_slug("template")),
            authority=authority,
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
            GeneCreate(
                name="Audit Gene",
                slug=_slug("gene"),
                source_ref="github:org/repo/gene",
                parent_gene_id="parent-gene-1",
            ),
            authority=_gene_authority(
                db=test_db,
                tenant_id=test_project_db.tenant_id,
                current_user=test_user,
            ),
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
            GenomeCreate(name="Audit Genome", slug=_slug("genome")),
            authority=_gene_authority(
                db=test_db,
                tenant_id=test_project_db.tenant_id,
                current_user=test_user,
            ),
        )

        assert response.created_by == test_user.id

    @pytest.mark.asyncio
    async def test_rate_gene_records_authenticated_user(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        authority = _gene_authority(
            db=test_db,
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
        )
        gene = await create_gene(
            GeneCreate(name="Rated Gene", slug=_slug("rated-gene")),
            authority=authority,
        )

        response = await rate_gene(
            gene.id,
            GeneRatingCreate(rating=5, comment="Useful"),
            authority=authority,
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
        authority = _gene_authority(
            db=test_db,
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
        )
        genome = await create_genome(
            GenomeCreate(name="Rated Genome", slug=_slug("rated-genome")),
            authority=authority,
        )

        response = await rate_genome(
            genome.id,
            GenomeRatingCreate(rating=4, comment="Works"),
            authority=authority,
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
        authority = _gene_authority(
            db=test_db,
            tenant_id=test_project_db.tenant_id,
            current_user=test_user,
        )
        gene = await create_gene(
            GeneCreate(name="Reviewed Gene", slug=_slug("reviewed-gene")),
            authority=authority,
        )

        review = await create_gene_review(
            gene.id,
            GeneReviewCreate(rating=5, content="Solid capability."),
            authority=authority,
        )

        assert review.user_id == test_user.id
        assert review.user_id != test_project_db.tenant_id

        await delete_gene_review(
            gene.id,
            review.id,
            authority=authority,
        )
