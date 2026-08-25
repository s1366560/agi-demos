"""DI sub-container for instance/deploy/cluster/gene/template domain."""

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.gene_service import GeneService
from src.domain.ports.repositories.evolution_event_repository import (
    EvolutionEventRepository,
)
from src.domain.ports.repositories.gene_rating_repository import GeneRatingRepository
from src.domain.ports.repositories.gene_repository import GeneRepository
from src.domain.ports.repositories.gene_review_repository import GeneReviewRepository
from src.domain.ports.repositories.genome_repository import GenomeRepository
from src.domain.ports.repositories.instance_gene_repository import (
    InstanceGeneRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_evolution_event_repository import (
    SqlEvolutionEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_gene_rating_repository import (
    SqlGeneRatingRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_gene_repository import (
    SqlGeneRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_gene_review_repository import (
    SqlGeneReviewRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_genome_repository import (
    SqlGenomeRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_instance_gene_repository import (
    SqlInstanceGeneRepository,
)


class InstanceContainer:
    """Sub-container for instance/deploy/cluster/gene/template repositories.

    Provides factory methods for all repositories in the instance management
    domain, including instances, deployments, clusters, genes, genomes,
    templates, and related entities.
    """

    def __init__(
        self,
        db: AsyncSession | None = None,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        self._db = db
        self._redis_client = redis_client

    # --- Gene ---

    def gene_repository(self) -> GeneRepository:
        """Get GeneRepository for gene marketplace persistence."""
        assert self._db is not None
        return SqlGeneRepository(self._db)

    def genome_repository(self) -> GenomeRepository:
        """Get GenomeRepository for genome persistence."""
        assert self._db is not None
        return SqlGenomeRepository(self._db)

    def instance_gene_repository(self) -> InstanceGeneRepository:
        """Get InstanceGeneRepository for instance-gene relationship persistence."""
        assert self._db is not None
        return SqlInstanceGeneRepository(self._db)

    def gene_rating_repository(self) -> GeneRatingRepository:
        """Get GeneRatingRepository for gene/genome rating persistence."""
        assert self._db is not None
        return SqlGeneRatingRepository(self._db)

    def evolution_event_repository(self) -> EvolutionEventRepository:
        """Get EvolutionEventRepository for evolution event persistence."""
        assert self._db is not None
        return SqlEvolutionEventRepository(self._db)

    def gene_review_repository(self) -> GeneReviewRepository:
        """Get GeneReviewRepository for gene review persistence."""
        assert self._db is not None
        return SqlGeneReviewRepository(self._db)

    # =================================================================
    # Service factories
    # =================================================================

    def gene_service(self) -> GeneService:
        """Get GeneService for gene marketplace operations."""
        return GeneService(
            gene_repo=self.gene_repository(),
            genome_repo=self.genome_repository(),
            instance_gene_repo=self.instance_gene_repository(),
            gene_rating_repo=self.gene_rating_repository(),
            evolution_event_repo=self.evolution_event_repository(),
            gene_review_repo=self.gene_review_repository(),
        )
