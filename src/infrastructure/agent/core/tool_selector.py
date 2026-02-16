"""Tool Selection Strategy - Intelligent tool filtering for LLM context optimization.

When too many tools are available, this module provides intelligent
selection based on relevance to the conversation context.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

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


class ToolSelector:
    """Selects the most relevant tools based on context.

    When the number of available tools exceeds a limit,
    this selector ranks and filters tools to reduce LLM
    context consumption while preserving functionality.
    """

    def __init__(self):
        """Initialize the tool selector."""
        self._stopwords = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "need", "dare", "ought", "used", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "as", "into",
            "through", "during", "before", "after", "above", "below",
            "between", "under", "again", "further", "then", "once",
            "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
            "you", "your", "yours", "yourself", "yourselves", "he", "him",
            "his", "himself", "she", "her", "hers", "herself", "it", "its",
            "itself", "they", "them", "their", "theirs", "themselves",
            "what", "which", "who", "whom", "this", "that", "these", "those",
            "and", "but", "or", "if", "because", "as", "until", "while",
        }

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
        scores: Dict[str, float] = {}
        for name, tool in tools.items():
            scores[name] = self.score_tool_relevance(tool, context)

        # Sort by score (descending)
        sorted_tools = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # Select top tools
        selected = []
        always_include = context.always_include or CORE_TOOLS

        # First, add all always-include tools
        for name in tools:
            if name in always_include:
                selected.append(name)

        # Then add top-scored tools until we hit the limit
        for name, score in sorted_tools:
            if name not in selected:
                selected.append(name)
                if len(selected) >= context.max_tools:
                    break

        logger.debug(
            "Selected %d/%d tools (always_include: %d)",
            len(selected), len(tools), len(always_include & set(tools.keys()))
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
        keywords = {
            word for word in words
            if word not in self._stopwords and len(word) >= 2
        }

        return keywords


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
