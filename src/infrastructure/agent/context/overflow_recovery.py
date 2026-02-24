"""Overflow recovery coordinator with explicit staged state machine."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from src.infrastructure.agent.context.window_manager import (
    ContextWindowConfig,
    ContextWindowManager,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OverflowRecoveryConfig:
    """Configuration for staged overflow recovery."""

    context_shrink_ratio: float = 0.75
    tail_keep_messages: int = 20
    max_tool_chars: int = 400
    max_assistant_chars: int = 1600


@dataclass(frozen=True)
class OverflowRecoveryResult:
    """Result for a staged overflow recovery execution."""

    messages: list[dict[str, Any]]
    metadata: dict[str, Any]


class OverflowRecoveryCoordinator:
    """State-machine coordinator for overflow recovery."""

    def __init__(self, config: OverflowRecoveryConfig | None = None) -> None:
        self._config = config or OverflowRecoveryConfig()

    @property
    def config(self) -> OverflowRecoveryConfig:
        return self._config

    def build_aggressive_config(self, base_config: ContextWindowConfig) -> ContextWindowConfig:
        """Build aggressive compression config used for force-compaction stage."""
        l1 = min(base_config.l1_trigger_pct, 0.35)
        l2 = min(base_config.l2_trigger_pct, 0.55)
        l3 = min(base_config.l3_trigger_pct, 0.75)
        if l2 <= l1:
            l2 = min(l1 + 0.1, 0.85)
        if l3 <= l2:
            l3 = min(l2 + 0.1, 0.95)

        reduced_context_tokens = max(
            4096,
            int(base_config.max_context_tokens * self._config.context_shrink_ratio),
        )
        return replace(
            base_config,
            max_context_tokens=reduced_context_tokens,
            l1_trigger_pct=l1,
            l2_trigger_pct=l2,
            l3_trigger_pct=l3,
        )

    @staticmethod
    def truncate_messages(
        messages: list[dict[str, Any]],
        *,
        max_tool_chars: int = 400,
        max_assistant_chars: int = 1600,
    ) -> tuple[list[dict[str, Any]], int]:
        """Apply deterministic content truncation."""
        if not messages:
            return messages, 0

        truncated_count = 0
        updated: list[dict[str, Any]] = []
        for msg in messages:
            role = str(msg.get("role", ""))
            content = msg.get("content")
            if not isinstance(content, str):
                updated.append(msg)
                continue

            if role == "tool" and len(content) > max_tool_chars:
                truncated_count += 1
                updated.append(
                    {
                        **msg,
                        "content": (
                            content[:max_tool_chars]
                            + "\n[... tool output truncated for overflow recovery]"
                        ),
                    }
                )
                continue

            if role == "assistant" and len(content) > max_assistant_chars:
                truncated_count += 1
                updated.append(
                    {
                        **msg,
                        "content": (
                            content[:max_assistant_chars]
                            + "\n[... assistant output truncated for overflow recovery]"
                        ),
                    }
                )
                continue

            updated.append(msg)

        return updated, truncated_count

    def _tail_trim_messages(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        """Keep system prefix + recent tail for final fallback stage."""
        if not messages:
            return messages, 0

        has_system = messages[0].get("role") == "system"
        prefix = messages[:1] if has_system else []
        body = messages[1:] if has_system else messages
        if len(body) <= self._config.tail_keep_messages:
            return messages, 0

        dropped = len(body) - self._config.tail_keep_messages
        return prefix + body[-self._config.tail_keep_messages :], dropped

    async def recover(
        self,
        *,
        context_request: Any,
        current_messages: list[dict[str, Any]],
        base_manager: ContextWindowManager,
        build_context: Callable[[Any, ContextWindowManager], Awaitable[Any]],
        estimate_messages_tokens: Callable[[list[dict[str, Any]]], int],
    ) -> OverflowRecoveryResult:
        """Run staged overflow recovery: force_compact -> truncate -> tail_trim."""
        stages: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {
            "strategy": "force_compaction_then_truncate_then_tail_trim",
            "forced_compaction": False,
            "truncated_messages": 0,
            "dropped_messages": 0,
            "stages": stages,
        }

        before_tokens = estimate_messages_tokens(current_messages)
        recovered_messages = current_messages

        try:
            recovery_manager = ContextWindowManager(self.build_aggressive_config(base_manager.config))
            recovery_result = await build_context(context_request, recovery_manager)
            recovered_messages = recovery_result.messages
            metadata["forced_compaction"] = bool(recovery_result.was_compressed)
            metadata["forced_compression_level"] = recovery_result.metadata.get(
                "compression_level", "none"
            )
            stages.append(
                {
                    "stage": "force_compaction",
                    "applied": True,
                    "compressed": bool(recovery_result.was_compressed),
                    "level": recovery_result.metadata.get("compression_level", "none"),
                }
            )
        except Exception as recovery_error:
            logger.warning("[OverflowRecovery] force_compaction stage failed: %s", recovery_error)
            stages.append(
                {
                    "stage": "force_compaction",
                    "applied": False,
                    "error": str(recovery_error),
                }
            )

        recovered_messages, truncated_count = self.truncate_messages(
            recovered_messages,
            max_tool_chars=self._config.max_tool_chars,
            max_assistant_chars=self._config.max_assistant_chars,
        )
        metadata["truncated_messages"] = truncated_count
        stages.append(
            {
                "stage": "truncate",
                "applied": truncated_count > 0,
                "truncated_messages": truncated_count,
            }
        )

        after_truncate_tokens = estimate_messages_tokens(recovered_messages)
        should_tail_trim = (
            after_truncate_tokens >= int(before_tokens * 0.90)
            or truncated_count == 0
            or len(recovered_messages) > self._config.tail_keep_messages + 1
        )
        dropped_messages = 0
        if should_tail_trim:
            recovered_messages, dropped_messages = self._tail_trim_messages(recovered_messages)
        metadata["dropped_messages"] = dropped_messages
        stages.append(
            {
                "stage": "tail_trim",
                "applied": dropped_messages > 0,
                "dropped_messages": dropped_messages,
            }
        )

        after_tokens = estimate_messages_tokens(recovered_messages)
        metadata["tokens_before"] = before_tokens
        metadata["tokens_after"] = after_tokens
        metadata["final_stage"] = "tail_trim" if dropped_messages > 0 else "truncate"

        return OverflowRecoveryResult(messages=recovered_messages, metadata=metadata)

