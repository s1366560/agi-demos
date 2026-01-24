"""CUA adapter for MCP server."""

import asyncio
import importlib
import logging
from typing import Any, Dict, Optional

from .config import CUAConfig, CUAProviderType
from .tools import (
    CUABrowserNavigateTool,
    CUAClickTool,
    CUADragTool,
    CUAScreenshotTool,
    CUAScrollTool,
    CUATypeTool,
)

logger = logging.getLogger(__name__)


class CUAAdapter:
    """Adapter to manage CUA Computer and expose tools."""

    def __init__(self, config: CUAConfig):
        self._config = config
        self._computer = None
        self._initialized = False
        self._lock = asyncio.Lock()

    @property
    def config(self) -> CUAConfig:
        return self._config

    @property
    def is_enabled(self) -> bool:
        return self._config.enabled

    async def initialize(self) -> None:
        if not self._config.enabled:
            logger.warning("CUA is disabled, skipping initialization")
            return

        async with self._lock:
            if self._initialized:
                return

            logger.info("Initializing CUA with provider: %s", self._config.provider.value)

            if self._config.provider == CUAProviderType.LOCAL:
                self._computer = None
                self._initialized = True
                logger.info("CUA initialized in local mode")
                return

            self._computer = await self._create_computer()

            if hasattr(self._computer, "run"):
                logger.info("Starting CUA computer environment...")
                await self._computer.run()
                logger.info("CUA computer environment started")

            self._initialized = True

    async def _create_computer(self) -> Any:
        try:
            computer_module = importlib.import_module("computer")
            Computer = getattr(computer_module, "Computer")
        except Exception as exc:
            raise RuntimeError(
                "cua-computer is required for CUA MCP server. "
                "Install it or ensure vendor/cua/libs/python/computer is available."
            ) from exc

        provider_type = self._config.provider.value

        if self._config.provider == CUAProviderType.DOCKER:
            return Computer(
                os_type=self._config.os_type.value,
                provider_type="docker",
                display=self._config.docker.display,
                memory=self._config.docker.memory,
                cpu=self._config.docker.cpu,
            )
        if self._config.provider == CUAProviderType.LOCAL:
            return Computer(
                os_type=self._config.os_type.value,
                use_host_computer_server=True,
            )
        if self._config.provider == CUAProviderType.CLOUD:
            return Computer(
                os_type=self._config.os_type.value,
                provider_type="cloud",
            )

        raise ValueError(f"Unknown provider type: {provider_type}")

    async def shutdown(self) -> None:
        async with self._lock:
            if not self._initialized:
                return

            try:
                if self._computer and hasattr(self._computer, "stop"):
                    await self._computer.stop()
            finally:
                self._computer = None
                self._initialized = False

    def create_tools(self) -> Dict[str, Any]:
        if not self._config.enabled:
            return {}

        return {
            "cua_click": CUAClickTool(self),
            "cua_type": CUATypeTool(self),
            "cua_scroll": CUAScrollTool(self),
            "cua_drag": CUADragTool(self),
            "cua_browser_navigate": CUABrowserNavigateTool(self),
            "cua_screenshot": CUAScreenshotTool(self),
        }

    async def take_screenshot(self) -> Optional[str]:
        if not self._initialized:
            logger.info("CUA adapter not initialized, initializing now...")
            await self.initialize()

        if not self._initialized:
            logger.error("CUA adapter initialization failed")
            return None

        try:
            if self._config.provider == CUAProviderType.LOCAL:
                import base64

                try:
                    mss_module = importlib.import_module("mss")
                    mss_tools = importlib.import_module("mss.tools")
                    to_png = getattr(mss_tools, "to_png")
                except Exception as exc:
                    raise RuntimeError("mss is required for local screenshots") from exc

                with mss_module.mss() as sct:
                    monitor = sct.monitors[1]
                    screenshot = sct.grab(monitor)
                    png_bytes = to_png(screenshot.rgb, screenshot.size)
                    return base64.b64encode(png_bytes).decode("utf-8")

            if self._computer:
                if hasattr(self._computer, "screenshot"):
                    return await self._computer.screenshot()
                if hasattr(self._computer, "interface") and hasattr(
                    self._computer.interface, "screenshot"
                ):
                    return await self._computer.interface.screenshot()
        except Exception as exc:
            logger.error("Failed to take screenshot: %s", exc)

        return None

    async def click(self, x: int, y: int) -> bool:
        if not self._initialized or not self._computer:
            return False

        try:
            if hasattr(self._computer, "click"):
                await self._computer.click(x=x, y=y)
                return True
            if hasattr(self._computer, "interface") and hasattr(self._computer.interface, "click"):
                await self._computer.interface.click(x=x, y=y)
                return True
        except Exception as exc:
            logger.error("Failed to click at (%s, %s): %s", x, y, exc)

        return False

    async def type_text(self, text: str) -> bool:
        if not self._initialized or not self._computer:
            return False

        try:
            if hasattr(self._computer, "type"):
                await self._computer.type(text=text)
                return True
            if hasattr(self._computer, "interface") and hasattr(self._computer.interface, "type"):
                await self._computer.interface.type(text=text)
                return True
        except Exception as exc:
            logger.error("Failed to type text: %s", exc)

        return False

    async def scroll(self, x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> bool:
        if not self._initialized or not self._computer:
            return False

        try:
            if hasattr(self._computer, "scroll"):
                await self._computer.scroll(x=x, y=y, scroll_x=delta_x, scroll_y=delta_y)
                return True
        except Exception as exc:
            logger.error("Failed to scroll: %s", exc)

        return False

    async def drag(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        if not self._initialized or not self._computer:
            return False

        try:
            if hasattr(self._computer, "drag"):
                await self._computer.drag(x1=x1, y1=y1, x2=x2, y2=y2)
                return True
        except Exception as exc:
            logger.error("Failed to drag: %s", exc)

        return False
