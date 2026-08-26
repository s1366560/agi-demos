"""Generation-bound runtime coverage for the skill loader tool."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.agent.tools.context import ToolContext


def _context(label: str) -> ToolContext:
    return ToolContext(
        session_id=f"session-{label}",
        message_id=f"message-{label}",
        call_id=f"call-{label}",
        agent_name=f"agent-{label}",
        conversation_id=f"conversation-{label}",
    )


@pytest.mark.unit
async def test_bound_skill_loader_runtimes_are_isolated_during_interleaved_awaits() -> None:
    from src.infrastructure.agent.tools.skill_loader import make_skill_loader_tool

    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    class _SkillService:
        def __init__(self, label: str, *, wait: bool) -> None:
            self.label = label
            self.wait = wait
            self.list_calls: list[dict[str, Any]] = []
            self.load_calls: list[dict[str, Any]] = []
            self.usage_calls: list[dict[str, Any]] = []

        async def list_available_skills(self, **kwargs: Any) -> list[object]:
            self.list_calls.append(kwargs)
            if self.wait:
                first_entered.set()
                await release_first.wait()
            else:
                await first_entered.wait()
                release_first.set()
                await asyncio.sleep(0)
            return []

        async def load_skill_content(self, **kwargs: Any) -> str:
            self.load_calls.append(kwargs)
            return f"# Instructions from {self.label}"

        async def record_skill_usage(self, **kwargs: Any) -> None:
            self.usage_calls.append(kwargs)

    class _SkillSyncService:
        def __init__(self, label: str) -> None:
            self.label = label
            self.calls: list[dict[str, Any]] = []

        async def sync_for_skill(self, **kwargs: Any) -> object:
            self.calls.append(kwargs)
            return SimpleNamespace(synced=True, resource_paths=[f"/{self.label}/resource.txt"])

        def build_resource_paths_hint(self, **_kwargs: Any) -> str:
            return f"resources:{self.label}\n"

    service_a = _SkillService("generation-a", wait=True)
    service_b = _SkillService("generation-b", wait=False)
    sync_a = _SkillSyncService("generation-a")
    sync_b = _SkillSyncService("generation-b")
    tool_a = make_skill_loader_tool(
        skill_service=service_a,
        tenant_id="tenant-a",
        project_id="project-a",
        agent_mode="react-a",
        skill_sync_service=sync_a,
        sandbox_id="sandbox-a",
        available_skill_names=("skill-a",),
        skip_database=False,
    )
    tool_b = make_skill_loader_tool(
        skill_service=service_b,
        tenant_id="tenant-b",
        project_id="project-b",
        agent_mode="react-b",
        skill_sync_service=sync_b,
        sandbox_id="sandbox-b",
        available_skill_names=("skill-b",),
        skip_database=False,
    )

    assert tool_a.sandbox_id == "sandbox-a"
    assert tool_b.sandbox_id == "sandbox-b"

    result_a, result_b = await asyncio.gather(
        tool_a.execute(_context("a"), name="shared-skill"),
        tool_b.execute(_context("b"), name="shared-skill"),
    )

    assert "generation-a" in result_a.output
    assert "generation-b" in result_b.output
    assert service_a.list_calls == [
        {
            "tenant_id": "tenant-a",
            "project_id": "project-a",
            "tier": 1,
            "agent_mode": "react-a",
            "skip_database": False,
        }
    ]
    assert service_b.list_calls == [
        {
            "tenant_id": "tenant-b",
            "project_id": "project-b",
            "tier": 1,
            "agent_mode": "react-b",
            "skip_database": False,
        }
    ]
    assert sync_a.calls[0]["sandbox_id"] == "sandbox-a"
    assert sync_b.calls[0]["sandbox_id"] == "sandbox-b"
    assert service_a.load_calls[0]["tenant_id"] == "tenant-a"
    assert service_b.load_calls[0]["tenant_id"] == "tenant-b"
    assert service_a.usage_calls[0]["project_id"] == "project-a"
    assert service_b.usage_calls[0]["project_id"] == "project-b"


@pytest.mark.unit
async def test_bound_skill_loader_available_names_do_not_use_legacy_global_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.tools import skill_loader as skill_loader_module
    from src.infrastructure.agent.tools.skill_loader import make_skill_loader_tool

    service = SimpleNamespace(
        list_available_skills=lambda **_kwargs: None,
        load_skill_content=lambda **_kwargs: None,
    )

    async def _empty_list(**_kwargs: Any) -> list[object]:
        return []

    async def _missing_content(**_kwargs: Any) -> None:
        return None

    service.list_available_skills = _empty_list
    service.load_skill_content = _missing_content
    monkeypatch.setattr(skill_loader_module, "_available_skill_names", ["legacy-leak"])
    monkeypatch.setattr(
        skill_loader_module,
        "_load_skill_content_from_cwd",
        lambda _name: (None, None),
    )

    tool_a = make_skill_loader_tool(
        skill_service=service,
        tenant_id="tenant-a",
        project_id="project-a",
        available_skill_names=("only-a",),
    )
    tool_b = make_skill_loader_tool(
        skill_service=service,
        tenant_id="tenant-b",
        project_id="project-b",
        available_skill_names=("only-b",),
    )

    result_a, result_b = await asyncio.gather(
        tool_a.execute(_context("a"), name="missing"),
        tool_b.execute(_context("b"), name="missing"),
    )

    assert "only-a" in result_a.output
    assert "only-b" not in result_a.output
    assert "legacy-leak" not in result_a.output
    assert "only-b" in result_b.output
    assert "only-a" not in result_b.output
    assert "legacy-leak" not in result_b.output
