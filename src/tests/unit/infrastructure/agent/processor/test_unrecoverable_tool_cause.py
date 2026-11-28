"""Same-cause failures stop the main loop inside the existing error budget."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest

from plugins.business.agent.engine.processor.factory import ProcessorFactory
from plugins.business.agent.engine.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from plugins.business.agent.engine.react.project_react_agent import ProjectReActAgent
from plugins.business.agent.engine.react.react_agent_stream_mixin import StreamMixin
from src.domain.events.agent_events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentObserveEvent,
)
from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.tools.hooks import ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.truncation import OutputTruncator

pytestmark = pytest.mark.unit


def _processor(
    execute: Any, *, pipeline: bool, name: str, repeatable: bool = False
) -> SessionProcessor:
    definition = ToolDefinition(
        name=name,
        description="test",
        parameters={"type": "object", "properties": {}},
        execute=execute,
        repeatable_observation=repeatable,
    )
    detector = MagicMock()
    detector.should_intervene.return_value = False
    processor = SessionProcessor(
        config=ProcessorConfig(model="test-model"),
        tools=[definition],
        permission_manager=MagicMock(),
        tool_pipeline=ToolPipeline(
            permission_manager=MagicMock(),
            doom_detector=detector,
            truncator=OutputTruncator(),
            hooks=ToolHookRegistry(),
        )
        if pipeline
        else None,
    )
    processor._abort_event = asyncio.Event()
    processor.permission_manager.ask = MagicMock()
    return processor


def _install_model(monkeypatch: pytest.MonkeyPatch, generate: Any) -> None:
    monkeypatch.setattr(
        "plugins.business.agent.engine.processor.processor.LLMStream.generate",
        generate,
    )


@pytest.mark.parametrize("pipeline", [False, True])
async def test_hundred_false_successes_stop_inside_existing_error_budget(
    monkeypatch: pytest.MonkeyPatch, pipeline: bool
) -> None:
    calls = {"model": 0, "tool": 0}
    messages: list[str] = []

    async def execute(**kwargs: Any) -> ToolResult:
        calls["tool"] += 1
        messages.append(str(kwargs.get("message")))
        return ToolResult(
            output="Not a git repository",
            metadata={"in_git_repo": False, "working_dir": "/workspace"},
            is_error=False,
        )

    async def generate(_self: Any, _messages: Any, **_kwargs: Any) -> Any:
        calls["model"] += 1
        if calls["model"] > 20:
            raise AssertionError("model loop exceeded the existing error budget")
        call_id = f"call-{calls['model']}"
        yield _event(
            StreamEventType.TOOL_CALL_START,
            {"call_id": call_id, "name": "generate_commit"},
        )
        yield _event(
            StreamEventType.TOOL_CALL_END,
            {
                "call_id": call_id,
                "name": "generate_commit",
                "arguments": {
                    "message": chr(96 + calls["model"]),
                    "auto_add": False,
                    "dry_run": True,
                },
            },
        )
        yield _event(StreamEventType.FINISH, {"reason": "tool_calls"})

    processor = _processor(execute, pipeline=pipeline, name="generate_commit")
    _install_model(monkeypatch, generate)
    events = [event async for event in processor._run_native_loop("session", [])]
    budget = processor.doom_loop_detector.error_threshold

    assert calls["model"] == budget
    assert calls["tool"] == budget
    assert len(set(messages)) == budget
    assert processor._state.name == "ERROR"
    assert processor._stop_record is not None
    assert processor._stop_record["status"] == "stopped"
    assert processor._stop_record["code"] == "UNRECOVERABLE_TOOL_CAUSE"
    assert processor._stop_record["fingerprint"] == "not_a_git_repository|."
    assert processor._stop_record["count"] == budget
    errors = [
        event
        for event in events
        if isinstance(event, AgentErrorEvent) and event.code == "UNRECOVERABLE_TOOL_CAUSE"
    ]
    assert len(errors) == 1
    assert "working_dir" in errors[0].message
    assert "repo_path" in errors[0].message
    observations = [event for event in events if isinstance(event, AgentObserveEvent)]
    assert len(observations) == budget
    assert all(event.status == "error" for event in observations)
    assert all(event.error and "workspace-relative" in event.error for event in observations)
    assert not any(isinstance(event, AgentCompleteEvent) for event in events)
    processor.permission_manager.ask.assert_not_called()


async def test_correcting_the_repo_resumes_and_cancel_stays_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"model": 0, "tool": 0}

    async def execute(**kwargs: Any) -> ToolResult:
        calls["tool"] += 1
        if kwargs.get("working_dir") == "probe_repo":
            if calls["tool"] >= 7:
                processor._abort_event.set()
            return ToolResult(
                output="Dry run: True",
                metadata={"in_git_repo": True, "dry_run": True},
                is_error=False,
            )
        return ToolResult(
            output="Not a git repository",
            metadata={"in_git_repo": False},
            is_error=False,
        )

    async def generate(_self: Any, _messages: Any, **_kwargs: Any) -> Any:
        calls["model"] += 1
        call_id = f"call-{calls['model']}"
        arguments: dict[str, Any] = {
            "message": f"msg-{calls['model']}",
            "auto_add": False,
            "dry_run": True,
        }
        if calls["tool"] >= 2:
            arguments["working_dir"] = "probe_repo"
        yield _event(
            StreamEventType.TOOL_CALL_START, {"call_id": call_id, "name": "generate_commit"}
        )
        yield _event(
            StreamEventType.TOOL_CALL_END,
            {"call_id": call_id, "name": "generate_commit", "arguments": arguments},
        )
        yield _event(StreamEventType.FINISH, {"reason": "tool_calls"})

    processor = _processor(execute, pipeline=False, name="generate_commit")
    _install_model(monkeypatch, generate)
    events = [event async for event in processor._run_native_loop("session", [])]

    assert calls["tool"] == 7
    assert calls["model"] == 7
    assert processor.doom_loop_detector.same_cause_count("not_a_git_repository|.") == 2
    assert processor.doom_loop_detector.same_cause_count("not_a_git_repository|probe_repo") == 0
    assert any(isinstance(event, AgentErrorEvent) and event.code == "ABORTED" for event in events)
    assert not any(
        isinstance(event, AgentErrorEvent) and event.code == "UNRECOVERABLE_TOOL_CAUSE"
        for event in events
    )
    assert not any(isinstance(event, AgentCompleteEvent) for event in events)
    assert processor._state.name == "ERROR"


async def test_repeatable_progress_tool_is_not_a_same_cause_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"model": 0, "tool": 0}

    async def execute(**_kwargs: Any) -> ToolResult:
        calls["tool"] += 1
        if calls["tool"] >= 8:
            processor._abort_event.set()
        return ToolResult(output="updated", is_error=False)

    async def generate(_self: Any, _messages: Any, **_kwargs: Any) -> Any:
        calls["model"] += 1
        call_id = f"call-{calls['model']}"
        yield _event(StreamEventType.TOOL_CALL_START, {"call_id": call_id, "name": "todowrite"})
        yield _event(
            StreamEventType.TOOL_CALL_END,
            {
                "call_id": call_id,
                "name": "todowrite",
                "arguments": {"todos": [{"id": "1", "content": "keep going", "status": "pending"}]},
            },
        )
        yield _event(StreamEventType.FINISH, {"reason": "tool_calls"})

    processor = _processor(execute, pipeline=False, name="todowrite", repeatable=True)
    _install_model(monkeypatch, generate)
    events = [event async for event in processor._run_native_loop("session", [])]

    assert calls["tool"] == 8
    assert any(isinstance(event, AgentErrorEvent) and event.code == "ABORTED" for event in events)
    assert not any(
        isinstance(event, AgentErrorEvent) and event.code == "UNRECOVERABLE_TOOL_CAUSE"
        for event in events
    )
    processor.permission_manager.ask.assert_not_called()


async def test_same_sentinel_on_another_tool_does_not_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"model": 0, "tool": 0}

    async def execute(**_kwargs: Any) -> ToolResult:
        calls["tool"] += 1
        if calls["tool"] >= 8:
            processor._abort_event.set()
        return ToolResult(output="Not a git repository", is_error=False)

    async def generate(_self: Any, _messages: Any, **_kwargs: Any) -> Any:
        calls["model"] += 1
        call_id = f"call-{calls['model']}"
        yield _event(StreamEventType.TOOL_CALL_START, {"call_id": call_id, "name": "git_log"})
        yield _event(
            StreamEventType.TOOL_CALL_END,
            {
                "call_id": call_id,
                "name": "git_log",
                "arguments": {"message": f"m{calls['model']}"},
            },
        )
        yield _event(StreamEventType.FINISH, {"reason": "tool_calls"})

    processor = _processor(execute, pipeline=False, name="git_log")
    _install_model(monkeypatch, generate)
    events = [event async for event in processor._run_native_loop("session", [])]

    assert calls["tool"] == 8
    assert processor.doom_loop_detector.same_cause_count("not_a_git_repository|.") == 0
    assert any(isinstance(event, AgentErrorEvent) and event.code == "ABORTED" for event in events)
    assert not any(
        isinstance(event, AgentErrorEvent) and event.code == "UNRECOVERABLE_TOOL_CAUSE"
        for event in events
    )


def test_main_and_project_loops_share_the_session_processor_guard() -> None:
    assert "_react_agent.stream" in inspect.getsource(ProjectReActAgent.execute_chat)
    assert "create_for_main" in inspect.getsource(StreamMixin)
    assert "SessionProcessor" in inspect.getsource(ProcessorFactory.create_for_main)


def _event(event_type: Any, data: dict[str, Any]) -> Any:
    return type("Event", (), {"type": event_type, "data": data})()
