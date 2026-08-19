"""Integrity tests for the builtin route baseline (the P1 row source of truth).

Since the route surface is mounted from this baseline by
``route_loader.install_builtin_routes``, the JSON is authoritative: these
tests guard its internal consistency instead of diffing against main.py.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.infrastructure.plugins.route_inventory import INVENTORY_PATH

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _baseline() -> dict:
    return json.loads((_REPO_ROOT / INVENTORY_PATH).read_text(encoding="utf-8"))


@pytest.mark.unit
def test_baseline_digest_matches_entries() -> None:
    baseline = _baseline()
    canonical = json.dumps(baseline["entries"], sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == baseline["digest"]


@pytest.mark.unit
def test_baseline_covers_the_full_builtin_surface() -> None:
    baseline = _baseline()
    includes = [entry for entry in baseline["entries"] if entry["kind"] == "include_router"]
    helpers = [entry for entry in baseline["entries"] if entry["kind"] == "helper"]

    assert len(includes) == 67
    assert {entry["row_id"] for entry in helpers} == {
        "http-route-capabilities",
        "workspace-core-static",
        "workspace-core",
        "workspace-core-runtime",
        "task-session",
    }


@pytest.mark.unit
def test_row_ids_are_unique_and_stable() -> None:
    baseline = _baseline()
    row_ids = [entry["row_id"] for entry in baseline["entries"]]

    assert len(row_ids) == len(set(row_ids))
    assert all(row_id and " " not in row_id for row_id in row_ids)
    # Intentional repeated mounts stay addressable.
    assert "support" in row_ids
    assert "support-2" in row_ids


@pytest.mark.unit
def test_modules_present_for_all_entries() -> None:
    baseline = _baseline()
    unresolved = [entry["row_id"] for entry in baseline["entries"] if not entry.get("module")]
    assert unresolved == []
