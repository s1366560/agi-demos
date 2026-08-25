"""DI sub-container for instance/deploy/cluster/gene/template domain."""

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession


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
