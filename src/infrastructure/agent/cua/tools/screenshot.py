"""
CUA Screenshot Tool.

Tool for capturing screenshots from the computer display.
"""

import json
import logging
from typing import TYPE_CHECKING, Any, Dict

from .computer_action import CUABaseTool

if TYPE_CHECKING:
    from ..adapter import CUAAdapter

logger = logging.getLogger(__name__)


class CUAScreenshotTool(CUABaseTool):
    """
    Tool for capturing screenshots.

    This tool allows the agent to capture the current screen state.
    Screenshots are essential for visual understanding and decision making.
    """

    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_screenshot",
            description=(
                "Capture a screenshot of the current screen. "
                "Use this to see the current state of the UI, verify actions, "
                "or analyze visual elements before taking action."
            ),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for this tool."""
        return {
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "description": "Optional region to capture (full screen if not specified)",
                    "properties": {
                        "x": {"type": "integer", "description": "Left edge X coordinate"},
                        "y": {"type": "integer", "description": "Top edge Y coordinate"},
                        "width": {"type": "integer", "description": "Width of region"},
                        "height": {"type": "integer", "description": "Height of region"},
                    },
                },
                "format": {
                    "type": "string",
                    "enum": ["png", "jpeg"],
                    "default": "png",
                    "description": "Image format",
                },
            },
            "required": [],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        """Get the output schema for tool composition."""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "image_base64": {
                    "type": "string",
                    "description": "Base64-encoded screenshot image",
                },
                "format": {"type": "string"},
                "dimensions": {
                    "type": "object",
                    "properties": {
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                },
            },
        }

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute screenshot capture.

        Args:
            region: Optional region to capture
            format: Image format (png or jpeg)

        Returns:
            Result with base64-encoded screenshot
        """
        region = kwargs.get("region")
        image_format = kwargs.get("format", "png")

        try:
            # Take screenshot
            screenshot_b64 = await self._adapter.take_screenshot()

            if screenshot_b64:
                # Calculate approximate dimensions from base64 length
                # (rough estimate - actual dimensions require image parsing)
                estimated_size = len(screenshot_b64) * 3 // 4  # Base64 to bytes

                return json.dumps(
                    {
                        "success": True,
                        "action": "screenshot",
                        "image_base64": screenshot_b64,
                        "format": image_format,
                        "estimated_bytes": estimated_size,
                        "region": region,
                    }
                )
            else:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Screenshot capture failed - adapter not initialized",
                    }
                )

        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            return json.dumps({"success": False, "error": str(e)})

    def can_compose_with(self, other_tool: Any) -> bool:
        """
        Check if screenshot output can be used with another tool.

        Screenshots can be composed with analysis tools, OCR tools,
        or used as input for visual reasoning.
        """
        # Screenshot can be composed with any tool that accepts image input
        return True


class CUAScreenshotAnalyzeTool(CUABaseTool):
    """
    Tool for analyzing screenshot content.

    This tool captures a screenshot and provides analysis of UI elements.
    Useful for understanding the current state before taking actions.
    """

    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_screenshot_analyze",
            description=(
                "Capture and analyze the current screen. "
                "Returns a description of visible UI elements, text, and layout. "
                "Use this to understand what's on screen before taking action."
            ),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for this tool."""
        return {
            "type": "object",
            "properties": {
                "focus_area": {
                    "type": "string",
                    "description": "Optional area to focus analysis on (e.g., 'top menu', 'center')",
                },
                "extract_text": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to extract visible text",
                },
                "identify_buttons": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to identify clickable elements",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute screenshot capture and analysis.

        Args:
            focus_area: Area to focus on
            extract_text: Whether to extract text
            identify_buttons: Whether to identify buttons

        Returns:
            Analysis results
        """
        focus_area = kwargs.get("focus_area")
        extract_text = kwargs.get("extract_text", True)
        identify_buttons = kwargs.get("identify_buttons", True)

        try:
            # Take screenshot
            screenshot_b64 = await self._adapter.take_screenshot()

            if not screenshot_b64:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Screenshot capture failed",
                    }
                )

            # In a full implementation, this would:
            # 1. Use vision model to analyze the screenshot
            # 2. Extract text using OCR
            # 3. Identify UI elements
            # 4. Return structured analysis

            return json.dumps(
                {
                    "success": True,
                    "action": "screenshot_analyze",
                    "has_screenshot": True,
                    "focus_area": focus_area,
                    "analysis": {
                        "extract_text": extract_text,
                        "identify_buttons": identify_buttons,
                        "note": "Full analysis requires vision model integration",
                    },
                    "image_base64": screenshot_b64,
                }
            )

        except Exception as e:
            logger.error(f"Screenshot analyze error: {e}")
            return json.dumps({"success": False, "error": str(e)})
