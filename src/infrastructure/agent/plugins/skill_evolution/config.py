"""Skill evolution plugin configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class SkillEvolutionConfig:
    """Configuration for the skill evolution plugin.

    Controls session capture, judging thresholds, evolution cadence,
    and publishing behaviour.
    """

    enabled: bool = True
    min_sessions_per_skill: int = 5
    min_avg_score: float = 0.6
    evolution_interval_minutes: int = 60
    session_retention_days: int = 30
    llm_model: str = ""
    max_sessions_per_batch: int = 50
    publish_mode: str = "review"
    auto_apply: bool = False

    # Per-tenant overrides stored as tenant_id -> overrides dict
    tenant_overrides: dict[str, dict[str, object]] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> SkillEvolutionConfig:
        return cls(
            enabled=os.getenv("SKILL_EVOLUTION_ENABLED", "true").lower() == "true",
            min_sessions_per_skill=int(
                os.getenv("SKILL_EVOLUTION_MIN_SESSIONS", "5")
            ),
            min_avg_score=float(os.getenv("SKILL_EVOLUTION_MIN_AVG_SCORE", "0.6")),
            evolution_interval_minutes=int(
                os.getenv("SKILL_EVOLUTION_INTERVAL_MINUTES", "60")
            ),
            session_retention_days=int(
                os.getenv("SKILL_EVOLUTION_SESSION_RETENTION_DAYS", "30")
            ),
            llm_model=os.getenv("SKILL_EVOLUTION_LLM_MODEL", ""),
            max_sessions_per_batch=int(
                os.getenv("SKILL_EVOLUTION_MAX_SESSIONS_PER_BATCH", "50")
            ),
            publish_mode=os.getenv("SKILL_EVOLUTION_PUBLISH_MODE", "review"),
            auto_apply=os.getenv("SKILL_EVOLUTION_AUTO_APPLY", "false").lower()
            == "true",
        )
