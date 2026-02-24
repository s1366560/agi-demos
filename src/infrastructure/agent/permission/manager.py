"""Permission Manager - Reference: OpenCode permission/next.ts (269 lines)

Implements allow/deny/ask three-level permission control.
Uses asyncio.Event for Promise-like async waiting.

Extended with dynamic mode-based permission management for Plan Mode support.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .errors import PermissionDeniedError, PermissionRejectedError
from .rules import (
    PermissionAction,
    PermissionRule,
    default_ruleset,
    evaluate_rules,
    explore_mode_ruleset,
)

logger = logging.getLogger(__name__)


class AgentPermissionMode(str, Enum):
    """Agent permission mode for dynamic rule adjustment."""

    BUILD = "build"  # Full access (default)
    PLAN = "plan"  # Read-only + plan editing
    EXPLORE = "explore"  # Pure read-only (SubAgent)


@dataclass
class PermissionRequest:
    """Permission request waiting for user response."""

    id: str
    permission: str
    patterns: list[str]
    session_id: str
    metadata: dict[str, Any]
    always_patterns: list[str]  # Patterns to allow if user chooses "always"


@dataclass
class _PendingRequest:
    """Internal pending request with async primitives."""

    request: PermissionRequest
    event: asyncio.Event
    result: dict[str, Any] = field(default_factory=dict)


class PermissionManager:
    """
    Permission Manager - Reference: OpenCode PermissionNext

    Implements three-level permission control:
    - ALLOW: Permission granted automatically
    - DENY: Permission denied, raises error
    - ASK: Requires user confirmation via SSE events

    Features:
    - Rule-based evaluation with pattern matching
    - Session-scoped runtime approvals
    - "Always" option adds permanent rules
    - Batch rejection (reject cancels all pending for session)
    - Dynamic mode-based permission (BUILD/PLAN/EXPLORE modes)

    Example:
        manager = PermissionManager()

        # Set up SSE event publisher
        manager.set_event_publisher(publish_sse_event)

        # Switch to Plan Mode
        manager.set_mode(AgentPermissionMode.PLAN)

        # Check permission before tool execution
        try:
            await manager.ask(
                permission="bash",
                patterns=["rm -rf *"],
                session_id="session_123",
                metadata={"command": "rm -rf *"}
            )
            # Permission granted, proceed with tool
        except PermissionRejectedError:
            # User rejected, abort
            pass
    """

    def __init__(self, ruleset: list[PermissionRule] | None = None) -> None:
        """
        Initialize permission manager.

        Args:
            ruleset: Initial rules. If None, uses default ruleset.
        """
        self.ruleset = ruleset or default_ruleset()
        self.approved: list[PermissionRule] = []  # Runtime-approved rules
        self.mode_rules: list[PermissionRule] = []  # Mode-specific rules
        self.pending: dict[str, _PendingRequest] = {}
        self._event_publisher: Callable[[dict], Awaitable[None]] | None = None
        self._request_counter = 0
        self._current_mode = AgentPermissionMode.BUILD

    def set_event_publisher(
        self,
        publisher: Callable[[dict], Awaitable[None]],
    ) -> None:
        """
        Set the SSE event publisher for permission requests.

        Args:
            publisher: Async function that publishes events to frontend
        """
        self._event_publisher = publisher

    def set_mode(self, mode: AgentPermissionMode) -> None:
        """
        Set the agent permission mode.

        This dynamically adjusts permissions based on the mode:
        - BUILD: Full access (all tools available)
        - PLAN: Read-only + plan editing (no file modifications)
        - EXPLORE: Pure read-only (SubAgent, no plan editing)

        Args:
            mode: The permission mode to set
        """
        self._current_mode = mode

        # Clear mode-specific rules
        self.mode_rules.clear()

        # Apply mode-specific ruleset
        if mode == AgentPermissionMode.PLAN:
            # Plan mode ruleset removed during refactoring - use explore mode as fallback
            self.mode_rules = explore_mode_ruleset()
            logger.info("Permission mode set to PLAN (using read-only rules)")
        elif mode == AgentPermissionMode.EXPLORE:
            self.mode_rules = explore_mode_ruleset()
            logger.info("Permission mode set to EXPLORE (pure read-only)")
        else:
            # BUILD mode - no additional restrictions
            logger.info("Permission mode set to BUILD (full access)")

    def get_mode(self) -> AgentPermissionMode:
        """
        Get the current agent permission mode.

        Returns:
            Current permission mode
        """
        return self._current_mode

    @property
    def is_plan_mode(self) -> bool:
        """Check if currently in Plan Mode."""
        return self._current_mode == AgentPermissionMode.PLAN

    @property
    def is_explore_mode(self) -> bool:
        """Check if currently in Explore Mode."""
        return self._current_mode == AgentPermissionMode.EXPLORE

    @property
    def is_build_mode(self) -> bool:
        """Check if currently in Build Mode."""
        return self._current_mode == AgentPermissionMode.BUILD

    def evaluate(
        self,
        permission: str,
        pattern: str,
    ) -> PermissionRule:
        """
        Evaluate permission for a given pattern.

        Uses "last match wins" strategy across:
        1. Base ruleset
        2. Mode-specific rules (based on current mode)
        3. Runtime-approved rules

        Args:
            permission: Permission type (e.g., "read", "bash")
            pattern: Target pattern (e.g., file path, command)

        Returns:
            Matching rule with action
        """
        return evaluate_rules(permission, pattern, self.ruleset, self.mode_rules, self.approved)

    async def ask(
        self,
        permission: str,
        patterns: list[str],
        session_id: str,
        metadata: dict[str, Any] | None = None,
        always_patterns: list[str] | None = None,
    ) -> str:
        """
        Request permission for an action.

        Reference: OpenCode PermissionNext.ask()

        For each pattern:
        - ALLOW: Continue to next pattern
        - DENY: Raise PermissionDeniedError
        - ASK: Wait for user response

        Args:
            permission: Permission type being requested
            patterns: Target patterns to check
            session_id: Current session ID
            metadata: Additional context for the request
            always_patterns: Patterns to auto-approve if user chooses "always"

        Returns:
            "allow" if all patterns are allowed

        Raises:
            PermissionDeniedError: If any pattern is denied by rule
            PermissionRejectedError: If user rejects the request
        """
        for pattern in patterns:
            rule = self.evaluate(permission, pattern)

            if rule.action == PermissionAction.DENY:
                raise PermissionDeniedError(permission, pattern)

            if rule.action == PermissionAction.ASK:
                # Create async wait
                self._request_counter += 1
                request_id = f"perm_{self._request_counter}"
                event = asyncio.Event()
                result_holder: dict[str, Any] = {"result": None}

                request = PermissionRequest(
                    id=request_id,
                    permission=permission,
                    patterns=patterns,
                    session_id=session_id,
                    metadata=metadata or {},
                    always_patterns=always_patterns or patterns,
                )

                self.pending[request_id] = _PendingRequest(
                    request=request,
                    event=event,
                    result=result_holder,
                )

                # Publish SSE event for frontend
                if self._event_publisher:
                    try:
                        await self._event_publisher(
                            {
                                "type": "permission_asked",
                                "data": {
                                    "request_id": request_id,
                                    "permission": permission,
                                    "patterns": patterns,
                                    "metadata": metadata,
                                },
                            }
                        )
                    except Exception as e:
                        logger.error(f"Failed to publish permission event: {e}")
                        # Clean up and default to reject
                        del self.pending[request_id]
                        raise PermissionRejectedError(
                            permission, patterns, "Failed to request permission"
                        ) from e

                # Wait for user response
                try:
                    await event.wait()
                except asyncio.CancelledError:
                    # Clean up on cancellation
                    if request_id in self.pending:
                        del self.pending[request_id]
                    raise

                result = result_holder["result"]
                if result == "reject":
                    raise PermissionRejectedError(permission, patterns)

                # Permission granted for this pattern
                return result

            # action == ALLOW, continue to next pattern

        return "allow"

    async def reply(
        self,
        request_id: str,
        reply: str,  # "once" | "always" | "reject"
        message: str | None = None,
    ) -> None:
        """
        Handle user response to permission request.

        Reference: OpenCode PermissionNext.reply()

        Reply options:
        - "once": Allow this specific request
        - "always": Allow and add permanent rule
        - "reject": Deny and cancel all pending for session

        Args:
            request_id: ID of the permission request
            reply: User's response
            message: Optional message from user
        """
        pending = self.pending.get(request_id)
        if not pending:
            logger.warning(f"Permission request not found: {request_id}")
            return

        del self.pending[request_id]

        if reply == "reject":
            pending.result["result"] = "reject"
            pending.event.set()

            # Reject all pending requests for the same session
            session_id = pending.request.session_id
            for pid, p in list(self.pending.items()):
                if p.request.session_id == session_id:
                    del self.pending[pid]
                    p.result["result"] = "reject"
                    p.event.set()

                    # Publish rejection event
                    if self._event_publisher:
                        try:
                            await self._event_publisher(
                                {
                                    "type": "permission_replied",
                                    "data": {
                                        "request_id": pid,
                                        "reply": "reject",
                                        "session_id": session_id,
                                    },
                                }
                            )
                        except Exception as e:
                            logger.error(f"Failed to publish rejection event: {e}")

            logger.info(f"Permission rejected for session {session_id}")

        elif reply == "once":
            pending.result["result"] = "allow"
            pending.event.set()
            logger.info(f"Permission granted once: {pending.request.permission}")

        elif reply == "always":
            # Add permanent rules for the always_patterns
            for pattern in pending.request.always_patterns:
                self.approved.append(
                    PermissionRule(
                        pending.request.permission,
                        pattern,
                        PermissionAction.ALLOW,
                    )
                )

            pending.result["result"] = "allow"
            pending.event.set()

            # Check if other pending requests now pass
            session_id = pending.request.session_id
            for pid, p in list(self.pending.items()):
                if p.request.session_id != session_id:
                    continue

                # Check if all patterns now pass
                all_allowed = all(
                    self.evaluate(p.request.permission, pat).action == PermissionAction.ALLOW
                    for pat in p.request.patterns
                )

                if all_allowed:
                    del self.pending[pid]
                    p.result["result"] = "allow"
                    p.event.set()

                    # Publish auto-approval event
                    if self._event_publisher:
                        try:
                            await self._event_publisher(
                                {
                                    "type": "permission_replied",
                                    "data": {
                                        "request_id": pid,
                                        "reply": "always",
                                        "session_id": session_id,
                                        "auto_approved": True,
                                    },
                                }
                            )
                        except Exception as e:
                            logger.error(f"Failed to publish auto-approval event: {e}")

            logger.info(
                f"Permission granted always: {pending.request.permission} "
                f"for patterns {pending.request.always_patterns}"
            )

    def get_pending_requests(self, session_id: str | None = None) -> list[PermissionRequest]:
        """
        Get pending permission requests.

        Args:
            session_id: Filter by session ID (optional)

        Returns:
            List of pending requests
        """
        requests = [p.request for p in self.pending.values()]
        if session_id:
            requests = [r for r in requests if r.session_id == session_id]
        return requests

    def cancel_all(self, session_id: str) -> int:
        """
        Cancel all pending requests for a session.

        Args:
            session_id: Session ID to cancel

        Returns:
            Number of requests cancelled
        """
        cancelled = 0
        for pid, p in list(self.pending.items()):
            if p.request.session_id == session_id:
                del self.pending[pid]
                p.result["result"] = "reject"
                p.event.set()
                cancelled += 1
        return cancelled

    def add_rule(self, rule: PermissionRule) -> None:
        """
        Add a rule to the base ruleset.

        Args:
            rule: Rule to add
        """
        self.ruleset.append(rule)

    def clear_approved(self) -> None:
        """Clear all runtime-approved rules."""
        self.approved.clear()

    def reset(self) -> None:
        """Reset manager to initial state."""
        self.approved.clear()
        self.mode_rules.clear()
        self.pending.clear()
        self._request_counter = 0
        self._current_mode = AgentPermissionMode.BUILD

    def get_disabled_tools(self, tools: list[str]) -> set:
        """
        Get the set of tools that are disabled based on current mode and rules.

        A tool is disabled if there's a DENY rule for that tool's permission.

        Args:
            tools: List of tool names to check

        Returns:
            Set of disabled tool names
        """
        from .rules import get_disabled_tools

        # Merge all rule sources
        all_rules = self.ruleset + self.mode_rules + self.approved
        return get_disabled_tools(tools, all_rules)

    def get_allowed_tools(self, tools: list[str]) -> list[str]:
        """
        Get the list of tools that are allowed in the current mode.

        Args:
            tools: List of all available tool names

        Returns:
            List of allowed tool names
        """
        disabled = self.get_disabled_tools(tools)
        return [t for t in tools if t not in disabled]
