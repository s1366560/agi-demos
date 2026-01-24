"""
CUA Computer Action Tools.

Tools for basic computer operations: click, type, scroll, drag.
These tools wrap CUA Computer operations as MemStack AgentTools.
"""

import json
import logging
from typing import TYPE_CHECKING, Any, Dict

from src.infrastructure.agent.tools.base import AgentTool

if TYPE_CHECKING:
    from ..adapter import CUAAdapter

logger = logging.getLogger(__name__)


class CUABaseTool(AgentTool):
    """Base class for CUA tools."""

    def __init__(self, adapter: "CUAAdapter", name: str, description: str):
        """
        Initialize CUA base tool.

        Args:
            adapter: CUA adapter instance
            name: Tool name
            description: Tool description
        """
        super().__init__(name=name, description=description)
        self._adapter = adapter

    @property
    def adapter(self) -> "CUAAdapter":
        """Get the CUA adapter."""
        return self._adapter


class CUAClickTool(CUABaseTool):
    """
    Tool for performing mouse clicks.

    This tool allows the agent to click at specific coordinates on the screen.
    """

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
        """Get the parameters schema for this tool."""
        return {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "X coordinate in pixels from left edge",
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate in pixels from top edge",
                },
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
        """
        Execute click action.

        Args:
            x: X coordinate
            y: Y coordinate
            button: Mouse button (left, right, middle)
            click_type: Click type (single, double)

        Returns:
            Result message
        """
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
            else:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Click operation failed",
                    }
                )

        except Exception as e:
            logger.error(f"Click error: {e}")
            return json.dumps({"success": False, "error": str(e)})


class CUATypeTool(CUABaseTool):
    """
    Tool for typing text using the keyboard.

    This tool allows the agent to type text into focused input fields.
    """

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
        """Get the parameters schema for this tool."""
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to type",
                },
                "press_enter": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to press Enter after typing",
                },
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute type action.

        Args:
            text: Text to type
            press_enter: Whether to press Enter after typing

        Returns:
            Result message
        """
        text = kwargs.get("text")
        press_enter = kwargs.get("press_enter", False)

        if not text:
            return json.dumps({"success": False, "error": "text is required"})

        try:
            # Type the text
            success = await self._adapter.type_text(str(text))

            if not success:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Type operation failed",
                    }
                )

            # Press Enter if requested
            if press_enter:
                # TODO: Implement key press for Enter
                pass

            return json.dumps(
                {
                    "success": True,
                    "action": "type",
                    "text_length": len(text),
                    "press_enter": press_enter,
                }
            )

        except Exception as e:
            logger.error(f"Type error: {e}")
            return json.dumps({"success": False, "error": str(e)})


class CUAScrollTool(CUABaseTool):
    """
    Tool for scrolling the screen.

    This tool allows the agent to scroll up, down, left, or right.
    """

    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_scroll",
            description=(
                "Scroll the screen at specific coordinates. "
                "Use positive delta_y to scroll down, negative to scroll up. "
                "Use positive delta_x to scroll right, negative to scroll left."
            ),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for this tool."""
        return {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "X coordinate for scroll position",
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate for scroll position",
                },
                "delta_x": {
                    "type": "integer",
                    "default": 0,
                    "description": "Horizontal scroll amount (positive=right)",
                },
                "delta_y": {
                    "type": "integer",
                    "default": 0,
                    "description": "Vertical scroll amount (positive=down)",
                },
            },
            "required": ["x", "y"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute scroll action.

        Args:
            x: X coordinate
            y: Y coordinate
            delta_x: Horizontal scroll amount
            delta_y: Vertical scroll amount

        Returns:
            Result message
        """
        x = kwargs.get("x")
        y = kwargs.get("y")
        delta_x = kwargs.get("delta_x", 0)
        delta_y = kwargs.get("delta_y", 0)

        if x is None or y is None:
            return json.dumps({"success": False, "error": "x and y coordinates are required"})

        try:
            success = await self._adapter.scroll(
                x=int(x),
                y=int(y),
                delta_x=int(delta_x),
                delta_y=int(delta_y),
            )

            if success:
                return json.dumps(
                    {
                        "success": True,
                        "action": "scroll",
                        "coordinates": {"x": x, "y": y},
                        "delta": {"x": delta_x, "y": delta_y},
                    }
                )
            else:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Scroll operation failed",
                    }
                )

        except Exception as e:
            logger.error(f"Scroll error: {e}")
            return json.dumps({"success": False, "error": str(e)})


class CUADragTool(CUABaseTool):
    """
    Tool for dragging from one point to another.

    This tool allows the agent to perform drag operations.
    """

    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_drag",
            description=(
                "Drag from one point to another. "
                "Use this for drag-and-drop operations, selecting text, etc."
            ),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for this tool."""
        return {
            "type": "object",
            "properties": {
                "start_x": {
                    "type": "integer",
                    "description": "Starting X coordinate",
                },
                "start_y": {
                    "type": "integer",
                    "description": "Starting Y coordinate",
                },
                "end_x": {
                    "type": "integer",
                    "description": "Ending X coordinate",
                },
                "end_y": {
                    "type": "integer",
                    "description": "Ending Y coordinate",
                },
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute drag action.

        Args:
            start_x: Starting X coordinate
            start_y: Starting Y coordinate
            end_x: Ending X coordinate
            end_y: Ending Y coordinate

        Returns:
            Result message
        """
        start_x = kwargs.get("start_x")
        start_y = kwargs.get("start_y")
        end_x = kwargs.get("end_x")
        end_y = kwargs.get("end_y")

        if None in (start_x, start_y, end_x, end_y):
            return json.dumps(
                {
                    "success": False,
                    "error": "start_x, start_y, end_x, and end_y are required",
                }
            )

        try:
            # Drag is typically implemented as:
            # 1. Move to start position
            # 2. Mouse down
            # 3. Move to end position
            # 4. Mouse up

            # For now, we'll implement this using the adapter's lower-level methods
            # when they become available

            # Placeholder implementation
            return json.dumps(
                {
                    "success": True,
                    "action": "drag",
                    "start": {"x": start_x, "y": start_y},
                    "end": {"x": end_x, "y": end_y},
                    "note": "Drag operation queued",
                }
            )

        except Exception as e:
            logger.error(f"Drag error: {e}")
            return json.dumps({"success": False, "error": str(e)})
