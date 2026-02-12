"""
Routing decision schemas for LLM-based SubAgent routing.

Defines the function calling schema and response models
used by the IntentRouter to make routing decisions.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class RoutingCandidate:
    """A SubAgent candidate presented to the LLM for routing."""

    name: str
    display_name: str
    description: str
    examples: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LLMRoutingDecision:
    """Parsed routing decision from LLM function call response."""

    subagent_name: Optional[str] = None
    confidence: float = 0.0
    reasoning: str = ""
    matched: bool = False


def build_routing_tool_schema(candidates: List[RoutingCandidate]) -> List[Dict[str, Any]]:
    """Build the function calling tool schema for routing.

    Creates a single tool `route_to_subagent` whose `subagent_name` parameter
    is an enum of available SubAgent names.  If no SubAgent fits, the LLM
    should set subagent_name to "none".

    Args:
        candidates: Available SubAgent candidates.

    Returns:
        List with one tool definition for LLM function calling.
    """
    names = [c.name for c in candidates] + ["none"]

    return [
        {
            "type": "function",
            "function": {
                "name": "route_to_subagent",
                "description": (
                    "Route the user query to the most appropriate specialized agent. "
                    "Choose 'none' if no agent is a good fit."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subagent_name": {
                            "type": "string",
                            "enum": names,
                            "description": "Name of the best-matching agent, or 'none'.",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Confidence score (0.0-1.0) for the routing decision.",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Brief reason for the routing decision.",
                        },
                    },
                    "required": ["subagent_name", "confidence", "reasoning"],
                },
            },
        }
    ]


def build_routing_system_prompt(candidates: List[RoutingCandidate]) -> str:
    """Build the system prompt for the routing LLM call.

    Lists all available SubAgents with their descriptions and examples
    so the LLM can make an informed routing decision.

    Args:
        candidates: Available SubAgent candidates.

    Returns:
        System prompt string.
    """
    lines = [
        "You are a query router. Analyze the user query and route it to the "
        "most appropriate specialized agent. If none fits well, choose 'none'.",
        "",
        "Available agents:",
    ]

    for c in candidates:
        lines.append(f"- **{c.name}** ({c.display_name}): {c.description}")
        if c.examples:
            examples_str = "; ".join(c.examples[:3])
            lines.append(f"  Examples: {examples_str}")

    lines.extend([
        "",
        "Rules:",
        "- Only route if confidence >= 0.6",
        "- Choose 'none' if the query is general or doesn't clearly match any agent",
        "- Prefer the most specific agent when multiple could match",
    ])

    return "\n".join(lines)


def parse_routing_response(response: Dict[str, Any]) -> LLMRoutingDecision:
    """Parse LLM function call response into a routing decision.

    Args:
        response: Raw response from LLM generate() call.

    Returns:
        Parsed LLMRoutingDecision.
    """
    import json

    tool_calls = response.get("tool_calls", [])
    if not tool_calls:
        # No function call - LLM declined to route
        content = response.get("content", "")
        return LLMRoutingDecision(
            reasoning=f"LLM did not call routing function: {content[:200]}",
        )

    # Parse the first tool call
    tool_call = tool_calls[0]
    func = tool_call if isinstance(tool_call, dict) else tool_call.__dict__
    function_data = func.get("function", func)

    # Extract arguments
    args_raw = function_data.get("arguments", "{}")
    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw)
        except json.JSONDecodeError:
            return LLMRoutingDecision(reasoning=f"Failed to parse arguments: {args_raw[:200]}")
    else:
        args = args_raw

    name = args.get("subagent_name", "none")
    confidence = float(args.get("confidence", 0.0))
    reasoning = args.get("reasoning", "")

    if name == "none" or confidence < 0.1:
        return LLMRoutingDecision(
            confidence=confidence,
            reasoning=reasoning or "LLM chose no agent",
        )

    return LLMRoutingDecision(
        subagent_name=name,
        confidence=confidence,
        reasoning=reasoning,
        matched=True,
    )
