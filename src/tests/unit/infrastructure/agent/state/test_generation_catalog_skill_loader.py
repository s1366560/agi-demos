"""Tests that profile-enabled generation catalog skills are loadable."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.domain.model.agent.skill import Skill, SkillStatus
from src.infrastructure.agent.state import agent_worker_state
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.skill_loader import (
    make_skill_loader_tool,
    skill_availability_for_tool,
)
from src.infrastructure.plugins.v2.agent_capabilities import (
    AGENT_CAPABILITY_RESOLVER_SERVICE_V2,
    AgentCapabilitySetV2,
)


def _catalog_skill() -> Skill:
    return Skill(
        id="plugin-v2:darwinian-evolver:tenant-a",
        tenant_id="tenant-a",
        name="darwinian-evolver",
        description="Evolve prompts, regex, SQL, or code with an LLM loop.",
        tools=["terminal"],
        status=SkillStatus.ACTIVE,
        file_path="/opt/memstack/skills/darwinian-evolver/SKILL.md",
        full_content="# Darwinian Evolver\n\nRun the packaged evolutionary loop.",
        agent_modes=["*"],
    )


class _CatalogResolver:
    def __init__(self, skills: tuple[Skill, ...]) -> None:
        self._skills = skills

    async def resolve(
        self,
        *,
        agent: object,
        tenant_id: str,
        project_id: str,
    ) -> AgentCapabilitySetV2:
        assert tenant_id == "tenant-a"
        assert project_id == "project-a"
        return AgentCapabilitySetV2(skills=self._skills, subagents=())


class _Operation:
    def __init__(self, resolver: _CatalogResolver) -> None:
        self._resolver = resolver

    def require(self, service_id: object) -> _CatalogResolver:
        assert service_id == AGENT_CAPABILITY_RESOLVER_SERVICE_V2
        return self._resolver


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="session",
        message_id="message",
        call_id="call",
        agent_name="agent",
        conversation_id="conversation",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_catalog_skill_fills_gap_when_filesystem_cache_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = _catalog_skill()
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
        lambda: _Operation(_CatalogResolver((skill,))),
    )
    loaded: dict[str, Skill] = {
        "code-review": Skill(
            id="fs-code-review",
            tenant_id="tenant-a",
            name="code-review",
            description="Review code",
            tools=["read"],
            status=SkillStatus.ACTIVE,
            file_path="/workspace/.memstack/skills/code-review/SKILL.md",
            full_content="# Code review",
        )
    }

    await agent_worker_state._merge_generation_catalog_skills_for_worker(
        loaded,
        tenant_id="tenant-a",
        project_id="project-a",
        cache_key="tenant-a:project-a",
    )

    assert "darwinian-evolver" in loaded
    assert loaded["darwinian-evolver"].full_content is not None
    assert loaded["code-review"].id == "fs-code-review"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_catalog_merge_does_not_override_skill_that_already_has_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog_skill()
    catalog.full_content = "# Catalog copy"
    local = _catalog_skill()
    local.id = "local-darwinian"
    local.full_content = "# Project copy"
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
        lambda: _Operation(_CatalogResolver((catalog,))),
    )
    loaded = {"darwinian-evolver": local}

    await agent_worker_state._merge_generation_catalog_skills_for_worker(
        loaded,
        tenant_id="tenant-a",
        project_id="project-a",
        cache_key="tenant-a:project-a",
    )

    assert loaded["darwinian-evolver"].id == "local-darwinian"
    assert loaded["darwinian-evolver"].full_content == "# Project copy"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_catalog_merge_is_noop_without_pinned_operation() -> None:
    loaded: dict[str, Skill] = {}
    await agent_worker_state._merge_generation_catalog_skills_for_worker(
        loaded,
        tenant_id="tenant-a",
        project_id="project-a",
        cache_key="tenant-a:project-a",
    )
    assert loaded == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_loader_loads_catalog_skill_when_skill_service_misses() -> None:
    skill = _catalog_skill()
    from unittest.mock import AsyncMock

    skill_service = SimpleNamespace(
        list_available_skills=AsyncMock(return_value=[]),
        load_skill_content=AsyncMock(return_value=None),
        record_skill_usage=AsyncMock(),
    )

    async def resolve(name: str) -> Skill | None:
        return skill if name == "darwinian-evolver" else None

    tool = make_skill_loader_tool(
        skill_service=skill_service,
        tenant_id="tenant-a",
        project_id="project-a",
        available_skill_names=("code-review", "darwinian-evolver"),
        marketplace_skill_resolver=resolve,
    )

    availability = skill_availability_for_tool(tool)
    assert availability is not None
    assert "darwinian-evolver" in availability.snapshot()

    result = await tool.execute(_ctx(), name="darwinian-evolver")

    assert result.is_error is False
    assert "Darwinian Evolver" in result.output
    skill_service.load_skill_content.assert_not_awaited()
