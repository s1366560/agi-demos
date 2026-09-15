"""Unit tests for deterministic processor execution summaries."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)


def create_todoread_tool(tasks: list[dict[str, Any]]) -> ToolDefinition:
    """Build a simple todoread tool returning the provided tasks."""

    async def execute(*, session_id: str) -> dict[str, Any]:
        assert session_id
        return {"todos": tasks}

    return ToolDefinition(
        name="todoread",
        description="Read tasks",
        parameters={"type": "object", "properties": {}, "required": []},
        execute=execute,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_execution_summary_includes_task_and_usage_counts() -> None:
    processor = SessionProcessor(
        config=ProcessorConfig(model="test-model"),
        tools=[
            create_todoread_tool(
                [
                    {"id": "task-1", "status": "completed"},
                    {"id": "task-2", "status": "cancelled"},
                    {"id": "task-3", "status": "failed"},
                ]
            )
        ],
    )
    processor._artifact_count = 2
    processor._step_count = 4
    processor.cost_tracker.call_count = 3
    processor.cost_tracker.total_cost = Decimal("0.123456")
    processor.cost_tracker.total_tokens.input = 10
    processor.cost_tracker.total_tokens.output = 5
    processor.cost_tracker.total_tokens.reasoning = 2

    summary = await processor._build_execution_summary("session-1")

    assert summary["step_count"] == 4
    assert summary["artifact_count"] == 2
    assert summary["call_count"] == 3
    assert summary["total_cost_formatted"] == "$0.123456"
    assert summary["total_tokens"]["total"] == 17
    assert summary["tasks"] == {
        "total": 3,
        "completed": 1,
        "pending": 0,
        "in_progress": 0,
        "failed": 1,
        "cancelled": 1,
        "other": 0,
        "remaining": 1,
    }


@pytest.mark.unit
async def test_execution_summary_omits_unobserved_usage_instead_of_reporting_zero() -> None:
    processor = SessionProcessor(config=ProcessorConfig(model="test-model"), tools=[])
    processor._step_count = 2
    summary = await processor._build_execution_summary("session-unknown")
    assert summary["step_count"] == 2
    assert summary["call_count"] == 0
    assert "total_tokens" not in summary
    assert "total_cost" not in summary
    assert "total_cost_formatted" not in summary


@pytest.mark.unit
async def test_execution_summary_preserves_explicitly_observed_zero_usage() -> None:
    processor = SessionProcessor(config=ProcessorConfig(model="test-model"), tools=[])
    processor.cost_tracker.calculate(
        usage={"input_tokens": 0, "output_tokens": 0}, model_name="test-model"
    )
    summary = await processor._build_execution_summary("session-zero")
    assert summary["call_count"] == 1
    assert summary["total_tokens"]["input"] == 0
    assert summary["total_cost"] == 0
