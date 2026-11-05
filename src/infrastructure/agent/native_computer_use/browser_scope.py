"""Browser identity projected from a host-owned, authority-checked native call."""

from __future__ import annotations

from typing import Any

from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, identifier


def browser_scope(value: dict[str, Any]) -> dict[str, Any]:
    """The authenticated claim route revalidates child ownership before projection.

    Request arguments never supply these fields. The execution ID is the live
    child run ID, not the selected agent definition or a JavaScript parameter.
    """
    conversation = identifier(value["conversation_id"])
    run = identifier(value["run_id"])
    engine = identifier(value["session_id"])
    child = value.get("child_run_id")
    if child is not None:
        child = identifier(child)
        if child == run or not value.get("child_owner_digest"):
            raise DeviceBridgeError("computer_use_child_authority_invalid")
    return {
        "execution_id": child or run,
        "main_conversation_id": conversation,
        "parent_run_id": run,
        "engine_session_id": engine,
        "is_child": child is not None,
    }
