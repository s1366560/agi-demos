"""Periodic evolution cycle scheduler.

Runs the full pipeline (summarize -> judge -> aggregate -> evolve)
on a configurable interval. Designed to be started/stopped by the
plugin lifecycle hooks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
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

_CAPTURE_TRIGGER_DELAY_SECONDS = 5.0
_STARTUP_TRIGGER_DELAY_SECONDS = 0.1
_BACKLOG_CONTINUE_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class _EvolutionRunRequest:
    tenant_id: str
    project_id: str | None = None
    skill_name: str | None = None


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
        self._run_lock = asyncio.Lock()
        self._pending_tasks: dict[_EvolutionRunRequest, asyncio.Task[None]] = {}
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
        self.schedule_all(reason="startup", delay_seconds=_STARTUP_TRIGGER_DELAY_SECONDS)
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
        for task in list(self._pending_tasks.values()):
            task.cancel()
        for task in list(self._pending_tasks.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._pending_tasks.clear()
        logger.info("Skill evolution scheduler stopped")

    def schedule_all(self, *, reason: str, delay_seconds: float = 0.0) -> bool:
        """Schedule a background sweep for all tenants with captured sessions."""
        return self.schedule_run(
            tenant_id="",
            reason=reason,
            delay_seconds=delay_seconds,
        )

    def schedule_run(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
        reason: str = "capture",
        delay_seconds: float = _CAPTURE_TRIGGER_DELAY_SECONDS,
        allow_when_stopped: bool = False,
    ) -> bool:
        """Schedule an autonomous evolution cycle without blocking the caller.

        Requests are keyed by tenant/project/skill so bursty after-turn capture
        coalesces into one background pipeline run.
        """
        if not self._config.enabled:
            return False
        if not allow_when_stopped and not self._running:
            return False

        request = _EvolutionRunRequest(
            tenant_id=tenant_id,
            project_id=project_id,
            skill_name=skill_name,
        )
        existing = self._pending_tasks.get(request)
        if existing is not None and not existing.done():
            return False

        task = asyncio.create_task(
            self._delayed_execute_request(
                request,
                delay_seconds=max(0.0, delay_seconds),
                reason=reason,
                require_running=not allow_when_stopped,
            )
        )
        self._track_request(request, task)
        return True

    def _track_request(
        self,
        request: _EvolutionRunRequest,
        task: asyncio.Task[None],
    ) -> None:
        self._pending_tasks[request] = task

        def _discard_if_current(done_task: asyncio.Task[None]) -> None:
            if self._pending_tasks.get(request) is done_task:
                self._pending_tasks.pop(request, None)

        task.add_done_callback(_discard_if_current)

    async def run_once(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
    ) -> dict[str, Any]:
        """Execute a single evolution cycle for a specific tenant.

        Returns a summary dict with counts for each stage.
        """
        return await self._execute_serialized(
            tenant_id=tenant_id, project_id=project_id, skill_name=skill_name
        )

    def _is_running(self) -> bool:
        return self._running

    async def _loop(self) -> None:
        interval = self._config.evolution_interval_minutes * 60
        while self._is_running():
            try:
                await asyncio.sleep(interval)
                if not self._is_running():
                    break
                logger.info("Evolution cycle triggered — discovering tenants")
                await self._execute_all_tenants(reason="interval")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Evolution scheduling error")

    async def _delayed_execute_request(
        self,
        request: _EvolutionRunRequest,
        *,
        delay_seconds: float,
        reason: str,
        require_running: bool = True,
    ) -> None:
        try:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            if require_running and not self._is_running():
                return
            if request.tenant_id:
                result = await self._execute_serialized(
                    tenant_id=request.tenant_id,
                    project_id=request.project_id,
                    skill_name=request.skill_name,
                )
                logger.info(
                    "Evolution cycle complete for tenant=%s skill=%s reason=%s: %s",
                    request.tenant_id,
                    request.skill_name or "*",
                    reason,
                    result,
                )
                self._schedule_backlog_continuation(request, result)
            else:
                await self._execute_all_tenants(reason=reason)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Autonomous evolution request failed tenant=%s skill=%s reason=%s",
                request.tenant_id or "*",
                request.skill_name or "*",
                reason,
            )

    async def _execute_all_tenants(self, *, reason: str) -> None:
        tenant_ids = await self._discover_tenants()
        for tid in tenant_ids:
            try:
                result = await self._execute_serialized(tenant_id=tid)
                logger.info(
                    "Evolution cycle complete for tenant=%s reason=%s: %s",
                    tid,
                    reason,
                    result,
                )
                self._schedule_backlog_continuation(
                    _EvolutionRunRequest(tenant_id=tid),
                    result,
                )
            except Exception:
                logger.exception("Evolution cycle failed for tenant=%s", tid)

    def _schedule_backlog_continuation(
        self,
        request: _EvolutionRunRequest,
        result: dict[str, Any],
    ) -> None:
        if not self._is_running():
            return
        if not self._should_continue_backlog(result):
            return

        logger.info(
            "Skill evolution backlog remains for tenant=%s skill=%s; scheduling continuation",
            request.tenant_id,
            request.skill_name or "*",
        )
        task = asyncio.create_task(
            self._delayed_execute_request(
                request,
                delay_seconds=_BACKLOG_CONTINUE_DELAY_SECONDS,
                reason="backlog",
            )
        )
        self._track_request(request, task)

    def _should_continue_backlog(self, result: dict[str, Any]) -> bool:
        batch_limit = self._config.max_sessions_per_batch
        return (
            int(result.get("summarized") or 0) >= batch_limit
            or int(result.get("judged") or 0) >= batch_limit
        )

    async def _execute_serialized(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
    ) -> dict[str, Any]:
        async with self._run_lock:
            return await self._execute_cycle(
                tenant_id=tenant_id,
                project_id=project_id,
                skill_name=skill_name,
            )

    async def _execute_cycle(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
    ) -> dict[str, Any]:
        if self._session_factory is None:
            return {"skipped": True, "reason": "no session_factory"}

        result: dict[str, Any] = {
            "summarized": 0,
            "judged": 0,
            "groups": 0,
            "jobs": 0,
            "blocked_by_review": 0,
        }

        async with self._session_factory() as db:
            from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
                SqlSkillRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
                SqlSkillVersionRepository,
            )
            from src.infrastructure.agent.plugins.skill_evolution.repository import (
                SkillEvolutionRepository,
            )

            repo = SkillEvolutionRepository(db)
            run_config = await _load_tenant_config(db, tenant_id=tenant_id, default_config=self._config)
            self._summarizer._config = run_config
            self._judge._config = run_config
            self._aggregator._config = run_config
            self._engine._config = run_config
            skill_repo = SqlSkillRepository(db)
            skill_version_repo = SqlSkillVersionRepository(db)
            llm_client = await self._get_llm_client(db=db, tenant_id=tenant_id)

            # Stage 1: Summarize unprocessed sessions
            unprocessed = await repo.get_unprocessed_sessions(
                tenant_id=tenant_id,
                skill_name=skill_name,
                project_id=project_id,
                filter_project_id=skill_name is not None or project_id is not None,
                min_skill_sessions=run_config.scoring_min_sessions_per_skill,
                limit=run_config.max_sessions_per_batch,
            )
            logger.info(
                "Skill evolution summarization stage tenant=%s skill=%s pending=%d",
                tenant_id,
                skill_name or "*",
                len(unprocessed),
            )
            if unprocessed:
                result["summarized"] = await self._summarizer.summarize_batch(
                    unprocessed, llm_client, repo
                )
                await db.commit()

            # Stage 2: Judge unscored sessions
            unscored = await repo.get_unscored_sessions(
                tenant_id=tenant_id,
                skill_name=skill_name,
                project_id=project_id,
                filter_project_id=skill_name is not None or project_id is not None,
                min_skill_sessions=run_config.scoring_min_sessions_per_skill,
                limit=run_config.max_sessions_per_batch,
            )
            logger.info(
                "Skill evolution judging stage tenant=%s skill=%s pending=%d",
                tenant_id,
                skill_name or "*",
                len(unscored),
            )
            if unscored:
                result["judged"] = await self._judge.judge_batch(unscored, llm_client, repo)
                await db.commit()

            # Stage 3: Aggregate
            groups = await self._aggregator.aggregate(
                repo,
                tenant_id=tenant_id,
                project_id=project_id,
                filter_project_id=skill_name is not None or project_id is not None,
            )
            if skill_name is not None:
                groups = {
                    name: group for name, group in groups.items() if group.skill_name == skill_name
                }
            result["groups"] = len(groups)

            # Stage 4: Evolve
            if groups:
                jobs = await self._engine.evolve_all(
                    groups,
                    llm_client,
                    repo,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    skill_repository=skill_repo,
                    skill_version_repository=skill_version_repo,
                )
                result["jobs"] = len(jobs)
                result["blocked_by_review"] = self._engine.last_blocked_by_review_count
                await db.commit()

            # Cleanup old sessions
            cleaned = await repo.cleanup_old_sessions(
                retention_days=run_config.session_retention_days
            )
            if cleaned > 0:
                await db.commit()
                logger.info("Cleaned %d old evolution sessions", cleaned)

        return result

    async def _get_llm_client(
        self,
        *,
        db: AsyncSession,
        tenant_id: str,
    ) -> LLMClient:
        try:
            return await self._llm_provider_manager.get_llm_client(
                tenant_id=tenant_id,
            )
        except TypeError:
            return await self._llm_provider_manager.get_llm_client()
        except RuntimeError:
            logger.info("No registered LLM client for skill evolution; resolving tenant provider")

        from src.application.services.llm_provider_manager import (
            OperationType as ManagerOperationType,
        )
        from src.application.services.provider_resolution_service import (
            ProviderResolutionService,
        )
        from src.domain.llm_providers.models import OperationType as ProviderOperationType
        from src.infrastructure.persistence.llm_providers_repository import (
            SQLAlchemyProviderRepository,
        )

        repository = SQLAlchemyProviderRepository(session=db)
        resolver = ProviderResolutionService(repository)
        provider = await resolver.resolve_provider(
            tenant_id=tenant_id,
            operation_type=ProviderOperationType.LLM,
        )
        self._llm_provider_manager.register_provider(provider)
        _ = await self._llm_provider_manager.health_check_all()
        return await self._llm_provider_manager.get_llm_client(
            tenant_id=tenant_id,
            operation=ManagerOperationType.LLM,
            preferred_provider=provider.provider_type,
            allow_fallback=False,
        )

    async def _discover_tenants(self) -> list[str]:
        """Discover tenant IDs to run evolution for.

        Scans the sessions table for distinct tenant IDs. Falls back
        to a single empty-string ID if no sessions exist.
        """
        if self._session_factory is None:
            return []
        try:
            async with self._session_factory() as db:
                from sqlalchemy import func, select

                from src.infrastructure.agent.plugins.skill_evolution.models import (
                    SkillEvolutionSession,
                )

                stmt = (
                    select(SkillEvolutionSession.tenant_id)
                    .where(SkillEvolutionSession.tenant_id != "")
                    .group_by(SkillEvolutionSession.tenant_id)
                    .order_by(func.count(SkillEvolutionSession.id).desc())
                    .limit(100)
                )
                result = await db.execute(stmt)
                tenant_ids = [row[0] for row in result.all() if row[0]]
                logger.info(
                    "Discovered %d tenants for skill evolution: %s",
                    len(tenant_ids),
                    tenant_ids[:10],
                )
                return tenant_ids if tenant_ids else [""]
        except Exception:
            logger.exception("Failed to discover tenants for evolution")
            return [""]


async def _load_tenant_config(
    db: AsyncSession,
    *,
    tenant_id: str,
    default_config: SkillEvolutionConfig,
) -> SkillEvolutionConfig:
    from sqlalchemy.exc import SQLAlchemyError

    from src.infrastructure.adapters.secondary.persistence.plugin_config_repository import (
        PluginConfigRepository,
    )

    try:
        row = await PluginConfigRepository(db).get_by_tenant_and_plugin(
            tenant_id=tenant_id,
            plugin_name="skill_evolution",
        )
    except (AttributeError, SQLAlchemyError):
        return default_config
    config = row.config if row is not None and isinstance(row.config, dict) else {}
    return default_config.with_overrides(config)
