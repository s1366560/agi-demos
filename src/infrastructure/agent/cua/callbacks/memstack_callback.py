"""
MemStack Callback Adapter for CUA.

Bridges CUA's AsyncCallbackHandler to MemStack's SSE event system.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class MemStackCallbackAdapter:
    """
    Adapter that converts CUA callbacks to MemStack SSE events.

    This class implements the CUA AsyncCallbackHandler interface and converts
    all callback events to MemStack-compatible SSE event format.

    Usage:
        event_queue = asyncio.Queue()
        callback = MemStackCallbackAdapter(event_queue)

        agent = ComputerAgent(callbacks=[callback])

        # Events will be pushed to event_queue
        async for event in agent.run(...):
            ...
    """

    def __init__(
        self,
        event_queue: asyncio.Queue,
        include_screenshots: bool = True,
        max_screenshot_size: Optional[int] = None,
    ):
        """
        Initialize callback adapter.

        Args:
            event_queue: Queue to push SSE events to
            include_screenshots: Whether to include screenshots in events
            max_screenshot_size: Max screenshot size in bytes (None for unlimited)
        """
        self._event_queue = event_queue
        self._include_screenshots = include_screenshots
        self._max_screenshot_size = max_screenshot_size
        self._run_start_time: Optional[datetime] = None
        self._step_count = 0
        self._total_tokens = 0
        self._total_cost = 0.0

    def _create_event(
        self, event_type: str, data: Dict[str, Any], timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a standardized event dictionary."""
        return {
            "type": event_type,
            "data": data,
            "timestamp": timestamp or datetime.utcnow().isoformat(),
        }

    async def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an event to the queue."""
        event = self._create_event(event_type, data)
        await self._event_queue.put(event)
        logger.debug(f"Emitted CUA event: {event_type}")

    # === Run Lifecycle Callbacks ===

    async def on_run_start(self, kwargs: Dict[str, Any], old_items: List[Dict[str, Any]]) -> None:
        """Called at the start of an agent run loop."""
        self._run_start_time = datetime.utcnow()
        self._step_count = 0
        self._total_tokens = 0
        self._total_cost = 0.0

        await self._emit(
            "cua_run_start",
            {
                "model": kwargs.get("model", "unknown"),
                "message_count": len(old_items),
            },
        )

    async def on_run_end(
        self,
        kwargs: Dict[str, Any],
        old_items: List[Dict[str, Any]],
        new_items: List[Dict[str, Any]],
    ) -> None:
        """Called at the end of an agent run loop."""
        duration_ms = 0
        if self._run_start_time:
            duration_ms = int((datetime.utcnow() - self._run_start_time).total_seconds() * 1000)

        await self._emit(
            "cua_run_end",
            {
                "duration_ms": duration_ms,
                "steps": self._step_count,
                "total_tokens": self._total_tokens,
                "total_cost": self._total_cost,
                "new_items_count": len(new_items),
            },
        )

    async def on_run_continue(
        self,
        kwargs: Dict[str, Any],
        old_items: List[Dict[str, Any]],
        new_items: List[Dict[str, Any]],
    ) -> bool:
        """Called during agent run loop to determine if execution should continue."""
        # Always continue - budget management handled elsewhere
        return True

    # === LLM Lifecycle Callbacks ===

    async def on_llm_start(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Called before messages are sent to the agent loop."""
        self._step_count += 1
        await self._emit(
            "thought",
            {
                "content": f"Processing step {self._step_count}...",
                "thought_level": "cua_step",
            },
        )
        return messages

    async def on_llm_end(self, output: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Called after the agent loop returns output."""
        return output

    # === Computer Call Callbacks ===

    async def on_computer_call_start(self, item: Dict[str, Any]) -> None:
        """Called when a computer call is about to start."""
        action = item.get("action", {})
        action_type = action.get("type", "unknown")

        # Map to MemStack ACT event
        await self._emit(
            "act",
            {
                "tool_name": f"cua_{action_type}",
                "tool_input": action,
                "call_id": item.get("call_id", ""),
                "status": "running",
            },
        )

    async def on_computer_call_end(
        self, item: Dict[str, Any], result: List[Dict[str, Any]]
    ) -> None:
        """Called when a computer call has completed."""
        action = item.get("action", {})
        action_type = action.get("type", "unknown")

        # Extract screenshot if present
        screenshot_url = None
        for r in result:
            if r.get("type") == "computer_call_output":
                output = r.get("output", {})
                if output.get("type") == "input_image":
                    screenshot_url = output.get("image_url", "")
                    break

        # Map to MemStack OBSERVE event
        await self._emit(
            "observe",
            {
                "tool_name": f"cua_{action_type}",
                "call_id": item.get("call_id", ""),
                "result": result,
                "observation": f"Completed {action_type} action",
                "status": "completed",
                "has_screenshot": screenshot_url is not None,
            },
        )

    # === Function Call Callbacks ===

    async def on_function_call_start(self, item: Dict[str, Any]) -> None:
        """Called when a function call is about to start."""
        function_name = item.get("name", "unknown")

        await self._emit(
            "act",
            {
                "tool_name": function_name,
                "tool_input": item.get("arguments", {}),
                "call_id": item.get("call_id", ""),
                "status": "running",
            },
        )

    async def on_function_call_end(
        self, item: Dict[str, Any], result: List[Dict[str, Any]]
    ) -> None:
        """Called when a function call has completed."""
        function_name = item.get("name", "unknown")

        # Extract output from result
        output = None
        for r in result:
            if r.get("type") == "function_call_output":
                output = r.get("output")
                break

        await self._emit(
            "observe",
            {
                "tool_name": function_name,
                "call_id": item.get("call_id", ""),
                "result": output,
                "status": "completed",
            },
        )

    # === Text Callback ===

    async def on_text(self, item: Dict[str, Any]) -> None:
        """Called when a text message is encountered."""
        content = item.get("content", [])

        # Extract text from content items
        text_parts = []
        for content_item in content if isinstance(content, list) else [content]:
            if isinstance(content_item, dict) and content_item.get("type") == "text":
                text_parts.append(content_item.get("text", ""))
            elif isinstance(content_item, str):
                text_parts.append(content_item)

        if text_parts:
            await self._emit(
                "text_delta",
                {
                    "delta": "\n".join(text_parts),
                },
            )

    # === API Callbacks ===

    async def on_api_start(self, kwargs: Dict[str, Any]) -> None:
        """Called when an API call is about to start."""
        # Internal tracking, no event emitted
        logger.debug(f"CUA API call starting: {kwargs.get('model', 'unknown')}")

    async def on_api_end(self, kwargs: Dict[str, Any], result: Any) -> None:
        """Called when an API call has completed."""
        # Internal tracking, no event emitted
        logger.debug("CUA API call completed")

    # === Usage Callback ===

    async def on_usage(self, usage: Dict[str, Any]) -> None:
        """Called when usage information is received."""
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        self._total_tokens += total_tokens

        # Estimate cost (rough estimate, actual cost depends on model)
        # Using approximate GPT-4 pricing as reference
        estimated_cost = (prompt_tokens * 0.00003) + (completion_tokens * 0.00006)
        self._total_cost += estimated_cost

        await self._emit(
            "cost_update",
            {
                "tokens": {
                    "prompt": prompt_tokens,
                    "completion": completion_tokens,
                    "total": total_tokens,
                },
                "cost": estimated_cost,
                "cumulative_tokens": self._total_tokens,
                "cumulative_cost": self._total_cost,
            },
        )

    # === Screenshot Callback ===

    async def on_screenshot(self, screenshot: Union[str, bytes], name: str = "screenshot") -> None:
        """Called when a screenshot is taken."""
        if not self._include_screenshots:
            await self._emit(
                "screenshot",
                {
                    "name": name,
                    "available": True,
                    "included": False,
                },
            )
            return

        # Convert bytes to base64 string if needed
        if isinstance(screenshot, bytes):
            import base64

            screenshot = base64.b64encode(screenshot).decode("utf-8")

        # Check size limit
        if self._max_screenshot_size and len(screenshot) > self._max_screenshot_size:
            await self._emit(
                "screenshot",
                {
                    "name": name,
                    "available": True,
                    "included": False,
                    "reason": "exceeds_size_limit",
                },
            )
            return

        await self._emit(
            "screenshot",
            {
                "name": name,
                "image_base64": screenshot,
                "available": True,
                "included": True,
            },
        )

    # === Responses Callback ===

    async def on_responses(self, kwargs: Dict[str, Any], responses: Dict[str, Any]) -> None:
        """Called when responses are received."""
        output = responses.get("output", [])

        # Count different types of items
        message_count = 0
        computer_call_count = 0
        function_call_count = 0

        for item in output:
            item_type = item.get("type")
            if item_type == "message":
                message_count += 1
            elif item_type == "computer_call":
                computer_call_count += 1
            elif item_type == "function_call":
                function_call_count += 1

        await self._emit(
            "cua_response",
            {
                "messages": message_count,
                "computer_calls": computer_call_count,
                "function_calls": function_call_count,
                "total_items": len(output),
            },
        )
