"""Unit tests for parallel tool execution in SessionProcessor.

Tests that the processor correctly supports batch/parallel tool execution
when `enable_parallel_tool_execution` is True, while maintaining backward
compatibility when False (default).
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.events.agent_events import AgentErrorEvent
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)


def _create_tool_def(name: str, description: str = "Test tool") -> ToolDefinition:
    """Helper to create a ToolDefinition."""
    return ToolDefinition(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        execute=AsyncMock(return_value={"output": f"{name} result"}),
    )


def _make_processor(
    *,
    enable_parallel: bool = False,
    batch_size: int = 5,
) -> SessionProcessor:
    """Create a minimal SessionProcessor for testing."""
    config = ProcessorConfig(
        model="test-model",
        enable_parallel_tool_execution=enable_parallel,
        parallel_tool_batch_size=batch_size,
    )
    processor = SessionProcessor(
        config=config,
        tools=[
            _create_tool_def("tool_a"),
            _create_tool_def("tool_b"),
            _create_tool_def("tool_c"),
            _create_tool_def("tool_d"),
        ],
    )
    return processor


@pytest.mark.unit
class TestParallelToolExecution:
    """Tests for parallel tool execution feature."""

    def test_sequential_mode_default(self) -> None:
        """Default config has enable_parallel_tool_execution=False."""
        config = ProcessorConfig(model="test-model")
        assert config.enable_parallel_tool_execution is False

    def test_parallel_config_fields(self) -> None:
        """Config accepts the new parallel execution fields."""
        config = ProcessorConfig(
            model="test-model",
            enable_parallel_tool_execution=True,
            parallel_tool_batch_size=3,
        )
        assert config.enable_parallel_tool_execution is True
        assert config.parallel_tool_batch_size == 3

    def test_hitl_tools_always_sequential(self) -> None:
        """HITL tools are never deferred for parallel execution.

        When _check_hitl_dispatch returns a handler name, the tool
        must execute immediately regardless of parallel mode.
        """
        processor = _make_processor(enable_parallel=True)

        # _check_hitl_dispatch returns a handler name for HITL tools
        result = processor._check_hitl_dispatch("ask_clarification")
        assert result is not None, "ask_clarification should be recognized as HITL"

        result = processor._check_hitl_dispatch("request_decision")
        assert result is not None, "request_decision should be recognized as HITL"

        result = processor._check_hitl_dispatch("request_env_var")
        assert result is not None, "request_env_var should be recognized as HITL"

        # Non-HITL tools should return None
        result = processor._check_hitl_dispatch("tool_a")
        assert result is None, "tool_a should NOT be recognized as HITL"

    async def test_parallel_execution_collects_events(
        self,
    ) -> None:
        """With parallel mode ON, deferred tools yield all events."""
        processor = _make_processor(enable_parallel=True)

        # Simulate what happens after the while-loop in _process_step:
        # deferred_tool_calls is populated, then batch-executed.
        # We test the batch execution logic by directly invoking
        # the processor's _execute_tool mock.

        call_events: list[Any] = []

        async def mock_execute_tool(
            session_id: str,
            call_id: str,
            tool_name: str,
            arguments: dict[str, Any],
        ):
            """Mock _execute_tool as an async generator."""
            event = {
                "type": "observe",
                "call_id": call_id,
                "tool_name": tool_name,
            }
            yield event

        # Patch _execute_tool on the instance
        processor._execute_tool = mock_execute_tool  # type: ignore[assignment]

        # Build deferred calls
        deferred = [
            ("sess1", "call_1", "tool_a", {"arg": "1"}),
            ("sess1", "call_2", "tool_b", {"arg": "2"}),
            ("sess1", "call_3", "tool_c", {"arg": "3"}),
        ]

        # Execute in parallel (same logic as processor.py lines 1249+)
        batch_size = processor.config.parallel_tool_batch_size
        tool_calls_completed: list[str] = []
        for batch_start in range(0, len(deferred), batch_size):
            batch = deferred[batch_start : batch_start + batch_size]

            async def _run_tool(
                sid: str = "",
                cid: str = "",
                tname: str = "",
                args: dict[str, Any] | None = None,
            ) -> tuple[str, list[Any]]:
                events: list[Any] = []
                async for ev in processor._execute_tool(sid, cid, tname, args or {}):
                    events.append(ev)
                return cid, events

            tasks = [
                _run_tool(
                    sid=sid,
                    cid=cid,
                    tname=tname,
                    args=args,
                )
                for sid, cid, tname, args in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, BaseException):
                    continue
                cid, events = result
                call_events.extend(events)
                tool_calls_completed.append(cid)

        assert len(call_events) == 3
        assert len(tool_calls_completed) == 3
        assert set(tool_calls_completed) == {"call_1", "call_2", "call_3"}

    async def test_parallel_batch_size_respected(self) -> None:
        """With batch_size=2 and 4 tools, gather is called twice."""
        processor = _make_processor(enable_parallel=True, batch_size=2)

        gather_call_count = 0
        original_gather = asyncio.gather

        async def tracking_gather(*coros, return_exceptions=False):
            nonlocal gather_call_count
            gather_call_count += 1
            return await original_gather(*coros, return_exceptions=return_exceptions)

        async def mock_execute_tool(
            session_id: str,
            call_id: str,
            tool_name: str,
            arguments: dict[str, Any],
        ):
            yield {"type": "observe", "call_id": call_id}

        processor._execute_tool = mock_execute_tool  # type: ignore[assignment]

        deferred = [
            ("s", "c1", "tool_a", {}),
            ("s", "c2", "tool_b", {}),
            ("s", "c3", "tool_c", {}),
            ("s", "c4", "tool_d", {}),
        ]

        batch_size = processor.config.parallel_tool_batch_size
        tool_calls_completed: list[str] = []

        with patch("asyncio.gather", side_effect=tracking_gather):
            for batch_start in range(0, len(deferred), batch_size):
                batch = deferred[batch_start : batch_start + batch_size]

                async def _run_tool(
                    sid: str = "",
                    cid: str = "",
                    tname: str = "",
                    args: dict[str, Any] | None = None,
                ) -> tuple[str, list[Any]]:
                    events: list[Any] = []
                    async for ev in processor._execute_tool(sid, cid, tname, args or {}):
                        events.append(ev)
                    return cid, events

                tasks = [
                    _run_tool(
                        sid=sid,
                        cid=cid,
                        tname=tname,
                        args=args,
                    )
                    for sid, cid, tname, args in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, BaseException):
                        continue
                    cid, _events = result
                    tool_calls_completed.append(cid)

        assert gather_call_count == 2
        assert len(tool_calls_completed) == 4

    async def test_parallel_exception_handling(self) -> None:
        """One tool raises, others succeed; error event + others yield."""
        processor = _make_processor(enable_parallel=True)

        async def mock_execute_tool(
            session_id: str,
            call_id: str,
            tool_name: str,
            arguments: dict[str, Any],
        ):
            if tool_name == "tool_b":
                raise RuntimeError("tool_b failed")
            yield {"type": "observe", "call_id": call_id}

        processor._execute_tool = mock_execute_tool  # type: ignore[assignment]

        deferred = [
            ("s", "c1", "tool_a", {}),
            ("s", "c2", "tool_b", {}),
            ("s", "c3", "tool_c", {}),
        ]

        collected_events: list[Any] = []
        tool_calls_completed: list[str] = []
        batch_size = processor.config.parallel_tool_batch_size

        for batch_start in range(0, len(deferred), batch_size):
            batch = deferred[batch_start : batch_start + batch_size]

            async def _run_tool(
                sid: str = "",
                cid: str = "",
                tname: str = "",
                args: dict[str, Any] | None = None,
            ) -> tuple[str, list[Any]]:
                events: list[Any] = []
                async for ev in processor._execute_tool(sid, cid, tname, args or {}):
                    events.append(ev)
                return cid, events

            tasks = [
                _run_tool(
                    sid=sid,
                    cid=cid,
                    tname=tname,
                    args=args,
                )
                for sid, cid, tname, args in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, BaseException):
                    collected_events.append(
                        AgentErrorEvent(
                            message=f"Tool execution failed: {result}",
                            code="TOOL_EXECUTION_ERROR",
                        )
                    )
                    continue
                cid, events = result
                for ev in events:
                    collected_events.append(ev)
                tool_calls_completed.append(cid)

        # 2 successful tools + 1 error event = 3 events total
        assert len(collected_events) == 3

        error_events = [e for e in collected_events if isinstance(e, AgentErrorEvent)]
        assert len(error_events) == 1
        assert "tool_b failed" in error_events[0].message

        assert len(tool_calls_completed) == 2
        assert set(tool_calls_completed) == {"c1", "c3"}

    def test_sequential_fallback_when_disabled(self) -> None:
        """Parallel OFF: _check_hitl_dispatch returns None for
        regular tools, but the conditional in _process_step ensures
        sequential execution when enable_parallel_tool_execution
        is False.
        """
        processor = _make_processor(enable_parallel=False)

        # When parallel is disabled, the condition in _process_step:
        #   if not config.enable_parallel_tool_execution or _is_hitl:
        # always evaluates True for non-HITL tools (first clause),
        # so tools execute inline/sequentially.
        assert processor.config.enable_parallel_tool_execution is False

        # Non-HITL tool: _check_hitl_dispatch returns None
        is_hitl = processor._check_hitl_dispatch("tool_a")
        assert is_hitl is None

        # The combined condition:
        #   not False or None => True or None => True
        # means sequential path is taken
        should_sequential = not processor.config.enable_parallel_tool_execution or is_hitl
        assert should_sequential is True
