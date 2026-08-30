"""Production target-catalog coverage for protocol v2."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.infrastructure.plugins.v2.composer import compose_profile_v2, parse_profile_document_v2
from src.infrastructure.plugins.v2.protocol import (
    parse_plugin_manifest_v2,
    parse_profile_snapshot_v2,
)

_ROOT = Path(__file__).resolve().parents[4]
_CATALOG = _ROOT / "shared/catalogs/plugin-module-catalog.v2.json"
_BOOTSTRAP = _ROOT / "shared/profiles/memstack-default-bootstrap.v2.json"
_MANIFESTS = _ROOT / "config/plugin-manifests-v2"
_PRODUCTION_PROFILE = _ROOT / "config/plugin-profiles/memstack-production-target-hosts.v2.yaml"

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
    session_workspace_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-session-workspace-surface"
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
    conversation_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-conversation-surface"
    )
    conversation_renderer_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-conversation-renderer"
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
    assert len(entries) == 327
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
        < session_workspace_index
        < workspace_collaboration_index
        < new_thread_composer_index
        < my_work_queue_index
        < activity_inbox_index
        < conversation_index
        < conversation_renderer_index
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
    assert entries[session_workspace_index]["config"] == {
        "id": "desktop.session-workspace-surface",
        "kind": "ui-slot",
        "order": 91,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.session-workspace-surface.v1"],
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
    assert entries[conversation_index]["config"] == {
        "id": "desktop.conversation-surface",
        "kind": "ui-slot",
        "order": 96,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.conversation-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[conversation_renderer_index]["config"] == {
        "id": "desktop.conversation-renderer",
        "kind": "ui-slot",
        "order": 97,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.conversation-renderer.v1"],
            "schema_version": 1,
        },
    }
    assert entries[conversation_renderer_index]["permissions"] == ["ui.conversation.renderer"]


@pytest.mark.unit
def test_conversation_renderer_supports_explicit_profile_replace_and_disable() -> None:
    payload = yaml.safe_load(_PRODUCTION_PROFILE.read_text(encoding="utf-8"))
    renderer = next(
        entry
        for entry in payload["profile"]["entries"]
        if entry["entry_id"] == "builtin-desktop-conversation-renderer"
    )
    manifests = {}
    for path in sorted(_MANIFESTS.glob("*.v2.json")):
        manifest = parse_plugin_manifest_v2(json.loads(path.read_text(encoding="utf-8")))
        manifests[manifest.plugin_id] = manifest

    replacement = deepcopy(renderer)
    replacement["config"]["order"] = 98
    replaced_payload = deepcopy(payload)
    replaced_payload["patches"] = [{"target": renderer["entry_id"], "replacement": replacement}]
    replaced = compose_profile_v2(
        parse_profile_document_v2(replaced_payload),
        manifests,
        generation=901,
    )
    replaced_entry = next(
        entry for entry in replaced.entries if entry.entry_id == renderer["entry_id"]
    )
    assert replaced_entry.enabled is True
    assert replaced_entry.config["order"] == 98

    disabled_replacement = deepcopy(renderer)
    disabled_replacement["enabled"] = False
    disabled_payload = deepcopy(payload)
    disabled_payload["patches"] = [
        {"target": renderer["entry_id"], "replacement": disabled_replacement}
    ]
    disabled = compose_profile_v2(
        parse_profile_document_v2(disabled_payload),
        manifests,
        generation=902,
    )
    disabled_entry = next(
        entry for entry in disabled.entries if entry.entry_id == renderer["entry_id"]
    )
    assert disabled_entry.enabled is False
