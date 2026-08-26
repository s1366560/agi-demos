"""Generation isolation contracts for the skill-sync ToolInfo."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.skill_sync import make_skill_sync_tool


def _context(label: str) -> ToolContext:
    return ToolContext(
        session_id=f"session-{label}",
        message_id=f"message-{label}",
        call_id=f"call-{label}",
        agent_name=f"agent-{label}",
        conversation_id=f"conversation-{label}",
    )


@pytest.mark.unit
async def test_bound_skill_sync_runtimes_are_isolated_during_interleaved_awaits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.tools import skill_sync as skill_sync_module

    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def _execute(
        _skill_name: str,
        _skill_path: str | None,
        _change_summary: str | None,
        _ctx: ToolContext,
        *,
        runtime: Any,
    ) -> ToolResult:
        if runtime.tenant_id == "tenant-a":
            first_entered.set()
            await release_first.wait()
        else:
            await first_entered.wait()
            release_first.set()
        return ToolResult(output=f"{runtime.tenant_id}/{runtime.project_id}")

    monkeypatch.setattr(skill_sync_module, "_skill_sync_execute_sync", _execute)
    first_tool = make_skill_sync_tool(
        tenant_id="tenant-a",
        project_id="project-a",
        sandbox_adapter=object(),
        sandbox_id="sandbox-a",
        session_factory=lambda: None,
        skill_loader_tool=object(),
    )
    second_tool = make_skill_sync_tool(
        tenant_id="tenant-b",
        project_id="project-b",
        sandbox_adapter=object(),
        sandbox_id="sandbox-b",
        session_factory=lambda: None,
        skill_loader_tool=object(),
    )

    first_task = asyncio.create_task(
        first_tool.execute(_context("a"), skill_name="shared-skill")
    )
    await first_entered.wait()
    second_result = await second_tool.execute(_context("b"), skill_name="shared-skill")
    first_result = await first_task

    assert first_result.output == "tenant-a/project-a"
    assert second_result.output == "tenant-b/project-b"


@pytest.mark.unit
async def test_bound_skill_sync_passes_exact_runtime_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.tools import skill_sync as skill_sync_module

    captured: dict[str, Any] = {}
    sandbox_adapter = object()
    skill_loader_tool = object()

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_args: object) -> bool:
            return False

        async def commit(self) -> None:
            captured["committed"] = True

    session = _Session()

    class _SkillReverseSync:
        def __init__(self, **kwargs: object) -> None:
            captured["constructor"] = kwargs

        async def sync_from_sandbox(self, **kwargs: object) -> dict[str, object]:
            captured["operation"] = kwargs
            return {
                "skill_id": "skill-id",
                "version_number": 3,
                "version_label": "v3",
                "files_synced": 2,
            }

    monkeypatch.setattr(
        "src.application.services.skill_reverse_sync.SkillReverseSync",
        _SkillReverseSync,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_repository."
        "SqlSkillRepository",
        lambda session: ("skill-repo", session),
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        lambda session: ("version-repo", session),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.resolve_project_base_path",
        lambda project_id: f"/project/{project_id}",
    )
    monkeypatch.setattr(
        skill_sync_module,
        "_skill_sync_invalidate_caches",
        lambda **kwargs: captured.setdefault("cache", kwargs) or {},
    )
    tool = make_skill_sync_tool(
        tenant_id="tenant-exact",
        project_id="project-exact",
        sandbox_adapter=sandbox_adapter,
        sandbox_id="sandbox-exact",
        session_factory=lambda: session,
        skill_loader_tool=skill_loader_tool,
    )

    result = await tool.execute(
        _context("exact"),
        skill_name=" exact-skill ",
        skill_path="/workspace/exact-skill",
        change_summary="exact change",
    )

    assert result.is_error is False
    assert captured["committed"] is True
    assert captured["constructor"] == {
        "skill_repository": ("skill-repo", session),
        "skill_version_repository": ("version-repo", session),
        "host_project_path": "/project/project-exact",
    }
    assert captured["operation"] == {
        "skill_name": "exact-skill",
        "tenant_id": "tenant-exact",
        "sandbox_adapter": sandbox_adapter,
        "sandbox_id": "sandbox-exact",
        "project_id": "project-exact",
        "change_summary": "exact change",
        "created_by": "agent",
        "skill_path": "/workspace/exact-skill",
    }
    assert captured["cache"] == {
        "skill_name": "exact-skill",
        "tenant_id": "tenant-exact",
        "project_id": "project-exact",
        "skill_loader_tool": skill_loader_tool,
    }
