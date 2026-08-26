"""Generation-bound skill roster coverage for command interception."""

from __future__ import annotations

import pytest

from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.tools.skill_loader import (
    make_skill_loader_tool,
    skill_availability_for_tool,
)


@pytest.mark.unit
def test_command_context_uses_bound_skill_roster_including_empty_roster() -> None:
    loader = make_skill_loader_tool(
        skill_service=object(),
        tenant_id="tenant-a",
        project_id="project-a",
        available_skill_names=(),
    )
    processor = SessionProcessor(
        config=ProcessorConfig(model="test-model", skill_names=["stale-global-skill"]),
        tools=convert_tools({"skill_loader": loader}),
    )

    assert processor._build_command_context()["skills"] == []

    availability = skill_availability_for_tool(loader)
    assert availability is not None
    assert availability.include("generation-a-skill") is True
    assert processor._build_command_context()["skills"] == ["generation-a-skill"]


@pytest.mark.unit
def test_command_context_skill_rosters_do_not_cross_generations() -> None:
    loader_a = make_skill_loader_tool(
        skill_service=object(),
        tenant_id="tenant-a",
        project_id="project-a",
        available_skill_names=("skill-a",),
    )
    loader_b = make_skill_loader_tool(
        skill_service=object(),
        tenant_id="tenant-b",
        project_id="project-b",
        available_skill_names=("skill-b",),
    )
    processor_a = SessionProcessor(
        config=ProcessorConfig(model="test-model"),
        tools=convert_tools({"skill_loader": loader_a}),
    )
    processor_b = SessionProcessor(
        config=ProcessorConfig(model="test-model"),
        tools=convert_tools({"skill_loader": loader_b}),
    )

    availability_a = skill_availability_for_tool(loader_a)
    assert availability_a is not None
    assert availability_a.include("synced-a") is True

    assert processor_a._build_command_context()["skills"] == ["skill-a", "synced-a"]
    assert processor_b._build_command_context()["skills"] == ["skill-b"]
