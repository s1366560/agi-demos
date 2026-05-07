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

# Scopes that are declared in the enum but not yet wired into the
# routing context (they map to ``None`` above). Bindings using these
# scopes silently never match, which is a footgun: rejecting them at
# registration surfaces the missing wiring loudly instead of letting
# the caller create dead bindings.
_UNSUPPORTED_SCOPES: frozenset[BindingScope] = frozenset(
    {BindingScope.USER_AGENT, BindingScope.PROJECT_ROLE}
)


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
        if binding.scope in _UNSUPPORTED_SCOPES:
            raise ValueError(
                f"BindingScope.{binding.scope.name} is declared but not yet "
                f"wired into the routing context. Bindings registered with "
                f"this scope would never match. Use a supported scope "
                f"(CONVERSATION, PROJECT, TENANT, DEFAULT) or extend "
                f"RoutingContext + _SCOPE_TO_CONTEXT_FIELD first."
            )
        # Persist first so a save failure does NOT leave a binding dangling
        # in the in-memory cache that no other process can see.
        await self._binding_repo.save(binding)
        self._bindings[binding.id] = binding

    async def remove_binding(self, binding_id: str) -> None:
        # Symmetric: remove from cache only after the persistent delete
        # succeeds, so a failed delete does not lose the in-memory binding.
        await self._binding_repo.delete(binding_id)
        self._bindings.pop(binding_id, None)

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
        except re.error as e:
            # Bump from DEBUG to WARNING so an invalid pattern is visible in
            # production logs / metrics rather than silently dropping the
            # binding from match results. Structured extras let log
            # aggregators (or a future Prometheus counter) alert on
            # mis-configured filters.
            logger.warning(
                "Invalid regex in binding %s: %s",
                binding.id,
                pattern,
                extra={
                    "event": "binding_filter_regex_error",
                    "binding_id": binding.id,
                    "agent_id": binding.agent_id,
                    "scope": binding.scope.value,
                    "regex_error": str(e),
                },
            )
            return False
        except Exception:
            logger.exception(
                "Regex evaluation failed for binding %s",
                binding.id,
                extra={
                    "event": "binding_filter_eval_error",
                    "binding_id": binding.id,
                    "agent_id": binding.agent_id,
                    "scope": binding.scope.value,
                },
            )
            return False
