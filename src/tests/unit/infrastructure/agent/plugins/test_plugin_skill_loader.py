"""Unit tests for SKILL.md-based plugin skill loading."""

from __future__ import annotations

import pytest

from src.infrastructure.agent.plugins.discovery import DiscoveredPlugin
from src.infrastructure.agent.plugins.plugin_skill_loader import (
    load_plugin_skills_from_markdown,
)

pytestmark = pytest.mark.unit


def test_load_plugin_skills_enforces_manifest_contracts(tmp_path) -> None:
    """SKILL.md plugin skills should respect manifest-declared contracts.skills."""
    plugin_dir = tmp_path / "demo-plugin"
    skills_dir = plugin_dir / "skills"
    (skills_dir / "allowed").mkdir(parents=True)
    (skills_dir / "blocked").mkdir(parents=True)
    (plugin_dir / "memstack.plugin.json").write_text("{}", encoding="utf-8")
    _write_skill(skills_dir / "allowed" / "SKILL.md", name="allowed")
    _write_skill(skills_dir / "blocked" / "SKILL.md", name="blocked")

    skills, diagnostics = load_plugin_skills_from_markdown(
        [
            DiscoveredPlugin(
                name="demo-plugin",
                plugin=object(),
                source="local",
                manifest_path=str(plugin_dir / "memstack.plugin.json"),
                skills=("skills",),
                contracts={"skills": ("allowed",)},
            )
        ],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert [skill.name for skill in skills] == ["allowed"]
    assert [(item.code, item.level) for item in diagnostics] == [
        ("plugin_contract_violation", "error")
    ]
    assert "blocked" in diagnostics[0].message


def _write_skill(path, *, name: str) -> None:
    path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f'description: "{name} skill"',
                "tools:",
                "  - test_tool",
                "---",
                "",
                f"# {name}",
            ]
        ),
        encoding="utf-8",
    )
