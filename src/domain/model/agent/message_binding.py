"""Message binding value object for routing messages to agents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.model.agent.binding_scope import BindingScope
from src.domain.shared_kernel import ValueObject


@dataclass(frozen=True)
class MessageBinding(ValueObject):
    """A binding rule that routes messages to a specific agent.

    Bindings are evaluated by the MessageRouter in scope-priority order.
    The first matching binding determines which agent handles the message.

    Attributes:
        id: unique identifier for this binding.
        agent_id: the target agent/subagent ID to route to.
        scope: the scope level for priority ordering.
        scope_id: the specific scope entity ID (e.g. conversation_id, project_id).
        priority: tie-breaker within the same scope (lower = higher priority).
        filter_pattern: optional regex or keyword pattern to match messages.
        is_active: whether this binding is currently active.
        created_at: when this binding was created.
        updated_at: when this binding was last modified.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    scope: BindingScope = BindingScope.DEFAULT
    scope_id: str = ""
    priority: int = 0
    filter_pattern: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("MessageBinding.agent_id must not be empty")

    def matches_scope(self, scope: BindingScope, scope_id: str) -> bool:
        """Check if this binding matches the given scope and scope_id."""
        return self.scope == scope and self.scope_id == scope_id and self.is_active
