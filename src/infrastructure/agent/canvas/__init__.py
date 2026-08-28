"""Canvas/A2UI module for dynamic UI block management.

Public API:
    - CanvasBlockType, CanvasBlock, CanvasState  (models)
    - CanvasManager                               (state management)
    - canvas_create, canvas_update, canvas_delete (tools)
    - build_canvas_event_dict                     (event helper)
    - A2UI builder helpers                        (a2ui_builder)
"""

from src.infrastructure.agent.canvas.a2ui_builder import (
    badge_component,
    begin_rendering,
    button_component,
    canonicalize_a2ui_messages,
    card_component,
    checkbox_component,
    column_component,
    data_model_update,
    delete_surface,
    divider_component,
    extract_surface_id,
    extract_surface_ids,
    image_component,
    modal_component,
    pack_messages,
    progress_component,
    radio_component,
    row_component,
    select_component,
    surface_update,
    table_component,
    tabs_component,
    text_component,
    text_field_component,
    validate_a2ui_incremental_surface_id,
    validate_a2ui_message_syntax,
    validate_a2ui_messages,
)
from src.infrastructure.agent.canvas.events import build_canvas_event_dict
from src.infrastructure.agent.canvas.manager import CanvasManager
from src.infrastructure.agent.canvas.models import (
    CanvasBlock,
    CanvasBlockType,
    CanvasState,
)

__all__ = [
    "CanvasBlock",
    "CanvasBlockType",
    "CanvasManager",
    "CanvasState",
    "badge_component",
    "begin_rendering",
    "build_canvas_event_dict",
    "button_component",
    "canonicalize_a2ui_messages",
    "card_component",
    "checkbox_component",
    "column_component",
    "data_model_update",
    "delete_surface",
    "divider_component",
    "extract_surface_id",
    "extract_surface_ids",
    "image_component",
    "modal_component",
    "pack_messages",
    "progress_component",
    "radio_component",
    "row_component",
    "select_component",
    "surface_update",
    "table_component",
    "tabs_component",
    "text_component",
    "text_field_component",
    "validate_a2ui_incremental_surface_id",
    "validate_a2ui_message_syntax",
    "validate_a2ui_messages",
]
