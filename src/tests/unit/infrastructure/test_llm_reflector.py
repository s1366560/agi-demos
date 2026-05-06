"""Tests for ``LLMReflector`` adapter."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.domain.model.flow.playbook import Playbook, PlaybookStatus, TriggerPattern
from src.domain.model.flow.reflection_verdict import ReflectionAction
from src.infrastructure.adapters.secondary.llm_reflector import LLMReflector


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.content = content
        self.last_messages: list[dict[str, str]] | None = None

    async def __call__(
        self,
        *,
        messages: list[dict[str, str]],
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.last_messages = messages
        return {"content": self.content}


def _signal() -> FrictionSignal:
    return FrictionSignal(
        project_id="p1",
        task_id="t1",
        kind=FrictionKind.BOUNCE,
        source_lane="dev",
        target_lane="todo",
    )


def _playbook(name: str = "Existing") -> Playbook:
    return Playbook(
        project_id="p1",
        name=name,
        trigger=TriggerPattern(description="x"),
        status=PlaybookStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_returns_empty_when_no_signals() -> None:
    reflector = LLMReflector(completion=_FakeCompletion("{}"))
    result = await reflector.reflect(
        project_id="p1", signals=[], existing_playbooks=[]
    )
    assert result == []


@pytest.mark.asyncio
async def test_parses_create_verdict() -> None:
    payload = json.dumps(
        {
            "verdicts": [
                {
                    "action": "create",
                    "rationale": "dev->todo bounce repeats",
                    "proposed_playbook": {
                        "name": "Tighten Backlog Gate",
                        "trigger": {"description": "dev->todo bounce"},
                        "steps": [{"order": 1, "instruction": "Add AC checks"}],
                    },
                }
            ]
        }
    )
    reflector = LLMReflector(completion=_FakeCompletion(payload))
    result = await reflector.reflect(
        project_id="p1", signals=[_signal()], existing_playbooks=[]
    )
    assert len(result) == 1
    assert result[0].action is ReflectionAction.CREATE
    assert result[0].proposed_playbook is not None
    assert result[0].proposed_playbook["name"] == "Tighten Backlog Gate"


@pytest.mark.asyncio
async def test_parses_reinforce_verdict() -> None:
    payload = json.dumps(
        {
            "verdicts": [
                {"action": "reinforce", "playbook_id": "pb1", "rationale": "helped"},
            ]
        }
    )
    reflector = LLMReflector(completion=_FakeCompletion(payload))
    result = await reflector.reflect(
        project_id="p1", signals=[_signal()], existing_playbooks=[_playbook()]
    )
    assert len(result) == 1
    assert result[0].action is ReflectionAction.REINFORCE
    assert result[0].playbook_id == "pb1"


@pytest.mark.asyncio
async def test_skips_malformed_entries() -> None:
    payload = json.dumps(
        {
            "verdicts": [
                {"action": "reinforce"},  # missing playbook_id
                {"action": "create"},  # missing proposed_playbook
                {"action": "unknown_action"},
                {"action": "noop", "rationale": ""},
            ]
        }
    )
    reflector = LLMReflector(completion=_FakeCompletion(payload))
    result = await reflector.reflect(
        project_id="p1", signals=[_signal()], existing_playbooks=[]
    )
    assert len(result) == 1
    assert result[0].action is ReflectionAction.NOOP


@pytest.mark.asyncio
async def test_returns_empty_on_non_json_content() -> None:
    reflector = LLMReflector(completion=_FakeCompletion("not json"))
    result = await reflector.reflect(
        project_id="p1", signals=[_signal()], existing_playbooks=[]
    )
    assert result == []


@pytest.mark.asyncio
async def test_returns_empty_on_completion_exception() -> None:
    class _Boom:
        async def __call__(self, **_: Any) -> dict[str, Any]:
            raise RuntimeError("network down")

    reflector = LLMReflector(completion=_Boom())
    result = await reflector.reflect(
        project_id="p1", signals=[_signal()], existing_playbooks=[]
    )
    assert result == []


@pytest.mark.asyncio
async def test_truncates_signals_and_playbooks() -> None:
    fake = _FakeCompletion("{}")
    reflector = LLMReflector(completion=fake, max_signals=2, max_playbooks=1)
    await reflector.reflect(
        project_id="p1",
        signals=[_signal(), _signal(), _signal()],
        existing_playbooks=[_playbook("a"), _playbook("b")],
    )
    assert fake.last_messages is not None
    user_payload = json.loads(fake.last_messages[-1]["content"])
    assert len(user_payload["signals"]) == 2
    assert len(user_payload["existing_playbooks"]) == 1
