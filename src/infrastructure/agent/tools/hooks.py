"""Registry for pre/post tool execution hooks.

Hooks are matched against tool names using glob patterns and executed
in priority order (lower number = earlier execution).

Before-hooks can modify arguments, deny execution, or escalate to user
permission. After-hooks can modify the result.
"""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


class HookDecision(Enum):
    """Decision returned by before-hooks to control execution."""

    CONTINUE = "continue"  # Proceed with (possibly modified) args
    DENY = "deny"  # Block tool execution
    ASK = "ask"  # Escalate to user permission prompt


@dataclass
class HookResult:
    """Result from a before-hook execution."""

    decision: HookDecision = HookDecision.CONTINUE
    args: dict[str, Any] | None = None  # Modified args (None = unchanged)
    reason: str = ""  # Human-readable reason for deny/ask


# Type aliases for hook callables
BeforeHook = Callable[
    [str, dict[str, Any], ToolContext],
    Awaitable[HookResult],
]
AfterHook = Callable[
    [str, ToolResult, ToolContext],
    Awaitable[ToolResult],
]


@dataclass
class _RegisteredBeforeHook:
    """Internal registration entry for a before-hook."""

    hook: BeforeHook
    pattern: str  # Tool name glob pattern (e.g., "*", "terminal*", "mcp__*")
    priority: int  # Lower number = runs first
    name: str = ""  # Optional name for debugging


@dataclass
class _RegisteredAfterHook:
    """Internal registration entry for an after-hook."""

    hook: AfterHook
    pattern: str  # Tool name glob pattern (e.g., "*", "terminal*", "mcp__*")
    priority: int  # Lower number = runs first
    name: str = ""  # Optional name for debugging


class HookPriority:
    """Well-known priority constants for hook ordering.

    Lower values execute earlier. Custom hooks should use values
    between the defined constants to interleave as needed.
    """

    SECURITY = 10
    VALIDATION = 50
    DEFAULT = 100
    LOGGING = 200
    CLEANUP = 500


class ToolHookRegistry:
    """Registry for pre/post tool execution hooks.

    Hooks are matched against tool names using glob patterns
    and executed in priority order (lower number = earlier execution).

    Before-hooks can modify arguments, deny execution, or escalate
    to user permission. After-hooks can modify the result.
    """

    def __init__(self) -> None:
        self._before_hooks: list[_RegisteredBeforeHook] = []
        self._after_hooks: list[_RegisteredAfterHook] = []

    def register_before(
        self,
        hook: BeforeHook,
        pattern: str = "*",
        priority: int = HookPriority.DEFAULT,
        name: str = "",
    ) -> None:
        """Register a before-execution hook.

        Args:
            hook: Async callable receiving (tool_name, args, ctx).
            pattern: Glob pattern to match tool names.
            priority: Execution order (lower = earlier).
            name: Optional name for debugging/logging.
        """
        entry = _RegisteredBeforeHook(hook=hook, pattern=pattern, priority=priority, name=name)
        self._before_hooks.append(entry)
        self._before_hooks.sort(key=lambda h: h.priority)

    def register_after(
        self,
        hook: AfterHook,
        pattern: str = "*",
        priority: int = HookPriority.DEFAULT,
        name: str = "",
    ) -> None:
        """Register an after-execution hook.

        Args:
            hook: Async callable receiving (tool_name, result, ctx).
            pattern: Glob pattern to match tool names.
            priority: Execution order (lower = earlier).
            name: Optional name for debugging/logging.
        """
        entry = _RegisteredAfterHook(hook=hook, pattern=pattern, priority=priority, name=name)
        self._after_hooks.append(entry)
        self._after_hooks.sort(key=lambda h: h.priority)

    async def run_before(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> HookResult:
        """Run all matching before-hooks in priority order.

        Stops at first DENY or ASK decision. CONTINUE hooks
        may modify args which are passed to subsequent hooks.

        Args:
            tool_name: Name of the tool being executed.
            args: Tool arguments (may be modified by hooks).
            ctx: Tool execution context.

        Returns:
            HookResult with final decision and possibly modified args.
        """
        current_args = dict(args)  # Defensive copy
        for entry in self._before_hooks:
            if not fnmatch.fnmatch(tool_name, entry.pattern):
                continue
            try:
                result = await entry.hook(tool_name, current_args, ctx)
                if result.decision != HookDecision.CONTINUE:
                    logger.info(
                        "Hook '%s' returned %s for tool '%s': %s",
                        entry.name or "<anonymous>",
                        result.decision.value,
                        tool_name,
                        result.reason,
                    )
                    return result
                if result.args is not None:
                    current_args = result.args
            except Exception:
                logger.exception(
                    "Before-hook '%s' failed for tool '%s'",
                    entry.name or "<anonymous>",
                    tool_name,
                )
                # Hook failures don't block execution
        return HookResult(decision=HookDecision.CONTINUE, args=current_args)

    async def run_after(
        self,
        tool_name: str,
        result: ToolResult,
        ctx: ToolContext,
    ) -> ToolResult:
        """Run all matching after-hooks in priority order.

        Each hook receives the result from the previous hook.

        Args:
            tool_name: Name of the tool that was executed.
            result: Tool execution result (may be modified by hooks).
            ctx: Tool execution context.

        Returns:
            Possibly modified ToolResult.
        """
        current_result = result
        for entry in self._after_hooks:
            if not fnmatch.fnmatch(tool_name, entry.pattern):
                continue
            try:
                current_result = await entry.hook(tool_name, current_result, ctx)
            except Exception:
                logger.exception(
                    "After-hook '%s' failed for tool '%s'",
                    entry.name or "<anonymous>",
                    tool_name,
                )
                # Hook failures don't modify result
        return current_result

    def clear(self) -> None:
        """Remove all registered hooks."""
        self._before_hooks.clear()
        self._after_hooks.clear()

    @property
    def before_hook_count(self) -> int:
        """Number of registered before-hooks."""
        return len(self._before_hooks)

    @property
    def after_hook_count(self) -> int:
        """Number of registered after-hooks."""
        return len(self._after_hooks)
