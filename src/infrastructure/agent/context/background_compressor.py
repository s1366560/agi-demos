"""
Background Compressor - Non-blocking async context compression.

Runs compression as a background task after each agent step,
storing results for the next LLM call to pick up.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient


from src.infrastructure.agent.context.compaction import ModelLimits
from src.infrastructure.agent.context.compression_engine import (
    CompressionResult,
    ContextCompressionEngine,
)
from src.infrastructure.agent.context.compression_state import CompressionLevel

logger = logging.getLogger(__name__)


class BackgroundCompressor:
    """Manages async background compression of conversation context.

    After each agent step, the processor can schedule compression
    without blocking the main request path. The compressed result
    is cached and applied to the next LLM call.
    """

    def __init__(self, engine: ContextCompressionEngine) -> None:
        self._engine = engine
        self._task: Optional[asyncio.Task] = None
        self._last_result: Optional[CompressionResult] = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_result(self) -> Optional[CompressionResult]:
        return self._last_result

    def schedule(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        model_limits: ModelLimits,
        llm_client: Optional[LLMClient] = None,
        level: Optional[CompressionLevel] = None,
    ) -> bool:
        """Schedule background compression.

        Returns True if a new task was scheduled, False if one is already running.
        """
        if self.is_running:
            logger.debug("Background compression already running, skipping")
            return False

        self._engine.state.mark_pending(level or self._engine.select_level(messages, model_limits))

        self._task = asyncio.create_task(
            self._run(system_prompt, messages, model_limits, llm_client, level)
        )
        logger.info("Background compression scheduled")
        return True

    async def _run(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        model_limits: ModelLimits,
        llm_client: Optional[LLMClient],
        level: Optional[CompressionLevel],
    ) -> None:
        """Execute compression in background."""
        try:
            result = await self._engine.compress(
                system_prompt=system_prompt,
                messages=messages,
                model_limits=model_limits,
                llm_client=llm_client,
                level=level,
            )
            self._last_result = result
            logger.info(
                f"Background compression complete: "
                f"level={result.level.value}, saved={result.tokens_saved} tokens"
            )
        except Exception as e:
            logger.error(f"Background compression failed: {e}", exc_info=True)
            self._engine.state.clear_pending()

    async def get_result(self, timeout: float = 5.0) -> Optional[CompressionResult]:
        """Wait for and return the background compression result.

        Args:
            timeout: Max seconds to wait for completion

        Returns:
            CompressionResult if available, None if timed out or no result
        """
        if self._task is None:
            return self._last_result

        if not self._task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=timeout)
            except asyncio.TimeoutError:
                logger.debug("Background compression still running after timeout")
                return None

        return self._last_result

    def cancel(self) -> None:
        """Cancel any running background compression."""
        if self._task and not self._task.done():
            self._task.cancel()
            self._engine.state.clear_pending()
            logger.info("Background compression cancelled")

    def reset(self) -> None:
        """Reset compressor state."""
        self.cancel()
        self._last_result = None
        self._engine.reset()
