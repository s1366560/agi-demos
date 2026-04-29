"""Persistence layer for skill evolution sessions and jobs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.agent.plugins.skill_evolution.models import (
    SkillEvolutionJob,
    SkillEvolutionSession,
)

logger = logging.getLogger(__name__)


class SkillEvolutionRepository:
    """CRUD operations for skill evolution data.

    Takes an ``AsyncSession`` directly (same pattern as other
    SQL repositories in the project).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- sessions -------------------------------------------------------

    async def save_session(self, session: SkillEvolutionSession) -> SkillEvolutionSession:
        self._session.add(session)
        await self._session.flush()
        return session

    async def get_unprocessed_sessions(
        self,
        *,
        tenant_id: str,
        skill_name: str | None = None,
        limit: int = 50,
    ) -> list[SkillEvolutionSession]:
        stmt = (
            select(SkillEvolutionSession)
            .where(
                SkillEvolutionSession.tenant_id == tenant_id,
                SkillEvolutionSession.processed == False,  # noqa: E712
            )
            .order_by(SkillEvolutionSession.created_at.asc())
            .limit(limit)
        )
        if skill_name is not None:
            stmt = stmt.where(SkillEvolutionSession.skill_name == skill_name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_unscored_sessions(
        self,
        *,
        tenant_id: str,
        limit: int = 50,
    ) -> list[SkillEvolutionSession]:
        stmt = (
            select(SkillEvolutionSession)
            .where(
                SkillEvolutionSession.tenant_id == tenant_id,
                SkillEvolutionSession.processed == True,  # noqa: E712
                SkillEvolutionSession.overall_score.is_(None),
            )
            .order_by(SkillEvolutionSession.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_processed(self, session_ids: list[str]) -> None:
        stmt = (
            update(SkillEvolutionSession)
            .where(SkillEvolutionSession.id.in_(session_ids))
            .values(processed=True)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def update_summary(
        self, session_id: str, *, trajectory: dict[str, object], summary: str
    ) -> None:
        stmt = (
            update(SkillEvolutionSession)
            .where(SkillEvolutionSession.id == session_id)
            .values(trajectory=trajectory, summary=summary, processed=True)
        )
        await self._session.execute(stmt)

    async def update_scores(
        self,
        session_id: str,
        *,
        judge_scores: dict[str, object],
        overall_score: float,
    ) -> None:
        stmt = (
            update(SkillEvolutionSession)
            .where(SkillEvolutionSession.id == session_id)
            .values(judge_scores=judge_scores, overall_score=overall_score)
        )
        await self._session.execute(stmt)

    async def get_sessions_by_skill(
        self,
        *,
        tenant_id: str,
        skill_name: str,
        min_score: float | None = None,
        limit: int = 100,
    ) -> list[SkillEvolutionSession]:
        stmt = (
            select(SkillEvolutionSession)
            .where(
                SkillEvolutionSession.tenant_id == tenant_id,
                SkillEvolutionSession.skill_name == skill_name,
                SkillEvolutionSession.overall_score.isnot(None),
            )
            .order_by(SkillEvolutionSession.created_at.desc())
            .limit(limit)
        )
        if min_score is not None:
            stmt = stmt.where(SkillEvolutionSession.overall_score >= min_score)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_scored_sessions_grouped_by_skill(
        self,
        *,
        tenant_id: str,
        min_sessions: int = 5,
        min_avg_score: float = 0.6,
    ) -> list[dict[str, object]]:
        sub = (
            select(
                SkillEvolutionSession.skill_name,
                func.count(SkillEvolutionSession.id).label("session_count"),
                func.avg(SkillEvolutionSession.overall_score).label("avg_score"),
                func.count(
                    func.nullif(SkillEvolutionSession.success == True, False)  # noqa: E712
                ).label("success_count"),
            )
            .where(
                SkillEvolutionSession.tenant_id == tenant_id,
                SkillEvolutionSession.overall_score.isnot(None),
            )
            .group_by(SkillEvolutionSession.skill_name)
            .having(
                func.count(SkillEvolutionSession.id) >= min_sessions,
                func.avg(SkillEvolutionSession.overall_score) >= min_avg_score,
            )
            .subquery()
        )
        stmt = select(sub).order_by(sub.c.session_count.desc())
        result = await self._session.execute(stmt)
        return [
            {
                "skill_name": row.skill_name,
                "session_count": row.session_count,
                "avg_score": float(row.avg_score) if row.avg_score else 0.0,
                "success_count": row.success_count or 0,
            }
            for row in result.all()
        ]

    async def get_skill_names_without_skills(
        self,
        *,
        tenant_id: str,
        existing_skill_names: set[str],
    ) -> list[dict[str, object]]:
        """Return skill names from sessions that don't match any existing skill."""
        stmt = (
            select(
                SkillEvolutionSession.skill_name,
                func.count(SkillEvolutionSession.id).label("session_count"),
            )
            .where(
                SkillEvolutionSession.tenant_id == tenant_id,
                SkillEvolutionSession.overall_score.isnot(None),
            )
            .group_by(SkillEvolutionSession.skill_name)
            .having(func.count(SkillEvolutionSession.id) >= 3)
            .order_by(func.count(SkillEvolutionSession.id).desc())
        )
        result = await self._session.execute(stmt)
        return [
            {"skill_name": row.skill_name, "session_count": row.session_count}
            for row in result.all()
            if row.skill_name not in existing_skill_names
            and row.skill_name != "__no_skill__"
        ]

    async def cleanup_old_sessions(self, *, retention_days: int = 30) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        stmt = delete(SkillEvolutionSession).where(
            SkillEvolutionSession.created_at < cutoff
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount or 0  # type: ignore[attr-defined,return-value]

    # -- jobs -----------------------------------------------------------

    async def save_job(self, job: SkillEvolutionJob) -> SkillEvolutionJob:
        self._session.add(job)
        await self._session.flush()
        return job

    async def get_pending_jobs(
        self, *, tenant_id: str, skill_name: str | None = None
    ) -> list[SkillEvolutionJob]:
        stmt = (
            select(SkillEvolutionJob)
            .where(
                SkillEvolutionJob.tenant_id == tenant_id,
                SkillEvolutionJob.status == "pending_review",
            )
            .order_by(SkillEvolutionJob.created_at.desc())
        )
        if skill_name is not None:
            stmt = stmt.where(SkillEvolutionJob.skill_name == skill_name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_job(self, job_id: str) -> SkillEvolutionJob | None:
        stmt = select(SkillEvolutionJob).where(SkillEvolutionJob.id == job_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_job_status(
        self,
        job_id: str,
        *,
        status: str,
        skill_version_id: str | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status}
        if status == "applied":
            values["applied_at"] = datetime.now(UTC)
        if skill_version_id is not None:
            values["skill_version_id"] = skill_version_id
        stmt = (
            update(SkillEvolutionJob)
            .where(SkillEvolutionJob.id == job_id)
            .values(**values)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_jobs(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        skill_name: str | None = None,
        limit: int = 50,
    ) -> list[SkillEvolutionJob]:
        stmt = (
            select(SkillEvolutionJob)
            .where(SkillEvolutionJob.tenant_id == tenant_id)
            .order_by(SkillEvolutionJob.created_at.desc())
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(SkillEvolutionJob.status == status)
        if skill_name is not None:
            stmt = stmt.where(SkillEvolutionJob.skill_name == skill_name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
