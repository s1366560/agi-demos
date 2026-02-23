"""Tool Selection Strategy - Intelligent tool filtering for LLM context optimization.

When too many tools are available, this module provides intelligent
selection based on relevance to the conversation context.
"""

import logging
import re
from dataclasses import dataclass, field
from hashlib import blake2b
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Set

logger = logging.getLogger(__name__)


# Core tools that should always be included
CORE_TOOLS: Set[str] = {
    "read",
    "write",
    "edit",
    "bash",
    "glob",
    "grep",
    "todoread",
    "todowrite",
}

# High priority baseline score for core tools
CORE_TOOL_BASELINE_SCORE = 100


@dataclass
class ToolSelectionContext:
    """Context for tool selection decisions.

    Provides the information needed to make intelligent
    decisions about which tools are most relevant.
    """

    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    project_id: Optional[str] = None
    max_tools: int = 30
    always_include: Set[str] = field(default_factory=lambda: CORE_TOOLS)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class SemanticToolRanker(Protocol):
    """Protocol for pluggable semantic ranking backends."""

    name: str

    def rank_tools(
        self,
        tools: Dict[str, Any],
        context: ToolSelectionContext,
        *,
        score_fallback: Callable[[Any], float],
    ) -> List[str]:
        """Return ordered tool names from highest to lowest relevance."""


class KeywordSemanticToolRanker:
    """Keyword relevance ranker (legacy behavior)."""

    name = "keyword"

    def rank_tools(
        self,
        tools: Dict[str, Any],
        context: ToolSelectionContext,
        *,
        score_fallback: Callable[[Any], float],
    ) -> List[str]:
        scored = [(name, score_fallback(tool)) for name, tool in tools.items()]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [name for name, _ in scored]


