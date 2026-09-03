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
            "builtin://memstack/desktop/artifact-content-authority",
            "builtin://memstack/desktop/automation-authority",
            "builtin://memstack/desktop/conversation-config-authority",
            "builtin://memstack/desktop/conversation-lifecycle-authority",
            "builtin://memstack/desktop/hitl-response-authority",
            "builtin://memstack/desktop/my-work-authority",
            "builtin://memstack/desktop/new-task-flow-authority",
            "builtin://memstack/desktop/new-thread-creation-authority",
            "builtin://memstack/desktop/project-agent-dashboard-authority",
            "builtin://memstack/desktop/project-agent-logs-authority",
            "builtin://memstack/desktop/project-agent-patterns-authority",
            "builtin://memstack/desktop/project-communities-authority",
            "builtin://memstack/desktop/project-entities-authority",
            "builtin://memstack/desktop/project-graph-authority",
            "builtin://memstack/desktop/project-memories-authority",
            "builtin://memstack/desktop/project-blackboard-authority",
            "builtin://memstack/desktop/project-overview-authority",
            "builtin://memstack/desktop/project-search-authority",
            "builtin://memstack/desktop/runtime-clusters-authority",
            "builtin://memstack/desktop/runtime-pool-authority",
            "builtin://memstack/desktop/session-artifact-action-authority",
            "builtin://memstack/desktop/plugin-marketplace-catalog-authority",
            "builtin://memstack/desktop/plugin-marketplace-management-authority",
            "builtin://memstack/desktop/renderer-host",
            "builtin://memstack/desktop/renderer-contribution-registry",
            "builtin://memstack/desktop/renderer-contribution",
            "builtin://memstack/desktop/session-projection-authority",
            "builtin://memstack/desktop/session-run-changes-authority",
            "builtin://memstack/desktop/session-run-input-authority",
            "builtin://memstack/desktop/session-run-control-authority",
            "builtin://memstack/desktop/session-timeline-authority",
            "builtin://memstack/desktop/tenant-agent-bindings-authority",
            "builtin://memstack/desktop/tenant-agent-dashboard-authority",
            "builtin://memstack/desktop/tenant-analytics-authority",
            "builtin://memstack/desktop/tenant-catalog-authority",
            "builtin://memstack/desktop/tenant-overview-authority",
            "builtin://memstack/desktop/tenant-projects-authority",
            "builtin://memstack/desktop/tenant-tasks-authority",
            "builtin://memstack/desktop/terminal-lifecycle-authority",
            "builtin://memstack/desktop/workspace-catalog-authority",
            "builtin://memstack/desktop/workspace-lifecycle-authority",
            "builtin://memstack/desktop/workspace-roster-authority",
            "builtin://memstack/desktop/workspace-agent-binding-authority",
            "builtin://memstack/desktop/workspace-autonomy-attention-authority",
            "builtin://memstack/desktop/workspace-member-mutation-authority",
            "builtin://memstack/desktop/workspace-conversation-catalog-authority",
            "builtin://memstack/desktop/workspace-context-authority",
            "builtin://memstack/desktop/workspace-execution-snapshot-authority",
            "builtin://memstack/desktop/workspace-message-catalog-authority",
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
    status_bar_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-status-bar-surface"
    )
    command_palette_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-command-palette-surface"
    )
    workspace_create_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-workspace-create-surface"
    )
    workspace_settings_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-workspace-settings-surface"
    )
    titlebar_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-titlebar-surface"
    )
    workbench_tab_bar_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-workbench-tab-bar-surface"
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
    sidebar_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-sidebar-surface"
    )
    right_sidebar_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-right-sidebar-surface"
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
    assert len(entries) == 384
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
        < status_bar_index
        < command_palette_index
        < session_canvas_index
        < workspace_create_index
        < workspace_settings_index
        < titlebar_index
        < workbench_tab_bar_index
        < workbench_index
        < session_workspace_index
        < workspace_collaboration_index
        < new_thread_composer_index
        < my_work_queue_index
        < activity_inbox_index
        < conversation_index
        < conversation_renderer_index
        < sidebar_index
        < right_sidebar_index
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
    assert entries[status_bar_index]["config"] == {
        "id": "desktop.status-bar-surface",
        "kind": "ui-slot",
        "order": 83,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.status-bar-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[command_palette_index]["config"] == {
        "id": "desktop.command-palette-surface",
        "kind": "ui-slot",
        "order": 84,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.command-palette-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[workspace_create_index]["config"] == {
        "id": "desktop.workspace-create-surface",
        "kind": "ui-slot",
        "order": 86,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.workspace-create-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[workspace_settings_index]["config"] == {
        "id": "desktop.workspace-settings-surface",
        "kind": "ui-slot",
        "order": 87,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.workspace-settings-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[titlebar_index]["config"] == {
        "id": "desktop.titlebar-surface",
        "kind": "ui-slot",
        "order": 88,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.titlebar-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[workbench_tab_bar_index]["config"] == {
        "id": "desktop.workbench-tab-bar-surface",
        "kind": "ui-slot",
        "order": 89,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.workbench-tab-bar-surface.v1"],
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
    assert entries[sidebar_index]["config"] == {
        "id": "desktop.sidebar-surface",
        "kind": "ui-slot",
        "order": 99,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.sidebar-surface.v1"],
            "schema_version": 1,
        },
    }
    assert entries[right_sidebar_index]["config"] == {
        "id": "desktop.right-sidebar-surface",
        "kind": "ui-slot",
        "order": 100,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.right-sidebar-surface.v1"],
            "schema_version": 1,
        },
    }


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
