"""Coordination hub for multi-agent lifecycle management.

Ties together SpawnManager, AgentMessageBus, AgentSessionRegistry,
and AgentRegistryPort into a unified API for spawning, messaging,
and stopping agents.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.agent_role import AgentRoleResolver
from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.agent.spawn_record import SpawnRecord
from src.domain.ports.agent.agent_registry import AgentRegistryPort
from src.domain.ports.services.agent_message_bus_port import (
    AgentMessage,
    AgentMessageBusPort,
    AgentMessageType,
)
from src.infrastructure.agent.orchestration.session_registry import (
    AgentSession,
    AgentSessionRegistry,
)
from src.infrastructure.agent.orchestration.spawn_manager import SpawnManager
from src.infrastructure.agent.subagent.spawn_validator import SpawnValidator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class SpawnResult:
    """Result of a successful agent spawn."""

    spawn_record: SpawnRecord
    session: AgentSession
    agent: Agent


@dataclass
class SendResult:
    """Result of a successful inter-agent message send."""

    message_id: str
    from_agent_id: str
    to_agent_id: str
    session_id: str


class AgentOrchestrator:
    """Coordination hub for multi-agent lifecycle management.

    Provides a unified API over SpawnManager, AgentSessionRegistry,
    AgentMessageBusPort, and AgentRegistryPort. Does NOT execute
    agents -- only manages spawn records, sessions, and messaging.
    """

    def __init__(
        self,
        agent_registry: AgentRegistryPort,
        session_registry: AgentSessionRegistry,
        spawn_manager: SpawnManager,
        message_bus: AgentMessageBusPort,
        spawn_validator: SpawnValidator | None = None,
        db_session: AsyncSession | None = None,
    ) -> None:
        self._agent_registry = agent_registry
        self._session_registry = session_registry
        self._spawn_manager = spawn_manager
        self._message_bus = message_bus
        self._spawn_validator = spawn_validator
        self._db_session = db_session

    async def spawn_agent(
        self,
        parent_agent_id: str,
        target_agent_id: str,
        message: str,
        mode: SpawnMode,
        parent_session_id: str,
        project_id: str,
        *,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str = "",
        span_id: str = "",
    ) -> SpawnResult:
        """Spawn a child agent session.

        Sets up the spawn record, registers a session, and sends
        the initial message. Does NOT execute the child agent.
        """
        agent = await self._agent_registry.get_by_id(target_agent_id)
        if agent is None:
            raise ValueError(f"Target agent not found: {target_agent_id}")
        if not agent.enabled:
            raise ValueError(f"Target agent is disabled: {target_agent_id}")
        if not agent.discoverable:
            raise ValueError(f"Target agent is not discoverable: {target_agent_id}")

        child_session_id = str(uuid.uuid4())

        parent_depth = await self._spawn_manager.get_spawn_depth(parent_session_id)
        child_depth = parent_depth + 1

        if self._spawn_validator is not None:
            validation = self._spawn_validator.validate(
                subagent_name=target_agent_id,
                current_depth=child_depth,
                conversation_id=conversation_id or "",
                requester_session_id=parent_session_id,
            )
            if not validation.allowed:
                raise ValueError(
                    f"Spawn rejected ({validation.rejection_code}): {validation.rejection_reason}"
                )

        max_depth = self._spawn_manager.max_spawn_depth
        child_role = AgentRoleResolver.resolve(child_depth, max_depth)

        enriched_metadata = dict(metadata) if metadata else {}
        enriched_metadata["agent_role"] = child_role.value
        enriched_metadata["agent_depth"] = child_depth

        spawn_record = await self._spawn_manager.register_spawn(
            parent_agent_id=parent_agent_id,
            child_agent_id=target_agent_id,
            child_session_id=child_session_id,
            project_id=project_id,
            mode=mode,
            task_summary=message[:200],
            parent_session_id=parent_session_id,
            conversation_id=conversation_id,
            metadata=enriched_metadata,
            trace_id=trace_id,
            span_id=span_id,
        )

        session = await self._session_registry.register(
            agent_id=target_agent_id,
            conversation_id=child_session_id,
            project_id=project_id,
        )

        _ = await self._message_bus.send_message(
            from_agent_id=parent_agent_id,
            to_agent_id=target_agent_id,
            session_id=child_session_id,
            content=message,
            message_type=AgentMessageType.REQUEST,
        )

        logger.info(
            "Spawned agent: parent=%s child=%s session=%s mode=%s",
            parent_agent_id,
            target_agent_id,
            child_session_id,
            mode.value,
        )

        return SpawnResult(
            spawn_record=spawn_record,
            session=session,
            agent=agent,
        )

    async def send_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        message: str,
        *,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> SendResult:
        """Send a message from one agent to another.

        The sender may be a registered agent or the root/main agent.
        If the sender is not found in the registry it is treated as the
        root agent and allowed to send without further validation.
        """
        from_agent = await self._agent_registry.get_by_id(from_agent_id)
        # Root/main agent may not be in the registry -- allow it.

        to_agent = await self._agent_registry.get_by_id(to_agent_id)
        if to_agent is None:
            raise ValueError(f"Target agent not found: {to_agent_id}")
        if from_agent is not None and not to_agent.accepts_messages_from(from_agent_id):
            raise ValueError(
                f"Target agent {to_agent_id} does not accept messages from sender: {from_agent_id}"
            )

        resolved_session_id = session_id
        if resolved_session_id is None:
            if project_id is None:
                raise ValueError("Either session_id or project_id must be provided")
            target_session = await self._session_registry.get_sessions(project_id)
            matching = [s for s in target_session if s.agent_id == to_agent_id]
            if not matching:
                raise ValueError(
                    f"No active session found for agent {to_agent_id} in project {project_id}"
                )
            resolved_session_id = matching[0].conversation_id

        message_id = await self._message_bus.send_message(
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            session_id=resolved_session_id,
            content=message,
            message_type=AgentMessageType.REQUEST,
        )

        logger.info(
            "Sent message: from=%s to=%s session=%s",
            from_agent_id,
            to_agent_id,
            resolved_session_id,
        )

        return SendResult(
            message_id=message_id,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            session_id=resolved_session_id,
        )

    async def stop_agent(
        self,
        agent_id: str,
        session_id: str,
        project_id: str,
        *,
        cascade: bool = True,
        conversation_id: str | None = None,
    ) -> list[str]:
        """Stop an agent session, optionally cascading to children."""
        stopped: list[str]

        async def _publish_cancelled_announce(
            child_session_id: str,
            child_agent_id: str,
        ) -> None:
            try:
                _ = await self._message_bus.send_message(
                    from_agent_id=child_agent_id,
                    to_agent_id=agent_id,
                    session_id=child_session_id,
                    content="cancelled",
                    message_type=AgentMessageType.ANNOUNCE,
                    metadata={"reason": "parent_cascade_stop"},
                )
            except Exception:
                logger.warning(
                    "Failed to publish cancelled announce for session=%s",
                    child_session_id,
                    exc_info=True,
                )

        if cascade:
            stopped = await self._spawn_manager.cascade_stop(
                session_id=session_id,
                project_id=project_id,
                conversation_id=conversation_id,
                on_stop=_publish_cancelled_announce,
            )
        else:
            stopped = []
            _ = await self._spawn_manager.update_status(
                child_session_id=session_id,
                new_status="stopped",
                conversation_id=conversation_id,
            )
            _ = await self._session_registry.unregister(
                conversation_id=session_id,
                project_id=project_id,
            )
            stopped.append(session_id)

        for sid in stopped:
            await self._message_bus.cleanup_session(sid)

        logger.info(
            "Stopped agent=%s session=%s cascade=%s stopped_count=%d",
            agent_id,
            session_id,
            cascade,
            len(stopped),
        )

        return stopped

    async def list_agents(
        self,
        project_id: str,
        tenant_id: str,
        *,
        discoverable_only: bool = True,
    ) -> list[Agent]:
        """List available agents for a project."""
        agents = await self._agent_registry.list_by_project(
            project_id=project_id,
            tenant_id=tenant_id,
            enabled_only=True,
        )
        if discoverable_only:
            agents = [a for a in agents if a.discoverable]
        return agents

    async def get_agent_sessions(
        self,
        parent_session_id: str,
        *,
        include_children: bool = True,
    ) -> list[SpawnRecord]:
        """Get spawn records for a parent session."""
        if include_children:
            return await self._spawn_manager.find_descendants(
                parent_session_id,
                include_self=True,
            )
        return await self._spawn_manager.find_children(
            parent_session_id,
        )

    async def get_agent_history(
        self,
        session_id: str,
        *,
        limit: int = 50,
    ) -> list[AgentMessage]:
        """Get message history for an agent session."""
        return await self._message_bus.get_message_history(
            session_id=session_id,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Agent Definition CRUD (used by agent_definition_manage tool)
    # ------------------------------------------------------------------

    async def get_agent(self, agent_id: str) -> Agent | None:
        """Get an agent definition by ID."""
        return await self._agent_registry.get_by_id(agent_id)

    async def get_agent_by_name(
        self,
        tenant_id: str,
        name: str,
    ) -> Agent | None:
        """Get an agent definition by name within a tenant."""
        return await self._agent_registry.get_by_name(tenant_id, name)

    async def create_agent(self, agent: Agent) -> Agent:
        """Create a new agent definition.

        Validates name uniqueness within the tenant before persisting.
        """
        existing = await self._agent_registry.get_by_name(
            agent.tenant_id,
            agent.name,
        )
        if existing is not None:
            raise ValueError(f"Agent with name '{agent.name}' already exists (id={existing.id})")
        created = await self._agent_registry.create(agent)
        if self._db_session is not None:
            await self._db_session.commit()
        logger.info(
            "Agent definition created: id=%s name=%s tenant=%s",
            created.id,
            created.name,
            created.tenant_id,
        )
        return created

    async def update_agent(self, agent: Agent) -> Agent:
        """Update an existing agent definition."""
        existing = await self._agent_registry.get_by_id(agent.id)
        if existing is None:
            raise ValueError(f"Agent not found: {agent.id}")
        updated = await self._agent_registry.update(agent)
        if self._db_session is not None:
            await self._db_session.commit()
        logger.info("Agent definition updated: id=%s", updated.id)
        return updated

    async def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent definition by ID."""
        existing = await self._agent_registry.get_by_id(agent_id)
        if existing is None:
            raise ValueError(f"Agent not found: {agent_id}")
        deleted = await self._agent_registry.delete(agent_id)
        if deleted and self._db_session is not None:
            await self._db_session.commit()
        if deleted:
            logger.info("Agent definition deleted: id=%s", agent_id)
        return deleted
