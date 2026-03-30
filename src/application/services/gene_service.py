"""
GeneService: Business logic for the Gene marketplace.

Handles Gene/Genome CRUD, install/uninstall lifecycle,
ratings, and evolution event tracking.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from src.domain.model.gene.enums import (
    ContentVisibility,
    EvolutionEventType,
    GeneReviewStatus,
    GeneSource,
    InstanceGeneStatus,
)
from src.domain.model.gene.gene import Gene, Genome
from src.domain.model.gene.instance_gene import (
    EvolutionEvent,
    GeneRating,
    GeneReview,
    GenomeRating,
    InstanceGene,
)
from src.domain.ports.repositories.evolution_event_repository import (
    EvolutionEventRepository,
)
from src.domain.ports.repositories.gene_rating_repository import (
    GeneRatingRepository,
)
from src.domain.ports.repositories.gene_repository import GeneRepository
from src.domain.ports.repositories.gene_review_repository import (
    GeneReviewRepository,
)
from src.domain.ports.repositories.genome_repository import GenomeRepository
from src.domain.ports.repositories.instance_gene_repository import (
    InstanceGeneRepository,
)

logger = logging.getLogger(__name__)


class GeneService:
    """Service for managing the Gene marketplace lifecycle."""

    def __init__(
        self,
        gene_repo: GeneRepository,
        genome_repo: GenomeRepository,
        instance_gene_repo: InstanceGeneRepository,
        gene_rating_repo: GeneRatingRepository,
        evolution_event_repo: EvolutionEventRepository,
        gene_review_repo: GeneReviewRepository,
    ) -> None:
        self._gene_repo = gene_repo
        self._genome_repo = genome_repo
        self._instance_gene_repo = instance_gene_repo
        self._gene_rating_repo = gene_rating_repo
        self._evolution_event_repo = evolution_event_repo
        self._gene_review_repo = gene_review_repo

    # ------------------------------------------------------------------
    # Gene marketplace CRUD
    # ------------------------------------------------------------------

    async def create_gene(  # noqa: PLR0913
        self,
        name: str,
        slug: str,
        created_by: str,
        tenant_id: str | None = None,
        description: str | None = None,
        short_description: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        source: str = "official",
        icon: str | None = None,
        version: str = "1.0.0",
        manifest: dict[str, Any] | None = None,
        dependencies: list[str] | None = None,
        synergies: list[str] | None = None,
        visibility: str = "public",
    ) -> Gene:
        """
        Create a new gene in the marketplace.

        Args:
            name: Gene display name.
            slug: URL-friendly unique identifier.
            created_by: User ID of the creator.
            tenant_id: Optional tenant scope.
            description: Full description.
            short_description: One-line summary.
            category: Gene category tag.
            tags: Searchable tags.
            source: Origin type (official, community, ...).
            icon: Icon URL or emoji.
            version: SemVer string.
            manifest: Structured capability manifest.
            dependencies: Slugs of required genes.
            synergies: Slugs of synergistic genes.
            visibility: public or org_private.

        Returns:
            The created Gene entity.
        """
        gene = Gene(
            name=name,
            slug=slug,
            created_by=created_by,
            tenant_id=tenant_id,
            description=description,
            short_description=short_description,
            category=category,
            tags=tags or [],
            source=GeneSource(source),
            icon=icon,
            version=version,
            manifest=manifest or {},
            dependencies=dependencies or [],
            synergies=synergies or [],
            visibility=ContentVisibility(visibility),
        )

        await self._gene_repo.save(gene)
        logger.info(f"Created gene {gene.id} (slug={slug})")
        return gene

    async def get_gene(self, gene_id: str) -> Gene | None:
        """
        Retrieve a gene by ID.

        Args:
            gene_id: Gene ID.

        Returns:
            Gene if found, None otherwise.
        """
        return await self._gene_repo.find_by_id(gene_id)

    async def list_genes(
        self,
        tenant_id: str | None = None,
        category: str | None = None,
        is_published: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Gene]:
        """
        List genes with optional filtering.

        Args:
            tenant_id: Filter by tenant.
            category: Filter by category (in-memory).
            is_published: Filter by published status (in-memory).
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of genes matching the filters.
        """
        if tenant_id:
            genes = await self._gene_repo.find_by_tenant(
                tenant_id,
                limit=limit,
                offset=offset,
            )
        else:
            genes = await self._gene_repo.search(
                query="",
                limit=limit,
                offset=offset,
            )

        if category is not None:
            genes = [g for g in genes if g.category == category]
        if is_published is not None:
            genes = [g for g in genes if g.is_published == is_published]

        return genes

    async def update_gene(
        self,
        gene_id: str,
        **fields: Any,  # noqa: ANN401
    ) -> Gene:
        """
        Update mutable fields on a gene.

        Args:
            gene_id: Gene ID.
            **fields: Keyword arguments for fields to update.

        Returns:
            Updated Gene entity.

        Raises:
            ValueError: If gene not found.
        """
        gene = await self._gene_repo.find_by_id(gene_id)
        if not gene:
            raise ValueError(f"Gene {gene_id} not found")

        allowed = {
            "name",
            "description",
            "short_description",
            "category",
            "tags",
            "icon",
            "version",
            "manifest",
            "dependencies",
            "synergies",
            "visibility",
            "source",
        }
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "visibility":
                value = ContentVisibility(value)
            if key == "source":
                value = GeneSource(value)
            setattr(gene, key, value)

        gene.updated_at = datetime.now(UTC)

        await self._gene_repo.save(gene)
        logger.info(f"Updated gene {gene_id}")
        return gene

    async def delete_gene(self, gene_id: str) -> None:
        """
        Soft-delete a gene.

        Args:
            gene_id: Gene ID.

        Raises:
            ValueError: If gene not found.
        """
        gene = await self._gene_repo.find_by_id(gene_id)
        if not gene:
            raise ValueError(f"Gene {gene_id} not found")

        gene.deleted_at = datetime.now(UTC)
        await self._gene_repo.save(gene)
        logger.info(f"Soft-deleted gene {gene_id}")

    async def publish_gene(self, gene_id: str) -> Gene:
        """
        Publish a gene to the marketplace.

        Args:
            gene_id: Gene ID.

        Returns:
            Updated Gene entity.

        Raises:
            ValueError: If gene not found.
        """
        gene = await self._gene_repo.find_by_id(gene_id)
        if not gene:
            raise ValueError(f"Gene {gene_id} not found")

        gene.is_published = True
        gene.review_status = GeneReviewStatus.auto_approved
        gene.updated_at = datetime.now(UTC)

        await self._gene_repo.save(gene)
        logger.info(f"Published gene {gene_id}")
        return gene

    async def unpublish_gene(self, gene_id: str) -> Gene:
        """
        Remove a gene from the marketplace.

        Args:
            gene_id: Gene ID.

        Returns:
            Updated Gene entity.

        Raises:
            ValueError: If gene not found.
        """
        gene = await self._gene_repo.find_by_id(gene_id)
        if not gene:
            raise ValueError(f"Gene {gene_id} not found")

        gene.is_published = False
        gene.updated_at = datetime.now(UTC)

        await self._gene_repo.save(gene)
        logger.info(f"Unpublished gene {gene_id}")
        return gene

    # ------------------------------------------------------------------
    # Genome CRUD
    # ------------------------------------------------------------------

    async def create_genome(
        self,
        name: str,
        slug: str,
        created_by: str,
        tenant_id: str | None = None,
        description: str | None = None,
        short_description: str | None = None,
        icon: str | None = None,
        gene_slugs: list[str] | None = None,
        config_override: dict[str, Any] | None = None,
        visibility: str = "public",
    ) -> Genome:
        """
        Create a new genome (curated gene bundle).

        Args:
            name: Genome display name.
            slug: URL-friendly unique identifier.
            created_by: User ID of the creator.
            tenant_id: Optional tenant scope.
            description: Full description.
            short_description: One-line summary.
            icon: Icon URL or emoji.
            gene_slugs: Ordered list of gene slugs.
            config_override: Per-gene config overrides.
            visibility: public or org_private.

        Returns:
            The created Genome entity.
        """
        genome = Genome(
            name=name,
            slug=slug,
            created_by=created_by,
            tenant_id=tenant_id,
            description=description,
            short_description=short_description,
            icon=icon,
            gene_slugs=gene_slugs or [],
            config_override=config_override or {},
            visibility=ContentVisibility(visibility),
        )

        await self._genome_repo.save(genome)
        logger.info(f"Created genome {genome.id} (slug={slug})")
        return genome

    async def get_genome(self, genome_id: str) -> Genome | None:
        """
        Retrieve a genome by ID.

        Args:
            genome_id: Genome ID.

        Returns:
            Genome if found, None otherwise.
        """
        return await self._genome_repo.find_by_id(genome_id)

    async def list_genomes(
        self,
        tenant_id: str | None = None,
        is_published: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Genome]:
        """
        List genomes with optional filtering.

        Args:
            tenant_id: Filter by tenant.
            is_published: Filter by published status (in-memory).
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of genomes matching the filters.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required to list genomes")

        genomes = await self._genome_repo.find_by_tenant(
            tenant_id,
            limit=limit,
            offset=offset,
        )

        if is_published is not None:
            genomes = [g for g in genomes if g.is_published == is_published]

        return genomes

    async def update_genome(
        self,
        genome_id: str,
        **fields: Any,  # noqa: ANN401
    ) -> Genome:
        """
        Update mutable fields on a genome.

        Args:
            genome_id: Genome ID.
            **fields: Keyword arguments for fields to update.

        Returns:
            Updated Genome entity.

        Raises:
            ValueError: If genome not found.
        """
        genome = await self._genome_repo.find_by_id(genome_id)
        if not genome:
            raise ValueError(f"Genome {genome_id} not found")

        allowed = {
            "name",
            "description",
            "short_description",
            "icon",
            "gene_slugs",
            "config_override",
            "visibility",
        }
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "visibility":
                value = ContentVisibility(value)
            setattr(genome, key, value)

        genome.updated_at = datetime.now(UTC)

        await self._genome_repo.save(genome)
        logger.info(f"Updated genome {genome_id}")
        return genome

    async def delete_genome(self, genome_id: str) -> None:
        """
        Soft-delete a genome.

        Args:
            genome_id: Genome ID.

        Raises:
            ValueError: If genome not found.
        """
        genome = await self._genome_repo.find_by_id(genome_id)
        if not genome:
            raise ValueError(f"Genome {genome_id} not found")

        genome.deleted_at = datetime.now(UTC)
        await self._genome_repo.save(genome)
        logger.info(f"Soft-deleted genome {genome_id}")

    async def publish_genome(self, genome_id: str) -> Genome:
        """
        Publish a genome to the marketplace.

        Args:
            genome_id: Genome ID.

        Returns:
            Updated Genome entity.

        Raises:
            ValueError: If genome not found.
        """
        genome = await self._genome_repo.find_by_id(genome_id)
        if not genome:
            raise ValueError(f"Genome {genome_id} not found")

        genome.is_published = True
        genome.updated_at = datetime.now(UTC)

        await self._genome_repo.save(genome)
        logger.info(f"Published genome {genome_id}")
        return genome

    # ------------------------------------------------------------------
    # Install / Uninstall
    # ------------------------------------------------------------------

    async def install_gene(
        self,
        instance_id: str,
        gene_id: str,
        genome_id: str | None = None,
        installed_version: str | None = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> InstanceGene:
        """
        Install a gene on an agent instance.

        Creates an InstanceGene record and logs a 'learned' evolution
        event.

        Args:
            instance_id: Target agent instance ID.
            gene_id: Gene to install.
            genome_id: Optional genome context.
            installed_version: Pinned version string.
            config_snapshot: Frozen config at install time.

        Returns:
            The created InstanceGene record.

        Raises:
            ValueError: If the gene does not exist or is already
                installed on the instance.
        """
        gene = await self._gene_repo.find_by_id(gene_id)
        if not gene:
            raise ValueError(f"Gene {gene_id} not found")

        existing = await self._instance_gene_repo.find_by_instance_and_gene(
            instance_id,
            gene_id,
        )
        if existing and existing.deleted_at is None:
            raise ValueError(f"Gene {gene_id} already installed on {instance_id}")

        instance_gene = InstanceGene(
            instance_id=instance_id,
            gene_id=gene_id,
            genome_id=genome_id,
            status=InstanceGeneStatus.installed,
            installed_version=installed_version or gene.version,
            config_snapshot=config_snapshot or {},
            installed_at=datetime.now(UTC),
        )

        await self._instance_gene_repo.save(instance_gene)

        event = EvolutionEvent(
            instance_id=instance_id,
            gene_id=gene_id,
            genome_id=genome_id,
            event_type=EvolutionEventType.learned,
            gene_name=gene.name,
            gene_slug=gene.slug,
        )
        await self._evolution_event_repo.save(event)

        logger.info(f"Installed gene {gene_id} on instance {instance_id}")
        return instance_gene

    async def uninstall_gene(self, instance_gene_id: str) -> None:
        """
        Uninstall a gene from an agent instance (soft-delete).

        Creates a 'forgot' evolution event.

        Args:
            instance_gene_id: InstanceGene record ID.

        Raises:
            ValueError: If the instance gene record is not found.
        """
        instance_gene = await self._instance_gene_repo.find_by_id(
            instance_gene_id,
        )
        if not instance_gene:
            raise ValueError(f"InstanceGene {instance_gene_id} not found")

        instance_gene.soft_delete()
        await self._instance_gene_repo.save(instance_gene)

        gene = await self._gene_repo.find_by_id(instance_gene.gene_id)
        gene_name = gene.name if gene else ""
        gene_slug = gene.slug if gene else None

        event = EvolutionEvent(
            instance_id=instance_gene.instance_id,
            gene_id=instance_gene.gene_id,
            genome_id=instance_gene.genome_id,
            event_type=EvolutionEventType.forgot,
            gene_name=gene_name,
            gene_slug=gene_slug,
        )
        await self._evolution_event_repo.save(event)

        logger.info(f"Uninstalled instance gene {instance_gene_id}")

    async def list_instance_genes(
        self,
        instance_id: str,
    ) -> list[InstanceGene]:
        """
        List all genes installed on an agent instance.

        Args:
            instance_id: Agent instance ID.

        Returns:
            List of InstanceGene records.
        """
        return await self._instance_gene_repo.find_by_instance(
            instance_id,
        )

    async def get_instance_gene(
        self,
        instance_gene_id: str,
    ) -> InstanceGene | None:
        """
        Retrieve an instance gene record by ID.

        Args:
            instance_gene_id: InstanceGene record ID.

        Returns:
            InstanceGene if found, None otherwise.
        """
        return await self._instance_gene_repo.find_by_id(
            instance_gene_id,
        )

    # ------------------------------------------------------------------
    # Ratings
    # ------------------------------------------------------------------

    async def rate_gene(
        self,
        gene_id: str,
        user_id: str,
        rating: int,
        comment: str | None = None,
    ) -> GeneRating:
        """
        Rate a gene (creates or updates the user's rating).

        Args:
            gene_id: Gene to rate.
            user_id: Rating author.
            rating: Numeric rating value.
            comment: Optional review text.

        Returns:
            The saved GeneRating.

        Raises:
            ValueError: If the gene does not exist.
        """
        gene = await self._gene_repo.find_by_id(gene_id)
        if not gene:
            raise ValueError(f"Gene {gene_id} not found")

        existing = await self._gene_rating_repo.find_user_gene_rating(
            gene_id,
            user_id,
        )
        if existing:
            existing.rating = rating
            existing.comment = comment
            await self._gene_rating_repo.save_gene_rating(existing)
            logger.info(f"Updated rating for gene {gene_id} by user {user_id}")
            return existing

        gene_rating = GeneRating(
            gene_id=gene_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
        )
        await self._gene_rating_repo.save_gene_rating(gene_rating)
        logger.info(f"Created rating for gene {gene_id} by user {user_id}")
        return gene_rating

    async def rate_genome(
        self,
        genome_id: str,
        user_id: str,
        rating: int,
        comment: str | None = None,
    ) -> GenomeRating:
        """
        Rate a genome (creates or updates the user's rating).

        Args:
            genome_id: Genome to rate.
            user_id: Rating author.
            rating: Numeric rating value.
            comment: Optional review text.

        Returns:
            The saved GenomeRating.

        Raises:
            ValueError: If the genome does not exist.
        """
        genome = await self._genome_repo.find_by_id(genome_id)
        if not genome:
            raise ValueError(f"Genome {genome_id} not found")

        existing = await self._gene_rating_repo.find_user_genome_rating(
            genome_id,
            user_id,
        )
        if existing:
            existing.rating = rating
            existing.comment = comment
            await self._gene_rating_repo.save_genome_rating(existing)
            logger.info(f"Updated rating for genome {genome_id} by user {user_id}")
            return existing

        genome_rating = GenomeRating(
            genome_id=genome_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
        )
        await self._gene_rating_repo.save_genome_rating(genome_rating)
        logger.info(f"Created rating for genome {genome_id} by user {user_id}")
        return genome_rating

    async def list_gene_ratings(
        self,
        gene_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GeneRating]:
        """
        List ratings for a gene.

        Args:
            gene_id: Gene ID.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of GeneRating records.
        """
        return await self._gene_rating_repo.find_gene_ratings(
            gene_id,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------
    # Evolution events
    # ------------------------------------------------------------------

    async def list_evolution_events(
        self,
        instance_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EvolutionEvent]:
        """
        List evolution events for an agent instance.

        Args:
            instance_id: Agent instance ID.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of EvolutionEvent records.
        """
        return await self._evolution_event_repo.find_by_instance(
            instance_id,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    async def create_gene_review(
        self,
        gene_id: str,
        user_id: str,
        rating: int,
        content: str,
        tenant_id: str,
    ) -> GeneReview:
        gene = await self._gene_repo.find_by_id(gene_id)
        if not gene:
            raise ValueError(f"Gene {gene_id} not found")

        review = GeneReview(
            gene_id=gene_id,
            user_id=user_id,
            rating=rating,
            content=content,
        )
        saved = await self._gene_review_repo.save(review)
        logger.info(f"Created review {saved.id} for gene {gene_id} by user {user_id}")
        return saved

    async def list_gene_reviews(
        self,
        gene_id: str,
        page: int,
        page_size: int,
        tenant_id: str,
    ) -> tuple[list[GeneReview], int]:
        return await self._gene_review_repo.find_by_gene_id(gene_id, page, page_size)

    async def delete_gene_review(
        self,
        review_id: str,
        user_id: str,
        tenant_id: str,
    ) -> None:
        review = await self._gene_review_repo.find_by_id(review_id)
        if not review:
            raise ValueError(f"Review {review_id} not found")
        if review.user_id != user_id:
            raise PermissionError("Cannot delete another user's review")
        await self._gene_review_repo.soft_delete(review_id, user_id)
        logger.info(f"Soft-deleted review {review_id}")
