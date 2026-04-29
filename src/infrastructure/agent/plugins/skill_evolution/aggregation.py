"""Aggregate scored sessions by skill name for evolution decisions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.infrastructure.agent.plugins.skill_evolution.config import SkillEvolutionConfig
from src.infrastructure.agent.plugins.skill_evolution.models import (
    SkillEvolutionSession,
)
from src.infrastructure.agent.plugins.skill_evolution.repository import (
    SkillEvolutionRepository,
)

logger = logging.getLogger(__name__)


@dataclass
class SkillSessionGroup:
    """A group of scored sessions for a single skill."""

    skill_name: str
    sessions: list[SkillEvolutionSession] = field(default_factory=list)
    session_count: int = 0
    avg_score: float = 0.0
    success_rate: float = 0.0

    def add(self, session: SkillEvolutionSession) -> None:
        self.sessions.append(session)
        self.session_count = len(self.sessions)
        scores = [
            s.overall_score
            for s in self.sessions
            if s.overall_score is not None
        ]
        self.avg_score = sum(scores) / len(scores) if scores else 0.0
        successes = sum(1 for s in self.sessions if s.success)
        self.success_rate = successes / self.session_count if self.session_count else 0.0


_NO_SKILL_KEY = "__no_skill__"


class SkillSessionAggregator:
    """Groups scored sessions by skill name and filters by quality thresholds.

    Only groups that meet ``min_sessions_per_skill`` and ``min_avg_score``
    are returned for evolution consideration.
    """

    def __init__(self, config: SkillEvolutionConfig) -> None:
        self._config = config

    async def aggregate(
        self,
        repo: SkillEvolutionRepository,
        *,
        tenant_id: str,
    ) -> dict[str, SkillSessionGroup]:
        """Aggregate scored sessions grouped by skill name.

        Returns a dict mapping skill_name -> SkillSessionGroup.
        Only groups meeting quality thresholds are included.
        """
        summary_rows = await repo.get_scored_sessions_grouped_by_skill(
            tenant_id=tenant_id,
            min_sessions=self._config.min_sessions_per_skill,
            min_avg_score=self._config.min_avg_score,
        )

        groups: dict[str, SkillSessionGroup] = {}

        for row in summary_rows:
            skill_name = str(row["skill_name"])
            if not skill_name or skill_name == _NO_SKILL_KEY:
                continue

            sessions = await repo.get_sessions_by_skill(
                tenant_id=tenant_id,
                skill_name=skill_name,
                min_score=self._config.min_avg_score,
                limit=self._config.max_sessions_per_batch,
            )

            group = SkillSessionGroup(skill_name=skill_name)
            for s in sessions:
                group.add(s)
            groups[skill_name] = group

        logger.info(
            "Aggregated %d skill groups for evolution (tenant=%s)",
            len(groups),
            tenant_id,
        )
        return groups
