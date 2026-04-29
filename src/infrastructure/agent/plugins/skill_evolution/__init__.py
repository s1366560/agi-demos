"""Skill Evolution Plugin.

Continuously improves SKILL.md files from real agent usage data.

Pipeline: Capture -> Summarize -> Judge -> Aggregate -> Evolve

Components:
- ``SkillEvolutionPlugin``: main plugin class with lifecycle + hooks
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
        register_builtin_skill_evolution_plugin,
    )

    plugin = SkillEvolutionPlugin(
        config=SkillEvolutionConfig.from_env(),
        skill_service=skill_service,
        llm_provider_manager=llm_provider_manager,
        session_factory=session_factory,
    )
    await plugin.on_enable()
"""

from __future__ import annotations

from .aggregation import SkillSessionAggregator, SkillSessionGroup
from .config import SkillEvolutionConfig
from .evolution_engine import EvolutionEngine
from .models import SkillEvolutionJob, SkillEvolutionSession
from .plugin import (
    SkillEvolutionPlugin,
    configure_skill_evolution_capture,
    register_builtin_skill_evolution_plugin,
)
from .repository import SkillEvolutionRepository
from .scheduler import EvolutionScheduler
from .session_collector import SessionCollector
from .session_judge import SessionJudge
from .skill_merger import SkillMerger
from .summarizer import SessionSummarizer

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
    "configure_skill_evolution_capture",
    "register_builtin_skill_evolution_plugin",
]
