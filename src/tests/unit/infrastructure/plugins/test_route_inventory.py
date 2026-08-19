"""Unit tests for the builtin FastAPI route inventory baseline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.plugins.route_inventory import (
    INVENTORY_PATH,
    MAIN_PY_PATH,
    generate_route_inventory,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]


@pytest.mark.unit
def test_inventory_matches_checked_in_baseline() -> None:
    inventory = generate_route_inventory()
    baseline_path = _REPO_ROOT / INVENTORY_PATH
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    assert inventory.to_payload() == baseline, (
        "builtin route surface drifted; regenerate with "
        "`uv run python scripts/generate_route_inventory.py`"
    )


@pytest.mark.unit
def test_inventory_covers_every_include_router_call() -> None:
    inventory = generate_route_inventory(_REPO_ROOT / MAIN_PY_PATH)
    includes = [entry for entry in inventory.entries if entry.kind == "include_router"]
    main_py = (_REPO_ROOT / MAIN_PY_PATH).read_text(encoding="utf-8")

    assert len(includes) == main_py.count("app.include_router(")
    assert len(includes) >= 60


@pytest.mark.unit
def test_row_ids_are_unique_and_stable() -> None:
    inventory = generate_route_inventory(_REPO_ROOT / MAIN_PY_PATH)
    row_ids = [entry.row_id for entry in inventory.entries]

    assert len(row_ids) == len(set(row_ids))
    assert all(row_id and " " not in row_id for row_id in row_ids)
    # Intentional repeated mounts stay addressable.
    assert "support" in row_ids
    assert "support-2" in row_ids


@pytest.mark.unit
def test_modules_resolve_for_all_entries() -> None:
    inventory = generate_route_inventory(_REPO_ROOT / MAIN_PY_PATH)

    unresolved = [entry.row_id for entry in inventory.entries if entry.module is None]
    assert unresolved == []


@pytest.mark.unit
def test_digest_changes_when_entries_change() -> None:
    inventory = generate_route_inventory(_REPO_ROOT / MAIN_PY_PATH)
    entries = inventory.entries
    modified = type(inventory)(
        source=inventory.source,
        entries=entries[1:],
    )

    assert modified.digest != inventory.digest
