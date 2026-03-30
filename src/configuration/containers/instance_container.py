"""DI sub-container for instance/deploy/cluster/gene/template domain."""

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.cluster_service import ClusterService
from src.application.services.deploy_service import DeployService
from src.application.services.gene_service import GeneService
from src.application.services.instance_service import InstanceService
from src.application.services.instance_template_service import InstanceTemplateService
from src.domain.ports.repositories.cluster_repository import ClusterRepository
from src.domain.ports.repositories.deploy_record_repository import DeployRecordRepository
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
from src.domain.ports.repositories.instance_member_repository import (
    InstanceMemberRepository,
)
from src.domain.ports.repositories.instance_repository import InstanceRepository
from src.domain.ports.repositories.instance_template_repository import (
    InstanceTemplateRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cluster_repository import (
    SqlClusterRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_deploy_record_repository import (
    SqlDeployRecordRepository,
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
from src.infrastructure.adapters.secondary.persistence.sql_instance_member_repository import (
    SqlInstanceMemberRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_instance_repository import (
    SqlInstanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_instance_template_repository import (
    SqlInstanceTemplateRepository,
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

    # --- Instance ---

    def instance_repository(self) -> InstanceRepository:
        """Get InstanceRepository for instance persistence."""
        assert self._db is not None
        return SqlInstanceRepository(self._db)

    def instance_member_repository(self) -> InstanceMemberRepository:
        """Get InstanceMemberRepository for instance membership persistence."""
        assert self._db is not None
        return SqlInstanceMemberRepository(self._db)

    # --- Deploy ---

    def deploy_record_repository(self) -> DeployRecordRepository:
        """Get DeployRecordRepository for deploy record persistence."""
        assert self._db is not None
        return SqlDeployRecordRepository(self._db)

    # --- Cluster ---

    def cluster_repository(self) -> ClusterRepository:
        """Get ClusterRepository for cluster persistence."""
        assert self._db is not None
        return SqlClusterRepository(self._db)

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

    # --- Template ---

    def instance_template_repository(self) -> InstanceTemplateRepository:
        """Get InstanceTemplateRepository for instance template persistence."""
        assert self._db is not None
        return SqlInstanceTemplateRepository(self._db)

    # =================================================================
    # Service factories
    # =================================================================

    def instance_service(self) -> InstanceService:
        """Get InstanceService for instance lifecycle operations."""
        return InstanceService(
            instance_repo=self.instance_repository(),
            instance_member_repo=self.instance_member_repository(),
            deploy_record_repo=self.deploy_record_repository(),
            cluster_repo=self.cluster_repository(),
        )

    def deploy_service(self) -> DeployService:
        """Get DeployService for deployment lifecycle operations."""
        return DeployService(
            deploy_record_repo=self.deploy_record_repository(),
            instance_repo=self.instance_repository(),
            redis_client=self._redis_client,
        )

    def cluster_service(self) -> ClusterService:
        """Get ClusterService for cluster management operations."""
        return ClusterService(
            cluster_repo=self.cluster_repository(),
        )

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

    def instance_template_service(self) -> InstanceTemplateService:
        """Get InstanceTemplateService for template management operations."""
        return InstanceTemplateService(
            template_repo=self.instance_template_repository(),
        )
