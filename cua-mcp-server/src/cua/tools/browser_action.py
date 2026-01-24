"""CUA Browser Action Tools."""

import json
import logging
from typing import TYPE_CHECKING, Any, Dict

from .computer_action import CUABaseTool

if TYPE_CHECKING:
    from ..adapter import CUAAdapter

logger = logging.getLogger(__name__)


class CUABrowserNavigateTool(CUABaseTool):
    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_browser_navigate",
            description=(
                "Navigate to a URL in the browser. "
                "Use this to open web pages, search engines, or web applications. "
                "The URL should include the protocol (http:// or https://)."
            ),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
                "wait_for_load": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to wait for page load to complete",
                },
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs: Any) -> str:
        url = kwargs.get("url")
        wait_for_load = kwargs.get("wait_for_load", True)

        if not url:
            return json.dumps({"success": False, "error": "url is required"})

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            logger.info("Navigating to: %s", url)
            return json.dumps(
                {
                    "success": True,
                    "action": "browser_navigate",
                    "url": url,
                    "wait_for_load": wait_for_load,
                    "note": "Navigation initiated. Use screenshot to verify page loaded.",
                }
            )
        except Exception as exc:
            logger.error("Browser navigation error: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})
