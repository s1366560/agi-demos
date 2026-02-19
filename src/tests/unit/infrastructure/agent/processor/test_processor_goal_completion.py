"""Unit tests for SessionProcessor goal-completion evaluation."""

import json
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.processor import ProcessorConfig, SessionProcessor, ToolDefinition


def create_todoread_tool(tasks):
    """Create a todoread ToolDefinition returning fixed tasks."""

    async def execute(**kwargs):
        return json.dumps(
            {
                "session_id": kwargs.get("session_id", "session-test"),
                "total_count": len(tasks),
                "todos": tasks,
            }
        )

    return ToolDefinition(
        name="todoread",
        description="Read todos",
        parameters={"type": "object", "properties": {}},
        execute=execute,
    )


@pytest.mark.unit
class TestProcessorGoalCompletion:
    """Goal-completion behavior for SessionProcessor."""

    @pytest.fixture
    def config(self):
        return ProcessorConfig(model="test-model", max_no_progress_steps=2)

    @pytest.mark.asyncio
    async def test_task_goal_pending_returns_not_complete(self, config):
        processor = SessionProcessor(
            config=config,
            tools=[
                create_todoread_tool(
                    [
                        {"id": "t1", "status": "completed"},
                        {"id": "t2", "status": "in_progress"},
                    ]
                )
            ],
        )

        result = await processor._evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is False
        assert result.should_stop is False
        assert result.source == "tasks"
        assert result.pending_tasks == 1

    @pytest.mark.asyncio
    async def test_task_goal_all_terminal_success_returns_complete(self, config):
        processor = SessionProcessor(
            config=config,
            tools=[
                create_todoread_tool(
                    [
                        {"id": "t1", "status": "completed"},
                        {"id": "t2", "status": "cancelled"},
                    ]
                )
            ],
        )

        result = await processor._evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is True
        assert result.source == "tasks"

    @pytest.mark.asyncio
    async def test_task_goal_failed_returns_stop(self, config):
        processor = SessionProcessor(
            config=config,
            tools=[
                create_todoread_tool(
                    [
                        {"id": "t1", "status": "failed"},
                        {"id": "t2", "status": "completed"},
                    ]
                )
            ],
        )

        result = await processor._evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is False
        assert result.should_stop is True
        assert result.source == "tasks"

    @pytest.mark.asyncio
    async def test_no_tasks_uses_llm_self_check_true(self, config):
        processor = SessionProcessor(
            config=config,
            tools=[create_todoread_tool([])],
        )
        processor._llm_client = AsyncMock()
        processor._llm_client.generate = AsyncMock(
            return_value={"content": '{"goal_achieved": true, "reason": "all done"}'}
        )

        result = await processor._evaluate_goal_completion(
            session_id="session-1",
            messages=[
                {"role": "user", "content": "please finish"},
                {"role": "assistant", "content": "working"},
            ],
        )

        assert result.achieved is True
        assert result.source == "llm_self_check"

    @pytest.mark.asyncio
    async def test_no_tasks_invalid_self_check_defaults_not_complete(self, config):
        processor = SessionProcessor(
            config=config,
            tools=[create_todoread_tool([])],
        )
        processor._llm_client = AsyncMock()
        processor._llm_client.generate = AsyncMock(return_value={"content": "not json"})

        result = await processor._evaluate_goal_completion(
            session_id="session-1",
            messages=[
                {"role": "user", "content": "please finish"},
                {"role": "assistant", "content": "still working"},
            ],
        )

        assert result.achieved is False
        assert result.source == "assistant_text"

    @pytest.mark.asyncio
    async def test_no_tasks_plain_text_self_check_is_parsed(self, config):
        processor = SessionProcessor(
            config=config,
            tools=[create_todoread_tool([])],
        )
        processor._llm_client = AsyncMock()
        processor._llm_client.generate = AsyncMock(
            return_value={
                "content": "goal_achieved: false\nreason: still implementing remaining items"
            }
        )

        result = await processor._evaluate_goal_completion(
            session_id="session-1",
            messages=[
                {"role": "user", "content": "please finish"},
                {"role": "assistant", "content": "working"},
            ],
        )

        assert result.achieved is False
        assert result.source == "llm_self_check"
        assert "remaining" in result.reason.lower()

    def test_extract_goal_json_handles_braces_in_string(self, config):
        processor = SessionProcessor(config=config, tools=[])
        parsed = processor._extract_goal_json(
            'prefix {"goal_achieved": true, "reason": "keep } brace"} suffix'
        )
        assert parsed is not None
        assert parsed.get("goal_achieved") is True

    def test_extract_goal_from_plain_text_prefers_explicit_negative(self, config):
        processor = SessionProcessor(config=config, tools=[])
        parsed = processor._extract_goal_from_plain_text(
            "goal not achieved yet; some sub-goal achieved already"
        )
        assert parsed is not None
        assert parsed.get("goal_achieved") is False

    def test_extract_goal_from_plain_text_reason_is_line_bounded(self, config):
        processor = SessionProcessor(config=config, tools=[])
        parsed = processor._extract_goal_from_plain_text(
            "goal_achieved: true\nreason: done line one\nextra line"
        )
        assert parsed is not None
        assert parsed.get("goal_achieved") is True
        assert parsed.get("reason") == "done line one"
