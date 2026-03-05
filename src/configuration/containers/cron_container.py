"""DI sub-container for cron domain."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.cron_service import CronJobService
from src.domain.ports.repositories.cron_job_repository import (
    CronJobRepository,
    CronJobRunRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
    SqlCronJobRepository,
    SqlCronJobRunRepository,
)


class CronContainer:
    """Sub-container for cron-job-related services.

    Provides factory methods for cron repositories and the
    application-level CronJobService.
    """

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._db = db

    def cron_job_repository(self) -> CronJobRepository:
        """Get CronJobRepository for job persistence."""
        assert self._db is not None
        return SqlCronJobRepository(self._db)

    def cron_job_run_repository(self) -> CronJobRunRepository:
        """Get CronJobRunRepository for run persistence."""
        assert self._db is not None
        return SqlCronJobRunRepository(self._db)

    def cron_job_service(self) -> CronJobService:
        """Get CronJobService with all dependencies injected."""
        return CronJobService(
            cron_job_repo=self.cron_job_repository(),
            cron_job_run_repo=self.cron_job_run_repository(),
        )
