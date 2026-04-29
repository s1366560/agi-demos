"""Skill evolution plugin — main entry point.

Wires together session capture, the evolution pipeline, and the
periodic scheduler. Registered as a built-in runtime plugin that
hooks into ``after_turn_complete`` for data capture.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.application.services.llm_provider_manager import LLMProviderManager
    from src.application.services.skill_service import SkillService
    from src.infrastructure.agent.plugins.skill_evolution.config import (
        SkillEvolutionConfig,
    )

from src.infrastructure.agent.plugins.registry import AgentPluginRegistry
from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

PLUGIN_NAME = "skill-evolution"

logger = logging.getLogger(__name__)


async def _after_turn_complete(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Hook handler: capture skill session data after each turn.

    Checks whether a skill was matched during the turn and, if so,
    persists a SkillEvolutionSession for later evolution analysis.
    """
    collector = _get_collector()
    if collector is None:
        return dict(payload)

    try:
        await collector.capture_from_hook(
            payload,
            session_factory=_get_session_factory(),
        )
    except Exception:
        logger.exception("Skill evolution session capture failed")

    return dict(payload)


_collector: Any = None
_config: Any = None
_session_factory: Any = None
_scheduler: Any = None


def _get_collector() -> Any:  # noqa: ANN401
    return _collector


def _get_session_factory() -> Any:  # noqa: ANN401
    return _session_factory


class SkillEvolutionPlugin:
    """Built-in plugin that evolves SKILL.md files from real usage data.

    Lifecycle:
    - ``setup()``: registers hooks via the runtime API.
    - ``on_enable()`` / ``on_disable()``: starts/stops the evolution scheduler.
    """

    def __init__(
        self,
        config: SkillEvolutionConfig,
        skill_service: SkillService,
        llm_provider_manager: LLMProviderManager,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        global _config, _session_factory, _collector, _scheduler

        self.config = config
        self.skill_service = skill_service
        self.llm_provider_manager = llm_provider_manager
        self.session_factory = session_factory

        _config = config
        _session_factory = session_factory

        # Build pipeline components
        from src.infrastructure.agent.plugins.skill_evolution.aggregation import (
            SkillSessionAggregator,
        )
        from src.infrastructure.agent.plugins.skill_evolution.evolution_engine import (
            EvolutionEngine,
        )
        from src.infrastructure.agent.plugins.skill_evolution.session_collector import (
            SessionCollector,
        )
        from src.infrastructure.agent.plugins.skill_evolution.session_judge import (
            SessionJudge,
        )
        from src.infrastructure.agent.plugins.skill_evolution.skill_merger import (
            SkillMerger,
        )
        from src.infrastructure.agent.plugins.skill_evolution.summarizer import (
            SessionSummarizer,
        )

        merger = SkillMerger(skill_service)
        self.summarizer = SessionSummarizer(config)
        self.judge = SessionJudge(config)
        self.aggregator = SkillSessionAggregator(config)
        self.engine = EvolutionEngine(config, skill_service, merger)
        self.collector = SessionCollector(config)

        _collector = self.collector

        from src.infrastructure.agent.plugins.skill_evolution.scheduler import (
            EvolutionScheduler,
        )

        self._scheduler_instance = EvolutionScheduler(
            config=config,
            summarizer=self.summarizer,
            judge=self.judge,
            aggregator=self.aggregator,
            engine=self.engine,
            llm_provider_manager=llm_provider_manager,
            session_factory=session_factory,
        )
        _scheduler = self._scheduler_instance

    @property
    def scheduler(self) -> Any:  # noqa: ANN401
        return self._scheduler_instance

    def setup(self, api: PluginRuntimeApi) -> None:
        """Register hooks with the plugin runtime."""
        api.register_hook(
            "after_turn_complete",
            _after_turn_complete,
            hook_family="mutating",
            priority=30,
            display_name="Skill evolution capture",
            description=(
                "Captures skill-execution data after each turn for "
                "periodic evolution analysis and SKILL.md improvement."
            ),
            overwrite=True,
        )
        logger.info("Skill evolution plugin hooks registered")

    async def on_enable(self) -> None:
        """Start the evolution scheduler."""
        if self.config.enabled:
            await self._scheduler_instance.start()

    async def on_disable(self) -> None:
        """Stop the evolution scheduler."""
        await self._scheduler_instance.stop()

    async def trigger_evolution(
        self, *, tenant_id: str, project_id: str | None = None
    ) -> dict[str, Any]:
        """Manually trigger an evolution cycle for a tenant."""
        return await self._scheduler_instance.run_once(
            tenant_id=tenant_id, project_id=project_id
        )


def register_builtin_skill_evolution_plugin(
    registry: AgentPluginRegistry,
    config: SkillEvolutionConfig | None = None,
    skill_service: Any = None,  # noqa: ANN401
    llm_provider_manager: Any = None,  # noqa: ANN401
    session_factory: Any = None,  # noqa: ANN401
) -> SkillEvolutionPlugin:
    """Initialize the full skill evolution plugin with dependencies.

    The hook registration happens in ``_register_builtin_hooks()`` via
    ``registry.py``.  This function wires the heavy dependencies
    (skill service, LLM provider manager, DB session factory) so the
    collector and scheduler can actually persist and process data.

    Args:
        registry: The agent plugin registry (used for hook lookup only).
        config: Plugin config; loaded from env if None.
        skill_service: SkillService instance for reading/updating skills.
        llm_provider_manager: LLM provider manager for LLM calls.
        session_factory: SQLAlchemy async session factory for persistence.

    Returns:
        The constructed SkillEvolutionPlugin instance.
    """
    if config is None:
        from src.infrastructure.agent.plugins.skill_evolution.config import (
            SkillEvolutionConfig,
        )

        config = SkillEvolutionConfig.from_env()

    plugin = SkillEvolutionPlugin(
        config=config,
        skill_service=skill_service,
        llm_provider_manager=llm_provider_manager,
        session_factory=session_factory,
    )

    return plugin
