"""Safe presentation of persisted permission decisions; never grants authority."""

from collections.abc import Mapping
from typing import Any

from src.infrastructure.agent.hitl.utils import sanitize_hitl_text, sanitize_permission_description


def permission_granted(response: object, metadata: Mapping[str, Any]) -> bool | None:
    """Decode exact protocol actions and legacy booleans, rejecting conflicts."""
    decision = None
    if isinstance(response, str):
        if response in ("allow", "allow_always", "true"):
            decision = True
        elif response in ("deny", "false"):
            decision = False
        elif response:
            return None
    legacy = metadata.get("granted")
    if isinstance(legacy, bool):
        if decision is not None and decision is not legacy:
            return None
        return legacy
    return decision


def permission_history_item(
    data: dict[str, Any],
    answered_map: dict[str, Any],
    status_map: dict[str, Any],
) -> dict[str, Any]:
    request_id = data.get("request_id", "")
    status = status_map.get(request_id, {})
    stored = status.get("permission_metadata", {})
    event_metadata = data.get("metadata")
    event_metadata = event_metadata if isinstance(event_metadata, Mapping) else {}

    def text_field(key: str, fallback: object = "") -> str:
        return sanitize_hitl_text(stored.get(key, data.get(key, fallback))) or ""

    tool = text_field("tool_name", event_metadata.get("tool", ""))
    answered = False
    granted = None
    if request_id in answered_map:
        answered = True
        granted = permission_granted(None, answered_map[request_id])
    elif status.get("status") in ("answered", "completed"):
        answered = True
        granted = permission_granted(status.get("response"), status.get("response_metadata", {}))
    remember = stored.get("allow_remember", data.get("allow_remember", True))
    return {
        "requestId": request_id,
        "action": text_field("action", data.get("permission", "")),
        "resource": text_field("resource", tool),
        "reason": text_field("reason"),
        "toolName": tool,
        "toolDisplayName": text_field("tool_display_name"),
        "riskLevel": text_field("risk_level", "medium"),
        "description": sanitize_permission_description(
            stored.get("description", data.get("description"))
        )
        or "",
        "allowRemember": remember if isinstance(remember, bool) else False,
        "answered": answered,
        "granted": granted,
    }
