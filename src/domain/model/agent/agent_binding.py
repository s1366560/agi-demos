"""
Agent binding entity for routing rules.

Maps channel contexts (type, id, account, peer) to specific agents,
enabling flexible multi-agent routing with specificity-based resolution.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class AgentBinding:
    """Routing rule that maps a channel context to an agent.

    Priority resolution (most-specific wins):
    1. channel_type + channel_id + account_id + peer_id -> agent_id
    2. channel_type + channel_id + account_id           -> agent_id
    3. channel_type + channel_id                        -> agent_id
    4. channel_type                                     -> agent_id
    5. (default agent)

    Attributes:
        id: Unique identifier
        tenant_id: Tenant that owns this binding
        agent_id: Target agent for this binding
        channel_type: Channel type filter (None = wildcard)
        channel_id: Channel instance filter (None = wildcard)
        account_id: User account filter (None = wildcard)
        peer_id: Peer identity filter (None = wildcard)
        group_id: Broadcast group identifier. Bindings sharing the same
            group_id form a broadcast group where messages are delivered
            to ALL agents in the group (None = not in any group)
        priority: Explicit priority override (higher = more specific)
        enabled: Whether this binding is active
        created_at: When this binding was created
    """

    id: str
    tenant_id: str
    agent_id: str
    channel_type: str | None = None
    channel_id: str | None = None
    account_id: str | None = None
    peer_id: str | None = None
    group_id: str | None = None
    priority: int = 0
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the binding.

        Checks required fields (id, tenant_id, agent_id) and ensures
        priority is non-negative. group_id is optional and enables
        broadcast group routing when set.
        """
        if not self.id:
            raise ValueError("id cannot be empty")
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.agent_id:
            raise ValueError("agent_id cannot be empty")
        if self.priority < 0:
            raise ValueError("priority must be non-negative")

    @property
    def specificity_score(self) -> int:
        """Calculate specificity for most-specific-wins resolution.

        Returns:
            Combined specificity score from field presence + priority
        """
        score = 0
        if self.peer_id is not None:
            score += 8
        if self.account_id is not None:
            score += 4
        if self.channel_id is not None:
            score += 2
        if self.channel_type is not None:
            score += 1
        return score + self.priority

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "agent_id": self.agent_id,
            "channel_type": self.channel_type,
            "channel_id": self.channel_id,
            "account_id": self.account_id,
            "peer_id": self.peer_id,
            "group_id": self.group_id,
            "priority": self.priority,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "specificity_score": self.specificity_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentBinding":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            agent_id=data["agent_id"],
            channel_type=data.get("channel_type"),
            channel_id=data.get("channel_id"),
            account_id=data.get("account_id"),
            peer_id=data.get("peer_id"),
            group_id=data.get("group_id"),
            priority=data.get("priority", 0),
            enabled=data.get("enabled", True),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(UTC),
        )
