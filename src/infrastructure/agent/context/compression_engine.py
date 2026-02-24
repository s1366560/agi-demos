"""
Context Compression Engine - Adaptive multi-level context compression.

Implements a self-adaptive compression system with three levels:
- L1 (Prune): Tool output pruning via existing compaction logic
- L2 (Summarize): Incremental chunk-based summarization
- L3 (Deep Compress): Global distillation of all summaries into one compact summary

The AdaptiveStrategySelector picks the level based on context occupancy:
- < 60%  -> NONE (no action)
- 60-80% -> L1_PRUNE
- 80-90% -> L2_SUMMARIZE (includes L1)
- 90%+   -> L3_DEEP_COMPRESS (includes L1 + L2)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient


from src.infrastructure.agent.context.compaction import (
    ModelLimits,
    calculate_usable_context,
)
from src.infrastructure.agent.context.compression_history import (
    CompressionHistory,
    CompressionRecord,
)
from src.infrastructure.agent.context.compression_state import (
    CompressionLevel,
    CompressionState,
    SummaryChunk,
)

logger = logging.getLogger(__name__)

# Default chunk size for incremental summarization
DEFAULT_CHUNK_SIZE = 10

# Default role-aware truncation limits (chars). User messages carry requirements
# and constraints, so they get more budget than assistant responses.
_DEFAULT_ROLE_TRUNCATE_LIMITS = {
    "user": 800,
    "assistant": 300,
    "tool": 200,
    "system": 1000,
}
_DEFAULT_TRUNCATE_LIMIT = 500

# Summarization prompts
CHUNK_SUMMARY_PROMPT = """Summarize the following conversation segment concisely.

Priority rules (highest to lowest):
1. User requirements, constraints, and questions - preserve verbatim when short
2. Open tasks, unresolved TODOs, blockers, and failures
3. Most recent verified tool observations (include tool name + key outcome)
4. Key decisions and conclusions reached
5. Entity names, IDs, paths, and relationships needed for continuity
6. Assistant reasoning - compress aggressively, keep only outcomes

{previous_summary_context}

--- USER MESSAGES ---
{user_text}

--- ASSISTANT & TOOL MESSAGES ---
{assistant_text}

Provide a concise summary (under {max_tokens} tokens). Start with user requirements,
then verified observations, then open tasks/blockers. Never present unverified work as completed:"""

DEEP_COMPRESS_PROMPT = """Distill the following conversation context into an ultra-compact summary.

Structure your summary in these sections:
1. USER GOAL: The user's primary objective and constraints (MUST preserve)
2. VERIFIED TOOL EVIDENCE: Tool name + key observed result
3. OPEN TASKS/BLOCKERS: Unfinished work, failures, and pending validation
4. DECISIONS: All critical decisions made so far
5. STATE: Current task state, what has been done, what remains
6. CONTEXT: Important entities, relationships, paths, and IDs

Previous summaries:
{summaries}

Recent context:
{recent_text}

