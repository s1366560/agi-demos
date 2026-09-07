"""Project skill discovery must never import the API process working directory."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.state import agent_worker_state


@pytest.mark.unit
@pytest.mark.parametrize("project_exists", [True, False])
async def test_project_skill_scan_never_falls_back_to_api_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_exists: bool
) -> None:
    api_root = tmp_path / "api"
    project_root = tmp_path / "project"
    api_skill = api_root / ".memstack/skills/private-api-skill/SKILL.md"
    api_skill.parent.mkdir(parents=True)
    api_skill.write_text(
        "---\nname: private-api-skill\ndescription: API-only resource\n---\nPrivate.\n"
    )
    if project_exists:
        project_skill = project_root / ".memstack/skills/project-skill/SKILL.md"
        project_skill.parent.mkdir(parents=True)
        project_skill.write_text(
            "---\nname: project-skill\ndescription: Project resource\n---\nProject.\n"
        )
    monkeypatch.chdir(api_root)
    adapter = SimpleNamespace(
        _active_sandboxes={
            "sandbox-a": SimpleNamespace(project_id="project-a", project_path=str(project_root))
        }
    )
    monkeypatch.setattr(agent_worker_state, "_sandbox_adapter_for_path_v2", lambda: adapter)
    monkeypatch.setattr(
        agent_worker_state, "resolve_generation_cache_descriptor_v2", lambda _: None
    )
    merge = AsyncMock()
    monkeypatch.setattr(agent_worker_state, "_merge_database_skills_for_worker", merge)
    monkeypatch.setattr(
        agent_worker_state, "_add_workspace_runtime_skill", lambda skills, *_: skills
    )

    skills = await agent_worker_state.get_or_create_skills("tenant-a", "project-a")

    names = {skill.name for skill in skills}
    assert "private-api-skill" not in names
    assert ("project-skill" in names) is project_exists
    merge.assert_awaited_once()
    assert merge.await_args.kwargs["tenant_id"] == "tenant-a"
    assert merge.await_args.kwargs["project_id"] == "project-a"


@pytest.mark.unit
@pytest.mark.parametrize("project_exists", [True, False])
def test_identified_project_never_resolves_to_api_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_exists: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_worker_state, "_sandbox_adapter_for_path_v2", lambda: None)
    monkeypatch.setattr(Path, "exists", lambda _: project_exists)

    resolved = agent_worker_state.resolve_project_base_path("isolated-project")

    assert resolved == Path("/tmp/memstack_isolated-project")
    assert resolved != Path.cwd()


@pytest.mark.unit
@pytest.mark.parametrize("project_exists", [True, False])
def test_bound_sandbox_directory_remains_authoritative_without_memstack_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_exists: bool
) -> None:
    project_root = tmp_path / "bound-project"
    if project_exists:
        project_root.mkdir()
    adapter = SimpleNamespace(
        _active_sandboxes={
            "sandbox-a": SimpleNamespace(project_id="project-a", project_path=str(project_root))
        }
    )
    monkeypatch.setattr(agent_worker_state, "_sandbox_adapter_for_path_v2", lambda: adapter)

    assert agent_worker_state.resolve_project_base_path("project-a") == project_root
