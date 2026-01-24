"""CUA Computer Action Tools."""

import json
import logging
from typing import TYPE_CHECKING, Any, Dict

from tools.base import ToolBase

if TYPE_CHECKING:
    from ..adapter import CUAAdapter

logger = logging.getLogger(__name__)


class CUABaseTool(ToolBase):
    """Base class for CUA tools."""

    def __init__(self, adapter: "CUAAdapter", name: str, description: str):
        super().__init__(name=name, description=description)
        self._adapter = adapter

    @property
    def adapter(self) -> "CUAAdapter":
        return self._adapter


class CUAClickTool(CUABaseTool):
    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_click",
            description=(
                "Click at specific coordinates on the screen. "
                "Use this to interact with UI elements like buttons, links, and input fields. "
                "Coordinates are in pixels from the top-left corner."
            ),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate in pixels from left edge"},
                "y": {"type": "integer", "description": "Y coordinate in pixels from top edge"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                    "description": "Mouse button to click",
                },
                "click_type": {
                    "type": "string",
                    "enum": ["single", "double"],
                    "default": "single",
                    "description": "Type of click",
                },
            },
            "required": ["x", "y"],
        }

    async def execute(self, **kwargs: Any) -> str:
        x = kwargs.get("x")
        y = kwargs.get("y")
        button = kwargs.get("button", "left")
        click_type = kwargs.get("click_type", "single")

        if x is None or y is None:
            return json.dumps({"success": False, "error": "x and y coordinates are required"})

        try:
            success = await self._adapter.click(x=int(x), y=int(y))
            if success:
                return json.dumps(
                    {
                        "success": True,
                        "action": "click",
                        "coordinates": {"x": x, "y": y},
                        "button": button,
                        "click_type": click_type,
                    }
                )
            return json.dumps({"success": False, "error": "Click operation failed"})
        except Exception as exc:
            logger.error("Click error: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})


class CUATypeTool(CUABaseTool):
    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_type",
            description=(
                "Type text using the keyboard. "
                "Use this after clicking on an input field to enter text. "
                "Supports special keys like Enter, Tab, etc."
            ),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type"},
                "press_enter": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to press Enter after typing",
                },
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> str:
        text = kwargs.get("text")
        press_enter = kwargs.get("press_enter", False)

        if not text:
            return json.dumps({"success": False, "error": "text is required"})

        try:
            success = await self._adapter.type_text(str(text))
            if not success:
                return json.dumps({"success": False, "error": "Type operation failed"})

            if press_enter:
                await self._adapter.type_text("\n")

            return json.dumps(
                {
                    "success": True,
                    "action": "type",
                    "text": text,
                    "press_enter": press_enter,
                }
            )
        except Exception as exc:
            logger.error("Type error: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})


class CUAScrollTool(CUABaseTool):
    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_scroll",
            description=(
                "Scroll at specific coordinates on the screen. "
                "Use this to scroll pages or lists. "
                "Positive delta_y scrolls down, negative scrolls up."
            ),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate in pixels"},
                "y": {"type": "integer", "description": "Y coordinate in pixels"},
                "delta_x": {
                    "type": "integer",
                    "default": 0,
                    "description": "Horizontal scroll delta",
                },
                "delta_y": {
                    "type": "integer",
                    "default": 0,
                    "description": "Vertical scroll delta",
                },
            },
            "required": ["x", "y"],
        }

    async def execute(self, **kwargs: Any) -> str:
        x = kwargs.get("x")
        y = kwargs.get("y")
        delta_x = kwargs.get("delta_x", 0)
        delta_y = kwargs.get("delta_y", 0)

        if x is None or y is None:
            return json.dumps({"success": False, "error": "x and y are required"})

        try:
            success = await self._adapter.scroll(
                x=int(x), y=int(y), delta_x=int(delta_x), delta_y=int(delta_y)
            )
            if success:
                return json.dumps(
                    {
                        "success": True,
                        "action": "scroll",
                        "coordinates": {"x": x, "y": y},
                        "delta_x": delta_x,
                        "delta_y": delta_y,
                    }
                )
            return json.dumps({"success": False, "error": "Scroll operation failed"})
        except Exception as exc:
            logger.error("Scroll error: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})


class CUADragTool(CUABaseTool):
    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_drag",
            description=(
                "Drag from one coordinate to another. "
                "Use this to move items, resize windows, or select regions."
            ),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "x1": {"type": "integer", "description": "Start X coordinate"},
                "y1": {"type": "integer", "description": "Start Y coordinate"},
                "x2": {"type": "integer", "description": "End X coordinate"},
                "y2": {"type": "integer", "description": "End Y coordinate"},
            },
            "required": ["x1", "y1", "x2", "y2"],
        }

    async def execute(self, **kwargs: Any) -> str:
        x1 = kwargs.get("x1")
        y1 = kwargs.get("y1")
        x2 = kwargs.get("x2")
        y2 = kwargs.get("y2")

        if None in (x1, y1, x2, y2):
            return json.dumps({"success": False, "error": "x1, y1, x2, y2 are required"})

        try:
            success = await self._adapter.drag(x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2))
            if success:
                return json.dumps(
                    {
                        "success": True,
                        "action": "drag",
                        "start": {"x": x1, "y": y1},
                        "end": {"x": x2, "y": y2},
                    }
                )
            return json.dumps({"success": False, "error": "Drag operation failed"})
        except Exception as exc:
            logger.error("Drag error: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})
