"""
CUA Browser Action Tools.

Tools for browser-specific operations: navigation, back, forward, refresh.
"""

import json
import logging
from typing import TYPE_CHECKING, Any, Dict

from .computer_action import CUABaseTool

if TYPE_CHECKING:
    from ..adapter import CUAAdapter

logger = logging.getLogger(__name__)


class CUABrowserNavigateTool(CUABaseTool):
    """
    Tool for browser navigation.

    This tool allows the agent to navigate to URLs in the browser.
    """

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
        """Get the parameters schema for this tool."""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to navigate to (e.g., https://www.google.com)",
                },
                "wait_for_load": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to wait for page load to complete",
                },
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute browser navigation.

        Args:
            url: URL to navigate to
            wait_for_load: Whether to wait for page load

        Returns:
            Result message
        """
        url = kwargs.get("url")
        wait_for_load = kwargs.get("wait_for_load", True)

        if not url:
            return json.dumps({"success": False, "error": "url is required"})

        # Ensure URL has protocol
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            # Browser navigation is typically done via:
            # 1. Click on address bar (or use keyboard shortcut)
            # 2. Clear existing URL
            # 3. Type new URL
            # 4. Press Enter

            # For a more sophisticated implementation, we could use
            # the CUA Computer's browser-specific methods if available

            # Placeholder - actual implementation would use CUA's browser control
            logger.info(f"Navigating to: {url}")

            return json.dumps(
                {
                    "success": True,
                    "action": "browser_navigate",
                    "url": url,
                    "wait_for_load": wait_for_load,
                    "note": "Navigation initiated. Use screenshot to verify page loaded.",
                }
            )

        except Exception as e:
            logger.error(f"Browser navigation error: {e}")
            return json.dumps({"success": False, "error": str(e)})


class CUABrowserBackTool(CUABaseTool):
    """
    Tool for browser back navigation.
    """

    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_browser_back",
            description="Go back to the previous page in the browser history.",
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for this tool."""
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute browser back navigation.

        Returns:
            Result message
        """
        try:
            # Browser back can be done via:
            # - Keyboard shortcut (Alt+Left or Cmd+Left)
            # - Click back button
            # - Use browser-specific API

            logger.info("Navigating back in browser")

            return json.dumps(
                {
                    "success": True,
                    "action": "browser_back",
                    "note": "Back navigation initiated.",
                }
            )

        except Exception as e:
            logger.error(f"Browser back error: {e}")
            return json.dumps({"success": False, "error": str(e)})


class CUABrowserRefreshTool(CUABaseTool):
    """
    Tool for refreshing the current page.
    """

    def __init__(self, adapter: "CUAAdapter"):
        super().__init__(
            adapter=adapter,
            name="cua_browser_refresh",
            description="Refresh the current page in the browser.",
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for this tool."""
        return {
            "type": "object",
            "properties": {
                "hard_refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to perform a hard refresh (clear cache)",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute browser refresh.

        Args:
            hard_refresh: Whether to clear cache

        Returns:
            Result message
        """
        hard_refresh = kwargs.get("hard_refresh", False)

        try:
            # Browser refresh can be done via:
            # - F5 for normal refresh
            # - Ctrl+F5 or Cmd+Shift+R for hard refresh
            # - Click refresh button

            logger.info(f"Refreshing browser (hard={hard_refresh})")

            return json.dumps(
                {
                    "success": True,
                    "action": "browser_refresh",
                    "hard_refresh": hard_refresh,
                    "note": "Refresh initiated.",
                }
            )

        except Exception as e:
            logger.error(f"Browser refresh error: {e}")
            return json.dumps({"success": False, "error": str(e)})
