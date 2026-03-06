"""Canvas/A2UI module for dynamic UI block management.

Public API:
    - CanvasBlockType, CanvasBlock, CanvasState  (models)
    - CanvasManager                               (state management)
    - configure_canvas                            (DI)
    - canvas_create, canvas_update, canvas_delete (tools)
    - build_canvas_event_dict                     (event helper)
    - A2UI builder helpers                        (a2ui_builder)
"""

from src.infrastructure.agent.canvas.a2ui_builder import (
    begin_rendering,
    button_component,
    card_component,
    column_component,
    data_model_update,
    delete_surface,
    divider_component,
    pack_messages,
    row_component,
    surface_update,
    text_component,
    text_field_component,
)
from src.infrastructure.agent.canvas.events import build_canvas_event_dict
from src.infrastructure.agent.canvas.manager import CanvasManager
from src.infrastructure.agent.canvas.models import (
    CanvasBlock,
    CanvasBlockType,
    CanvasState,
)
from src.infrastructure.agent.canvas.tools import configure_canvas

__all__ = [
    "CanvasBlock",
    "CanvasBlockType",
    "CanvasManager",
    "CanvasState",
    "begin_rendering",
    "build_canvas_event_dict",
    "button_component",
    "card_component",
    "column_component",
    "configure_canvas",
    "data_model_update",
    "delete_surface",
    "divider_component",
    "pack_messages",
    "row_component",
    "surface_update",
    "text_component",
    "text_field_component",
]
