"""Heartbeat runner for periodic agent self-check during long sessions.

Ported from OpenClaw's heartbeat-runner.ts. Adapts the file-based timer
pattern into an asyncio-friendly class that integrates with ReActAgent's
stream() lifecycle.

The HeartbeatRunner tracks timing state and provides:
- ``check_due()`` — whether a heartbeat check is needed
- ``run_once()`` — load HEARTBEAT.md and decide if the agent should act
- ``process_reply()`` — strip HEARTBEAT_OK from the agent's reply

Unlike OpenClaw which runs heartbeats as separate LLM calls through a
session system, MemStack integrates heartbeat checks into the ReActAgent
stream() loop — checking between phases whether a heartbeat is due.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.heartbeat.config import HeartbeatConfig
from src.infrastructure.agent.heartbeat.tokens import (
    is_heartbeat_content_effectively_empty,
    strip_heartbeat_token,
)

if TYPE_CHECKING:
    from src.infrastructure.agent.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeartbeatCheckResult:
    """Result of a heartbeat check.

    Attributes:
        should_run: Whether the agent should process a heartbeat prompt.
        prompt: The heartbeat prompt text (non-empty only when should_run is True).
        heartbeat_content: Raw HEARTBEAT.md content (for logging/debugging).
        reason_skipped: Why the heartbeat was skipped (empty when should_run is True).
    """

    should_run: bool
    prompt: str = ""
    heartbeat_content: str = ""
    reason_skipped: str = ""


@dataclass(frozen=True)
class HeartbeatReplyResult:
    """Result of processing an agent's heartbeat reply.

    Attributes:
        should_suppress: Whether the reply should be suppressed (HEARTBEAT_OK).
        cleaned_text: The reply text after token stripping.
        did_strip: Whether HEARTBEAT_OK was found and removed.
    """

    should_suppress: bool
    cleaned_text: str = ""
    did_strip: bool = False


@dataclass
class _HeartbeatTimingState:
    """Internal timing state for the heartbeat runner.

    Tracks per-session timing to determine when the next heartbeat is due.
    """

    last_run_time: float = 0.0
    next_due_time: float = 0.0
    run_count: int = 0
    consecutive_ok_count: int = 0
    consecutive_actionable_count: int = 0


class HeartbeatRunner:
    """Async heartbeat runner for periodic agent self-check.

    Integrates with ReActAgent's stream() lifecycle to periodically check
    HEARTBEAT.md for user instructions. When actionable content is found,
    the runner provides a prompt for the agent to process. When the agent
    replies with HEARTBEAT_OK, the reply is suppressed.

    Usage::

        runner = HeartbeatRunner(
            config=HeartbeatConfig(enabled=True, interval_minutes=30),
            workspace_manager=workspace_manager,
        )

        # During stream() between phases:
        if runner.check_due():
            result = await runner.run_once()
            if result.should_run:
                # Inject result.prompt into agent context
                ...

        # After agent replies to heartbeat:
        reply_result = runner.process_reply(agent_reply_text)
        if reply_result.should_suppress:
            # Don't emit this reply to the user
            ...
    """

    def __init__(
        self,
        config: HeartbeatConfig,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        """Initialize HeartbeatRunner.

        Args:
            config: Heartbeat configuration (interval, prompt, thresholds).
            workspace_manager: WorkspaceManager for loading HEARTBEAT.md.
                If None, heartbeat checks always return should_run=False.
        """
        self._config = config
        self._workspace_manager = workspace_manager
        self._state = _HeartbeatTimingState()
        self._enabled = config.enabled and workspace_manager is not None

        # Initialize next_due_time to now + interval so the first check
        # doesn't fire immediately at session start.
        if self._enabled:
            now = time.monotonic()
            self._state.next_due_time = now + config.interval_seconds
            self._state.last_run_time = now

    @property
    def enabled(self) -> bool:
        """Whether heartbeat checks are active."""
        return self._enabled

    @property
    def config(self) -> HeartbeatConfig:
        """Current heartbeat configuration."""
        return self._config

    @property
    def run_count(self) -> int:
        """Number of heartbeat checks performed."""
        return self._state.run_count

    @property
    def stats(self) -> dict[str, Any]:
        """Diagnostic statistics for observability."""
        return {
            "enabled": self._enabled,
            "run_count": self._state.run_count,
            "consecutive_ok": self._state.consecutive_ok_count,
            "consecutive_actionable": self._state.consecutive_actionable_count,
            "interval_minutes": self._config.interval_minutes,
            "next_due_in_seconds": max(0.0, self._state.next_due_time - time.monotonic())
            if self._enabled
            else None,
        }

    def check_due(self) -> bool:
        """Check whether a heartbeat is due based on timing state.

        Returns:
            True if a heartbeat check should be performed now.
        """
        if not self._enabled:
            return False

        now = time.monotonic()
        return now >= self._state.next_due_time

    async def run_once(self, *, force: bool = False) -> HeartbeatCheckResult:
        """Perform a single heartbeat check.

        Loads HEARTBEAT.md via WorkspaceManager and determines whether the
        agent should process a heartbeat prompt.

        Args:
            force: If True, skip the timing check and run immediately.

        Returns:
            HeartbeatCheckResult indicating whether the agent should act.
        """
        if not self._enabled:
            return HeartbeatCheckResult(
                should_run=False,
                reason_skipped="heartbeat_disabled",
            )

        if not force and not self.check_due():
            return HeartbeatCheckResult(
                should_run=False,
                reason_skipped="not_due",
            )

        assert self._workspace_manager is not None  # guaranteed by _enabled

        # Update timing state
        now = time.monotonic()
        self._state.last_run_time = now
        self._state.next_due_time = now + self._config.interval_seconds
        self._state.run_count += 1

        # Load HEARTBEAT.md (force reload to pick up user changes)
        try:
            self._workspace_manager.invalidate_cache()
            workspace_files = await self._workspace_manager.load_all(force_reload=True)
            heartbeat_content = workspace_files.heartbeat_text
        except Exception as e:
            logger.warning("HeartbeatRunner: Failed to load HEARTBEAT.md: %s", e)
            return HeartbeatCheckResult(
                should_run=False,
                reason_skipped=f"load_error: {e}",
            )

        # Check if HEARTBEAT.md has no actionable content
        if heartbeat_content is None:
            logger.debug("HeartbeatRunner: HEARTBEAT.md not found, skipping")
            return HeartbeatCheckResult(
                should_run=False,
                reason_skipped="file_not_found",
            )

        if is_heartbeat_content_effectively_empty(heartbeat_content):
            logger.debug("HeartbeatRunner: HEARTBEAT.md is effectively empty, skipping")
            self._state.consecutive_ok_count += 1
            self._state.consecutive_actionable_count = 0
            return HeartbeatCheckResult(
                should_run=False,
                heartbeat_content=heartbeat_content,
                reason_skipped="effectively_empty",
            )

        # Actionable content found — build the prompt
        self._state.consecutive_actionable_count += 1
        self._state.consecutive_ok_count = 0

        prompt = self._build_heartbeat_prompt(heartbeat_content)
        logger.info(
            "HeartbeatRunner: Actionable content found in HEARTBEAT.md (run #%d, %d chars)",
            self._state.run_count,
            len(heartbeat_content),
        )

        return HeartbeatCheckResult(
            should_run=True,
            prompt=prompt,
            heartbeat_content=heartbeat_content,
        )

    def process_reply(self, reply_text: str | None) -> HeartbeatReplyResult:
        """Process the agent's reply to a heartbeat prompt.

        Strips HEARTBEAT_OK token and determines whether the reply should
        be suppressed or delivered to the user.

        Args:
            reply_text: The agent's reply text.

        Returns:
            HeartbeatReplyResult with suppression decision and cleaned text.
        """
        should_skip, cleaned_text, did_strip = strip_heartbeat_token(
            reply_text,
            mode="heartbeat",
            max_ack_chars=self._config.ack_max_chars,
        )

        if should_skip:
            self._state.consecutive_ok_count += 1
            self._state.consecutive_actionable_count = 0
            logger.debug(
                "HeartbeatRunner: Reply suppressed (HEARTBEAT_OK, run #%d)",
                self._state.run_count,
            )
        else:
            self._state.consecutive_ok_count = 0
            self._state.consecutive_actionable_count += 1
            logger.info(
                "HeartbeatRunner: Actionable reply (%d chars, run #%d)",
                len(cleaned_text),
                self._state.run_count,
            )

        return HeartbeatReplyResult(
            should_suppress=should_skip,
            cleaned_text=cleaned_text,
            did_strip=did_strip,
        )

    def reset(self) -> None:
        """Reset timing state (e.g., after conversation restart)."""
        now = time.monotonic()
        self._state = _HeartbeatTimingState(
            next_due_time=now + self._config.interval_seconds,
            last_run_time=now,
        )
        logger.debug("HeartbeatRunner: State reset")

    def _build_heartbeat_prompt(self, heartbeat_content: str) -> str:
        """Build the full heartbeat prompt including HEARTBEAT.md content.

        Combines the configured base prompt with the actual file content,
        wrapped in XML tags for clear separation.

        Args:
            heartbeat_content: Raw HEARTBEAT.md content.

        Returns:
            Complete prompt string for the agent.
        """
        return (
            f"{self._config.prompt}\n\n"
            f"<heartbeat-instructions>\n"
            f"{heartbeat_content}\n"
            f"</heartbeat-instructions>"
        )
