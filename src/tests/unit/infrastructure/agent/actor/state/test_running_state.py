"""Unit tests for Redis-backed agent running/finished state."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.actor.state import running_state


@pytest.mark.asyncio
async def test_clear_agent_running_records_finished_marker_from_running_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"msg-1")
    redis.delete = AsyncMock()
    redis.setex = AsyncMock()
    monkeypatch.setattr(
        running_state,
        "get_redis_client",
        AsyncMock(return_value=redis),
    )

    await running_state.clear_agent_running("conv-1")

    redis.get.assert_awaited_once_with("agent:running:conv-1")
    redis.delete.assert_awaited_once_with("agent:running:conv-1")
    redis.setex.assert_awaited_once_with(
        "agent:finished:conv-1",
        running_state.AGENT_FINISHED_TTL_SECONDS,
        "msg-1",
    )


@pytest.mark.asyncio
async def test_clear_agent_running_records_finished_marker_from_explicit_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock()
    redis.setex = AsyncMock()
    monkeypatch.setattr(
        running_state,
        "get_redis_client",
        AsyncMock(return_value=redis),
    )

    await running_state.clear_agent_running("conv-1", "msg-explicit")

    redis.setex.assert_awaited_once_with(
        "agent:finished:conv-1",
        running_state.AGENT_FINISHED_TTL_SECONDS,
        "msg-explicit",
    )


@pytest.mark.asyncio
async def test_mark_agent_finished_is_noop_without_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_redis = AsyncMock()
    monkeypatch.setattr(running_state, "get_redis_client", get_redis)

    await running_state.mark_agent_finished("conv-1", "")

    get_redis.assert_not_awaited()
