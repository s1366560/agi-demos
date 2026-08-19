"""Composition tests for the shipped profile templates (P4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests
from src.infrastructure.plugins.dump_config import load_profile_document
from src.infrastructure.plugins.profile import compose_profile

_TEMPLATES_DIR = Path(__file__).resolve().parents[5] / "config" / "plugin-profiles" / "templates"


@pytest.mark.unit
def test_server_template_composes_with_all_builtins() -> None:
    document = load_profile_document(_TEMPLATES_DIR / "server.yaml")
    snapshot = compose_profile(document, default_builtin_manifests())

    row_ids = sorted(row.manifest.id for row in snapshot.rows)
    assert row_ids == [
        "memory-runtime",
        "sisyphus-runtime",
        "skill-evolution",
        "workspace-runtime",
    ]


@pytest.mark.unit
def test_desktop_template_disables_skill_evolution() -> None:
    document = load_profile_document(_TEMPLATES_DIR / "desktop.yaml")
    snapshot = compose_profile(document, default_builtin_manifests())

    row_ids = sorted(row.manifest.id for row in snapshot.rows)
    assert row_ids == ["memory-runtime", "sisyphus-runtime", "workspace-runtime"]


@pytest.mark.unit
def test_headless_template_is_the_minimal_composition() -> None:
    document = load_profile_document(_TEMPLATES_DIR / "headless.yaml")
    snapshot = compose_profile(document, default_builtin_manifests())

    row_ids = sorted(row.manifest.id for row in snapshot.rows)
    assert row_ids == ["sisyphus-runtime", "workspace-runtime"]


@pytest.mark.unit
def test_template_ids_are_distinct_and_stable() -> None:
    ids = set()
    for name in ("server", "desktop", "headless"):
        document = load_profile_document(_TEMPLATES_DIR / f"{name}.yaml")
        assert document.profile_id == f"memstack-{name}"
        ids.add(document.profile_id)
    assert len(ids) == 3
