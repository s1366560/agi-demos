"""One exact protocol-v2 module and Profile entry per builtin runtime hook."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.plugins.v2.agent_events import (
    AGENT_BEFORE_REQUEST_EVENT_V2,
    AGENT_SESSION_START_EVENT_V2,
    TOOLS_AFTER_EXECUTE_EVENT_V2,
)
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.sisyphus_runtime import (
    SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2,
    SISYPHUS_BEFORE_REQUEST_MODULE_V2,
    SISYPHUS_SESSION_START_MODULE_V2,
)
from src.infrastructure.plugins.v2.workspace_runtime import (
    WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2,
    WORKSPACE_BEFORE_REQUEST_MODULE_V2,
    WORKSPACE_SESSION_START_MODULE_V2,
)

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_EVENT_MODULES = {
    AGENT_SESSION_START_EVENT_V2: (
        SISYPHUS_SESSION_START_MODULE_V2,
        WORKSPACE_SESSION_START_MODULE_V2,
    ),
    AGENT_BEFORE_REQUEST_EVENT_V2: (
        SISYPHUS_BEFORE_REQUEST_MODULE_V2,
        WORKSPACE_BEFORE_REQUEST_MODULE_V2,
    ),
    TOOLS_AFTER_EXECUTE_EVENT_V2: (
        SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2,
        WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2,
    ),
}


@pytest.mark.unit
def test_default_profile_has_one_entry_per_runtime_hook_in_event_order() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    runtime_modules = [
        entry.module_ref
        for entry in document.entries
        if entry.module_ref in {item for modules in _EVENT_MODULES.values() for item in modules}
    ]

    assert runtime_modules == [item for modules in _EVENT_MODULES.values() for item in modules]


@pytest.mark.unit
def test_each_runtime_hook_module_handles_exactly_one_fixed_mode_event() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    modules = {module.module_ref: module for module in manifest.modules}

    for event, module_refs in _EVENT_MODULES.items():
        for module_ref in module_refs:
            assert [contract.event for contract in modules[module_ref].contract.events.handles] == [
                event
            ]
            assert modules[module_ref].contract.events.handles[0].mode.value == "serial"
