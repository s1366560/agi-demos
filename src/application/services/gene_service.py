"""
GeneService: Business logic for the Gene marketplace.

Handles Gene/Genome CRUD, install/uninstall lifecycle,
ratings, and evolution event tracking.
"""

import logging
from datetime import UTC, datetime
from typing import Any, cast

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
        source_ref: str | None = None,
        icon: str | None = None,
        version: str = "1.0.0",
        manifest: dict[str, Any] | None = None,
        dependencies: list[str] | None = None,
        synergies: list[str] | None = None,
        parent_gene_id: str | None = None,
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
            visibility: public, org_private, or unlisted.

        Returns:
            The created Gene entity.
        """
        existing_gene = await self._gene_repo.find_by_slug(slug, tenant_id=tenant_id)
        if existing_gene is not None:
            raise ValueError("Gene slug already exists")

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
            source_ref=source_ref,
            icon=icon,
            version=version,
            manifest=manifest or {},
            dependencies=dependencies or [],
            synergies=synergies or [],
            parent_gene_id=parent_gene_id,
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
        include_global: bool = False,
        category: str | None = None,
        search: str | None = None,
        slugs: list[str] | None = None,
        visibility: str | ContentVisibility | None = None,
        is_published: bool | None = None,
        exclude_installed_instance_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Gene]:
        """List genes with optional filtering."""
        genes, _total = await self.list_genes_with_total(
            tenant_id=tenant_id,
            include_global=include_global,
            category=category,
            search=search,
            slugs=slugs,
            visibility=visibility,
            is_published=is_published,
            exclude_installed_instance_id=exclude_installed_instance_id,
            limit=limit,
            offset=offset,
        )
        return genes

    async def list_genes_with_total(
        self,
        tenant_id: str | None = None,
        include_global: bool = False,
        category: str | None = None,
        search: str | None = None,
        slugs: list[str] | None = None,
        visibility: str | ContentVisibility | None = None,
        is_published: bool | None = None,
        exclude_installed_instance_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Gene], int]:
        """
        List genes with optional filtering and total count.

        Args:
            tenant_id: Filter by tenant.
            include_global: Include published public global entries for tenant lists.
            category: Filter by category.
            search: Search by name, slug, description, or short description.
            slugs: Exact slug allow-list.
            visibility: Filter by visibility.
            is_published: Filter by published status.
            exclude_installed_instance_id: Exclude genes active on this instance.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            Page of genes and total matching count.
        """
        visibility_filter = self._normalize_visibility_filter(visibility)
        effective_is_published = (
            True if tenant_id is None and is_published is None else is_published
        )
        genes = await self._gene_repo.find_by_filters(
            tenant_id=tenant_id,
            include_global=include_global,
            category=category,
            search=search,
            slugs=slugs,
            visibility=visibility_filter,
            is_published=effective_is_published,
            exclude_installed_instance_id=exclude_installed_instance_id,
            limit=limit,
            offset=offset,
        )
        total = await self._gene_repo.count_by_filters(
            tenant_id=tenant_id,
            include_global=include_global,
            category=category,
            search=search,
            slugs=slugs,
            visibility=visibility_filter,
            is_published=effective_is_published,
            exclude_installed_instance_id=exclude_installed_instance_id,
        )
        return genes, total

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
            "slug",
            "description",
            "short_description",
            "category",
            "tags",
            "icon",
            "version",
            "manifest",
            "dependencies",
            "synergies",
            "source_ref",
            "parent_gene_id",
            "visibility",
            "source",
        }
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "slug":
                if not isinstance(value, str) or not value:
                    raise ValueError("Gene slug cannot be empty")
                existing_gene = await self._gene_repo.find_by_slug(value, tenant_id=gene.tenant_id)
                if existing_gene is not None and existing_gene.id != gene_id:
                    raise ValueError("Gene slug already exists")
            if key == "visibility":
                value = ContentVisibility(value)
            if key == "source":
                value = GeneSource(value)
            if key in {"tags", "dependencies", "synergies"} and value is None:
                value = []
            if key == "manifest" and value is None:
                value = {}
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
            visibility: public, org_private, or unlisted.

        Returns:
            The created Genome entity.
        """
        existing_genome = await self._genome_repo.find_by_slug(slug, tenant_id=tenant_id)
        if existing_genome is not None:
            raise ValueError("Genome slug already exists")

        validated_gene_slugs = await self._validate_genome_gene_slugs(
            gene_slugs,
            tenant_id=tenant_id,
        )

        genome = Genome(
            name=name,
            slug=slug,
            created_by=created_by,
            tenant_id=tenant_id,
            description=description,
            short_description=short_description,
            icon=icon,
            gene_slugs=validated_gene_slugs,
            config_override=config_override or {},
            visibility=ContentVisibility(visibility),
        )

        await self._genome_repo.save(genome)
        logger.info(f"Created genome {genome.id} (slug={slug})")
        return genome

    async def _validate_genome_gene_slugs(
        self,
        gene_slugs: object,
        *,
        tenant_id: str | None,
    ) -> list[str]:
        if gene_slugs is None:
            return []
        if not isinstance(gene_slugs, list):
            raise ValueError("Genome gene slugs must be a list")

        normalized: list[str] = []
        seen: set[str] = set()
        for slug in cast(list[object], gene_slugs):
            if not isinstance(slug, str):
                raise ValueError("Genome gene slugs must be strings")
            normalized_slug = slug.strip()
            if not normalized_slug or normalized_slug in seen:
                continue
            seen.add(normalized_slug)
            normalized.append(normalized_slug)

        if not normalized:
            return []

        genes = await self._gene_repo.find_by_filters(
            tenant_id=tenant_id,
            include_global=tenant_id is not None,
            slugs=normalized,
            limit=len(normalized),
            offset=0,
        )
        found_slugs = {gene.slug for gene in genes}
        missing_slugs = [slug for slug in normalized if slug not in found_slugs]
        if missing_slugs:
            raise ValueError("Genome gene slugs not found")

        return normalized

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
        include_global: bool = False,
        search: str | None = None,
        visibility: str | ContentVisibility | None = None,
        is_published: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Genome]:
        """List genomes with optional filtering."""
        genomes, _total = await self.list_genomes_with_total(
            tenant_id=tenant_id,
            include_global=include_global,
            search=search,
            visibility=visibility,
            is_published=is_published,
            limit=limit,
            offset=offset,
        )
        return genomes

    async def list_genomes_with_total(
        self,
        tenant_id: str | None = None,
        include_global: bool = False,
        search: str | None = None,
        visibility: str | ContentVisibility | None = None,
        is_published: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Genome], int]:
        """
        List genomes with optional filtering and total count.

        Args:
            tenant_id: Filter by tenant.
            include_global: Include published public global entries for tenant lists.
            search: Search by name, slug, description, or short description.
            visibility: Filter by visibility.
            is_published: Filter by published status.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            Page of genomes and total matching count.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required to list genomes")

        visibility_filter = self._normalize_visibility_filter(visibility)
        genomes = await self._genome_repo.find_by_filters(
            tenant_id=tenant_id,
            include_global=include_global,
            search=search,
            visibility=visibility_filter,
            is_published=is_published,
            limit=limit,
            offset=offset,
        )
        total = await self._genome_repo.count_by_filters(
            tenant_id=tenant_id,
            include_global=include_global,
            search=search,
            visibility=visibility_filter,
            is_published=is_published,
        )
        return genomes, total

    @staticmethod
    def _normalize_visibility_filter(
        visibility: str | ContentVisibility | None,
    ) -> str | None:
        if visibility is None:
            return None
        try:
            return ContentVisibility(visibility).value
        except ValueError as exc:
            raise ValueError("Invalid visibility filter") from exc

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
            "slug",
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
            if key == "slug":
                if not isinstance(value, str) or not value:
                    raise ValueError("Genome slug cannot be empty")
                existing_genome = await self._genome_repo.find_by_slug(
                    value, tenant_id=genome.tenant_id
                )
                if existing_genome is not None and existing_genome.id != genome_id:
                    raise ValueError("Genome slug already exists")
            elif key == "visibility":
                value = ContentVisibility(value)
            elif key == "gene_slugs":
                value = await self._validate_genome_gene_slugs(value, tenant_id=genome.tenant_id)
            elif key == "config_override" and value is None:
                value = {}
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

    async def unpublish_genome(self, genome_id: str) -> Genome:
        """
        Remove a genome from the marketplace.

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

        genome.is_published = False
        genome.updated_at = datetime.now(UTC)

        await self._genome_repo.save(genome)
        logger.info(f"Unpublished genome {genome_id}")
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

        installed_at = datetime.now(UTC)
        if existing is not None:
            existing.genome_id = genome_id
            existing.status = InstanceGeneStatus.installed
            existing.installed_version = installed_version or gene.version
            existing.learning_output = None
            existing.config_snapshot = config_snapshot or {}
            existing.agent_self_eval = None
            existing.usage_count = 0
            existing.variant_published = False
            existing.installed_at = installed_at
            existing.deleted_at = None
            instance_gene = existing
        else:
            instance_gene = InstanceGene(
                instance_id=instance_id,
                gene_id=gene_id,
                genome_id=genome_id,
                status=InstanceGeneStatus.installed,
                installed_version=installed_version or gene.version,
                config_snapshot=config_snapshot or {},
                installed_at=installed_at,
            )

        await self._instance_gene_repo.save(instance_gene)
        _ = await self._gene_repo.adjust_install_count(gene_id, 1)

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

    async def install_genome(
        self,
        instance_id: str,
        genome_id: str,
        tenant_id: str,
        config_snapshot: dict[str, Any] | None = None,
    ) -> list[InstanceGene]:
        """
        Install every gene in a genome on an agent instance.

        Args:
            instance_id: Target agent instance ID.
            genome_id: Genome bundle to install.
            tenant_id: Tenant scope used to resolve tenant and public global genes.
            config_snapshot: Optional install config override.

        Returns:
            The installed InstanceGene records.

        Raises:
            ValueError: If the genome is missing, empty, references missing genes,
                or any member gene is already installed.
        """
        genome = await self._genome_repo.find_by_id(genome_id)
        if not genome:
            raise ValueError(f"Genome {genome_id} not found")
        if not genome.gene_slugs:
            raise ValueError("Genome has no genes")

        genes = await self._gene_repo.find_by_filters(
            tenant_id=tenant_id,
            include_global=True,
            slugs=genome.gene_slugs,
            limit=len(genome.gene_slugs),
            offset=0,
        )
        genes_by_slug = {gene.slug: gene for gene in genes}
        ordered_genes = [genes_by_slug[slug] for slug in genome.gene_slugs if slug in genes_by_slug]
        missing_slugs = [slug for slug in genome.gene_slugs if slug not in genes_by_slug]
        if missing_slugs:
            raise ValueError("Genome gene slugs not found")

        for gene in ordered_genes:
            existing = await self._instance_gene_repo.find_by_instance_and_gene(
                instance_id,
                gene.id,
            )
            if existing and existing.deleted_at is None:
                raise ValueError(f"Gene {gene.id} already installed on {instance_id}")

        installed_genes: list[InstanceGene] = []
        for gene in ordered_genes:
            installed_genes.append(
                await self.install_gene(
                    instance_id=instance_id,
                    gene_id=gene.id,
                    genome_id=genome.id,
                    config_snapshot=self._genome_gene_config(
                        genome.config_override,
                        config_snapshot,
                        gene.slug,
                    ),
                )
            )

        _ = await self._genome_repo.adjust_install_count(genome_id, 1)
        await self._evolution_event_repo.save(
            EvolutionEvent(
                instance_id=instance_id,
                genome_id=genome.id,
                event_type=EvolutionEventType.installed_genome,
                gene_name=genome.name,
                gene_slug=genome.slug,
                details={
                    "gene_count": len(installed_genes),
                    "gene_slugs": list(genome.gene_slugs),
                },
            )
        )

        logger.info(f"Installed genome {genome_id} on instance {instance_id}")
        return installed_genes

    @staticmethod
    def _genome_gene_config(
        genome_config: dict[str, Any],
        request_config: dict[str, Any] | None,
        gene_slug: str,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {}
        for source in (genome_config, request_config or {}):
            gene_specific_config = source.get(gene_slug)
            if isinstance(gene_specific_config, dict):
                config.update(cast(dict[str, Any], gene_specific_config))
                continue
            has_gene_specific_configs = any(isinstance(value, dict) for value in source.values())
            if not has_gene_specific_configs:
                config.update(source)
        return config

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

        was_installed = (
            instance_gene.deleted_at is None
            and instance_gene.status == InstanceGeneStatus.installed
        )
        instance_gene.soft_delete()
        await self._instance_gene_repo.save(instance_gene)

        gene = await self._gene_repo.find_by_id(instance_gene.gene_id)
        if gene is not None and was_installed:
            _ = await self._gene_repo.adjust_install_count(instance_gene.gene_id, -1)
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
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        tenant_id: str | None = None,
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
            limit=limit,
            offset=offset,
            search=search,
            tenant_id=tenant_id,
        )

    async def list_instance_genes_with_summary(
        self,
        instance_id: str,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        tenant_id: str | None = None,
    ) -> tuple[list[InstanceGene], int, int, int]:
        """List active instance genes with collection totals."""
        instance_genes = await self.list_instance_genes(
            instance_id,
            limit=limit,
            offset=offset,
            search=search,
            tenant_id=tenant_id,
        )
        total, installed_total, usage_total = await self._instance_gene_repo.summarize_by_instance(
            instance_id,
            search=search,
            tenant_id=tenant_id,
        )
        return instance_genes, total, installed_total, usage_total

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
            saved_rating = await self._gene_rating_repo.save_gene_rating(existing)
            await self._refresh_gene_average_rating(gene)
            logger.info(f"Updated rating for gene {gene_id} by user {user_id}")
            return saved_rating

        gene_rating = GeneRating(
            gene_id=gene_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
        )
        saved_rating = await self._gene_rating_repo.save_gene_rating(gene_rating)
        await self._refresh_gene_average_rating(gene)
        logger.info(f"Created rating for gene {gene_id} by user {user_id}")
        return saved_rating

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
            saved_rating = await self._gene_rating_repo.save_genome_rating(existing)
            await self._refresh_genome_average_rating(genome)
            logger.info(f"Updated rating for genome {genome_id} by user {user_id}")
            return saved_rating

        genome_rating = GenomeRating(
            genome_id=genome_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
        )
        saved_rating = await self._gene_rating_repo.save_genome_rating(genome_rating)
        await self._refresh_genome_average_rating(genome)
        logger.info(f"Created rating for genome {genome_id} by user {user_id}")
        return saved_rating

    async def _refresh_gene_average_rating(self, gene: Gene) -> None:
        gene.avg_rating = await self._gene_rating_repo.get_gene_average_rating(gene.id)
        gene.updated_at = datetime.now(UTC)
        _ = await self._gene_repo.save(gene)

    async def _refresh_genome_average_rating(self, genome: Genome) -> None:
        genome.avg_rating = await self._gene_rating_repo.get_genome_average_rating(genome.id)
        genome.updated_at = datetime.now(UTC)
        _ = await self._genome_repo.save(genome)

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

    async def list_genome_ratings(
        self,
        genome_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GenomeRating]:
        """
        List ratings for a genome.

        Args:
            genome_id: Genome ID.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of GenomeRating records.
        """
        return await self._gene_rating_repo.find_genome_ratings(
            genome_id,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------
    # Evolution events
    # ------------------------------------------------------------------

    async def create_evolution_event(
        self,
        instance_id: str,
        *,
        gene_id: str | None = None,
        genome_id: str | None = None,
        event_type: EvolutionEventType | str = EvolutionEventType.learned,
        gene_name: str = "",
        gene_slug: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> EvolutionEvent:
        """
        Create an evolution event record.

        Args:
            instance_id: Agent instance ID.
            gene_id: Optional gene ID.
            genome_id: Optional genome ID.
            event_type: Evolution event type.
            gene_name: Human-readable gene name snapshot.
            gene_slug: Optional gene slug snapshot.
            details: Additional event payload.

        Returns:
            Saved EvolutionEvent record.
        """
        event_type_value = (
            event_type
            if isinstance(event_type, EvolutionEventType)
            else EvolutionEventType(event_type)
        )
        event = EvolutionEvent(
            instance_id=instance_id,
            gene_id=gene_id,
            genome_id=genome_id,
            event_type=event_type_value,
            gene_name=gene_name,
            gene_slug=gene_slug,
            details=details or {},
        )
        return await self._evolution_event_repo.save(event)

    async def get_evolution_event(self, event_id: str) -> EvolutionEvent | None:
        """
        Get a single evolution event by ID.

        Args:
            event_id: Evolution event ID.

        Returns:
            EvolutionEvent or None if not found.
        """
        return await self._evolution_event_repo.find_by_id(event_id)

    async def list_evolution_events(
        self,
        instance_id: str | None = None,
        *,
        tenant_id: str | None = None,
        gene_id: str | None = None,
        event_type: EvolutionEventType | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EvolutionEvent]:
        """List evolution events for an agent instance or gene."""
        events, _total = await self.list_evolution_events_with_total(
            instance_id=instance_id,
            tenant_id=tenant_id,
            gene_id=gene_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
        return events

    async def list_evolution_events_with_total(
        self,
        instance_id: str | None = None,
        *,
        tenant_id: str | None = None,
        gene_id: str | None = None,
        event_type: EvolutionEventType | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EvolutionEvent], int]:
        """
        List evolution events for an agent instance or gene with total count.

        Args:
            instance_id: Agent instance ID.
            tenant_id: Optional tenant scope for the event's instance.
            gene_id: Optional gene ID.
            event_type: Optional event type filter.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            Page of EvolutionEvent records and total matching count.
        """
        if not instance_id and not gene_id:
            raise ValueError("Either instance_id or gene_id is required")

        event_type_value = (
            event_type
            if event_type is None or isinstance(event_type, EvolutionEventType)
            else EvolutionEventType(event_type)
        )
        events = await self._evolution_event_repo.find_by_filters(
            tenant_id=tenant_id,
            instance_id=instance_id,
            gene_id=gene_id,
            event_type=event_type_value,
            limit=limit,
            offset=offset,
        )
        total = await self._evolution_event_repo.count_by_filters(
            tenant_id=tenant_id,
            instance_id=instance_id,
            gene_id=gene_id,
            event_type=event_type_value,
        )
        return events, total

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
        gene_id: str,
        review_id: str,
        user_id: str,
        tenant_id: str,
    ) -> None:
        review = await self._gene_review_repo.find_by_id(review_id)
        if not review:
            raise ValueError(f"Review {review_id} not found")
        if review.gene_id != gene_id:
            raise ValueError(f"Review {review_id} not found")
        if review.user_id != user_id:
            raise PermissionError("Cannot delete another user's review")
        await self._gene_review_repo.soft_delete(review_id, user_id)
        logger.info(f"Soft-deleted review {review_id}")
