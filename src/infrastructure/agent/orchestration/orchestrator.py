"""Coordination hub for multi-agent lifecycle management.

Ties together SpawnManager, AgentMessageBus, AgentSessionRegistry,
and AgentRegistryPort into a unified API for spawning, messaging,
and stopping agents.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
from src.infrastructure.agent.orchestration.send_denied import (
    SendDenied,
    denial_code_from_error,
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

_SYSTEM_PARENT_AGENT_IDS = frozenset({"__system__"})


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


@dataclass(frozen=True)
class SpawnExecutionRequest:
    """Execution payload for launching a spawned child session."""

    parent_agent_id: str
    child_agent_id: str
    child_agent_name: str
    child_session_id: str
    parent_session_id: str
    project_id: str
    tenant_id: str = ""
    user_id: str = ""
    message: str = ""
    mode: SpawnMode = SpawnMode.RUN
    conversation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    span_id: str = ""


class AgentOrchestrator:
    """Coordination hub for multi-agent lifecycle management.

    Provides a unified API over SpawnManager, AgentSessionRegistry,
    AgentMessageBusPort, and AgentRegistryPort. When a spawn executor
    is configured, spawned child sessions can also be launched here.
    """

    def __init__(
        self,
        agent_registry: AgentRegistryPort,
        session_registry: AgentSessionRegistry,
        spawn_manager: SpawnManager,
        message_bus: AgentMessageBusPort,
        spawn_validator: SpawnValidator | None = None,
        db_session: AsyncSession | None = None,
        spawn_executor: Callable[[SpawnExecutionRequest], Awaitable[None]] | None = None,
    ) -> None:
        self._agent_registry = agent_registry
        self._session_registry = session_registry
        self._spawn_manager = spawn_manager
        self._message_bus = message_bus
        self._spawn_validator = spawn_validator
        self._db_session = db_session
        self._spawn_executor = spawn_executor

    @staticmethod
    def _is_system_parent_agent(agent_ref: str) -> bool:
        """Return whether an agent reference is an explicit trusted system parent."""
        return agent_ref in _SYSTEM_PARENT_AGENT_IDS

    async def _resolve_agent_ref(
        self,
        agent_ref: str,
        *,
        tenant_id: str = "",
        project_id: str | None = None,
    ) -> Agent | None:
        """Resolve an agent by ID first, then by tenant-scoped name for legacy callers."""
        effective_tenant_id = tenant_id or None
        effective_project_id = project_id or None

        agent = await self._agent_registry.get_by_id(
            agent_ref,
            tenant_id=effective_tenant_id,
            project_id=effective_project_id,
        )
        if agent is None and effective_tenant_id is not None:
            agent = await self._agent_registry.get_by_name(effective_tenant_id, agent_ref)
        if agent is None:
            return None
        if effective_tenant_id is not None and agent.tenant_id != effective_tenant_id:
            return None
        if effective_project_id is not None and agent.project_id not in (
            None,
            effective_project_id,
        ):
            return None
        return agent

    async def _resolve_message_sender(
        self,
        from_agent_id: str,
        *,
        tenant_id: str = "",
        project_id: str | None = None,
    ) -> Agent:
        """Resolve and validate the sender for an agent-to-agent message."""
        from_agent = await self._resolve_agent_ref(
            from_agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if from_agent is None:
            raise ValueError(f"Sender agent not found: {from_agent_id}")
        if not from_agent.enabled:
            raise ValueError(f"Sender agent is disabled: {from_agent.id}")
        if not from_agent.agent_to_agent_enabled:
            raise ValueError(f"Sender agent-to-agent messaging is disabled: {from_agent.id}")
        return from_agent

    async def _resolve_message_target(
        self,
        to_agent_id: str,
        *,
        sender_agent_id: str,
        sender_agent_name: str = "",
        tenant_id: str = "",
        project_id: str | None = None,
    ) -> Agent:
        """Resolve and validate the target for an agent-to-agent message."""
        to_agent = await self._resolve_agent_ref(
            to_agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if to_agent is None:
            raise ValueError(f"Target agent not found: {to_agent_id}")
        if not to_agent.enabled:
            raise ValueError(f"Target agent is disabled: {to_agent.id}")
        if not to_agent.agent_to_agent_enabled:
            raise ValueError(f"Target agent-to-agent messaging is disabled: {to_agent.id}")
        sender_refs = [sender_agent_id]
        if sender_agent_name and sender_agent_name != sender_agent_id:
            sender_refs.append(sender_agent_name)
        if not any(to_agent.accepts_messages_from(sender_ref) for sender_ref in sender_refs):
            raw_allowlist = getattr(to_agent, "agent_to_agent_allowlist", None)
            allowlist = (
                list(raw_allowlist)
                if isinstance(raw_allowlist, (list, tuple, set, frozenset))
                else []
            )
            if allowlist:
                allowlist_hint = f" Allowed senders: {', '.join(allowlist)}."
            else:
                allowlist_hint = (
                    " Configure agent_to_agent_allowlist to permit additional senders."
                )
            raise ValueError(
                f"Target agent {to_agent.id} does not accept messages from sender: "
                f"{sender_agent_id}.{allowlist_hint}"
            )
        return to_agent

    async def _validate_message_sender_session(
        self,
        *,
        sender_session_id: str | None,
        project_id: str | None,
        sender_agent_id: str,
    ) -> None:
        """Ensure the active session belongs to the resolved sending agent."""
        if project_id is None:
            return
        if not sender_session_id:
            raise ValueError("sender_session_id is required for agent-to-agent messaging")
        sender_session = await self._session_registry.get_session_for_conversation(
            sender_session_id,
            project_id,
        )
        if sender_session is None or sender_session.agent_id != sender_agent_id:
            raise ValueError(
                f"Sender session {sender_session_id} does not belong to sender agent "
                f"{sender_agent_id}"
            )

    async def _resolve_message_session_id(
        self,
        *,
        session_id: str | None,
        project_id: str | None,
        target_agent_id: str,
    ) -> str:
        """Resolve and validate the destination session for an inter-agent message."""
        if session_id is not None:
            if project_id is None:
                raise ValueError("project_id is required when session_id is provided")
            target_session = await self._session_registry.get_session_for_conversation(
                session_id,
                project_id,
            )
            if target_session is None:
                raise ValueError(f"Session {session_id} was not found in project {project_id}")
            if target_session.agent_id != target_agent_id:
                raise ValueError(
                    f"Session {session_id} does not belong to target agent {target_agent_id}"
                )
            return target_session.conversation_id

        if project_id is None:
            raise ValueError("Either session_id or project_id must be provided")

        target_sessions = await self._session_registry.get_sessions(project_id)
        matching = [session for session in target_sessions if session.agent_id == target_agent_id]
        if not matching:
            raise ValueError(
                f"No active session found for agent {target_agent_id} in project {project_id}"
            )
        latest_session = max(matching, key=lambda session: session.registered_at)
        return latest_session.conversation_id

    async def _resolve_spawn_parent_agent_id(
        self,
        *,
        parent_agent_id: str,
        parent_session_id: str,
        tenant_id: str = "",
        project_id: str,
    ) -> tuple[str, int | None]:
        """Resolve and validate the parent agent/session for child spawns."""
        if self._is_system_parent_agent(parent_agent_id):
            return parent_agent_id, None

        parent_agent = await self._resolve_agent_ref(
            parent_agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if parent_agent is None:
            raise ValueError(f"Parent agent not found: {parent_agent_id}")
        if not parent_agent.enabled:
            raise ValueError(f"Parent agent is disabled: {parent_agent_id}")
        if not parent_agent.can_spawn:
            raise ValueError(
                f"Parent agent is not allowed to spawn child agents: {parent_agent_id}"
            )

        resolved_parent_agent_id = parent_agent.id
        parent_session = await self._session_registry.get_session_for_conversation(
            parent_session_id,
            project_id,
        )
        if parent_session is None or parent_session.agent_id != resolved_parent_agent_id:
            raise ValueError(
                f"Parent session {parent_session_id} does not belong to parent agent "
                f"{resolved_parent_agent_id}"
            )
        return resolved_parent_agent_id, parent_agent.max_spawn_depth

    async def _resolve_spawn_target_agent(
        self,
        target_agent_id: str,
        *,
        tenant_id: str = "",
        project_id: str,
    ) -> Agent:
        """Resolve and validate the target agent for a child spawn."""
        target_agent = await self._resolve_agent_ref(
            target_agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if target_agent is None:
            raise ValueError(f"Target agent not found: {target_agent_id}")
        if not target_agent.enabled:
            raise ValueError(f"Target agent is disabled: {target_agent_id}")
        if not target_agent.discoverable:
            raise ValueError(f"Target agent is not discoverable: {target_agent_id}")
        return target_agent

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
        tenant_id: str = "",
        user_id: str = "",
    ) -> SpawnResult:
        """Spawn a child agent session.

        Sets up the spawn record, registers a session, and sends
        the initial message. Optionally launches the child session.
        """
        (
            resolved_parent_agent_id,
            parent_agent_max_depth,
        ) = await self._resolve_spawn_parent_agent_id(
            parent_agent_id=parent_agent_id,
            parent_session_id=parent_session_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        agent = await self._resolve_spawn_target_agent(
            target_agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        resolved_target_agent_id = agent.id

        child_session_id = str(uuid.uuid4())

        parent_depth = await self._spawn_manager.get_spawn_depth(parent_session_id)
        child_depth = parent_depth + 1
        if parent_agent_max_depth is not None and child_depth > parent_agent_max_depth:
            raise ValueError(
                f"Parent agent {resolved_parent_agent_id} exceeded max_spawn_depth "
                f"{parent_agent_max_depth}"
            )

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
            parent_agent_id=resolved_parent_agent_id,
            child_agent_id=resolved_target_agent_id,
            child_session_id=child_session_id,
            project_id=project_id,
            mode=mode,
            task_summary=message[:200],
            parent_session_id=parent_session_id,
            conversation_id=conversation_id,
            metadata=enriched_metadata,
            trace_id=trace_id,
            span_id=span_id,
            requester_session_key=parent_session_id,
        )

        session = await self._session_registry.register(
            agent_id=resolved_target_agent_id,
            conversation_id=child_session_id,
            project_id=project_id,
        )

        _ = await self._message_bus.send_message(
            from_agent_id=resolved_parent_agent_id,
            to_agent_id=resolved_target_agent_id,
            session_id=child_session_id,
            content=message,
            message_type=AgentMessageType.REQUEST,
        )

        if self._spawn_executor is not None:
            try:
                await self._spawn_executor(
                    SpawnExecutionRequest(
                        parent_agent_id=resolved_parent_agent_id,
                        child_agent_id=resolved_target_agent_id,
                        child_agent_name=getattr(agent, "display_name", "") or agent.name,
                        child_session_id=child_session_id,
                        parent_session_id=parent_session_id,
                        project_id=project_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        message=message,
                        mode=mode,
                        conversation_id=conversation_id,
                        metadata=enriched_metadata,
                        trace_id=trace_id,
                        span_id=span_id,
                    )
                )
            except Exception:
                await self._spawn_manager.update_status(
                    child_session_id,
                    "failed",
                    conversation_id=conversation_id,
                )
                await self._session_registry.unregister(
                    conversation_id=child_session_id,
                    project_id=project_id,
                )
                raise

        logger.info(
            "Spawned agent: parent=%s child=%s session=%s mode=%s",
            resolved_parent_agent_id,
            resolved_target_agent_id,
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
        sender_session_id: str | None = None,
        project_id: str | None = None,
        tenant_id: str = "",
    ) -> SendResult | SendDenied:
        """Send a message from one agent to another.

        Sender and target must both resolve within the current tenant/project
        scope and explicitly opt in to agent-to-agent messaging.

        Returns
        -------
        SendResult
            On successful delivery.
        SendDenied
            On any validation failure. Callers should treat ``isinstance(result, SendDenied)``
            as the denial branch; ``result`` is a frozen dataclass with a
            machine-readable ``code`` enum and structured field set.
        """
        effective_project_id = project_id or None

        # ── sender resolution ───────────────────────────────────────────
        try:
            from_agent = await self._resolve_message_sender(
                from_agent_id,
                tenant_id=tenant_id,
                project_id=effective_project_id,
            )
        except ValueError as exc:
            return denial_code_from_error(
                exc,
                from_agent_ref=from_agent_id,
                to_agent_ref=to_agent_id,
                sender_session_id=sender_session_id,
                project_id=effective_project_id,
                tenant_id=tenant_id,
                resolved_from_agent_id=None,
                resolved_to_agent_id=None,
                target_session_id=None,
            )

        # ── target resolution ───────────────────────────────────────────
        to_agent = None
        try:
            to_agent = await self._resolve_message_target(
                to_agent_id,
                sender_agent_id=from_agent.id,
                sender_agent_name=from_agent.name,
                tenant_id=tenant_id,
                project_id=effective_project_id,
            )
        except ValueError as exc:
            allowlist: list[str] | None = None
            if "does not accept messages from sender" in str(exc):
                message = str(exc)
                marker = "Allowed senders:"
                if marker in message:
                    suffix = message.split(marker, 1)[1].strip().rstrip(".")
                    allowlist = [entry.strip() for entry in suffix.split(",") if entry.strip()]
            return denial_code_from_error(
                exc,
                from_agent_ref=from_agent_id,
                to_agent_ref=to_agent_id,
                sender_session_id=sender_session_id,
                project_id=effective_project_id,
                tenant_id=tenant_id,
                resolved_from_agent_id=from_agent.id,
                resolved_to_agent_id=None,
                target_session_id=None,
                allowlist=allowlist,
            )

        # ── session resolution ──────────────────────────────────────────
        try:
            resolved_session_id = await self._resolve_message_session_id(
                session_id=session_id,
                project_id=effective_project_id,
                target_agent_id=to_agent.id,
            )
        except ValueError as exc:
            return denial_code_from_error(
                exc,
                from_agent_ref=from_agent_id,
                to_agent_ref=to_agent_id,
                sender_session_id=sender_session_id,
                project_id=effective_project_id,
                tenant_id=tenant_id,
                resolved_from_agent_id=from_agent.id,
                resolved_to_agent_id=to_agent.id,
                target_session_id=None,
            )

        # ── sender session validation ───────────────────────────────────
        try:
            await self._validate_message_sender_session(
                sender_session_id=sender_session_id,
                project_id=effective_project_id,
                sender_agent_id=from_agent.id,
            )
        except ValueError as exc:
            return denial_code_from_error(
                exc,
                from_agent_ref=from_agent_id,
                to_agent_ref=to_agent_id,
                sender_session_id=sender_session_id,
                project_id=effective_project_id,
                tenant_id=tenant_id,
                resolved_from_agent_id=from_agent.id,
                resolved_to_agent_id=to_agent.id,
                target_session_id=resolved_session_id,
            )

        # ── deliver message ─────────────────────────────────────────────
        message_id = await self._message_bus.send_message(
            from_agent_id=from_agent.id,
            to_agent_id=to_agent.id,
            session_id=resolved_session_id,
            content=message,
            message_type=AgentMessageType.REQUEST,
        )

        logger.info(
            "Sent message: from=%s to=%s session=%s",
            from_agent.id,
            to_agent.id,
            resolved_session_id,
        )

        return SendResult(
            message_id=message_id,
            from_agent_id=from_agent.id,
            to_agent_id=to_agent.id,
            session_id=resolved_session_id,
        )

    async def update_spawn_status(
        self,
        child_session_id: str,
        new_status: str,
        *,
        conversation_id: str | None = None,
    ) -> SpawnRecord | None:
        """Update lifecycle status for a spawned child session."""
        return await self._spawn_manager.update_status(
            child_session_id=child_session_id,
            new_status=new_status,
            conversation_id=conversation_id,
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
        agent.validate()
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
        agent.validate()
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
