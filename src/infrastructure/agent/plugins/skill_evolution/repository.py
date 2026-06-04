"""Persistence layer for skill evolution sessions and jobs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    Skill,
)
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

    async def get_conversation_trace_events(
        self,
        *,
        conversation_id: str,
        limit: int = 120,
    ) -> list[dict[str, object]]:
        """Return persisted execution events usable for trajectory reconstruction."""
        stmt = (
            select(AgentExecutionEvent.event_type, AgentExecutionEvent.event_data)
            .where(
                AgentExecutionEvent.conversation_id == conversation_id,
                AgentExecutionEvent.event_type.in_(
                    ["assistant_message", "act", "observe", "complete", "error"]
                ),
            )
            .order_by(AgentExecutionEvent.event_time_us.asc(), AgentExecutionEvent.event_counter.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        events: list[dict[str, object]] = []
        for row in result.all():
            event_data = row.event_data if isinstance(row.event_data, dict) else {}
            events.append({"event_type": row.event_type, "event_data": event_data})
        return events

    async def get_unprocessed_sessions(
        self,
        *,
        tenant_id: str,
        skill_name: str | None = None,
        min_skill_sessions: int = 1,
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
        else:
            stmt = stmt.where(SkillEvolutionSession.skill_name != "__no_skill__")
        stmt = self._filter_by_min_skill_sessions(
            stmt,
            tenant_id=tenant_id,
            min_skill_sessions=min_skill_sessions,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_unscored_sessions(
        self,
        *,
        tenant_id: str,
        skill_name: str | None = None,
        min_skill_sessions: int = 1,
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
        if skill_name is not None:
            stmt = stmt.where(SkillEvolutionSession.skill_name == skill_name)
        else:
            stmt = stmt.where(SkillEvolutionSession.skill_name != "__no_skill__")
        stmt = self._filter_by_min_skill_sessions(
            stmt,
            tenant_id=tenant_id,
            min_skill_sessions=min_skill_sessions,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def _filter_by_min_skill_sessions(
        self,
        stmt: Select[tuple[SkillEvolutionSession]],
        *,
        tenant_id: str,
        min_skill_sessions: int,
    ) -> Select[tuple[SkillEvolutionSession]]:
        if min_skill_sessions <= 1:
            return stmt
        eligible_skill_names = (
            select(SkillEvolutionSession.skill_name)
            .where(
                SkillEvolutionSession.tenant_id == tenant_id,
                SkillEvolutionSession.skill_name != "__no_skill__",
            )
            .group_by(SkillEvolutionSession.skill_name)
            .having(func.count(SkillEvolutionSession.id) >= min_skill_sessions)
            .subquery()
        )
        return stmt.where(
            SkillEvolutionSession.skill_name.in_(select(eligible_skill_names.c.skill_name))
        )

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
            if row.skill_name not in existing_skill_names and row.skill_name != "__no_skill__"
        ]

    async def cleanup_old_sessions(self, *, retention_days: int = 30) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        stmt = (
            delete(SkillEvolutionSession)
            .where(SkillEvolutionSession.created_at < cutoff)
            .execution_options(synchronize_session=False)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0)

    # -- jobs -----------------------------------------------------------

    async def save_job(self, job: SkillEvolutionJob) -> SkillEvolutionJob:
        self._session.add(job)
        await self._session.flush()
        return job

    async def has_job_for_sessions(
        self,
        *,
        tenant_id: str,
        skill_name: str,
        session_ids: list[str],
    ) -> bool:
        """Return true when this exact session batch already produced a job."""
        job = await self.get_job_for_sessions(
            tenant_id=tenant_id,
            skill_name=skill_name,
            session_ids=session_ids,
            excluded_statuses={"rejected"},
        )
        return job is not None

    async def get_job_for_sessions(
        self,
        *,
        tenant_id: str,
        skill_name: str,
        session_ids: list[str],
        excluded_statuses: set[str] | None = None,
    ) -> SkillEvolutionJob | None:
        """Return the existing job for an exact session batch, if any."""
        if not session_ids:
            return None

        expected = set(session_ids)
        excluded = excluded_statuses or set()
        stmt = select(SkillEvolutionJob).where(
            SkillEvolutionJob.tenant_id == tenant_id,
            SkillEvolutionJob.skill_name == skill_name,
        )
        result = await self._session.execute(stmt)
        for job in result.scalars().all():
            if job.status in excluded:
                continue
            if set(job.session_ids or []) == expected:
                return job
        return None

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
        stmt = update(SkillEvolutionJob).where(SkillEvolutionJob.id == job_id).values(**values)
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

    async def count_sessions_by_skill(
        self,
        *,
        tenant_id: str,
        skill_name: str,
    ) -> int:
        stmt = select(func.count(SkillEvolutionSession.id)).where(
            SkillEvolutionSession.tenant_id == tenant_id,
            SkillEvolutionSession.skill_name == skill_name,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

    async def get_overview_stats(self, *, tenant_id: str) -> dict[str, object]:
        """Return tenant-level capture and processing totals for the evolution UI."""
        stmt = select(
            func.count(SkillEvolutionSession.id).label("total_sessions"),
            func.count()
            .filter(SkillEvolutionSession.skill_name != "__no_skill__")
            .label("skill_sessions"),
            func.count()
            .filter(SkillEvolutionSession.skill_name == "__no_skill__")
            .label("no_skill_sessions"),
            func.count()
            .filter(
                SkillEvolutionSession.skill_name != "__no_skill__",
                SkillEvolutionSession.processed == False,  # noqa: E712
            )
            .label("unprocessed_sessions"),
            func.count()
            .filter(
                SkillEvolutionSession.skill_name != "__no_skill__",
                SkillEvolutionSession.processed == True,  # noqa: E712
            )
            .label("processed_sessions"),
            func.count()
            .filter(
                SkillEvolutionSession.skill_name != "__no_skill__",
                SkillEvolutionSession.overall_score.isnot(None),
            )
            .label("scored_sessions"),
            func.count()
            .filter(SkillEvolutionSession.success == True)  # noqa: E712
            .label("successful_sessions"),
            func.avg(SkillEvolutionSession.overall_score)
            .filter(SkillEvolutionSession.skill_name != "__no_skill__")
            .label("avg_score"),
        ).where(SkillEvolutionSession.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        row = result.mappings().one()

        job_stmt = select(
            func.count(SkillEvolutionJob.id).label("total_jobs"),
            func.count().filter(SkillEvolutionJob.status == "pending_review").label("pending_jobs"),
            func.count().filter(SkillEvolutionJob.status == "applied").label("applied_jobs"),
            func.count().filter(SkillEvolutionJob.status == "skipped").label("skipped_jobs"),
            func.count().filter(SkillEvolutionJob.status == "rejected").label("rejected_jobs"),
        ).where(SkillEvolutionJob.tenant_id == tenant_id)
        job_result = await self._session.execute(job_stmt)
        job_row = job_result.mappings().one()

        return {
            "total_sessions": int(row["total_sessions"] or 0),
            "skill_sessions": int(row["skill_sessions"] or 0),
            "no_skill_sessions": int(row["no_skill_sessions"] or 0),
            "unprocessed_sessions": int(row["unprocessed_sessions"] or 0),
            "processed_sessions": int(row["processed_sessions"] or 0),
            "scored_sessions": int(row["scored_sessions"] or 0),
            "successful_sessions": int(row["successful_sessions"] or 0),
            "avg_score": float(row["avg_score"]) if row["avg_score"] is not None else None,
            "total_jobs": int(job_row["total_jobs"] or 0),
            "pending_jobs": int(job_row["pending_jobs"] or 0),
            "applied_jobs": int(job_row["applied_jobs"] or 0),
            "skipped_jobs": int(job_row["skipped_jobs"] or 0),
            "rejected_jobs": int(job_row["rejected_jobs"] or 0),
        }

    async def get_skill_session_summaries(
        self,
        *,
        tenant_id: str,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """Group captured sessions by skill name for the evolution overview."""
        job_counts = (
            select(
                SkillEvolutionJob.skill_name.label("skill_name"),
                func.count(SkillEvolutionJob.id).label("job_count"),
                func.count()
                .filter(SkillEvolutionJob.status == "pending_review")
                .label("pending_job_count"),
                func.max(SkillEvolutionJob.created_at).label("latest_job_at"),
            )
            .where(SkillEvolutionJob.tenant_id == tenant_id)
            .group_by(SkillEvolutionJob.skill_name)
            .subquery()
        )
        stmt = (
            select(
                func.min(Skill.id).label("skill_id"),
                SkillEvolutionSession.skill_name.label("skill_name"),
                func.count(SkillEvolutionSession.id).label("session_count"),
                func.count()
                .filter(SkillEvolutionSession.success == True)  # noqa: E712
                .label("success_count"),
                func.count()
                .filter(SkillEvolutionSession.processed == False)  # noqa: E712
                .label("unprocessed_count"),
                func.count()
                .filter(SkillEvolutionSession.overall_score.isnot(None))
                .label("scored_count"),
                func.avg(SkillEvolutionSession.overall_score).label("avg_score"),
                func.max(SkillEvolutionSession.created_at).label("latest_session_at"),
                func.coalesce(job_counts.c.job_count, 0).label("job_count"),
                func.coalesce(job_counts.c.pending_job_count, 0).label("pending_job_count"),
                job_counts.c.latest_job_at.label("latest_job_at"),
            )
            .outerjoin(
                job_counts,
                job_counts.c.skill_name == SkillEvolutionSession.skill_name,
            )
            .outerjoin(
                Skill,
                (Skill.tenant_id == tenant_id)
                & (Skill.name == SkillEvolutionSession.skill_name),
            )
            .where(
                SkillEvolutionSession.tenant_id == tenant_id,
                SkillEvolutionSession.skill_name != "__no_skill__",
            )
            .group_by(
                SkillEvolutionSession.skill_name,
                job_counts.c.job_count,
                job_counts.c.pending_job_count,
                job_counts.c.latest_job_at,
            )
            .order_by(
                func.count(SkillEvolutionSession.id).desc(),
                SkillEvolutionSession.skill_name.asc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        summaries: list[dict[str, object]] = []
        for row in result.mappings().all():
            summaries.append(
                {
                    "skill_id": row["skill_id"],
                    "skill_name": row["skill_name"],
                    "session_count": int(row["session_count"] or 0),
                    "success_count": int(row["success_count"] or 0),
                    "unprocessed_count": int(row["unprocessed_count"] or 0),
                    "scored_count": int(row["scored_count"] or 0),
                    "avg_score": (
                        float(row["avg_score"]) if row["avg_score"] is not None else None
                    ),
                    "latest_session_at": row["latest_session_at"],
                    "job_count": int(row["job_count"] or 0),
                    "pending_job_count": int(row["pending_job_count"] or 0),
                    "latest_job_at": row["latest_job_at"],
                }
            )
        return summaries

    async def list_recent_sessions(
        self,
        *,
        tenant_id: str,
        skill_name: str | None = None,
        limit: int = 50,
    ) -> list[SkillEvolutionSession]:
        """Return the newest captured sessions for audit and UI inspection."""
        stmt = (
            select(SkillEvolutionSession)
            .where(SkillEvolutionSession.tenant_id == tenant_id)
            .order_by(SkillEvolutionSession.created_at.desc())
            .limit(limit)
        )
        if skill_name is not None:
            stmt = stmt.where(SkillEvolutionSession.skill_name == skill_name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
