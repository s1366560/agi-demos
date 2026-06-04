"""Skill evolution plugin configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass
class SkillEvolutionConfig:
    """Configuration for the skill evolution plugin.

    Controls session capture, judging thresholds, evolution cadence,
    and publishing behaviour.
    """

    enabled: bool = True
    min_sessions_per_skill: int = 5
    scoring_min_sessions_per_skill: int = 5
    min_avg_score: float = 0.6
    evolution_interval_minutes: int = 60
    session_retention_days: int = 30
    llm_model: str = ""
    max_sessions_per_batch: int = 50
    llm_concurrency: int = 2
    llm_timeout_seconds: int = 120
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
            scoring_min_sessions_per_skill=int(
                os.getenv("SKILL_EVOLUTION_SCORING_MIN_SESSIONS", "5")
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
            llm_concurrency=int(os.getenv("SKILL_EVOLUTION_LLM_CONCURRENCY", "2")),
            llm_timeout_seconds=int(
                os.getenv("SKILL_EVOLUTION_LLM_TIMEOUT_SECONDS", "120")
            ),
            publish_mode=os.getenv("SKILL_EVOLUTION_PUBLISH_MODE", "review"),
            auto_apply=os.getenv("SKILL_EVOLUTION_AUTO_APPLY", "false").lower()
            == "true",
        )

    def with_overrides(self, overrides: dict[str, object] | None) -> SkillEvolutionConfig:
        if not overrides:
            return self

        values: dict[str, Any] = {}
        if "enabled" in overrides:
            values["enabled"] = bool(overrides["enabled"])
        if "min_sessions_per_skill" in overrides:
            values["min_sessions_per_skill"] = max(
                1, _coerce_int(overrides["min_sessions_per_skill"])
            )
        if "scoring_min_sessions_per_skill" in overrides:
            values["scoring_min_sessions_per_skill"] = max(
                1, _coerce_int(overrides["scoring_min_sessions_per_skill"])
            )
        if "min_avg_score" in overrides:
            values["min_avg_score"] = min(
                1.0, max(0.0, _coerce_float(overrides["min_avg_score"]))
            )
        if "evolution_interval_minutes" in overrides:
            values["evolution_interval_minutes"] = max(
                1, _coerce_int(overrides["evolution_interval_minutes"])
            )
        if "max_sessions_per_batch" in overrides:
            values["max_sessions_per_batch"] = max(
                1, _coerce_int(overrides["max_sessions_per_batch"])
            )
        if "publish_mode" in overrides:
            mode = str(overrides["publish_mode"])
            if mode in {"review", "direct"}:
                values["publish_mode"] = mode
        if "auto_apply" in overrides:
            values["auto_apply"] = bool(overrides["auto_apply"])
        return replace(self, **values)


def _coerce_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str):
        return int(value)
    raise TypeError(f"Expected integer-compatible value, got {type(value).__name__}")


def _coerce_float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float | str):
        return float(value)
    raise TypeError(f"Expected float-compatible value, got {type(value).__name__}")
