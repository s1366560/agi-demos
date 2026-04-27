"""Unit tests for the cron agent tool."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.cron_tool import cron_tool

pytestmark = pytest.mark.unit


def _make_ctx(**overrides: Any) -> ToolContext:
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
        "project_id": "project-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


async def test_update_returns_invalid_schedule_error_before_session_access() -> None:
    result = await cron_tool.execute(
        _make_ctx(),
        action="update",
        job_id="job-1",
        patch={
            "schedule": {
                "kind": "every",
                "config": {"hours": 0, "minutes": 0, "seconds": 0},
            }
        },
    )

    payload = json.loads(result.output)

    assert result.is_error is True
    assert payload["error"].startswith("Invalid schedule:")
    assert "every schedule requires interval_seconds" in payload["error"]
