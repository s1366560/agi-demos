"""
CUA Adapter - Core bridge between CUA and MemStack.

This module provides the main adapter class that connects CUA's ComputerAgent
with MemStack's ReActAgent system.
"""

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from .config import CUAConfig, CUAProviderType

logger = logging.getLogger(__name__)


class CUAAdapter:
    """
    Main adapter class for CUA integration with MemStack.

    This adapter:
    - Creates and manages CUA Computer instances
    - Creates CUA tools for MemStack's tool system
    - Manages CUA ComputerAgent lifecycle
    - Bridges CUA callbacks to MemStack SSE events

    Usage:
        config = CUAConfig.from_env()
        adapter = CUAAdapter(config)

        # Create tools for L1 integration
        tools = adapter.create_tools()

        # Create subagent for L3 integration
        subagent = adapter.create_subagent()

        # Execute with full agent
        async for event in adapter.execute("Click the login button"):
            yield event
    """

    def __init__(self, config: CUAConfig):
        """
        Initialize CUA Adapter.

        Args:
            config: CUA configuration
        """
        self._config = config
        self._computer = None
        self._computer_agent = None
        self._initialized = False
        self._lock = asyncio.Lock()

    @property
    def config(self) -> CUAConfig:
        """Get current configuration."""
        return self._config

    @property
    def is_enabled(self) -> bool:
        """Check if CUA is enabled."""
        return self._config.enabled

    @property
    def is_initialized(self) -> bool:
        """Check if adapter is initialized."""
        return self._initialized

    async def initialize(self) -> None:
        """
        Initialize CUA components.

        This method:
        1. Creates Computer instance based on provider
        2. Starts the computer if needed (Docker container)
        3. Sets up the ComputerAgent
        """
        if not self._config.enabled:
            logger.warning("CUA is disabled, skipping initialization")
            return

        async with self._lock:
            if self._initialized:
                return

            logger.info(f"Initializing CUA with provider: {self._config.provider.value}")

            try:
                # Import CUA components
                # For LOCAL provider, use native screenshot without CUA Computer
                if self._config.provider == CUAProviderType.LOCAL:
                    logger.info("Using native local mode for CUA (no VM/container)")
                    self._computer = None  # No Computer instance needed for local mode
                    self._initialized = True
                    logger.info("CUA initialized successfully in local mode")
                    return

                # These are from vendor/cua for DOCKER/CLOUD providers
                self._computer = await self._create_computer()

                # Start the computer environment (Docker container, etc.)
                if hasattr(self._computer, "run"):
                    logger.info("Starting CUA computer environment...")
                    await self._computer.run()
                    logger.info("CUA computer environment started")

                self._initialized = True
                logger.info("CUA initialized successfully")

            except ImportError as e:
                logger.error(f"Failed to import CUA components: {e}")
                logger.error("Make sure vendor/cua is properly installed")
                raise RuntimeError(f"CUA import failed: {e}") from e

            except Exception as e:
                logger.error(f"Failed to initialize CUA: {e}")
                raise

    async def _create_computer(self) -> Any:
        """
        Create Computer instance based on provider type.

        Returns:
            Computer instance from CUA
        """
        # Import from installed cua-computer package
        from computer import Computer

        provider_type = self._config.provider.value

        if self._config.provider == CUAProviderType.DOCKER:
            # Docker provider configuration
            computer = Computer(
                os_type=self._config.os_type.value,
                provider_type="docker",
                display=self._config.docker.display,
                memory=self._config.docker.memory,
                cpu=self._config.docker.cpu,
            )
        elif self._config.provider == CUAProviderType.LOCAL:
            # Local provider - direct control of host machine
            # use_host_computer_server=True means it targets localhost instead of starting a VM
            computer = Computer(
                os_type=self._config.os_type.value,
                use_host_computer_server=True,
            )
        elif self._config.provider == CUAProviderType.CLOUD:
            # Cloud provider - remote VM
            computer = Computer(
                os_type=self._config.os_type.value,
                provider_type="cloud",
            )
        else:
            raise ValueError(f"Unknown provider type: {provider_type}")

        logger.info(f"Created Computer with provider: {provider_type}")
        return computer

    async def shutdown(self) -> None:
        """
        Shutdown CUA components and cleanup resources.
        """
        async with self._lock:
            if not self._initialized:
                return

            logger.info("Shutting down CUA adapter...")

            try:
                # Stop computer if it has a stop method
                if self._computer and hasattr(self._computer, "stop"):
                    await self._computer.stop()

                self._computer = None
                self._computer_agent = None
                self._initialized = False
                logger.info("CUA adapter shutdown complete")

            except Exception as e:
                logger.error(f"Error during CUA shutdown: {e}")
                raise

    def create_tools(self) -> Dict[str, Any]:
        """
        Create CUA tools for L1 integration.

        Returns:
            Dictionary of tool name -> tool instance

        Raises:
            RuntimeError: If adapter is not initialized
        """
        if not self._config.enabled:
            return {}

        # Import tool classes (will be implemented in tools/)
        from .tools import (
            CUABrowserNavigateTool,
            CUAClickTool,
            CUADragTool,
            CUAScreenshotTool,
            CUAScrollTool,
            CUATypeTool,
        )

        tools = {}

        # Always add screenshot tool
        if self._config.permissions.allow_screenshot:
            tools["cua_screenshot"] = CUAScreenshotTool(self)

        # Mouse operations
        if self._config.permissions.allow_mouse_click:
            tools["cua_click"] = CUAClickTool(self)
            tools["cua_drag"] = CUADragTool(self)
            tools["cua_scroll"] = CUAScrollTool(self)

        # Keyboard operations
        if self._config.permissions.allow_keyboard_input:
            tools["cua_type"] = CUATypeTool(self)

        # Browser operations
        if self._config.permissions.allow_browser_navigation:
            tools["cua_browser_navigate"] = CUABrowserNavigateTool(self)

        logger.info(f"Created {len(tools)} CUA tools: {list(tools.keys())}")
        return tools

    def create_skills(self) -> List[Any]:
        """
        Create CUA skills for L2 integration.

        Returns:
            List of Skill instances

        Raises:
            RuntimeError: If skill system is disabled
        """
        if not self._config.skill.enabled:
            return []

        from .skill_manager import CUASkillManager

        return CUASkillManager.get_builtin_skills(self._config)

    def create_subagent(self) -> Optional[Any]:
        """
        Create CUA subagent for L3 integration.

        Returns:
            CUASubAgent instance or None if disabled

        Raises:
            RuntimeError: If adapter is not initialized
        """
        if not self._config.subagent.enabled:
            return None

        from .subagent import CUASubAgent

        return CUASubAgent(self._config, self)

    async def execute(
        self,
        instruction: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute CUA agent with the given instruction.

        This method creates a full CUA ComputerAgent and executes it,
        streaming events back to the caller.

        Args:
            instruction: User instruction to execute
            context: Optional context (project_id, user_id, etc.)

        Yields:
            Event dictionaries for SSE streaming
        """
        if not self._config.enabled:
            yield {
                "type": "error",
                "data": {"message": "CUA is disabled", "code": "CUA_DISABLED"},
            }
            return

        if not self._initialized:
            await self.initialize()

        context = context or {}

        try:
            # Import CUA agent
            try:
                from agent import ComputerAgent
            except ImportError:
                import sys

                sys.path.insert(
                    0,
                    "/Users/tiejun.sun/Documents/github/vip-memory/vendor/cua/libs/python/agent",
                )
                from agent import ComputerAgent

            # Create callback adapter for SSE bridge
            from .callbacks import MemStackCallbackAdapter

            event_queue: asyncio.Queue = asyncio.Queue()
            callback = MemStackCallbackAdapter(event_queue)

            # Create ComputerAgent
            agent = ComputerAgent(
                model=self._config.model,
                tools=[self._computer] if self._computer else [],
                callbacks=[callback],
                max_retries=self._config.max_retries,
                screenshot_delay=self._config.screenshot_delay,
                telemetry_enabled=self._config.telemetry_enabled,
                api_key=self._config.api_key,
                api_base=self._config.api_base,
            )

            # Start execution event
            yield {
                "type": "cua_execution_start",
                "data": {
                    "instruction": instruction,
                    "model": self._config.model,
                    "provider": self._config.provider.value,
                },
            }

            # Run agent and stream events
            async def run_agent():
                try:
                    async for response in agent.run([{"role": "user", "content": instruction}]):
                        await event_queue.put({"type": "agent_response", "data": response})
                except Exception as e:
                    await event_queue.put({"type": "error", "data": {"message": str(e)}})
                finally:
                    await event_queue.put(None)  # Signal completion

            # Start agent in background
            agent_task = asyncio.create_task(run_agent())

            # Yield events from queue
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield event

            # Wait for agent task to complete
            await agent_task

            # Completion event
            yield {
                "type": "cua_execution_complete",
                "data": {"success": True},
            }

        except Exception as e:
            logger.error(f"CUA execution error: {e}", exc_info=True)
            yield {
                "type": "error",
                "data": {
                    "message": str(e),
                    "code": "CUA_EXECUTION_ERROR",
                },
            }

    async def take_screenshot(self) -> Optional[str]:
        """
        Take a screenshot from the computer.

        Returns:
            Base64-encoded screenshot image or None if failed
        """
        # Auto-initialize if not yet initialized
        if not self._initialized:
            logger.info("CUA adapter not initialized, initializing now...")
            await self.initialize()

        if not self._initialized:
            logger.error("CUA adapter initialization failed")
            return None

        try:
            # For LOCAL provider, use mss for native screenshot
            if self._config.provider == CUAProviderType.LOCAL:
                import base64

                import mss

                with mss.mss() as sct:
                    # Capture the primary monitor
                    monitor = sct.monitors[1]  # Primary monitor
                    screenshot = sct.grab(monitor)
                    # Convert to PNG bytes
                    from mss.tools import to_png

                    png_bytes = to_png(screenshot.rgb, screenshot.size)
                    # Encode to base64
                    return base64.b64encode(png_bytes).decode("utf-8")

            # For DOCKER/CLOUD providers, use CUA Computer
            if self._computer:
                if hasattr(self._computer, "screenshot"):
                    return await self._computer.screenshot()
                elif hasattr(self._computer, "interface") and hasattr(
                    self._computer.interface, "screenshot"
                ):
                    return await self._computer.interface.screenshot()
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")

        return None

    async def click(self, x: int, y: int) -> bool:
        """
        Perform a click at the given coordinates.

        Args:
            x: X coordinate
            y: Y coordinate

        Returns:
            True if successful
        """
        if not self._initialized or not self._computer:
            return False

        try:
            if hasattr(self._computer, "click"):
                await self._computer.click(x=x, y=y)
                return True
            elif hasattr(self._computer, "interface") and hasattr(
                self._computer.interface, "click"
            ):
                await self._computer.interface.click(x=x, y=y)
                return True
        except Exception as e:
            logger.error(f"Failed to click at ({x}, {y}): {e}")

        return False

    async def type_text(self, text: str) -> bool:
        """
        Type text using the keyboard.

        Args:
            text: Text to type

        Returns:
            True if successful
        """
        if not self._initialized or not self._computer:
            return False

        try:
            if hasattr(self._computer, "type"):
                await self._computer.type(text=text)
                return True
            elif hasattr(self._computer, "interface") and hasattr(self._computer.interface, "type"):
                await self._computer.interface.type(text=text)
                return True
        except Exception as e:
            logger.error(f"Failed to type text: {e}")

        return False

    async def scroll(self, x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> bool:
        """
        Scroll at the given coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            delta_x: Horizontal scroll amount
            delta_y: Vertical scroll amount

        Returns:
            True if successful
        """
        if not self._initialized or not self._computer:
            return False

        try:
            if hasattr(self._computer, "scroll"):
                await self._computer.scroll(x=x, y=y, scroll_x=delta_x, scroll_y=delta_y)
                return True
        except Exception as e:
            logger.error(f"Failed to scroll: {e}")

        return False

    def get_status(self) -> Dict[str, Any]:
        """
        Get adapter status information.

        Returns:
            Status dictionary
        """
        return {
            "enabled": self._config.enabled,
            "initialized": self._initialized,
            "provider": self._config.provider.value,
            "model": self._config.model,
            "permissions": {
                "screenshot": self._config.permissions.allow_screenshot,
                "click": self._config.permissions.allow_mouse_click,
                "type": self._config.permissions.allow_keyboard_input,
            },
        }
