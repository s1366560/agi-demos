"""Phase 0 gates: tenant routes, command schemas, and the shared permission set."""

import json
import re
from pathlib import Path

import pytest
from memstack_plugin_sdk.contract import PERMISSIONS, parse_contribution

from src.infrastructure.plugins.v2.command_schema import validate_command_document
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[6]
CONTRIBUTIONS = (
    ROOT / "plugins/business/agent/contributions.json",
    ROOT / "plugins/business/workspace/contributions.json",
    ROOT / "plugins/business/knowledge/workers/graph_projection/contributions.json",
    ROOT / "plugins/business/automation/contributions.json",
    ROOT / "plugins/business/environments/contributions.json",
    ROOT / "plugins/business/billing/contributions.json",
)


def test_business_pages_scope_tenant_routes_and_publish_command_schemas():
    for path in CONTRIBUTIONS:
        parsed = parse_contribution(json.loads(path.read_text()))
        assert parsed.commands
        for command in parsed.commands:
            assert command.input_schema["type"] == "object"
            assert command.output_schema["type"] == "object"
        for page in parsed.pages:
            for route in page.routes:
                parts = route.split("/")
                if len(parts) >= 3 and parts[1] == "tenant" and ":projectId" not in parts:
                    assert page.scope == "tenant", route
        for page in parsed.pages:
            if page.id in {"tenant-directory", "tenant-create"}:
                assert page.commands == ()
                assert page.entry is not None
                assert page.entry.path == "ui/tenant-scope.js"
                script = (path.parent / page.entry.path).read_text()
                assert "invoke" not in script
                assert "project_required" not in script
            if page.id == "tenant-chat":
                assert page.commands == (
                    "tenant-session-list",
                    "tenant-session-create",
                    "tenant-session-open",
                )
                assert page.entry is not None
                script = (path.parent / page.entry.path).read_text()
                assert "tenant-session-list" in script
                assert "project_required" not in script


def test_command_schema_rejects_values_outside_the_draft_2020_12_contract():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"title": {"type": "string", "maxLength": 3}},
        "required": ["title"],
    }
    validate_command_document(schema, {"title": "ok"}, "input_schema")
    with pytest.raises(OptionalBusinessError, match="maxLength|is too long|longer") as denied:
        validate_command_document(schema, {"title": "abcd"}, "input_schema")
    assert denied.value.code == "input_schema"


def test_typescript_permission_closed_set_matches_python():
    source = (ROOT / "sdk/memstack-plugin-sdk/src/index.ts").read_text()
    block = re.search(r"export const PERMISSIONS = \[(.*?)\n\] as const", source, re.S)
    assert block is not None
    typescript = set(re.findall(r"'([^']+)'", block.group(1)))
    assert typescript == set(PERMISSIONS)
    assert {"subagents.register", "ui.media.microphone"} <= typescript