class TokenVectorSemanticToolRanker:
    """Token-hashed vector ranker with keyword fallback blending."""

    name = "token_vector"

    def __init__(self, *, vector_dimensions: int = 128) -> None:
        self._vector_dimensions = max(16, int(vector_dimensions))

    def rank_tools(
        self,
        tools: Dict[str, Any],
        context: ToolSelectionContext,
        *,
        score_fallback: Callable[[Any], float],
    ) -> List[str]:
        user_message = str(context.metadata.get("user_message", "")).strip().lower()
        conversation_text = (
            " ".join(
                str(item.get("content", ""))
                for item in context.conversation_history
                if isinstance(item, dict)
            )
            .strip()
            .lower()
        )
        query_text = f"{user_message}\n{conversation_text}".strip()
        if not query_text:
            return KeywordSemanticToolRanker().rank_tools(
                tools,
                context,
                score_fallback=score_fallback,
            )

        query_vector = self._build_sparse_vector(query_text)
        scored: list[tuple[str, float]] = []
        for name, tool in tools.items():
            description = str(getattr(tool, "description", "") or "")
            tool_text = f"{name} {description}".strip().lower()
            semantic_score = self._cosine_similarity(
                query_vector,
                self._build_sparse_vector(tool_text),
            )
            # Blend lexical fallback with lightweight vector score.
            blended_score = score_fallback(tool) + (semantic_score * 25.0)
            scored.append((name, blended_score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return [name for name, _ in scored]

    def _build_sparse_vector(self, text: str) -> Dict[int, float]:
        counts: Dict[int, float] = {}
        for token in re.findall(r"\b[a-z][a-z0-9_]*\b", text):
            digest = blake2b(token.encode("utf-8"), digest_size=2).digest()
            slot = int.from_bytes(digest, byteorder="big") % self._vector_dimensions
            counts[slot] = counts.get(slot, 0.0) + 1.0
        return counts

    @staticmethod
    def _cosine_similarity(vec_a: Dict[int, float], vec_b: Dict[int, float]) -> float:
        if not vec_a or not vec_b:
            return 0.0
        dot = sum(value * vec_b.get(key, 0.0) for key, value in vec_a.items())
        norm_a = sum(value * value for value in vec_a.values()) ** 0.5
        norm_b = sum(value * value for value in vec_b.values()) ** 0.5
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)


class _CallableSemanticToolRanker:
    """Adapter for function-style semantic ranker callables."""

    name = "custom_callable"

    def __init__(
        self, callback: Callable[[Dict[str, Any], ToolSelectionContext], List[str]]
    ) -> None:
        self._callback = callback

    def rank_tools(
        self,
        tools: Dict[str, Any],
        context: ToolSelectionContext,
        *,
        score_fallback: Callable[[Any], float],
    ) -> List[str]:
        result = self._callback(tools, context)
        if not isinstance(result, list):
            raise TypeError("semantic_ranker callback must return List[str]")
        return [str(name) for name in result]


class ToolSelector:
    """Selects the most relevant tools based on context.

    When the number of available tools exceeds a limit,
    this selector ranks and filters tools to reduce LLM
    context consumption while preserving functionality.
    """

    def __init__(self):
        """Initialize the tool selector."""
        self._stopwords = {
            "a",
            "an",
            "the",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "need",
            "dare",
            "ought",
            "used",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "under",
            "again",
            "further",
            "then",
            "once",
            "i",
            "me",
            "my",
            "myself",
            "we",
            "our",
            "ours",
            "ourselves",
            "you",
            "your",
            "yours",
            "yourself",
            "yourselves",
            "he",
            "him",
            "his",
            "himself",
            "she",
            "her",
            "hers",
            "herself",
            "it",
            "its",
            "itself",
            "they",
            "them",
            "their",
            "theirs",
            "themselves",
            "what",
            "which",
            "who",
            "whom",
            "this",
            "that",
            "these",
            "those",
            "and",
            "but",
            "or",
            "if",
            "because",
            "until",
            "while",
        }
        self._keyword_ranker = KeywordSemanticToolRanker()
        self._vector_ranker = TokenVectorSemanticToolRanker()

    def select_tools(
        self,
        tools: Dict[str, Any],
        context: ToolSelectionContext,
    ) -> List[str]:
        """Select the most relevant tools.

        Args:
            tools: Dict of tool name -> tool object
            context: Selection context with history and limits

        Returns:
            List of selected tool names
        """
        # If under limit, return all
        if len(tools) <= context.max_tools:
            return list(tools.keys())

        # Score each tool
        ranker = self._resolve_semantic_ranker(context)
        ranked_names = self._rank_with_backend(
            ranker,
            tools,
            context,
        )

        # Select top tools
        selected = []
        always_include = context.always_include or CORE_TOOLS

        # First, add all always-include tools
        for name in tools:
            if name in always_include:
                selected.append(name)

        # Then add ranked tools until we hit the limit
        for name in ranked_names:
            if name not in selected:
                selected.append(name)
                if len(selected) >= context.max_tools:
                    break

        logger.debug(
            "Selected %d/%d tools (always_include: %d, semantic_backend: %s)",
            len(selected),
            len(tools),
            len(always_include & set(tools.keys())),
            getattr(ranker, "name", "unknown"),
        )

        return selected

    def score_tool_relevance(
        self,
        tool: Any,
        context: ToolSelectionContext,
    ) -> float:
        """Score a tool's relevance to the context.

        Args:
            tool: Tool object with name and description
            context: Selection context

        Returns:
            Relevance score (higher = more relevant)
        """
        # Core tools get high baseline score
        tool_name = getattr(tool, "name", "")
        if tool_name in CORE_TOOLS:
            return CORE_TOOL_BASELINE_SCORE

        score = 0.0

        # Get tool metadata
        description = getattr(tool, "description", "") or ""
        name_lower = tool_name.lower()
        desc_lower = description.lower()

        # Extract keywords from conversation
        conversation_text = self._extract_conversation_text(context.conversation_history)
        keywords = self._extract_keywords(conversation_text)

        # Score based on name matches
        for keyword in keywords:
            if keyword in name_lower:
                score += 10.0

        # Score based on description matches
        for keyword in keywords:
            if keyword in desc_lower:
                score += 5.0

        # MCP tools get slight bonus (they're user-configured, likely important)
        if tool_name.startswith("mcp__"):
            score += 1.0

        score += self._resolve_quality_boost(
            tool_name,
            context.metadata if isinstance(context.metadata, Mapping) else {},
        )

        return score

    def _extract_conversation_text(
        self,
        history: List[Dict[str, str]],
    ) -> str:
        """Extract all text from conversation history.

        Args:
            history: List of message dicts

        Returns:
            Combined text from all messages
        """
        texts = []
        for msg in history:
            content = msg.get("content", "")
            if isinstance(content, str):
                texts.append(content)
        return " ".join(texts).lower()

    def _extract_keywords(self, text: str) -> Set[str]:
        """Extract meaningful keywords from text.

        Args:
            text: Input text

        Returns:
            Set of keywords (lowercase, no stopwords)
        """
        # Tokenize on word boundaries
        words = re.findall(r"\b[a-z][a-z0-9_]*\b", text.lower())

        # Filter stopwords and short words
        keywords = {word for word in words if word not in self._stopwords and len(word) >= 2}

        return keywords

    def _resolve_semantic_ranker(self, context: ToolSelectionContext) -> SemanticToolRanker:
        metadata = context.metadata if isinstance(context.metadata, Mapping) else {}
        backend = str(metadata.get("semantic_backend", "embedding_vector")).strip().lower()

        if backend == "embedding_vector":
            embedding_ranker = metadata.get("embedding_ranker")
            if hasattr(embedding_ranker, "rank_tools"):
                return embedding_ranker  # type: ignore[return-value]
            if callable(embedding_ranker):
                return _CallableSemanticToolRanker(embedding_ranker)

        custom_ranker = metadata.get("semantic_ranker")
        if hasattr(custom_ranker, "rank_tools"):
            return custom_ranker  # type: ignore[return-value]
        if callable(custom_ranker):
            return _CallableSemanticToolRanker(custom_ranker)

        if backend == "keyword":
            return self._keyword_ranker
        return self._vector_ranker

    def _resolve_quality_boost(self, tool_name: str, metadata: Mapping[str, Any]) -> float:
        scores = metadata.get("tool_quality_scores")
        if isinstance(scores, Mapping):
            raw = scores.get(tool_name)
            try:
                score = float(raw)
            except (TypeError, ValueError):
                score = None
            if score is not None:
                return max(0.0, min(score, 1.0)) * 10.0

        stats = metadata.get("tool_quality_stats")
        if isinstance(stats, Mapping):
            raw_stats = stats.get(tool_name)
            if isinstance(raw_stats, Mapping):
                try:
                    success_rate = float(raw_stats.get("success_rate", 0.0))
                except (TypeError, ValueError):
                    success_rate = 0.0
                try:
                    avg_duration_ms = float(raw_stats.get("avg_duration_ms", 0.0))
                except (TypeError, ValueError):
                    avg_duration_ms = 0.0

                normalized_success = max(0.0, min(success_rate, 1.0))
                latency_penalty = min(max(avg_duration_ms, 0.0) / 5000.0, 1.0) * 0.2
                return max(0.0, normalized_success - latency_penalty) * 10.0

        return 0.0

    def _rank_with_backend(
        self,
        ranker: SemanticToolRanker,
        tools: Dict[str, Any],
        context: ToolSelectionContext,
    ) -> List[str]:
        def _score_fallback(tool: Any) -> float:
            return self.score_tool_relevance(tool, context)

        try:
            ranked_names = ranker.rank_tools(
                tools,
                context,
                score_fallback=_score_fallback,
            )
        except Exception:
            logger.exception("Semantic ranker failed, falling back to keyword backend")
            ranked_names = self._keyword_ranker.rank_tools(
                tools,
                context,
                score_fallback=_score_fallback,
            )

        unique_ranked: list[str] = []
        seen: set[str] = set()
        for name in ranked_names:
            if name in tools and name not in seen:
                unique_ranked.append(name)
                seen.add(name)

        # Guarantee all tools are represented in deterministic fallback order.
        if len(unique_ranked) < len(tools):
            for name in self._keyword_ranker.rank_tools(
                tools,
                context,
                score_fallback=_score_fallback,
            ):
                if name in seen:
                    continue
                unique_ranked.append(name)
                seen.add(name)

        return unique_ranked


# Global selector instance
_selector: Optional[ToolSelector] = None


def get_tool_selector() -> ToolSelector:
    """Get the global tool selector instance.

    Returns:
        ToolSelector singleton
    """
    global _selector
    if _selector is None:
        _selector = ToolSelector()
    return _selector
