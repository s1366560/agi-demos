"""Skill evolution runtime — scheduler and V2 lifecycle event handlers.

Wires together session capture, the evolution pipeline, and the
periodic scheduler. Protocol-v2 Fibers own event registration; this
module only implements the runtime behavior they invoke.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.application.services.skill_service import SkillService
    from src.infrastructure.agent.plugins.skill_evolution.config import (
        SkillEvolutionConfig,
    )
    from src.infrastructure.agent.plugins.skill_evolution.scheduler import LlmClientLease
    from src.infrastructure.plugins.v2.plugin_config_repository_lease_v2 import (
        PluginConfigRepositoryLeaseV2,
    )
    from src.infrastructure.plugins.v2.skill_evolution_repository_lease_v2 import (
        SkillEvolutionRepositoryLeaseV2,
    )

PLUGIN_NAME = "skill-evolution"

logger = logging.getLogger(__name__)


def _turn_key(payload: Mapping[str, Any]) -> str | None:
    conversation_id = payload.get("conversation_id")
    if isinstance(conversation_id, str) and conversation_id.strip():
        return f"conversation:{conversation_id.strip()}"
    session_id = payload.get("session_id")
    if isinstance(session_id, str) and session_id.strip():
        return f"session:{session_id.strip()}"
    return None


def _tool_event_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_result = payload.get("tool_result_text", payload.get("result"))
    metadata = payload.get("result_metadata")
    return {
        "tool_name": str(payload.get("tool_name", "")),
        "call_id": str(payload.get("call_id", "")),
        "success": not bool(payload.get("error")),
        "error": str(payload.get("error", ""))[:500] if payload.get("error") else None,
        "result": str(raw_result)[:1200] if raw_result is not None else "",
        "metadata": dict(metadata) if isinstance(metadata, Mapping) else {},
    }


class SkillEvolutionPlugin:
    """Runtime that evolves SKILL.md files from real usage data.

    Lifecycle:
    - ``on_enable()`` / ``on_disable()``: starts/stops the evolution scheduler.
    - V2 event Fibers call capture handlers on this exact runtime instance.
    """

    def __init__(
        self,
        config: SkillEvolutionConfig,
        skill_service: SkillService,
        llm_client_lease: LlmClientLease,
        plugin_config_repository_lease: PluginConfigRepositoryLeaseV2,
        skill_evolution_repository_lease: SkillEvolutionRepositoryLeaseV2,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.config = config
        self.skill_service = skill_service
        self.llm_client_lease = llm_client_lease
        self.plugin_config_repository_lease = plugin_config_repository_lease
        self.skill_evolution_repository_lease = skill_evolution_repository_lease
        self.session_factory = session_factory
        self._loaded_skill_names_by_turn: dict[str, list[str]] = {}
        self._tool_events_by_turn: dict[str, list[dict[str, Any]]] = {}

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

        from src.infrastructure.agent.plugins.skill_evolution.scheduler import (
            EvolutionScheduler,
        )

        self._scheduler_instance = EvolutionScheduler(
            config=config,
            summarizer=self.summarizer,
            judge=self.judge,
            aggregator=self.aggregator,
            engine=self.engine,
            llm_client_lease=llm_client_lease,
            plugin_config_repository_lease=plugin_config_repository_lease,
            skill_evolution_repository_lease=skill_evolution_repository_lease,
            session_factory=session_factory,
        )

    @property
    def scheduler(self) -> Any:  # noqa: ANN401
        return self._scheduler_instance

    async def record_tool_event(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Remember one tool observation for this runtime's turn attribution."""
        result_payload = dict(payload)
        key = _turn_key(payload)
        if key is not None:
            tool_events = self._tool_events_by_turn.setdefault(key, [])
            if len(tool_events) < 40:
                tool_events.append(_tool_event_summary(payload))

        if payload.get("tool_name") != "skill_loader" or payload.get("error"):
            return result_payload

        metadata = payload.get("result_metadata")
        if not isinstance(metadata, Mapping):
            return result_payload
        skill_name = metadata.get("name")
        if not isinstance(skill_name, str) or not skill_name.strip() or key is None:
            return result_payload

        loaded = self._loaded_skill_names_by_turn.setdefault(key, [])
        normalized = skill_name.strip()
        if normalized not in loaded:
            loaded.append(normalized)
        result_payload["loaded_skill_names"] = list(loaded)
        return result_payload

    async def capture_turn(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Persist attribution accumulated by this runtime for one completed turn."""
        result_payload = dict(payload)
        key = _turn_key(payload)
        loaded_skill_names = self._loaded_skill_names_by_turn.pop(key, []) if key else []
        tool_events = self._tool_events_by_turn.pop(key, []) if key else []
        if loaded_skill_names and not result_payload.get("loaded_skill_names"):
            result_payload["loaded_skill_names"] = loaded_skill_names
        if tool_events and not result_payload.get("tool_events"):
            result_payload["tool_events"] = tool_events

        try:
            captured_sessions = await self.collector.capture_from_hook(
                result_payload,
                repository_lease=self.skill_evolution_repository_lease,
                session_factory=self.session_factory,
            )
            self._schedule_captured_sessions(captured_sessions)
        except Exception:
            logger.exception("Skill evolution session capture failed")
        return result_payload

    def _schedule_captured_sessions(self, sessions: object) -> None:
        if not isinstance(sessions, list):
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
                self._scheduler_instance.schedule_run(
                    tenant_id=tenant_id.strip(),
                    project_id=getattr(session, "project_id", None),
                    skill_name=skill_name.strip(),
                    reason="capture",
                )
            except Exception:
                logger.exception(
                    "Failed to schedule autonomous skill evolution for '%s'",
                    skill_name,
                )

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


def build_skill_evolution_runtime(
    config: SkillEvolutionConfig | None = None,
    skill_service: Any = None,  # noqa: ANN401
    llm_client_lease: Any = None,  # noqa: ANN401
    session_factory: Any = None,  # noqa: ANN401
    *,
    plugin_config_repository_lease: Any,  # noqa: ANN401
    skill_evolution_repository_lease: Any,  # noqa: ANN401
) -> SkillEvolutionPlugin:
    """Initialize the full skill evolution runtime with dependencies.

    Event registration is generation-owned by protocol-v2 Fibers. This
    function only wires the heavy dependencies used by capture and the
    periodic scheduler.

    Args:
        config: Plugin config; loaded from env if None.
        skill_service: SkillService instance for reading/updating skills.
        llm_client_lease: Generation-pinned tenant LLM client lease factory.
        session_factory: SQLAlchemy async session factory for persistence.
        plugin_config_repository_lease: Generation-pinned PluginConfig repository lease.
        skill_evolution_repository_lease: Generation-pinned SkillEvolution repository lease.

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
        llm_client_lease=llm_client_lease,
        plugin_config_repository_lease=plugin_config_repository_lease,
        skill_evolution_repository_lease=skill_evolution_repository_lease,
        session_factory=session_factory,
    )

    return plugin
