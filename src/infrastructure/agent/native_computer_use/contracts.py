"""Host-owned authorization and device identities for native Computer Use."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PermissionProfile = Literal["read_only", "workspace_write", "full_access"]

# Declared first-party catalog. Effects are static tool metadata, not inferred intent.
READ_TOOL_NAMES = frozenset(
    {
        "computer_list_apps",
        "computer_get_app_state",
        "computer_capabilities",
        "computer_list_windows",
        "computer_clipboard_read",
        "computer_audio_status",
    }
)
TOOL_NAMES = READ_TOOL_NAMES | frozenset(
    {
        "computer_click",
        "computer_type_text",
        "computer_press_key",
        "computer_scroll",
        "computer_set_value",
        "computer_drag",
        "computer_secondary_action",
        "computer_paste",
        "computer_launch_app",
        "computer_activate_app",
        "computer_select_text",
        "computer_key_down",
        "computer_key_up",
        "computer_move",
        "computer_drag_step",
        "computer_clipboard_write",
        "computer_clipboard_release",
        "computer_audio_start",
        "computer_audio_stop",
        "computer_connector_call",
    }
)


@dataclass(frozen=True, kw_only=True)
class DeviceScope:
    """Authenticated desktop registration scope, never model-provided."""

    user_id: str
    tenant_id: str
    project_id: str
    device_id: str


@dataclass(frozen=True, kw_only=True)
class CallAuthorization:
    """Fresh run authority for exactly one host-approved tool invocation."""

    user_id: str
    tenant_id: str
    project_id: str
    conversation_id: str
    run_id: str
    session_id: str
    round: int
    permission_profile: PermissionProfile
    authorization_revision: int
    plan_version_id: str | None
    approved_tools: tuple[str, ...]
    call_id: str
    device_id: str | None = None
    child_run_id: str | None = None
    child_owner_digest: str | None = field(default=None, repr=False)
    run_kind: Literal["chat", "plan"] = "chat"
    allowed_mcp_servers: tuple[str, ...] = ()
