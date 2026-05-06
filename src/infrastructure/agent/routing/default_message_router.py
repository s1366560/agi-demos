"""Default implementation of MessageRouterPort using binding-based resolution."""

from __future__ import annotations

import logging
import re

from src.domain.model.agent.binding_scope import BindingScope
from src.domain.model.agent.conversation.message import Message
from src.domain.model.agent.message_binding import MessageBinding
from src.domain.model.agent.routing_context import RoutingContext
from src.domain.ports.agent.message_binding_repository_port import MessageBindingRepositoryPort

logger = logging.getLogger(__name__)

_SCOPE_TO_CONTEXT_FIELD: dict[BindingScope, str | None] = {
    BindingScope.CONVERSATION: "conversation_id",
    BindingScope.USER_AGENT: None,
    BindingScope.PROJECT_ROLE: None,
    BindingScope.PROJECT: "project_id",
    BindingScope.TENANT: "tenant_id",
    BindingScope.DEFAULT: None,
}


class DefaultMessageRouter:
    """Binding-based message router implementing MessageRouterPort.

    Maintains an in-memory binding dictionary and delegates persistence
    to a ``MessageBindingRepositoryPort``.  Resolution walks bindings
    sorted by ``(scope.priority, priority)`` and returns the first match.
    """

    def __init__(self, binding_repo: MessageBindingRepositoryPort) -> None:
        self._binding_repo = binding_repo
        self._bindings: dict[str, MessageBinding] = {}

    async def resolve_agent(
        self,
        message: Message,
        context: RoutingContext,
    ) -> str | None:
        sorted_bindings = sorted(
            self._bindings.values(),
            key=lambda b: (b.scope.priority, b.priority),
        )

        for binding in sorted_bindings:
            if not binding.is_active:
                continue

            if not self._matches_scope(binding, context):
                continue

            if not self._matches_filter(binding, message):
                continue

            return binding.agent_id

        return None

    async def register_binding(self, binding: MessageBinding) -> None:
        self._bindings[binding.id] = binding
        await self._binding_repo.save(binding)

    async def remove_binding(self, binding_id: str) -> None:
        self._bindings.pop(binding_id, None)
        await self._binding_repo.delete(binding_id)

    @staticmethod
    def _matches_scope(binding: MessageBinding, context: RoutingContext) -> bool:
        if binding.scope == BindingScope.DEFAULT:
            return True

        field_name = _SCOPE_TO_CONTEXT_FIELD.get(binding.scope)
        if field_name is None:
            return False

        context_value = getattr(context, field_name, None)
        return context_value == binding.scope_id

    # Caps to mitigate catastrophic backtracking (ReDoS). A binding
    # filter pattern is operator-supplied, but message content is
    # user-supplied; the product of the two is the danger surface.
    _MAX_FILTER_PATTERN_LEN = 200
    _MAX_FILTER_CONTENT_LEN = 4096

    @staticmethod
    def _matches_filter(binding: MessageBinding, message: Message) -> bool:
        if binding.filter_pattern is None:
            return True

        pattern = binding.filter_pattern
        content = message.content or ""

        if len(pattern) > DefaultMessageRouter._MAX_FILTER_PATTERN_LEN:
            logger.warning(
                "Binding %s filter_pattern too long (%d > %d); skipping",
                binding.id,
                len(pattern),
                DefaultMessageRouter._MAX_FILTER_PATTERN_LEN,
            )
            return False

        if len(content) > DefaultMessageRouter._MAX_FILTER_CONTENT_LEN:
            # Truncate rather than skip so a long legitimate message still
            # gets a chance to match the pattern's prefix.
            content = content[: DefaultMessageRouter._MAX_FILTER_CONTENT_LEN]

        try:
            return re.search(pattern, content) is not None
        except re.error:
            logger.debug(
                "Invalid regex in binding %s: %s",
                binding.id,
                pattern,
            )
            return False
        except Exception:
            logger.exception(
                "Regex evaluation failed for binding %s",
                binding.id,
            )
            return False
