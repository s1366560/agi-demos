"""Periodic evolution cycle scheduler.

Runs the full pipeline (summarize -> judge -> aggregate -> evolve)
on a configurable interval. Designed to be started/stopped by the
plugin lifecycle hooks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.application.services.llm_provider_manager import (
        LLMProviderManager,
    )
    from src.domain.llm_providers.llm_types import LLMClient
    from src.infrastructure.agent.plugins.skill_evolution.aggregation import (
        SkillSessionAggregator,
    )
    from src.infrastructure.agent.plugins.skill_evolution.config import (
        SkillEvolutionConfig,
    )
    from src.infrastructure.agent.plugins.skill_evolution.evolution_engine import (
        EvolutionEngine,
    )
    from src.infrastructure.agent.plugins.skill_evolution.session_judge import (
        SessionJudge,
    )
    from src.infrastructure.agent.plugins.skill_evolution.summarizer import (
        SessionSummarizer,
    )

logger = logging.getLogger(__name__)


class EvolutionScheduler:
    """Periodically triggers the evolution pipeline.

    The pipeline has four stages executed in order:
    1. Summarize unprocessed sessions
    2. Judge unscored sessions
    3. Aggregate by skill & filter by quality thresholds
    4. Evolve each qualifying skill group
    """

    def __init__(
        self,
        config: SkillEvolutionConfig,
        summarizer: SessionSummarizer,
        judge: SessionJudge,
        aggregator: SkillSessionAggregator,
        engine: EvolutionEngine,
        llm_provider_manager: LLMProviderManager,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._config = config
        self._summarizer = summarizer
        self._judge = judge
        self._aggregator = aggregator
        self._engine = engine
        self._llm_provider_manager = llm_provider_manager
        self._session_factory = session_factory
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if not self._config.enabled:
            logger.info("Skill evolution scheduler is disabled")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Skill evolution scheduler started (interval=%d min)",
            self._config.evolution_interval_minutes,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Skill evolution scheduler stopped")

    async def run_once(
        self, *, tenant_id: str, project_id: str | None = None
    ) -> dict[str, Any]:
        """Execute a single evolution cycle for a specific tenant.

        Returns a summary dict with counts for each stage.
        """
        return await self._execute_cycle(
            tenant_id=tenant_id, project_id=project_id
        )

    async def _loop(self) -> None:
        interval = self._config.evolution_interval_minutes * 60
        while self._running:
            try:
                await asyncio.sleep(interval)
                if not self._running:
                    break
                logger.info("Evolution cycle triggered — discovering tenants")
                tenant_ids = await self._discover_tenants()
                for tid in tenant_ids:
                    try:
                        result = await self._execute_cycle(tenant_id=tid)
                        logger.info(
                            "Evolution cycle complete for tenant=%s: %s", tid, result
                        )
                    except Exception:
                        logger.exception(
                            "Evolution cycle failed for tenant=%s", tid
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Evolution scheduling error")

    async def _execute_cycle(
        self, *, tenant_id: str, project_id: str | None = None
    ) -> dict[str, Any]:
        if self._session_factory is None:
            return {"skipped": True, "reason": "no session_factory"}

        result: dict[str, Any] = {
            "summarized": 0,
            "judged": 0,
            "groups": 0,
            "jobs": 0,
        }

        llm_client = await self._get_llm_client()

        async with self._session_factory() as db:
            from src.infrastructure.agent.plugins.skill_evolution.repository import (
                SkillEvolutionRepository,
            )

            repo = SkillEvolutionRepository(db)

            # Stage 1: Summarize unprocessed sessions
            unprocessed = await repo.get_unprocessed_sessions(
                tenant_id=tenant_id, limit=self._config.max_sessions_per_batch
            )
            if unprocessed:
                result["summarized"] = await self._summarizer.summarize_batch(
                    unprocessed, llm_client, repo
                )
                await db.commit()

            # Stage 2: Judge unscored sessions
            unscored = await repo.get_unscored_sessions(
                tenant_id=tenant_id, limit=self._config.max_sessions_per_batch
            )
            if unscored:
                result["judged"] = await self._judge.judge_batch(
                    unscored, llm_client, repo
                )
                await db.commit()

            # Stage 3: Aggregate
            groups = await self._aggregator.aggregate(repo, tenant_id=tenant_id)
            result["groups"] = len(groups)

            # Stage 4: Evolve
            if groups:
                jobs = await self._engine.evolve_all(
                    groups,
                    llm_client,
                    repo,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
                result["jobs"] = len(jobs)
                await db.commit()

            # Cleanup old sessions
            cleaned = await repo.cleanup_old_sessions(
                retention_days=self._config.session_retention_days
            )
            if cleaned > 0:
                await db.commit()
                logger.info("Cleaned %d old evolution sessions", cleaned)

        return result

    async def _get_llm_client(self) -> LLMClient:
        return await self._llm_provider_manager.get_llm_client()

    async def _discover_tenants(self) -> list[str]:
        """Discover tenant IDs to run evolution for.

        Scans the sessions table for distinct tenant IDs. Falls back
        to a single empty-string ID if no sessions exist.
        """
        if self._session_factory is None:
            return []
        try:
            async with self._session_factory() as db:
                from sqlalchemy import select

                from src.infrastructure.agent.plugins.skill_evolution.models import (
                    SkillEvolutionSession,
                )

                stmt = select(SkillEvolutionSession.tenant_id).distinct().limit(50)
                result = await db.execute(stmt)
                tenant_ids = [row[0] for row in result.all() if row[0]]
                return tenant_ids if tenant_ids else [""]
        except Exception:
            logger.exception("Failed to discover tenants for evolution")
            return [""]
