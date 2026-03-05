from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.model.cron.cron_job import CronJob
from src.domain.model.cron.cron_job_run import CronJobRun
from src.domain.model.cron.value_objects import CronRunStatus


class CronJobRepository(ABC):
    @abstractmethod
    async def save(self, domain_entity: CronJob) -> CronJob: ...

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> CronJob | None: ...

    @abstractmethod
    async def find_by_project(
        self,
        project_id: str,
        *,
        include_disabled: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CronJob]: ...

    @abstractmethod
    async def count_by_project(
        self,
        project_id: str,
        *,
        include_disabled: bool = False,
    ) -> int: ...

    @abstractmethod
    async def find_due_jobs(self, now: datetime) -> list[CronJob]: ...

    @abstractmethod
    async def delete(self, entity_id: str) -> bool: ...


class CronJobRunRepository(ABC):
    @abstractmethod
    async def save(self, domain_entity: CronJobRun) -> CronJobRun: ...

    @abstractmethod
    async def find_by_job(
        self,
        job_id: str,
        *,
        statuses: list[CronRunStatus] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CronJobRun]: ...

    @abstractmethod
    async def find_by_project(
        self,
        project_id: str,
        *,
        statuses: list[CronRunStatus] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CronJobRun]: ...

    @abstractmethod
    async def count_by_job(
        self,
        job_id: str,
        *,
        statuses: list[CronRunStatus] | None = None,
    ) -> int: ...
