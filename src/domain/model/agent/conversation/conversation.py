"""Conversation entity for multi-turn agent interactions."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.domain.model.agent.agent_mode import AgentMode  # stays in agent/
from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.domain.model.agent.conversation.errors import (
    CoordinatorRequiredError,
    ParticipantAlreadyPresentError,
    ParticipantLimitError,
    ParticipantNotPresentError,
    SenderNotInRosterError,
)
from src.domain.model.agent.merge_strategy import MergeStrategy
from src.domain.shared_kernel import Entity

if TYPE_CHECKING:
    from src.domain.events.agent_events import AgentDomainEvent


class ConversationStatus(str, Enum):
    """Status of a conversation."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


@dataclass(kw_only=True)
class Conversation(Entity):
    """
    A multi-turn conversation between a user and the AI agent.

    Conversations are scoped to a project and tenant, providing
    multi-tenancy isolation. They maintain message count and
    configuration for the agent.
    """

    project_id: str
    tenant_id: str
    user_id: str
    title: str
    status: ConversationStatus = ConversationStatus.ACTIVE
    agent_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    message_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    # Multi-level thinking support (work plan is stored in WorkPlan table)
    workflow_pattern_id: str | None = None  # Reference to active pattern

    # Plan Mode support
    current_mode: AgentMode = AgentMode.BUILD  # Current agent mode (BUILD/PLAN/EXPLORE)
    current_plan_id: str | None = None  # Reference to active Plan in Plan Mode
    parent_conversation_id: str | None = None  # Parent conversation for SubAgent sessions
    branch_point_message_id: str | None = None  # Message ID where branch was forked
    summary: str | None = None  # Auto-generated conversation summary

    # Fork/merge support (Phase 3)
    fork_source_id: str | None = None  # Conversation this was forked from
    fork_context_snapshot: str | None = None  # Serialized context at fork time
    merge_strategy: MergeStrategy = MergeStrategy.RESULT_ONLY  # How to merge results back

    # Multi-agent collaboration (P2-3 phase-2, Track B)
    #
    # ``participant_agents`` is the mutable roster — the list of agent IDs
    # allowed to read/write this conversation. It is the source of truth for
    # sender validation and @mention narrowing.
    #
    # ``conversation_mode`` may override ``project.agent_conversation_mode``;
    # ``None`` means "inherit project default" (resolved at application layer).
    #
    # ``coordinator_agent_id`` is MANDATORY when mode == AUTONOMOUS — that agent
    # owns per-tick routing decisions. In SHARED/ISOLATED modes it is optional.
    #
    # ``focused_agent_id`` selects the active agent for MULTI_AGENT_ISOLATED
    # mode (each human turn addresses one agent at a time).
    #
    # Autonomous-mode goal + budgets are sourced from the owning Workspace /
    # WorkspaceTask (see G2/G3); the Conversation no longer carries an inline
    # goal_contract. The Leader agent articulates intent via structured
    # tool-calls against the workspace, not a prose blob on this entity.
    participant_agents: list[str] = field(default_factory=list)
    conversation_mode: ConversationMode | None = None
    coordinator_agent_id: str | None = None
    focused_agent_id: str | None = None

    # Domain events pending dispatch to infrastructure (Redis stream, SSE).
    # Not persisted; consumed once by the application/repository layer.
    _pending_events: list["AgentDomainEvent"] = field(
        default_factory=list, repr=False, compare=False
    )

    def archive(self) -> None:
        """Archive this conversation."""
        self.status = ConversationStatus.ARCHIVED
        self.updated_at = datetime.now(UTC)

    def delete(self) -> None:
        """Mark this conversation as deleted."""
        self.status = ConversationStatus.DELETED
        self.updated_at = datetime.now(UTC)

    def increment_message_count(self) -> None:
        """Increment the message counter."""
        self.message_count += 1
        self.updated_at = datetime.now(UTC)

    def update_agent_config(self, config: dict[str, Any]) -> None:
        """
        Update the agent configuration for this conversation.

        Args:
            config: New agent configuration dictionary
        """
        self.agent_config.update(config)
        self.updated_at = datetime.now(UTC)

    def update_title(self, new_title: str) -> None:
        """
        Update the conversation title.

        Args:
            new_title: New title for the conversation
        """
        self.title = new_title
        self.updated_at = datetime.now(UTC)

    # Plan Mode methods

    def enter_plan_mode(self, plan_id: str | None = None) -> None:
        """
        Switch to Plan Mode (read-only analysis mode).

        Args:
            plan_id: Optional plan ID (deprecated, kept for compatibility)

        Raises:
            RuntimeError: If already in Plan Mode
        """
        if self.current_mode == AgentMode.PLAN:
            raise RuntimeError(f"Conversation {self.id} is already in Plan Mode")

        self.current_mode = AgentMode.PLAN
        self.current_plan_id = plan_id
        self.updated_at = datetime.now(UTC)

    def exit_plan_mode(self) -> None:
        """Exit Plan Mode and return to Build Mode."""
        self.current_mode = AgentMode.BUILD
        self.current_plan_id = None
        self.updated_at = datetime.now(UTC)

    def set_explore_mode(self) -> None:
        """
        Set the conversation to Explore Mode (for SubAgent sessions).

        This is typically used when creating a SubAgent session for
        code exploration during Plan Mode.
        """
        self.current_mode = AgentMode.EXPLORE
        self.updated_at = datetime.now(UTC)

    @property
    def is_in_plan_mode(self) -> bool:
        """Check if the conversation is in Plan Mode."""
        return self.current_mode == AgentMode.PLAN

    @property
    def is_in_explore_mode(self) -> bool:
        """Check if the conversation is in Explore Mode."""
        return self.current_mode == AgentMode.EXPLORE

    @property
    def is_subagent_session(self) -> bool:
        """Check if this is a SubAgent session."""
        return self.parent_conversation_id is not None

    @property
    def is_forked(self) -> bool:
        """Check if this conversation was forked from another."""
        return self.fork_source_id is not None

    def fork(
        self,
        *,
        user_id: str,
        title: str,
        merge_strategy: MergeStrategy = MergeStrategy.RESULT_ONLY,
        context_snapshot: str | None = None,
    ) -> "Conversation":
        """Create a child conversation forked from this one."""
        return Conversation(
            project_id=self.project_id,
            tenant_id=self.tenant_id,
            user_id=user_id,
            title=title,
            parent_conversation_id=self.id,
            fork_source_id=self.id,
            fork_context_snapshot=context_snapshot,
            merge_strategy=merge_strategy,
        )

    # =========================================================================
    # Multi-agent roster (P2-3 phase-2, Track B)
    # =========================================================================

    def resolve_mode(self, project_default: str | ConversationMode) -> ConversationMode:
        """Resolve the effective mode: conversation override wins, else project default.

        Deterministic: just reads a value. No NLP / heuristics.
        """
        if self.conversation_mode is not None:
            return self.conversation_mode
        if isinstance(project_default, ConversationMode):
            return project_default
        return ConversationMode(project_default)

    def has_participant(self, agent_id: str) -> bool:
        """Set-membership check — Agent First compliant (deterministic)."""
        return agent_id in self.participant_agents

    def add_participant(
        self,
        agent_id: str,
        *,
        effective_mode: ConversationMode,
        actor_id: str | None = None,
        role: str | None = None,
    ) -> None:
        """Add an agent to the roster.

        Enforces mode-specific invariants:
        - SINGLE_AGENT: at most one participant.
        - other modes: no hard cap at the domain level (application/DB may add).

        Emits ``ConversationParticipantJoinedEvent``.
        """
        if agent_id in self.participant_agents:
            raise ParticipantAlreadyPresentError(
                f"Agent {agent_id} is already a participant of conversation {self.id}"
            )
        if effective_mode == ConversationMode.SINGLE_AGENT and len(self.participant_agents) >= 1:
            raise ParticipantLimitError(
                f"Conversation {self.id} is in single_agent mode; cannot add a second agent"
            )
        self.participant_agents.append(agent_id)
        self.updated_at = datetime.now(UTC)

        # Lazy import to avoid cycle at module load time.
        from src.domain.events.agent_events import ConversationParticipantJoinedEvent

        self._pending_events.append(
            ConversationParticipantJoinedEvent(
                conversation_id=self.id,
                agent_id=agent_id,
                actor_id=actor_id,
                role=role,
            )
        )

    def remove_participant(
        self,
        agent_id: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Remove an agent from the roster.

        Also clears ``coordinator_agent_id`` / ``focused_agent_id`` if they
        pointed at the removed agent (deterministic cleanup — no judgment).

        Emits ``ConversationParticipantLeftEvent``.
        """
        if agent_id not in self.participant_agents:
            raise ParticipantNotPresentError(
                f"Agent {agent_id} is not a participant of conversation {self.id}"
            )
        self.participant_agents.remove(agent_id)
        if self.coordinator_agent_id == agent_id:
            self.coordinator_agent_id = None
        if self.focused_agent_id == agent_id:
            self.focused_agent_id = None
        self.updated_at = datetime.now(UTC)

        from src.domain.events.agent_events import ConversationParticipantLeftEvent

        self._pending_events.append(
            ConversationParticipantLeftEvent(
                conversation_id=self.id,
                agent_id=agent_id,
                actor_id=actor_id,
                reason=reason,
            )
        )

    def set_coordinator(self, agent_id: str | None) -> None:
        """Assign (or clear) the coordinator. The agent MUST be in the roster."""
        if agent_id is not None and agent_id not in self.participant_agents:
            raise ParticipantNotPresentError(
                f"Cannot set coordinator: agent {agent_id} is not a participant of {self.id}"
            )
        self.coordinator_agent_id = agent_id
        self.updated_at = datetime.now(UTC)

    def set_focused_agent(self, agent_id: str | None) -> None:
        """Assign (or clear) the focused agent (for isolated mode)."""
        if agent_id is not None and agent_id not in self.participant_agents:
            raise ParticipantNotPresentError(
                f"Cannot set focused agent: agent {agent_id} is not a participant of {self.id}"
            )
        self.focused_agent_id = agent_id
        self.updated_at = datetime.now(UTC)

    def assert_sender_in_roster(self, sender_agent_id: str | None) -> None:
        """Write-path invariant: a message's sender_agent_id, if set, MUST be
        a participant of this conversation.

        User messages (sender_agent_id is None) are always allowed.
        """
        if sender_agent_id is None:
            return
        if sender_agent_id not in self.participant_agents:
            raise SenderNotInRosterError(
                f"Agent {sender_agent_id} is not a participant of conversation {self.id}"
            )

    def assert_autonomous_invariants(self, effective_mode: ConversationMode) -> None:
        """When the effective mode is AUTONOMOUS, enforce structural preconditions.

        - ``coordinator_agent_id`` MUST be set and in the roster.

        Goal + budget constraints are now owned by the linked Workspace /
        WorkspaceTask (enforced by the application layer); the Conversation
        entity no longer carries that state.
        """
        if effective_mode != ConversationMode.AUTONOMOUS:
            return
        if self.coordinator_agent_id is None:
            raise CoordinatorRequiredError(
                f"Autonomous conversation {self.id} requires coordinator_agent_id"
            )
        if self.coordinator_agent_id not in self.participant_agents:
            raise ParticipantNotPresentError(
                f"coordinator_agent_id {self.coordinator_agent_id} must be in roster"
            )

    def consume_pending_events(self) -> list["AgentDomainEvent"]:
        """Drain pending domain events for dispatch by the repository/service.

        Following the tool pending_events pattern from
        ``src/infrastructure/agent/tools/todo_tools.py``.
        """
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for caching."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "title": self.title,
            "status": self.status.value,
            "message_count": self.message_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "summary": self.summary,
            "fork_source_id": self.fork_source_id,
            "fork_context_snapshot": self.fork_context_snapshot,
            "merge_strategy": self.merge_strategy.value,
            "participant_agents": list(self.participant_agents),
            "conversation_mode": (
                self.conversation_mode.value if self.conversation_mode is not None else None
            ),
            "coordinator_agent_id": self.coordinator_agent_id,
            "focused_agent_id": self.focused_agent_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        """Deserialize from dictionary."""
        merge_strategy_raw = data.get("merge_strategy")
        merge_strategy = (
            MergeStrategy(merge_strategy_raw) if merge_strategy_raw else MergeStrategy.RESULT_ONLY
        )
        mode_raw = data.get("conversation_mode")
        conversation_mode = ConversationMode(mode_raw) if mode_raw else None
        return cls(
            id=data["id"],
            project_id=data["project_id"],
            tenant_id=data["tenant_id"],
            user_id=data["user_id"],
            title=data["title"],
            status=ConversationStatus(data["status"]),
            message_count=data.get("message_count", 0),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=(
                datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
            ),
            summary=data.get("summary"),
            fork_source_id=data.get("fork_source_id"),
            fork_context_snapshot=data.get("fork_context_snapshot"),
            merge_strategy=merge_strategy,
            participant_agents=list(data.get("participant_agents") or []),
            conversation_mode=conversation_mode,
            coordinator_agent_id=data.get("coordinator_agent_id"),
            focused_agent_id=data.get("focused_agent_id"),
        )
