"""Unified tool execution pipeline.

Consolidates all cross-cutting tool execution concerns into a single
async-generator pipeline: pre-hooks, doom loop detection, permission
checking, execution, output truncation, post-hooks, and side-effect
event collection.

Each call to ``ToolPipeline.execute`` yields a stream of ``ToolEvent``
objects that the caller can forward to SSE or domain event buses.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.context import ToolContext
    from src.infrastructure.agent.tools.executor import (
        DoomLoopDetectorProtocol,
        PermissionManagerProtocol,
    )
    from src.infrastructure.agent.tools.hooks import ToolHookRegistry
    from src.infrastructure.agent.tools.result import ToolEvent, ToolResult
    from src.infrastructure.agent.tools.truncation import OutputTruncator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolInfoProtocol(Protocol):
    """Minimal interface for a tool that ToolPipeline can execute."""

    name: str
    permission: str | None

    async def execute(self, **kwargs: Any) -> Any:
        """Run the tool with the given keyword arguments."""
        ...


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class ToolPipeline:
    """Unified execution wrapper for all tool invocations.

    Wraps every tool call with the following ordered stages:

    1. Pre-hooks (modify args / deny / ask)
    2. Doom loop detection
    3. Permission check
    4. Execute
    5. Normalize result
    6. Truncate output
    7. Post-hooks
    8. Collect side-effect events from context
    9. Yield completed event
    """

    def __init__(
        self,
        permission_manager: PermissionManagerProtocol,
        doom_detector: DoomLoopDetectorProtocol,
        truncator: OutputTruncator,
        hooks: ToolHookRegistry,
    ) -> None:
        super().__init__()
        self._permission_manager = permission_manager
        self._doom_detector = doom_detector
        self._truncator = truncator
        self._hooks = hooks

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        tool: ToolInfoProtocol,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> AsyncIterator[ToolEvent]:
        """Run *tool* through the full pipeline, yielding events.

        This is an async generator. Callers should iterate with
        ``async for event in pipeline.execute(...): ...``.

        Args:
            tool: Any object satisfying ``ToolInfoProtocol``.
            args: Keyword arguments for the tool.
            ctx: Unified execution context.

        Yields:
            ``ToolEvent`` instances for each lifecycle stage.
        """
        from src.infrastructure.agent.tools.hooks import HookDecision
        from src.infrastructure.agent.tools.result import ToolEvent

        logger.debug("Pipeline start: tool=%s", tool.name)

        # Step 1 ---- Pre-hooks -------------------------------------------
        hook_result = await self._hooks.run_before(tool.name, args, ctx)

        if hook_result.decision == HookDecision.DENY:
            logger.warning(
                "Pre-hook denied tool=%s reason=%s",
                tool.name,
                hook_result.reason,
            )
            yield ToolEvent.denied(tool.name)
            return

        if hook_result.decision == HookDecision.ASK:
            yield ToolEvent.permission_asked(tool.name)
            approved = await ctx.ask(tool.permission or tool.name)
            if not approved:
                logger.warning("User denied hook-ask for tool=%s", tool.name)
                yield ToolEvent.denied(tool.name)
                return

        effective_args = hook_result.args if hook_result.args is not None else args

        # Step 2 ---- Doom loop check -------------------------------------
        if self._doom_detector.should_intervene(tool.name, effective_args):
            logger.warning("Doom loop detected for tool=%s", tool.name)
            yield ToolEvent.doom_loop(tool.name)
            return

        self._doom_detector.record(tool.name, effective_args)

        # Step 3 ---- Permission check ------------------------------------
        denied = await self._check_permission(tool, effective_args, ctx)
        if denied is not None:
            yield denied
            return

        # Steps 4-9 -- Execute, normalize, truncate, post-hooks, emit -----
        async for event in self._execute_and_finalize(
            tool,
            effective_args,
            ctx,
        ):
            yield event

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _execute_and_finalize(
        self,
        tool: ToolInfoProtocol,
        effective_args: dict[str, Any],
        ctx: ToolContext,
    ) -> AsyncIterator[ToolEvent]:
        """Execute tool and run post-execution pipeline stages.

        Covers steps 4 through 9: execute, normalize, truncate,
        post-hooks, side-effect collection, and completed event.
        """
        from src.infrastructure.agent.tools.context import ToolAbortedError
        from src.infrastructure.agent.tools.result import ToolEvent, ToolResult

        # Step 4 ---- Execute ---------------------------------------------
        yield ToolEvent.started(tool.name, effective_args)
        start_time = time.time()

        try:
            raw_result = await tool.execute(**effective_args)
        except ToolAbortedError:
            logger.debug("Tool aborted: tool=%s", tool.name)
            yield ToolEvent.aborted(tool.name)
            return
        except Exception as exc:
            logger.error(
                "Tool execution failed: tool=%s error=%s",
                tool.name,
                exc,
                exc_info=True,
            )
            error_result = ToolResult(output=str(exc), is_error=True)
            error_result = await self._hooks.run_after(
                tool.name,
                error_result,
                ctx,
            )
            yield ToolEvent.completed(tool.name, error_result)
            return

        duration_ms = int((time.time() - start_time) * 1000)

        # Step 5 ---- Normalize result ------------------------------------
        result = self._normalize_result(raw_result)

        # Step 6 ---- Truncate output -------------------------------------
        result = self._maybe_truncate(result, tool.name)

        # Step 7 ---- Post-hooks ------------------------------------------
        result = await self._hooks.run_after(tool.name, result, ctx)

        # Step 8 ---- Collect side-effect events from context -------------
        for event in ctx.consume_pending_events():
            if isinstance(event, ToolEvent):
                yield event
            else:
                # Legacy tool events (dicts) — wrap in a ToolEvent for
                # uniform pipeline output.  The processor inspects the
                # ``legacy_event`` type and yields the inner dict.
                yield ToolEvent(
                    type="legacy_event",
                    tool_name=tool.name,
                    data={"event": event},
                )

        # Step 9 ---- Yield completed event -------------------------------
        completed_event = ToolEvent.completed(tool.name, result)
        completed_event.data["duration_ms"] = duration_ms
        yield completed_event

        logger.debug(
            "Pipeline complete: tool=%s duration_ms=%d",
            tool.name,
            duration_ms,
        )

    def _maybe_truncate(self, result: ToolResult, tool_name: str) -> ToolResult:
        """Truncate output if result is not an error and has content."""
        if result.is_error or not result.output:
            return result

        original_metadata = dict(result.metadata)
        original_attachments = list(result.attachments)
        original_title = result.title

        truncated = self._truncator.truncate_to_result(
            result.output,
            tool_name=tool_name,
        )
        truncated.metadata = {**original_metadata, **truncated.metadata}
        truncated.attachments = original_attachments
        truncated.title = original_title
        return truncated

    async def _check_permission(
        self,
        tool: ToolInfoProtocol,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolEvent | None:
        """Evaluate tool permission rules.

        Returns a ``ToolEvent`` that should be yielded if execution must
        stop, or ``None`` if permission is granted.
        """
        from src.infrastructure.agent.tools.executor import PermissionAction
        from src.infrastructure.agent.tools.result import ToolEvent

        if not tool.permission:
            return None

        rule = self._permission_manager.evaluate(tool.permission, tool.name)

        if rule.action == PermissionAction.DENY:
            logger.warning(
                "Permission denied: tool=%s permission=%s",
                tool.name,
                tool.permission,
            )
            return ToolEvent.denied(tool.name)

        if rule.action == PermissionAction.ASK:
            result_str = await self._permission_manager.ask(
                permission=tool.permission,
                patterns=[tool.name],
                session_id=ctx.session_id,
                metadata={"tool": tool.name, "input": args},
            )
            if result_str == "reject":
                return ToolEvent.denied(tool.name)
        return None

    def _normalize_result(self, raw: Any) -> ToolResult:
        """Convert an arbitrary tool return value to ``ToolResult``.

        Handles four cases:
        - Already a ``ToolResult``: returned as-is.
        - ``dict`` with an ``"output"`` key: output extracted, rest as metadata.
        - ``str``: wrapped directly.
        - Anything else: JSON-serialized with ``default=str``.
        """
        from src.infrastructure.agent.tools.result import ToolResult

        if isinstance(raw, ToolResult):
            return raw

        if isinstance(raw, dict) and "output" in raw:
            raw_dict = cast(dict[str, Any], raw)
            output = str(raw_dict["output"])
            metadata: dict[str, Any] = {k: v for k, v in raw_dict.items() if k != "output"}
            return ToolResult(output=output, metadata=metadata)

        if isinstance(raw, str):
            return ToolResult(output=raw)

        return ToolResult(output=json.dumps(raw, default=str))


__all__ = ["ToolInfoProtocol", "ToolPipeline"]
