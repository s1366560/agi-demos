"""Conversation entity for multi-turn agent interactions."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from src.domain.model.agent.agent_mode import AgentMode  # stays in agent/
from src.domain.shared_kernel import Entity


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
    agent_config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    message_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None

    # Multi-level thinking support (work plan is stored in WorkPlan table)
    workflow_pattern_id: str | None = None  # Reference to active pattern

    # Plan Mode support
    current_mode: AgentMode = AgentMode.BUILD  # Current agent mode (BUILD/PLAN/EXPLORE)
    current_plan_id: Optional[str] = None  # Reference to active Plan in Plan Mode
    parent_conversation_id: Optional[str] = None  # Parent conversation for SubAgent sessions
    branch_point_message_id: Optional[str] = None  # Message ID where branch was forked
    summary: Optional[str] = None  # Auto-generated conversation summary

    def archive(self) -> None:
        """Archive this conversation."""
        self.status = ConversationStatus.ARCHIVED
        self.updated_at = datetime.now(timezone.utc)

    def delete(self) -> None:
        """Mark this conversation as deleted."""
        self.status = ConversationStatus.DELETED
        self.updated_at = datetime.now(timezone.utc)

    def increment_message_count(self) -> None:
        """Increment the message counter."""
        self.message_count += 1
        self.updated_at = datetime.now(timezone.utc)

    def update_agent_config(self, config: Dict[str, Any]) -> None:
        """
        Update the agent configuration for this conversation.

        Args:
            config: New agent configuration dictionary
        """
        self.agent_config.update(config)
        self.updated_at = datetime.now(timezone.utc)

    def update_title(self, new_title: str) -> None:
        """
        Update the conversation title.

        Args:
            new_title: New title for the conversation
        """
        self.title = new_title
        self.updated_at = datetime.now(timezone.utc)

    # Plan Mode methods

    def enter_plan_mode(self, plan_id: str) -> None:
        """
        Switch to Plan Mode with the given plan.

        Args:
            plan_id: The Plan entity ID to associate

        Raises:
            AlreadyInPlanModeError: If already in Plan Mode
        """
        from src.domain.model.agent.planning.plan import AlreadyInPlanModeError

        if self.current_mode == AgentMode.PLAN:
            raise AlreadyInPlanModeError(self.id)

        self.current_mode = AgentMode.PLAN
        self.current_plan_id = plan_id
        self.updated_at = datetime.now(timezone.utc)

    def exit_plan_mode(self) -> None:
        """
        Exit Plan Mode and return to Build Mode.

        Raises:
            NotInPlanModeError: If not currently in Plan Mode
        """
        from src.domain.model.agent.planning.plan import NotInPlanModeError

        if self.current_mode != AgentMode.PLAN:
            raise NotInPlanModeError(self.id)

        self.current_mode = AgentMode.BUILD
        self.current_plan_id = None
        self.updated_at = datetime.now(timezone.utc)

    def set_explore_mode(self) -> None:
        """
        Set the conversation to Explore Mode (for SubAgent sessions).

        This is typically used when creating a SubAgent session for
        code exploration during Plan Mode.
        """
        self.current_mode = AgentMode.EXPLORE
        self.updated_at = datetime.now(timezone.utc)

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

    def to_dict(self) -> Dict[str, Any]:
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
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conversation":
        """Deserialize from dictionary."""
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
        )
