"""Frontend plugin slot contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UiSlotKind(str, Enum):
    """Bounded surfaces a frontend plugin may contribute."""

    NAV_ITEM = "nav_item"
    SETTINGS_PAGE = "settings_page"
    CONVERSATION_RENDERER = "conversation_renderer"
    TOOL_RESULT_RENDERER = "tool_result_renderer"
    COMPOSER_ACTION = "composer_action"
    MCP_CANVAS = "mcp_canvas"


@dataclass(frozen=True)
class UiSlotDefinition:
    """One signed frontend module contribution."""

    plugin_id: str
    slot: UiSlotKind
    id: str
    module_ref: str
    permission: str
    sandbox: bool = True
