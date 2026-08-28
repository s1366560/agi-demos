"""Generation-bound runtime coverage for the skill installer tool."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.result import ToolResult


def _context(label: str) -> ToolContext:
    return ToolContext(
        session_id=f"session-{label}",
        message_id=f"message-{label}",
        call_id=f"call-{label}",
        agent_name=f"agent-{label}",
        conversation_id=f"conversation-{label}",
    )


@pytest.mark.unit
async def test_bound_skill_installer_runtimes_are_isolated_during_interleaved_awaits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.infrastructure.agent.tools import skill_installer as skill_installer_module
    from src.infrastructure.agent.tools.skill_installer import (
        make_skill_installer_tool,
    )

    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def _resolve(
        owner: str,
        _repo: str,
        skill_name: str | None,
        _branch: str,
    ) -> str:
        if owner == "owner-a":
            first_entered.set()
            await release_first.wait()
        else:
            await first_entered.wait()
            release_first.set()
            await asyncio.sleep(0)
        return skill_name or "shared-skill"

    async def _install(
        _ctx: ToolContext,
        _owner: str,
        _repo: str,
        skill_name: str,
        install_location: str,
        _branch: str,
        tenant_id: str,
        project_id: str,
    ) -> ToolResult:
        install_path = skill_installer_module._inst_get_install_path(
            install_location,
            skill_name,
        )
        return ToolResult(output=f"{tenant_id}/{project_id}/{install_path}")

    monkeypatch.setattr(skill_installer_module, "_inst_resolve_skill_name", _resolve)
    monkeypatch.setattr(skill_installer_module, "_inst_do_install", _install)

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    tool_a = make_skill_installer_tool(
        project_path=project_a,
        tenant_id="tenant-a",
        project_id="project-a",
    )
    tool_b = make_skill_installer_tool(
        project_path=project_b,
        tenant_id="tenant-b",
        project_id="project-b",
    )
    result_a, result_b = await asyncio.gather(
        tool_a.execute(
            _context("a"),
            skill_source="owner-a/repo",
            skill_name="shared-skill",
        ),
        tool_b.execute(
            _context("b"),
            skill_source="owner-b/repo",
            skill_name="shared-skill",
        ),
    )

    assert result_a.output == (
        f"tenant-a/project-a/{project_a / '.memstack' / 'skills' / 'shared-skill'}"
    )
    assert result_b.output == (
        f"tenant-b/project-b/{project_b / '.memstack' / 'skills' / 'shared-skill'}"
    )


@pytest.mark.unit
def test_unbound_skill_installer_template_rejects_legacy_runtime_fallback() -> None:
    from src.infrastructure.agent.tools import skill_installer as skill_installer_module

    with pytest.raises(RuntimeError, match="generation-bound runtime"):
        skill_installer_module._current_skill_installer_runtime()


@pytest.mark.unit
def test_skill_installer_module_has_no_legacy_configure_seam() -> None:
    from src.infrastructure.agent.tools import skill_installer as skill_installer_module

    assert not hasattr(skill_installer_module, "configure_skill_installer")
