"""
Context Window Manager - Dynamic context window sizing and compression.

Manages the context window for LLM conversations:
1. Estimates token counts for messages
2. Splits messages by token budget (system, history, recent, output)
3. Generates summaries for early messages when context exceeds threshold
4. Detects overflow and prunes tool outputs
5. Emits compression events for real-time feedback

Reference: OpenCode's context management with prune + compaction strategy
Adapted for Web applications with query-time compression (no DB modification).
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.infrastructure.agent.session.compaction import (
    ModelLimits,
    TokenCount,
    calculate_usable_context,
    is_overflow,
    should_compact,
)

logger = logging.getLogger(__name__)


class CompressionStrategy(str, Enum):
    """Context compression strategy."""

    NONE = "none"  # No compression needed
    TRUNCATE = "truncate"  # Simple truncation of old messages
    SUMMARIZE = "summarize"  # Generate summary of old messages


@dataclass
class ContextWindowConfig:
    """Configuration for context window management."""

    # Model limits (dynamically fetched from ProviderService)
    max_context_tokens: int = 128000
    max_output_tokens: int = 4096

    # Token budget allocation (percentages)
    system_budget_pct: float = 0.10  # 10% for system prompt
    history_budget_pct: float = 0.50  # 50% for historical context
    recent_budget_pct: float = 0.25  # 25% for recent messages
    output_reserve_pct: float = 0.15  # 15% reserved for output

    # Compression thresholds
    compression_trigger_pct: float = 0.80  # Trigger at 80% occupancy
    summary_max_tokens: int = 500  # Max tokens for summary

    # Token estimation
    chars_per_token: float = 4.0  # Rough estimate for tokenization

    def __post_init__(self):
        """Validate configuration."""
        total = (
            self.system_budget_pct
            + self.history_budget_pct
            + self.recent_budget_pct
            + self.output_reserve_pct
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Budget percentages must sum to 1.0, got {total}")


@dataclass
class ContextWindowResult:
    """Result of context window building."""

    # Messages to send to LLM
    messages: List[Dict[str, Any]]

    # Compression info
    was_compressed: bool = False
    compression_strategy: CompressionStrategy = CompressionStrategy.NONE
    original_message_count: int = 0
    final_message_count: int = 0

    # Token estimates
    estimated_tokens: int = 0
    token_budget: int = 0
    budget_utilization_pct: float = 0.0

    # Summary (if generated)
    summary: Optional[str] = None
    summarized_message_count: int = 0

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_event_data(self) -> Dict[str, Any]:
        """Convert to event data for SSE/WebSocket."""
        return {
            "was_compressed": self.was_compressed,
            "compression_strategy": self.compression_strategy.value,
            "original_message_count": self.original_message_count,
            "final_message_count": self.final_message_count,
            "estimated_tokens": self.estimated_tokens,
            "token_budget": self.token_budget,
            "budget_utilization_pct": round(self.budget_utilization_pct, 2),
            "summarized_message_count": self.summarized_message_count,
        }


class ContextWindowManager:
    """
    Manages context window for LLM conversations.

    Key features:
    - Dynamic model-based context sizing
    - Query-time compression (doesn't modify DB)
    - Sliding window with summary for early messages
    - Real-time compression events for frontend

    Usage:
        manager = ContextWindowManager(config)
        result = await manager.build_context_window(
            system_prompt="You are a helpful assistant.",
            messages=conversation_messages,
            llm_client=litellm_client,  # For summary generation
        )
        # Use result.messages for LLM call
    """

    def __init__(self, config: Optional[ContextWindowConfig] = None):
        """
        Initialize context window manager.

        Args:
            config: Configuration options. Uses defaults if None.
        """
        self.config = config or ContextWindowConfig()
        self._token_cache: Dict[str, int] = {}

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.

        Uses character-based estimation with caching.
        More accurate tokenization can be added later (tiktoken, etc.).

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        # Check cache
        cache_key = str(hash(text))
        if cache_key in self._token_cache:
            return self._token_cache[cache_key]

        # Estimate based on characters
        # Rough heuristic: ~4 chars per token for English, ~2 for Chinese
        char_count = len(text)

        # Detect if text contains significant Chinese/CJK characters
        cjk_pattern = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uac00-\ud7af]")
        cjk_chars = len(cjk_pattern.findall(text))
        cjk_ratio = cjk_chars / char_count if char_count > 0 else 0

        # Adjust chars_per_token based on CJK ratio
        if cjk_ratio > 0.3:
            # Mostly CJK text
            chars_per_token = 2.0
        elif cjk_ratio > 0.1:
            # Mixed text
            chars_per_token = 3.0
        else:
            # Mostly English/ASCII
            chars_per_token = self.config.chars_per_token

        tokens = int(char_count / chars_per_token)

        # Cache result
        self._token_cache[cache_key] = tokens
        return tokens

    def estimate_message_tokens(self, message: Dict[str, Any]) -> int:
        """
        Estimate token count for a message.

        Accounts for message structure overhead.

        Args:
            message: Message in OpenAI format

        Returns:
            Estimated token count
        """
        tokens = 4  # Message structure overhead

        # Content tokens
        content = message.get("content", "")
        if isinstance(content, str):
            tokens += self.estimate_tokens(content)
        elif isinstance(content, list):
            # Multi-part content (text + images, etc.)
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        tokens += self.estimate_tokens(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        tokens += 85  # Base tokens for image reference

        # Tool calls tokens
        tool_calls = message.get("tool_calls", [])
        for tool_call in tool_calls:
            tokens += self.estimate_tokens(tool_call.get("function", {}).get("name", ""))
            tokens += self.estimate_tokens(tool_call.get("function", {}).get("arguments", ""))
            tokens += 10  # Tool call structure overhead

        # Role and name tokens
        tokens += self.estimate_tokens(message.get("role", ""))
        tokens += self.estimate_tokens(message.get("name", ""))

        return tokens

    def estimate_messages_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """
        Estimate total token count for messages.

        Args:
            messages: List of messages in OpenAI format

        Returns:
            Total estimated token count
        """
        return sum(self.estimate_message_tokens(msg) for msg in messages)

    def calculate_budgets(self) -> Dict[str, int]:
        """
        Calculate token budgets for each category.

        Returns:
            Dict with budget for each category
        """
        available = self.config.max_context_tokens - self.config.max_output_tokens

        return {
            "system": int(available * self.config.system_budget_pct),
            "history": int(available * self.config.history_budget_pct),
            "recent": int(available * self.config.recent_budget_pct),
            "output_reserve": self.config.max_output_tokens,
            "total_available": available,
        }

    async def build_context_window(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        llm_client: Optional[Any] = None,
    ) -> ContextWindowResult:
        """
        Build context window with dynamic compression.

        Strategy:
        1. Calculate token budgets
        2. Check if compression needed
        3. If needed, summarize early messages
        4. Return optimized message list

        Args:
            system_prompt: System prompt text
            messages: Conversation messages in OpenAI format
            llm_client: Optional LLM client for summary generation

        Returns:
            ContextWindowResult with optimized messages
        """
        original_count = len(messages)
        budgets = self.calculate_budgets()

        # Estimate current usage
        system_tokens = self.estimate_tokens(system_prompt)
        messages_tokens = self.estimate_messages_tokens(messages)
        total_tokens = system_tokens + messages_tokens

        # Check if compression needed
        trigger_threshold = int(budgets["total_available"] * self.config.compression_trigger_pct)

        if total_tokens <= trigger_threshold:
            # No compression needed
            result_messages = self._build_messages_with_system(system_prompt, messages)
            return ContextWindowResult(
                messages=result_messages,
                was_compressed=False,
                compression_strategy=CompressionStrategy.NONE,
                original_message_count=original_count,
                final_message_count=len(result_messages),
                estimated_tokens=total_tokens,
                token_budget=budgets["total_available"],
                budget_utilization_pct=(total_tokens / budgets["total_available"]) * 100,
            )

        logger.info(
            f"Context compression triggered: {total_tokens} tokens "
            f"exceeds threshold {trigger_threshold}"
        )

        # Split messages into history and recent
        history_msgs, recent_msgs = self._split_messages_by_budget(
            messages,
            history_budget=budgets["history"],
            recent_budget=budgets["recent"],
        )

        # Generate summary for history if we have LLM client and enough messages
        summary = None
        summarized_count = 0
        strategy = CompressionStrategy.TRUNCATE

        if llm_client and len(history_msgs) > 2:
            try:
                summary = await self._generate_summary(history_msgs, llm_client)
                summarized_count = len(history_msgs)
                strategy = CompressionStrategy.SUMMARIZE
                logger.info(f"Generated summary for {summarized_count} messages")
            except Exception as e:
                logger.warning(f"Summary generation failed, falling back to truncation: {e}")
                summary = None

        # Build final message list
        result_messages = self._build_compressed_messages(
            system_prompt=system_prompt,
            summary=summary,
            recent_messages=recent_msgs,
        )

        final_tokens = self.estimate_messages_tokens(result_messages)

        return ContextWindowResult(
            messages=result_messages,
            was_compressed=True,
            compression_strategy=strategy,
            original_message_count=original_count,
            final_message_count=len(result_messages),
            estimated_tokens=final_tokens,
            token_budget=budgets["total_available"],
            budget_utilization_pct=(final_tokens / budgets["total_available"]) * 100,
            summary=summary,
            summarized_message_count=summarized_count,
        )

    def _build_messages_with_system(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build messages list with system prompt."""
        result = []

        if system_prompt:
            result.append({"role": "system", "content": system_prompt})

        result.extend(messages)
        return result

    def _split_messages_by_budget(
        self,
        messages: List[Dict[str, Any]],
        history_budget: int,
        recent_budget: int,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Split messages into history (for summarization) and recent (keep as-is).

        Strategy: Keep most recent messages within budget, rest goes to history.

        Args:
            messages: All messages
            history_budget: Token budget for history (to summarize)
            recent_budget: Token budget for recent messages

        Returns:
            Tuple of (history_messages, recent_messages)
        """
        if not messages:
            return [], []

        # Start from the end, collect recent messages within budget
        recent_messages = []
        recent_tokens = 0

        for msg in reversed(messages):
            msg_tokens = self.estimate_message_tokens(msg)
            if recent_tokens + msg_tokens <= recent_budget:
                recent_messages.insert(0, msg)
                recent_tokens += msg_tokens
            else:
                break

        # Remaining messages go to history
        recent_start_idx = len(messages) - len(recent_messages)
        history_messages = messages[:recent_start_idx]

        logger.debug(
            f"Split messages: {len(history_messages)} history, {len(recent_messages)} recent"
        )

        return history_messages, recent_messages

    async def _generate_summary(
        self,
        messages: List[Dict[str, Any]],
        llm_client: Any,
    ) -> str:
        """
        Generate summary of messages using LLM.

        Args:
            messages: Messages to summarize
            llm_client: LLM client for generation

        Returns:
            Summary text
        """
        # Build summary prompt
        conversation_text = self._format_messages_for_summary(messages)

        summary_prompt = f"""Please provide a concise summary of the following conversation history.
Focus on:
1. Key decisions and conclusions made
2. Important context and constraints mentioned
3. Current state of the task/discussion

Keep the summary under {self.config.summary_max_tokens} tokens.

Conversation:
{conversation_text}

Summary:"""

        # Call LLM for summary
        response = await llm_client.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that summarizes conversations.",
                },
                {"role": "user", "content": summary_prompt},
            ],
            max_tokens=self.config.summary_max_tokens,
            temperature=0.3,  # Low temperature for consistency
        )

        # Extract summary from response
        if hasattr(response, "choices") and response.choices:
            return response.choices[0].message.content.strip()
        elif isinstance(response, dict):
            return response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        return ""

    def _format_messages_for_summary(
        self,
        messages: List[Dict[str, Any]],
    ) -> str:
        """Format messages as text for summarization."""
        lines = []

        for msg in messages:
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "")

            if isinstance(content, list):
                # Multi-part content
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = " ".join(text_parts)

            # Truncate very long messages
            if len(content) > 500:
                content = content[:500] + "..."

            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _build_compressed_messages(
        self,
        system_prompt: str,
        summary: Optional[str],
        recent_messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Build compressed message list with summary.

        Args:
            system_prompt: System prompt
            summary: Summary of early messages (optional)
            recent_messages: Recent messages to keep

        Returns:
            Optimized message list
        """
        result = []

        # System prompt
        if system_prompt:
            system_content = system_prompt
            if summary:
                system_content += f"\n\n[Previous conversation summary]\n{summary}"
            result.append({"role": "system", "content": system_content})
        elif summary:
            result.append(
                {
                    "role": "system",
                    "content": f"[Previous conversation summary]\n{summary}",
                }
            )

        # Recent messages
        result.extend(recent_messages)

        return result

    def update_config(
        self,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> None:
        """
        Update configuration with new model limits.

        Called when model changes to adjust context window sizing.

        Args:
            max_context_tokens: New context limit
            max_output_tokens: New output limit
        """
        if max_context_tokens is not None:
            self.config.max_context_tokens = max_context_tokens
        if max_output_tokens is not None:
            self.config.max_output_tokens = max_output_tokens

        logger.debug(
            f"Updated context config: max_context={self.config.max_context_tokens}, "
            f"max_output={self.config.max_output_tokens}"
        )

    def clear_cache(self) -> None:
        """Clear token estimation cache."""
        self._token_cache.clear()

    def get_token_count(self, messages: List[Dict[str, Any]]) -> TokenCount:
        """
        Get detailed token count for messages.

        Args:
            messages: List of messages in OpenAI format

        Returns:
            TokenCount with breakdown by type
        """
        total = 0
        cache_read = 0
        cache_write = 0

        for msg in messages:
            msg_tokens = self.estimate_message_tokens(msg)
            total += msg_tokens

            # Check for cached tokens (e.g., from Anthropic's prompt caching)
            if msg.get("cache_control"):
                cache_read += msg_tokens

        return TokenCount(
            input=total,
            cache_read=cache_read,
            cache_write=cache_write,
        )

    def is_overflow(
        self,
        messages: List[Dict[str, Any]],
        model_limits: Optional[ModelLimits] = None,
        auto_compaction_enabled: bool = True,
    ) -> bool:
        """
        Check if context has overflowed the available token budget.

        Wrapper around compaction.is_overflow().

        Args:
            messages: List of messages in OpenAI format
            model_limits: Model token limits (uses config if None)
            auto_compaction_enabled: If False, never report overflow

        Returns:
            True if tokens exceed usable context window
        """
        if model_limits is None:
            model_limits = ModelLimits(
                context=self.config.max_context_tokens,
                input=0,  # Derive from context - output
                output=self.config.max_output_tokens,
            )

        tokens = self.get_token_count(messages)
        return is_overflow(tokens, model_limits, auto_compaction_enabled)

    def should_compact(
        self,
        messages: List[Dict[str, Any]],
        threshold: float = 0.8,
    ) -> bool:
        """
        Check if context should be compacted based on threshold.

        Args:
            messages: List of messages in OpenAI format
            threshold: Usage threshold (0.0-1.0) to trigger compaction

        Returns:
            True if compaction should be triggered
        """
        model_limits = ModelLimits(
            context=self.config.max_context_tokens,
            input=0,  # Derive from context - output
            output=self.config.max_output_tokens,
        )

        tokens = self.get_token_count(messages)
        return should_compact(tokens, model_limits, threshold)

    def get_usable_context(
        self,
        model_limits: Optional[ModelLimits] = None,
    ) -> int:
        """
        Calculate usable context tokens for input.

        Args:
            model_limits: Model token limits (uses config if None)

        Returns:
            Usable input tokens
        """
        if model_limits is None:
            model_limits = ModelLimits(
                context=self.config.max_context_tokens,
                input=0,  # Derive from context - output
                output=self.config.max_output_tokens,
            )

        return calculate_usable_context(model_limits)
