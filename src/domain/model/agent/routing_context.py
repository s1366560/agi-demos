"""Routing context value object for message-level routing decisions."""

from dataclasses import dataclass

from src.domain.shared_kernel import ValueObject


@dataclass(frozen=True)
class RoutingContext(ValueObject):
    """Immutable context snapshot provided to MessageRouterPort for routing decisions.

    Contains the minimal set of identifiers and metadata needed to determine
    which agent (or sub-agent) should handle a given message.

    Attributes:
        conversation_id: Active conversation identifier.
        project_id: Project scope for multi-tenancy.
        tenant_id: Tenant scope for multi-tenancy.
        channel_type: Originating channel (e.g. "web", "api", "feishu").
        parent_conversation_id: Parent conversation if this is a forked session.
    """

    conversation_id: str
    project_id: str
    tenant_id: str
    channel_type: str = "web"
    parent_conversation_id: str | None = None
