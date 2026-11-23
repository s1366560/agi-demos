"""ReAct continuation protocol run by the signed Agent worker.

Only structural progress crosses the worker boundary. Model messages, tool
arguments, credentials and goal judgements remain with their authorized executor.
"""

from typing import Any

# A release may narrow the caller's budget. The host always enforces its own limits.
MAX_ROUNDS_PER_TURN: int | None = None


def next_action(phase: str, outcome: str, steps: int) -> str:
    if phase == "stepped":
        return "judge"
    if outcome != "continue":
        return "finish"
    if phase == "judged":
        return "observe"
    if phase not in {"start", "observed", "restart"}:
        raise ValueError("unknown ReAct continuation phase")
    if MAX_ROUNDS_PER_TURN is not None and steps >= MAX_ROUNDS_PER_TURN:
        return "stop"
    return "step"


def react_loop(arguments: dict[str, Any]) -> dict[str, str]:
    return {"action": next_action(arguments["phase"], arguments["outcome"], arguments["steps"])}
