"""Tool Selection Strategy - structured tool filtering for LLM context optimization.

When too many tools are available, this module preserves deterministic safety
filters and allows an injected agent-backed ranker to order candidates. It
does not infer tool relevance from conversation keywords locally.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

logger = logging.getLogger(__name__)


# Core tools that should always be included
CORE_TOOLS: set[str] = {
    "read",
    "write",
    "edit",
    "bash",
    "glob",
    "grep",
    "todoread",
    "todowrite",
    "skill_loader",
}

# Skill management tools that should survive semantic budget pruning.
# skill_loader is in CORE_TOOLS (always available).
# skill_installer and skill_sync are NOT in CORE_TOOLS so that
# policy deny lists (e.g. plan mode) can still block them.
SKILL_TOOLS: set[str] = {
    "skill_loader",
    "skill_installer",
    "skill_sync",
}

# High priority baseline score for core tools
CORE_TOOL_BASELINE_SCORE = 100


@dataclass
class ToolSelectionContext:
    """Context for tool selection decisions.

    Provides the information needed to make intelligent
    decisions about which tools are most relevant.
    """

    conversation_history: list[dict[str, str]] = field(default_factory=list)
    project_id: str | None = None
    max_tools: int = 30
    always_include: set[str] = field(default_factory=lambda: CORE_TOOLS)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class SemanticToolRanker(Protocol):
    """Protocol for pluggable semantic ranking backends."""

    name: str

    def rank_tools(
        self,
        tools: dict[str, Any],
        context: ToolSelectionContext,
        *,
        score_fallback: Callable[[Any], float],
    ) -> list[str]:
        """Return ordered tool names from highest to lowest relevance."""
        ...


class DeterministicToolRanker:
    """Safe default ranker using only structured/static tool facts."""

    name = "deterministic"

    def rank_tools(
        self,
        tools: dict[str, Any],
        context: ToolSelectionContext,
        *,
        score_fallback: Callable[[Any], float],
    ) -> list[str]:
        _ = context
        ranked = [
            (name, score_fallback(tool), index) for index, (name, tool) in enumerate(tools.items())
        ]
        ranked.sort(key=lambda item: (-item[1], item[2]))
        return [name for name, _, _ in ranked]


class _CallableSemanticToolRanker:
    """Adapter for function-style semantic ranker callables."""

    name = "custom_callable"

    def __init__(
        self, callback: Callable[[dict[str, Any], ToolSelectionContext], list[str]]
    ) -> None:
        self._callback = callback

    def rank_tools(
        self,
        tools: dict[str, Any],
        context: ToolSelectionContext,
        *,
        score_fallback: Callable[[Any], float],
    ) -> list[str]:
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

    def __init__(self) -> None:
        """Initialize the tool selector."""
        self._deterministic_ranker = DeterministicToolRanker()

    def select_tools(
        self,
        tools: dict[str, Any],
        context: ToolSelectionContext,
    ) -> list[str]:
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

        # MCP tools get slight bonus (they're user-configured, likely important)
        if tool_name.startswith("mcp__"):
            score += 1.0

        score += self._resolve_quality_boost(
            tool_name,
            context.metadata if isinstance(context.metadata, Mapping) else {},
        )

        return score

    def _resolve_semantic_ranker(self, context: ToolSelectionContext) -> SemanticToolRanker:
        metadata = context.metadata if isinstance(context.metadata, Mapping) else {}
        backend = str(metadata.get("semantic_backend", "")).strip().lower()

        if backend == "embedding_vector":
            embedding_ranker = metadata.get("embedding_ranker")
            if hasattr(embedding_ranker, "rank_tools"):
                return embedding_ranker  # type: ignore[return-value]
            if callable(embedding_ranker):
                return _CallableSemanticToolRanker(
                    cast(
                        Callable[[dict[str, Any], ToolSelectionContext], list[str]],
                        embedding_ranker,
                    )
                )

        custom_ranker = metadata.get("semantic_ranker")
        if hasattr(custom_ranker, "rank_tools"):
            return custom_ranker  # type: ignore[return-value]
        if callable(custom_ranker):
            return _CallableSemanticToolRanker(
                cast(Callable[[dict[str, Any], ToolSelectionContext], list[str]], custom_ranker)
            )

        if backend and backend != "agent_decision":
            logger.debug("Ignoring unsupported local tool ranking backend: %s", backend)
        return self._deterministic_ranker

    def _resolve_quality_boost(self, tool_name: str, metadata: Mapping[str, Any]) -> float:
        scores = metadata.get("tool_quality_scores")
        if isinstance(scores, Mapping):
            raw = scores.get(tool_name)
            try:
                score = float(raw) if raw is not None else 0.0
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
        tools: dict[str, Any],
        context: ToolSelectionContext,
    ) -> list[str]:
        def _score_fallback(tool: Any) -> float:
            return self.score_tool_relevance(tool, context)

        try:
            ranked_names = ranker.rank_tools(
                tools,
                context,
                score_fallback=_score_fallback,
            )
        except Exception:
            logger.exception("Semantic ranker failed, using deterministic fallback")
            ranked_names = self._deterministic_ranker.rank_tools(
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
            for name in self._deterministic_ranker.rank_tools(
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
_selector: ToolSelector | None = None


def get_tool_selector() -> ToolSelector:
    """Get the global tool selector instance.

    Returns:
        ToolSelector singleton
    """
    global _selector
    if _selector is None:
        _selector = ToolSelector()
    return _selector
