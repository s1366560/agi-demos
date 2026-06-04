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
    result_payload = dict(payload)
    key = _turn_key(payload)
    loaded_skill_names = _loaded_skill_names_by_turn.pop(key, []) if key else []
    tool_events = _tool_events_by_turn.pop(key, []) if key else []
    if loaded_skill_names and not result_payload.get("loaded_skill_names"):
        result_payload["loaded_skill_names"] = loaded_skill_names
    if tool_events and not result_payload.get("tool_events"):
        result_payload["tool_events"] = tool_events

    collector = _get_collector()
    if collector is None:
        return result_payload

    try:
        captured_sessions = await collector.capture_from_hook(
            result_payload,
            session_factory=_get_session_factory(),
        )
        _schedule_captured_sessions(captured_sessions)
    except Exception:
        logger.exception("Skill evolution session capture failed")

    return result_payload


_collector: Any = None
_config: Any = None
_session_factory: Any = None
_scheduler: Any = None
_loaded_skill_names_by_turn: dict[str, list[str]] = {}
_tool_events_by_turn: dict[str, list[dict[str, Any]]] = {}


def _get_collector() -> Any:  # noqa: ANN401
    return _collector


def _get_session_factory() -> Any:  # noqa: ANN401
    return _session_factory


def _get_scheduler() -> Any:  # noqa: ANN401
    return _scheduler


def _turn_key(payload: Mapping[str, Any]) -> str | None:
    conversation_id = payload.get("conversation_id")
    if isinstance(conversation_id, str) and conversation_id.strip():
        return f"conversation:{conversation_id.strip()}"
    session_id = payload.get("session_id")
    if isinstance(session_id, str) and session_id.strip():
        return f"session:{session_id.strip()}"
    return None


async def _after_tool_execution(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Hook handler: remember successful skill_loader calls for turn attribution."""
    result_payload = dict(payload)
    key = _turn_key(payload)
    if key is not None:
        tool_events = _tool_events_by_turn.setdefault(key, [])
        if len(tool_events) < 40:
            tool_events.append(_tool_event_summary(payload))

    if payload.get("tool_name") != "skill_loader" or payload.get("error"):
        return result_payload

    metadata = payload.get("result_metadata")
    if not isinstance(metadata, Mapping):
        return result_payload

    skill_name = metadata.get("name")
    if not isinstance(skill_name, str) or not skill_name.strip():
        return result_payload

    if key is None:
        return result_payload

    loaded = _loaded_skill_names_by_turn.setdefault(key, [])
    normalized = skill_name.strip()
    if normalized not in loaded:
        loaded.append(normalized)
    result_payload["loaded_skill_names"] = list(loaded)
    return result_payload


def _tool_event_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_result = payload.get("result")
    metadata = payload.get("result_metadata")
    return {
        "tool_name": str(payload.get("tool_name", "")),
        "call_id": str(payload.get("call_id", "")),
        "success": not bool(payload.get("error")),
        "error": str(payload.get("error", ""))[:500] if payload.get("error") else None,
        "result": str(raw_result)[:1200] if raw_result is not None else "",
        "metadata": dict(metadata) if isinstance(metadata, Mapping) else {},
    }


def _schedule_captured_sessions(sessions: object) -> None:
    scheduler = _get_scheduler()
    if scheduler is None or not isinstance(sessions, list):
        return

    for session in sessions:
        skill_name = getattr(session, "skill_name", None)
        tenant_id = getattr(session, "tenant_id", None)
        if (
            not isinstance(skill_name, str)
            or not skill_name.strip()
            or skill_name == "__no_skill__"
            or not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            continue

        try:
            scheduler.schedule_run(
                tenant_id=tenant_id.strip(),
                project_id=getattr(session, "project_id", None),
                skill_name=skill_name.strip(),
                reason="capture",
            )
        except Exception:
            logger.exception("Failed to schedule autonomous skill evolution for '%s'", skill_name)


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
            "after_tool_execution",
            _after_tool_execution,
            hook_family="observer",
            priority=30,
            display_name="Skill evolution skill_loader tracking",
            description=(
                "Tracks skill_loader calls so dynamically loaded SKILL.md usage "
                "can be attributed during after-turn evolution capture."
            ),
            overwrite=True,
        )
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
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
    ) -> dict[str, Any]:
        """Manually trigger an evolution cycle for a tenant."""
        return await self._scheduler_instance.run_once(
            tenant_id=tenant_id, project_id=project_id, skill_name=skill_name
        )

    def schedule_evolution(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
        reason: str = "manual",
    ) -> dict[str, Any]:
        """Queue an evolution cycle without blocking the caller."""
        scheduled = self._scheduler_instance.schedule_run(
            tenant_id=tenant_id,
            project_id=project_id,
            skill_name=skill_name,
            reason=reason,
            delay_seconds=0,
            allow_when_stopped=True,
        )
        return {
            "scheduled": scheduled,
            "reason": reason,
            "status": "queued" if scheduled else "already_scheduled_or_not_running",
        }


def configure_skill_evolution_capture(
    session_factory: Any = None,  # noqa: ANN401
) -> None:
    """Initialize just the session capture layer of the skill evolution plugin.

    This is a lightweight setup that only initialises the collector with a
    DB session factory so that ``after_turn_complete`` hooks can persist
    skill-execution sessions. The full evolution pipeline (summarizer,
    judge, scheduler) is NOT started here — that requires the DI container.

    Safe to call multiple times; only the first non-None session_factory
    is retained.
    """
    global _config, _session_factory, _collector

    if _config is None:
        from src.infrastructure.agent.plugins.skill_evolution.config import (
            SkillEvolutionConfig,
        )

        _config = SkillEvolutionConfig.from_env()

    if _session_factory is None and session_factory is not None:
        _session_factory = session_factory

    if _collector is None:
        from src.infrastructure.agent.plugins.skill_evolution.session_collector import (
            SessionCollector,
        )

        _collector = SessionCollector(_config)


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
