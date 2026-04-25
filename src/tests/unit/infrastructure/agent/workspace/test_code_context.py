from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.agent.workspace import code_context as cc


@pytest.mark.unit
def test_load_agents_instruction_files_skips_contaminated_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "AGENTS.md").write_text("root sandbox policy", encoding="utf-8")
    repo = tmp_path / "my-evo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("project policy", encoding="utf-8")

    monkeypatch.setattr(cc, "resolve_host_workspace_root", lambda _project_id: tmp_path)

    files, warnings, host_code_root = cc.load_agents_instruction_files(
        project_id="project-1",
        sandbox_code_root="/workspace/my-evo",
    )

    assert warnings == ()
    assert host_code_root == repo
    assert [file.sandbox_path for file in files] == ["/workspace/my-evo/AGENTS.md"]
    assert files[0].content == "project policy"


@pytest.mark.unit
def test_load_agents_instruction_files_includes_nested_parent_within_code_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team = tmp_path / "team"
    repo = team / "my-evo"
    repo.mkdir(parents=True)
    (team / "AGENTS.md").write_text("team policy", encoding="utf-8")
    (repo / "AGENTS.md").write_text("project policy", encoding="utf-8")

    monkeypatch.setattr(cc, "resolve_host_workspace_root", lambda _project_id: tmp_path)

    files, warnings, _host_code_root = cc.load_agents_instruction_files(
        project_id="project-1",
        sandbox_code_root="/workspace/team/my-evo",
    )

    assert warnings == ()
    assert [file.sandbox_path for file in files] == [
        "/workspace/team/AGENTS.md",
        "/workspace/team/my-evo/AGENTS.md",
    ]
