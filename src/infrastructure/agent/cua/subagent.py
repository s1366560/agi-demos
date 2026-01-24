"""
CUA SubAgent.

Provides CUA as a SubAgent for L3 (SubAgent Layer) integration.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

from src.domain.model.agent.subagent import SubAgent, SubAgentStatus

if TYPE_CHECKING:
    from .adapter import CUAAdapter
    from .config import CUAConfig

logger = logging.getLogger(__name__)


class CUASubAgent(SubAgent):
    """
    CUA SubAgent for L3 integration.

    This class wraps the CUA ComputerAgent as a MemStack SubAgent,
    enabling automatic routing of computer-related tasks to CUA.

    Features:
    - Pattern-based routing (triggers)
    - Tool filtering for CUA-specific tools
    - Model override support
    - Execution statistics tracking
    """

    def __init__(self, config: "CUAConfig", adapter: "CUAAdapter"):
        """
        Initialize CUA SubAgent.

        Args:
            config: CUA configuration
            adapter: CUA adapter instance
        """
        super().__init__(
            id="cua_computer_agent",
            tenant_id="system",
            name="cua_computer_agent",
            display_name="计算机操作助手",
            description=(
                "AI assistant for computer operations and UI automation. "
                "Can browse websites, fill forms, click buttons, and more."
            ),
            system_prompt=self._build_system_prompt(),
            triggers=config.subagent.triggers,
            model_override=config.model if config.model else None,
            status=SubAgentStatus.ACTIVE,
        )

        self._config = config
        self._adapter = adapter
        self._execution_count = 0
        self._success_count = 0
        self._total_execution_time_ms = 0

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the CUA agent."""
        return """You are a Computer Use Agent capable of controlling a computer to complete tasks.

You can:
- Take screenshots to see the current screen state
- Click on UI elements (buttons, links, input fields)
- Type text using the keyboard
- Scroll the screen
- Navigate web browsers

Guidelines:
1. Always take a screenshot first to understand the current state
2. Identify the target element before clicking
3. Verify your actions by taking screenshots after each step
4. Report what you see and what you're doing
5. Ask for clarification if the task is unclear

Available tools:
- cua_screenshot: Capture the current screen
- cua_click: Click at specific coordinates
- cua_type: Type text using keyboard
- cua_scroll: Scroll the screen
- cua_browser_navigate: Navigate to a URL

Remember: You are operating in a sandboxed environment. Be careful and methodical."""

    @property
    def is_active(self) -> bool:
        """Check if the subagent is active."""
        return (
            self._config.enabled
            and self._config.subagent.enabled
            and self.status == SubAgentStatus.ACTIVE
        )

    def get_tool_filter(self) -> List[str]:
        """
        Get the tool filter pattern for this subagent.

        Returns:
            List of tool name patterns (supports wildcards)
        """
        return ["cua_*"]  # All CUA tools

    def get_allowed_tools(self) -> List[str]:
        """
        Get the list of allowed tool names.

        Returns:
            List of allowed tool names
        """
        allowed = []

        if self._config.permissions.allow_screenshot:
            allowed.append("cua_screenshot")

        if self._config.permissions.allow_mouse_click:
            allowed.extend(["cua_click", "cua_drag", "cua_scroll"])

        if self._config.permissions.allow_keyboard_input:
            allowed.append("cua_type")

        if self._config.permissions.allow_browser_navigation:
            allowed.append("cua_browser_navigate")

        return allowed

    def matches_query(self, query: str) -> float:
        """
        Calculate match score for a query.

        Args:
            query: User query

        Returns:
            Match score between 0.0 and 1.0
        """
        if not self.is_active:
            return 0.0

        query_lower = query.lower()
        max_score = 0.0

        for trigger in self.triggers:
            trigger_lower = trigger.lower()

            # Exact match
            if trigger_lower == query_lower:
                return 1.0

            # Trigger contained in query
            if trigger_lower in query_lower:
                score = len(trigger_lower) / len(query_lower)
                max_score = max(max_score, min(score + 0.3, 0.95))

            # Query contained in trigger
            if query_lower in trigger_lower:
                score = len(query_lower) / len(trigger_lower)
                max_score = max(max_score, min(score + 0.2, 0.9))

            # Word overlap
            trigger_words = set(trigger_lower.split())
            query_words = set(query_lower.split())
            overlap = trigger_words & query_words
            if overlap:
                score = len(overlap) / max(len(trigger_words), len(query_words))
                max_score = max(max_score, score * 0.7)

        return max_score

    async def execute(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute the subagent with the given query.

        Args:
            query: User query/instruction
            context: Optional execution context

        Yields:
            Event dictionaries for streaming
        """
        if not self.is_active:
            yield {
                "type": "error",
                "data": {
                    "message": "CUA SubAgent is not active",
                    "code": "SUBAGENT_INACTIVE",
                },
                "timestamp": datetime.utcnow().isoformat(),
            }
            return

        start_time = datetime.utcnow()
        self._execution_count += 1

        try:
            # Emit subagent start event
            yield {
                "type": "subagent_execution_start",
                "data": {
                    "subagent_id": self.id,
                    "subagent_name": self.display_name,
                    "query": query,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Delegate to adapter
            async for event in self._adapter.execute(query, context):
                yield event

            # Track success
            self._success_count += 1

            # Emit completion event
            execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            self._total_execution_time_ms += execution_time_ms

            yield {
                "type": "subagent_execution_complete",
                "data": {
                    "subagent_id": self.id,
                    "success": True,
                    "execution_time_ms": execution_time_ms,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"CUA SubAgent execution error: {e}", exc_info=True)

            execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            self._total_execution_time_ms += execution_time_ms

            yield {
                "type": "error",
                "data": {
                    "message": str(e),
                    "code": "SUBAGENT_EXECUTION_ERROR",
                    "subagent_id": self.id,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get execution statistics.

        Returns:
            Statistics dictionary
        """
        success_rate = (
            self._success_count / self._execution_count if self._execution_count > 0 else 0.0
        )
        avg_execution_time = (
            self._total_execution_time_ms / self._execution_count
            if self._execution_count > 0
            else 0.0
        )

        return {
            "subagent_id": self.id,
            "display_name": self.display_name,
            "is_active": self.is_active,
            "execution_count": self._execution_count,
            "success_count": self._success_count,
            "success_rate": success_rate,
            "total_execution_time_ms": self._total_execution_time_ms,
            "avg_execution_time_ms": avg_execution_time,
        }

    def reset_stats(self) -> None:
        """Reset execution statistics."""
        self._execution_count = 0
        self._success_count = 0
        self._total_execution_time_ms = 0