Provide a highly compressed summary that retains all essential information.
Do NOT mark unverified items as completed:"""


@dataclass
class AdaptiveThresholds:
    """Configurable thresholds for adaptive compression level selection."""

    l1_trigger_pct: float = 0.60  # 60% -> start pruning
    l2_trigger_pct: float = 0.80  # 80% -> start summarizing
    l3_trigger_pct: float = 0.90  # 90% -> deep compress

    def validate(self) -> None:
        if not (0 < self.l1_trigger_pct < self.l2_trigger_pct < self.l3_trigger_pct <= 1.0):
            raise ValueError(
                f"Thresholds must be ordered: l1({self.l1_trigger_pct}) "
                f"< l2({self.l2_trigger_pct}) < l3({self.l3_trigger_pct})"
            )


@dataclass
class CompressionResult:
    """Result of a compression operation."""

    messages: list[dict[str, Any]]
    level: CompressionLevel
    tokens_before: int
    tokens_after: int
    messages_before: int
    messages_after: int
    summary: str | None = None
    pruned_tool_outputs: int = 0
    duration_ms: float = 0.0

    @property
    def tokens_saved(self) -> int:
        return self.tokens_before - self.tokens_after

    @property
    def compression_ratio(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return self.tokens_after / self.tokens_before

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "compression_ratio": round(self.compression_ratio, 3),
            "messages_before": self.messages_before,
            "messages_after": self.messages_after,
            "pruned_tool_outputs": self.pruned_tool_outputs,
            "duration_ms": round(self.duration_ms, 1),
        }


# Type alias for token estimation function
TokenEstimator = Callable[[str], int]
MessageTokenEstimator = Callable[[dict[str, Any]], int]


class AdaptiveStrategySelector:
    """Selects compression level based on context occupancy."""

    def __init__(self, thresholds: AdaptiveThresholds | None = None) -> None:
        self._thresholds = thresholds or AdaptiveThresholds()
        self._thresholds.validate()

    def select(
        self,
        current_tokens: int,
        model_limits: ModelLimits,
        history: CompressionHistory | None = None,
    ) -> CompressionLevel:
        """Select the appropriate compression level.

        Args:
            current_tokens: Current total token count
            model_limits: Model token limits
            history: Compression history for adaptive tuning

        Returns:
            Recommended compression level
        """
        usable = calculate_usable_context(model_limits)
        if usable == 0:
            return CompressionLevel.NONE

        occupancy = current_tokens / usable

        if occupancy >= self._thresholds.l3_trigger_pct:
            level = CompressionLevel.L3_DEEP_COMPRESS
        elif occupancy >= self._thresholds.l2_trigger_pct:
            level = CompressionLevel.L2_SUMMARIZE
        elif occupancy >= self._thresholds.l1_trigger_pct:
            level = CompressionLevel.L1_PRUNE
        else:
            level = CompressionLevel.NONE

        logger.debug(
            f"Strategy selected: level={level.value}, "
            f"occupancy={occupancy:.1%} ({current_tokens}/{usable})"
        )
        return level

    def get_occupancy(self, current_tokens: int, model_limits: ModelLimits) -> float:
        """Calculate current context occupancy ratio."""
        usable = calculate_usable_context(model_limits)
        if usable == 0:
            return 0.0
        return current_tokens / usable


class ContextCompressionEngine:
    """Adaptive multi-level context compression engine.

    Orchestrates L1 (prune), L2 (summarize), and L3 (deep compress)
    based on context occupancy. Maintains compression state and history
    across the conversation session.
    """

    def __init__(
        self,
        estimate_tokens: TokenEstimator,
        estimate_message_tokens: MessageTokenEstimator,
        thresholds: AdaptiveThresholds | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        summary_max_tokens: int = 500,
        prune_min_tokens: int | None = None,
        prune_protect_tokens: int | None = None,
        prune_protected_tools: set[str] | None = None,
        assistant_truncate_chars: int = 2000,
        role_truncate_limits: dict[str, int] | None = None,
    ) -> None:
        self._estimate_tokens = estimate_tokens
        self._estimate_message_tokens = estimate_message_tokens
        self._selector = AdaptiveStrategySelector(thresholds)
        self._chunk_size = chunk_size
        self._summary_max_tokens = summary_max_tokens
        self._state = CompressionState()
        self._history = CompressionHistory()

        # L1 pruning config (fallback to compaction module defaults)
        self._prune_min_tokens = prune_min_tokens
        self._prune_protect_tokens = prune_protect_tokens
        self._prune_protected_tools = prune_protected_tools
        self._assistant_truncate_chars = assistant_truncate_chars
        self._role_truncate_limits = role_truncate_limits or dict(_DEFAULT_ROLE_TRUNCATE_LIMITS)

    @property
    def state(self) -> CompressionState:
        return self._state

    @property
    def history(self) -> CompressionHistory:
        return self._history

    def select_level(
        self,
        messages: list[dict[str, Any]],
        model_limits: ModelLimits,
    ) -> CompressionLevel:
        """Select compression level for current context state."""
        current_tokens = sum(self._estimate_message_tokens(m) for m in messages)
        return self._selector.select(current_tokens, model_limits, self._history)

    def get_occupancy(
        self,
        messages: list[dict[str, Any]],
        model_limits: ModelLimits,
    ) -> float:
        """Get current context occupancy ratio."""
        current_tokens = sum(self._estimate_message_tokens(m) for m in messages)
        return self._selector.get_occupancy(current_tokens, model_limits)

    async def compress(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model_limits: ModelLimits,
        llm_client: LLMClient | None = None,
        level: CompressionLevel | None = None,
    ) -> CompressionResult:
        """Compress context messages based on adaptive level selection.

        Args:
            system_prompt: System prompt text
            messages: Conversation messages in OpenAI format
            model_limits: Model token limits
            llm_client: LLM client for summary generation (required for L2/L3)
            level: Override compression level (auto-select if None)

        Returns:
            CompressionResult with compressed messages
        """
        start_time = time.monotonic()
        messages_before = len(messages)
        tokens_before = sum(self._estimate_message_tokens(m) for m in messages)
        tokens_before += self._estimate_tokens(system_prompt)

        # Select level if not overridden
        if level is None:
            level = self._selector.select(tokens_before, model_limits, self._history)

        if level == CompressionLevel.NONE:
            result_messages = self._build_with_system(system_prompt, messages)
            return CompressionResult(
                messages=result_messages,
                level=CompressionLevel.NONE,
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                messages_before=messages_before,
                messages_after=len(result_messages),
            )

        logger.info(f"Compressing context: level={level.value}, tokens={tokens_before}")

        pruned_count = 0
        summary = None

        # L1: Prune tool outputs
        if level in (
            CompressionLevel.L1_PRUNE,
            CompressionLevel.L2_SUMMARIZE,
            CompressionLevel.L3_DEEP_COMPRESS,
        ):
            messages, pruned_count = self._prune_tool_outputs(messages)

        # L2: Incremental summarization
        if level in (CompressionLevel.L2_SUMMARIZE, CompressionLevel.L3_DEEP_COMPRESS):
            if llm_client:
                messages, summary = await self._incremental_summarize(messages, llm_client)

        # L3: Deep compression (global distillation)
        if level == CompressionLevel.L3_DEEP_COMPRESS:
            if llm_client:
                messages, summary = await self._deep_compress(messages, llm_client)

        # Build final message list
        result_messages = self._build_compressed_output(system_prompt, summary, messages)
        tokens_after = sum(self._estimate_message_tokens(m) for m in result_messages)
        duration_ms = (time.monotonic() - start_time) * 1000

        # Update state
        self._state.current_level = level
        self._state.last_compression_at = datetime.now(UTC)
        self._state.clear_pending()

        # Record in history
        record = CompressionRecord(
            timestamp=datetime.now(UTC),
            level=level.value,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_before=messages_before,
            messages_after=len(result_messages),
            summary_generated=summary is not None,
            summary_tokens=self._estimate_tokens(summary) if summary else 0,
            pruned_tool_outputs=pruned_count,
            duration_ms=duration_ms,
        )
        self._history.record(record)

        result = CompressionResult(
            messages=result_messages,
            level=level,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_before=messages_before,
            messages_after=len(result_messages),
            summary=summary,
            pruned_tool_outputs=pruned_count,
            duration_ms=duration_ms,
        )

        logger.info(
            f"Compression complete: level={level.value}, "
            f"saved={result.tokens_saved} tokens ({tokens_before}->{tokens_after}), "
            f"messages={messages_before}->{len(result_messages)}, "
            f"duration={duration_ms:.0f}ms"
        )

        return result

    def _prune_tool_outputs(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """L1: Prune old tool outputs and long assistant messages.
        Replaces tool result content with placeholder for old tool calls,
        and truncates verbose assistant responses outside the protection window.
        Protects recent turns and critical tool types.
        """
        from src.infrastructure.agent.context.compaction import (
            PRUNE_MINIMUM_TOKENS,
            PRUNE_PROTECT_TOKENS,
            PRUNE_PROTECTED_TOOLS,
        )
        # Use instance config, falling back to compaction module defaults
        min_tokens = (
            self._prune_min_tokens if self._prune_min_tokens is not None else PRUNE_MINIMUM_TOKENS
        )
        protect_tokens = (
            self._prune_protect_tokens
            if self._prune_protect_tokens is not None
            else PRUNE_PROTECT_TOKENS
        )
        protected_tools = (
            self._prune_protected_tools
            if self._prune_protected_tools is not None
            else PRUNE_PROTECTED_TOOLS
        )
        prune_candidates, prunable_tokens = self._scan_prune_candidates(
            messages, protect_tokens, protected_tools
        )
        # Only prune if worthwhile
        if prunable_tokens < min_tokens:
            return messages, 0
        return self._apply_pruning(messages, prune_candidates, prunable_tokens)
    def _scan_prune_candidates(
        self,
        messages: list[dict[str, Any]],
        protect_tokens: int,
        protected_tools: frozenset[str],
    ) -> tuple[list[tuple[int, dict[str, Any], str]], int]:
        """Scan messages backwards for pruning candidates."""
        total_tool_tokens = 0
        prunable_tokens = 0
        prune_candidates: list[tuple[int, dict[str, Any], str]] = []
        assistant_truncate = self._assistant_truncate_chars

        turns = 0
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.get("role") == "user":
                turns += 1
            # Protect last 2 user turns
            if turns < 2:
                continue

            role = msg.get("role", "")
            if role == "tool":
                content = msg.get("content", "")
                tool_name = msg.get("name", "")
                tokens = self._estimate_tokens(content)
                total_tool_tokens += tokens
                # Skip protected tools
                if tool_name in protected_tools:
                    continue

                # Past protection window -> candidate for pruning
                if total_tool_tokens > protect_tokens:
                    prunable_tokens += tokens
                    prune_candidates.append((i, msg, "tool"))
            elif role == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > assistant_truncate:
                    tokens = self._estimate_tokens(content)
                    saved = tokens - self._estimate_tokens(content[:assistant_truncate])
                    if saved > 0:
                        prunable_tokens += saved
                        prune_candidates.append((i, msg, "assistant"))
        return prune_candidates, prunable_tokens
    def _apply_pruning(
        self,
        messages: list[dict[str, Any]],
        prune_candidates: list[tuple[int, dict[str, Any], str]],
        prunable_tokens: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Apply pruning to candidate messages."""
        assistant_truncate = self._assistant_truncate_chars
        pruned_count = 0
        result = list(messages)
        for idx, msg, msg_type in prune_candidates:
            if msg_type == "tool":
                result[idx] = {
                    **msg,
                    "content": "[Output compacted to save tokens]",
                }
            elif msg_type == "assistant":
                content = msg.get("content", "")
                result[idx] = {
                    **msg,
                    "content": content[:assistant_truncate]
                    + "\n[... response truncated to save tokens]",
                }
            pruned_count += 1
        logger.info(
            f"L1 Prune: pruned {pruned_count} messages "
            f"(tool + assistant), ~{prunable_tokens} tokens"
        )
        return result, pruned_count

    async def _incremental_summarize(
        self,
        messages: list[dict[str, Any]],
        llm_client: LLMClient,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """L2: Incrementally summarize old messages in chunks.

        Summarizes messages in groups of `chunk_size`, building a chain
        where each summary references the previous one.
        """
        # Determine which messages still need summarizing
        start_idx = self._state.messages_summarized_up_to
        # Keep the most recent messages unsummarized
        protect_count = max(len(messages) // 4, 4)
        end_idx = max(start_idx, len(messages) - protect_count)

        unsummarized = messages[start_idx:end_idx]
        if len(unsummarized) < self._chunk_size:
            # Not enough messages to form a chunk; use existing summary
            return messages[end_idx:], self._state.get_combined_summary()

        # Process in chunks
        for chunk_start in range(0, len(unsummarized), self._chunk_size):
            chunk_end = min(chunk_start + self._chunk_size, len(unsummarized))
            chunk = unsummarized[chunk_start:chunk_end]

            if len(chunk) < 3:
                break

            chunk_tokens = sum(self._estimate_message_tokens(m) for m in chunk)

            # Build previous summary context
            prev_summary = self._state.get_combined_summary()
            prev_context = ""
            if prev_summary:
                prev_context = f"Previous context summary:\n{prev_summary}\n\n"

            # Format chunk with role-aware partitioning
            user_text, assistant_text = self._partition_messages_by_role(chunk)

            prompt = CHUNK_SUMMARY_PROMPT.format(
                previous_summary_context=prev_context,
                user_text=user_text or "(no user messages in this segment)",
                assistant_text=assistant_text or "(no assistant messages in this segment)",
                max_tokens=self._summary_max_tokens,
            )

            try:
                response = await llm_client.chat_completion(
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a precise conversation summarizer.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=self._summary_max_tokens,
                    temperature=0.2,
                )

                summary_text = self._extract_response_text(response)
                if summary_text:
                    summary_tokens = self._estimate_tokens(summary_text)
                    self._state.add_summary_chunk(
                        SummaryChunk(
                            summary_text=summary_text,
                            message_start_index=start_idx + chunk_start,
                            message_end_index=start_idx + chunk_end,
                            original_token_count=chunk_tokens,
                            summary_token_count=summary_tokens,
                        )
                    )
            except Exception as e:
                logger.warning(f"L2 chunk summarization failed: {e}")
                break

        # Return only unsummarized (recent) messages + combined summary
        remaining = messages[end_idx:]
        combined_summary = self._state.get_combined_summary()

        logger.info(
            f"L2 Summarize: {len(self._state.summary_chunks)} chunks, "
            f"kept {len(remaining)} recent messages"
        )
        return remaining, combined_summary

    async def _deep_compress(
        self,
        messages: list[dict[str, Any]],
        llm_client: LLMClient,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """L3: Deep compress all context into one ultra-compact summary.

        Distills existing summaries + recent messages into a single
        compressed representation targeting ~10% of original token count.
        """
        existing_summary = self._state.get_combined_summary() or ""
        recent_text = self._format_messages_for_summary(messages)

        prompt = DEEP_COMPRESS_PROMPT.format(
            summaries=existing_summary if existing_summary else "(none)",
            recent_text=recent_text,
        )

        # Target very compact output
        compact_max_tokens = max(self._summary_max_tokens // 2, 200)

        try:
            response = await llm_client.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a context compression specialist. "
                            "Produce the most compact summary possible "
                            "while retaining all critical information."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=compact_max_tokens,
                temperature=0.1,
            )

            global_summary = self._extract_response_text(response)
            if global_summary:
                summary_tokens = self._estimate_tokens(global_summary)
                self._state.set_global_summary(global_summary, summary_tokens)

                # Keep only the most recent few messages
                keep_count = min(4, len(messages))
                remaining = messages[-keep_count:] if keep_count > 0 else []

                logger.info(
                    f"L3 Deep Compress: global summary={summary_tokens} tokens, "
                    f"kept {len(remaining)} recent messages"
                )
                return remaining, global_summary

        except Exception as e:
            logger.warning(f"L3 deep compression failed: {e}")

        return messages, self._state.get_combined_summary()

    def _build_with_system(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build message list with system prompt prepended."""
        result: list[dict[str, Any]] = []
        if system_prompt:
            result.append({"role": "system", "content": system_prompt})
        result.extend(messages)
        return result

    def _build_compressed_output(
        self,
        system_prompt: str,
        summary: str | None,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build final message list with summary injected into system prompt."""
        result: list[dict[str, Any]] = []

        system_content = system_prompt or ""
        if summary:
            system_content += f"\n\n[Previous conversation summary]\n{summary}"

        if system_content:
            result.append({"role": "system", "content": system_content})

        result.extend(messages)
        return result

    def _format_messages_for_summary(
        self,
        messages: list[dict[str, Any]],
    ) -> str:
        """Format messages as text for LLM summarization.

        Applies role-aware truncation: user messages get more budget
        than assistant/tool messages to preserve requirements.
        """
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if isinstance(content, list):
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = " ".join(text_parts)

            # Role-aware truncation limits
            limit = self._role_truncate_limits.get(role, _DEFAULT_TRUNCATE_LIMIT)
            if len(content) > limit:
                content = content[:limit] + "..."

            if content:
                lines.append(f"{role.capitalize()}: {content}")

        return "\n".join(lines)

    def _partition_messages_by_role(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Partition messages into user text and assistant/tool text.

        Returns (user_text, assistant_text) with role-aware truncation.
        Used by L2 summarization to give the LLM structured input.
        """
        user_lines: list[str] = []
        assistant_lines: list[str] = []

        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if isinstance(content, list):
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = " ".join(text_parts)

            limit = self._role_truncate_limits.get(role, _DEFAULT_TRUNCATE_LIMIT)
            if len(content) > limit:
                content = content[:limit] + "..."

            if not content:
                continue

            if role == "user":
                user_lines.append(f"User: {content}")
            elif role == "assistant":
                assistant_lines.append(f"Assistant: {content}")
            elif role == "tool":
                tool_name = msg.get("name", "unknown")
                assistant_lines.append(f"Tool[{tool_name}]: {content}")
            else:
                assistant_lines.append(f"{role.capitalize()}: {content}")

        return "\n".join(user_lines), "\n".join(assistant_lines)

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        """Extract text from LLM response (handles both object and dict formats)."""
        if hasattr(response, "choices") and response.choices:
            return response.choices[0].message.content.strip()
        elif isinstance(response, dict):
            return response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return ""

    def get_token_distribution(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str = "",
    ) -> dict[str, int]:
        """Calculate token distribution by message category.

        Returns breakdown: system, user, assistant, tool, summary.
        """
        distribution: dict[str, int] = {
            "system": self._estimate_tokens(system_prompt),
            "user": 0,
            "assistant": 0,
            "tool": 0,
            "summary": self._state.get_summary_token_count(),
        }

        for msg in messages:
            role = msg.get("role", "unknown")
            tokens = self._estimate_message_tokens(msg)
            if role in distribution:
                distribution[role] += tokens
            else:
                distribution.setdefault("other", 0)
                distribution["other"] = distribution.get("other", 0) + tokens

        return distribution

    def reset(self) -> None:
        """Reset engine state for a new conversation."""
        self._state.reset()
        self._history.reset()
