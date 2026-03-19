"""Message Router Port - Domain interface for binding-based message routing.

Defines the MessageRouterPort protocol that infrastructure adapters implement
to resolve which agent should handle a given message, based on registered
MessageBinding rules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.domain.model.agent.conversation.message import Message
    from src.domain.model.agent.message_binding import MessageBinding
    from src.domain.model.agent.routing_context import RoutingContext


@runtime_checkable
class MessageRouterPort(Protocol):
    """Protocol for binding-based message routing.

    The message router maintains a set of MessageBinding rules and uses
    them to resolve which agent (or sub-agent) should handle an incoming
    message.  Bindings can be scoped to conversations, projects, or
    tenants (see BindingScope).
    """

    async def resolve_agent(
        self,
        message: Message,
        context: RoutingContext,
    ) -> str | None:
        """Determine which agent should handle a message.

        Evaluates registered bindings against the message content and
        routing context to find the best-matching agent.

        Args:
            message: The incoming message to route.
            context: Routing context with conversation/project/tenant IDs.

        Returns:
            Agent identifier string if a binding matches, or None to
            fall through to the default routing chain.
        """
        ...

    async def register_binding(self, binding: MessageBinding) -> None:
        """Register a new message routing binding.

        Args:
            binding: The binding rule to register.
        """
        ...

    async def remove_binding(self, binding_id: str) -> None:
        """Remove a previously registered binding.

        Args:
            binding_id: Identifier of the binding to remove.
        """
        ...
