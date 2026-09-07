"""Public Agent lifecycle event keys owned by the protocol-v2 Agent spine."""

from __future__ import annotations

from typing import Final

AGENT_SESSION_START_EVENT_V2: Final[str] = "agent.session.start"
AGENT_BEFORE_REQUEST_EVENT_V2: Final[str] = "agent.before_request"
AGENT_BEFORE_PROMPT_BUILD_EVENT_V2: Final[str] = "agent.before_prompt_build"
AGENT_CONTEXT_OVERFLOW_EVENT_V2: Final[str] = "agent.context_overflow"
AGENT_AFTER_TURN_COMPLETE_EVENT_V2: Final[str] = "agent.after_turn_complete"
AGENT_SKILL_TOOL_OBSERVED_EVENT_V2: Final[str] = "agent.skill_tool_observed"
TOOLS_AFTER_EXECUTE_EVENT_V2: Final[str] = "tools.after_execute"
AGENT_RUNTIME_HOOK_EVENTS_V2: Final[tuple[str, ...]] = (
    AGENT_SESSION_START_EVENT_V2,
    AGENT_BEFORE_REQUEST_EVENT_V2,
    TOOLS_AFTER_EXECUTE_EVENT_V2,
)


__all__ = [
    "AGENT_AFTER_TURN_COMPLETE_EVENT_V2",
    "AGENT_BEFORE_PROMPT_BUILD_EVENT_V2",
    "AGENT_BEFORE_REQUEST_EVENT_V2",
    "AGENT_CONTEXT_OVERFLOW_EVENT_V2",
    "AGENT_RUNTIME_HOOK_EVENTS_V2",
    "AGENT_SESSION_START_EVENT_V2",
    "AGENT_SKILL_TOOL_OBSERVED_EVENT_V2",
    "TOOLS_AFTER_EXECUTE_EVENT_V2",
]
