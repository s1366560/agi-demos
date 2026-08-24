"""Skill Evolution Plugin.

Continuously improves SKILL.md files from real agent usage data.

Pipeline: Capture -> Summarize -> Judge -> Aggregate -> Evolve

Components:
- ``SkillEvolutionPlugin``: scheduler runtime used by V2 lifecycle effects
- ``SessionCollector``: captures skill-execution data from agent events
- ``SessionSummarizer``: LLM-driven session trajectory + summary
- ``SessionJudge``: LLM-driven 4-dimension quality scoring
- ``SkillSessionAggregator``: groups scored sessions by skill name
- ``EvolutionEngine``: LLM-driven evolution decision + execution
- ``SkillMerger``: applies evolution results to existing skills
- ``EvolutionScheduler``: periodic pipeline trigger

Usage::

    from src.infrastructure.agent.plugins.skill_evolution import (
        SkillEvolutionPlugin,
        SkillEvolutionConfig,
        build_skill_evolution_runtime,
    )

    plugin = SkillEvolutionPlugin(
        config=SkillEvolutionConfig.from_env(),
        skill_service=skill_service,
        llm_client_lease=llm_client_lease,
        session_factory=session_factory,
    )
    await plugin.on_enable()
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .aggregation import SkillSessionAggregator, SkillSessionGroup
    from .config import SkillEvolutionConfig
    from .evolution_engine import EvolutionEngine
    from .models import SkillEvolutionJob, SkillEvolutionSession
    from .plugin import (
        SkillEvolutionPlugin,
        build_skill_evolution_runtime,
        configure_skill_evolution_capture,
    )
    from .repository import SkillEvolutionRepository
    from .scheduler import EvolutionScheduler
    from .session_collector import SessionCollector
    from .session_judge import SessionJudge
    from .skill_merger import SkillMerger
    from .summarizer import SessionSummarizer

_EXPORTS = {
    "EvolutionEngine": (".evolution_engine", "EvolutionEngine"),
    "EvolutionScheduler": (".scheduler", "EvolutionScheduler"),
    "SessionCollector": (".session_collector", "SessionCollector"),
    "SessionJudge": (".session_judge", "SessionJudge"),
    "SessionSummarizer": (".summarizer", "SessionSummarizer"),
    "SkillEvolutionConfig": (".config", "SkillEvolutionConfig"),
    "SkillEvolutionJob": (".models", "SkillEvolutionJob"),
    "SkillEvolutionPlugin": (".plugin", "SkillEvolutionPlugin"),
    "SkillEvolutionRepository": (".repository", "SkillEvolutionRepository"),
    "SkillEvolutionSession": (".models", "SkillEvolutionSession"),
    "SkillMerger": (".skill_merger", "SkillMerger"),
    "SkillSessionAggregator": (".aggregation", "SkillSessionAggregator"),
    "SkillSessionGroup": (".aggregation", "SkillSessionGroup"),
    "build_skill_evolution_runtime": (".plugin", "build_skill_evolution_runtime"),
    "configure_skill_evolution_capture": (".plugin", "configure_skill_evolution_capture"),
}

__all__ = [
    "EvolutionEngine",
    "EvolutionScheduler",
    "SessionCollector",
    "SessionJudge",
    "SessionSummarizer",
    "SkillEvolutionConfig",
    "SkillEvolutionJob",
    "SkillEvolutionPlugin",
    "SkillEvolutionRepository",
    "SkillEvolutionSession",
    "SkillMerger",
    "SkillSessionAggregator",
    "SkillSessionGroup",
    "build_skill_evolution_runtime",
    "configure_skill_evolution_capture",
]


def __getattr__(name: str) -> object:
    """Resolve compatibility exports without entering the persistence model cycle."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    return getattr(import_module(module_name, __name__), attribute_name)
