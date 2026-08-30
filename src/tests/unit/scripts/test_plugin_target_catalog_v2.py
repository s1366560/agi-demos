"""Production target-catalog coverage for protocol v2."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.plugins.v2.protocol import parse_profile_snapshot_v2

_ROOT = Path(__file__).resolve().parents[4]
_CATALOG = _ROOT / "shared/catalogs/plugin-module-catalog.v2.json"
_BOOTSTRAP = _ROOT / "shared/profiles/memstack-default-bootstrap.v2.json"

_EXPECTED_TARGET_MODULES = {
    "rust-server": frozenset(
        {
            "builtin://memstack/rust-server/generation-host",
            "builtin://memstack/rust-server/http-routes",
        }
    ),
    "desktop-sidecar": frozenset(
        {
            "builtin://memstack/desktop-sidecar/http-routes",
            "builtin://memstack/desktop-sidecar/local-capability",
        }
    ),
    "web": frozenset(
        {
            "builtin://memstack/web/renderer-host",
            "builtin://memstack/web/renderer-contribution-registry",
            "builtin://memstack/web/renderer-contribution",
        }
    ),
    "desktop-renderer": frozenset(
        {
            "builtin://memstack/desktop/renderer-host",
            "builtin://memstack/desktop/renderer-contribution-registry",
            "builtin://memstack/desktop/renderer-contribution",
        }
    ),
}


@pytest.mark.unit
def test_generated_catalog_has_exact_production_modules_per_non_python_target() -> None:
    catalog = json.loads(_CATALOG.read_text(encoding="utf-8"))

    for target, expected_module_refs in _EXPECTED_TARGET_MODULES.items():
        matching = {
            module["module_ref"] for module in catalog["modules"] if target in module["targets"]
        }
        assert matching == expected_module_refs


@pytest.mark.unit
def test_generated_bootstrap_profile_projects_every_production_target() -> None:
    payload = json.loads(_BOOTSTRAP.read_text(encoding="utf-8"))
    snapshot = parse_profile_snapshot_v2(payload)
    modules = {
        module.module_ref: set(module.targets)
        for manifest in snapshot.manifests
        for module in manifest.modules
    }

    for target, module_refs in _EXPECTED_TARGET_MODULES.items():
        for module_ref in module_refs:
            assert target in {item.value for item in modules[module_ref]}
            assert any(
                entry.module_ref == module_ref and entry.enabled for entry in snapshot.entries
            )

    entries = payload["entries"]
    web_shell_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-web-authenticated-shell-surface"
    )
    web_routes_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-web-default-routes"
    )
    shell_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-authenticated-shell-surface"
    )
    workbench_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-workbench-surface"
    )
    new_thread_composer_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-new-thread-composer-surface"
    )
    workspace_collaboration_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-workspace-collaboration-surface"
    )
    session_canvas_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-session-canvas-surface"
    )
    activity_inbox_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-activity-inbox-surface"
    )
    my_work_queue_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-my-work-queue-surface"
    )
    desktop_routes_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-tenant-creation-routes"
    )
    assert len(entries) == 323
    assert web_shell_index < web_routes_index
    assert entries[web_shell_index]["config"] == {
        "id": "web.authenticated-shell-surface",
        "kind": "ui-slot",
        "order": 80,
        "payload": {
            "artifact_refs": ["web.ui-slots.authenticated-shell-surface.v1"],
            "schema_version": 1,
        },
    }
    assert (
        shell_index
        < session_canvas_index
        < workbench_index
        < workspace_collaboration_index
        < new_thread_composer_index
        < my_work_queue_index
        < activity_inbox_index
        < desktop_routes_index
    )
    assert entries[shell_index]["config"] == {
        "id": "desktop.authenticated-shell-surface",
        "kind": "ui-slot",
        "order": 80,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.authenticated-shell-surface.v2"],
            "schema_version": 1,
        },
    }
    assert entries[session_canvas_index]["config"] == {
        "id": "desktop.session-canvas-surface",
        "kind": "ui-slot",
        "order": 85,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.session-canvas-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[workbench_index]["config"] == {
        "id": "desktop.workbench-surface",
        "kind": "ui-slot",
        "order": 90,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.workbench-surface.v2"],
            "schema_version": 1,
        },
    }
    assert entries[workspace_collaboration_index]["config"] == {
        "id": "desktop.workspace-collaboration-surface",
        "kind": "ui-slot",
        "order": 92,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.workspace-collaboration-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[new_thread_composer_index]["config"] == {
        "id": "desktop.new-thread-composer-surface",
        "kind": "ui-slot",
        "order": 93,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.new-thread-composer-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[my_work_queue_index]["config"] == {
        "id": "desktop.my-work-queue-surface",
        "kind": "ui-slot",
        "order": 94,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.my-work-queue-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[activity_inbox_index]["config"] == {
        "id": "desktop.activity-inbox-surface",
        "kind": "ui-slot",
        "order": 95,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.activity-inbox-surface.v1"],
            "schema_version": 1,
        },
    }
