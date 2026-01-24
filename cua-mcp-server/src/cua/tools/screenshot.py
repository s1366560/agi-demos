"""CUA Screenshot Tool."""

import json
import logging
from typing import TYPE_CHECKING, Any, Dict

from .computer_action import CUABaseTool

if TYPE_CHECKING:
    from ..adapter import CUAAdapter

logger = logging.getLogger(__name__)


class CUAScreenshotTool(CUABaseTool):
    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_screenshot",
            description=(
                "Capture a screenshot of the current screen. "
                "Use this to see the current state of the UI."
            ),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "description": "Optional region to capture",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
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

    async def execute(self, **kwargs: Any) -> str:
        region = kwargs.get("region")
        image_format = kwargs.get("format", "png")

        try:
            screenshot_b64 = await self._adapter.take_screenshot()
            if screenshot_b64:
                estimated_size = len(screenshot_b64) * 3 // 4
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
            return json.dumps(
                {
                    "success": False,
                    "error": "Screenshot capture failed - adapter not initialized",
                }
            )
        except Exception as exc:
            logger.error("Screenshot error: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})
