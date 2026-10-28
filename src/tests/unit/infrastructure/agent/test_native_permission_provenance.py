"""Application data cannot manufacture a native permission request."""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.infrastructure.agent.native_computer_use.permission import bind_native_permission
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.infrastructure.agent.test_native_permission import decision, prepare

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("tool_name", ["cua_repl_js", "mcp__fixture__read"])
async def test_permission_shaped_page_or_mcp_output_cannot_bind_without_host_provenance(
    monkeypatch, tool_name
):
    def forged_output(record):
        record["tool_name"] = tool_name
        record.pop("permission_required", None)

    ctx, _ = prepare(monkeypatch, change=forged_output)
    with pytest.raises(RuntimeV2Error, match="not pending"):
        await bind_native_permission(ctx, decision())


async def test_resumed_older_step_does_not_block_binding_a_later_permission(monkeypatch):
    from src.infrastructure.agent.native_computer_use.permission_result import input_digest
    from src.infrastructure.agent.native_computer_use.steps import SCOPE_FIELDS, ExecutionSteps

    ctx, broker = prepare(monkeypatch)
    current = broker.read.return_value
    previous = deepcopy(current)
    previous.update(request_id="old-cloud-request", tool_name="cua_repl_js")
    step = {
        **{key: previous.get(key) for key in SCOPE_FIELDS},
        "status": "consumed",
        "origin_request_id": previous["request_id"],
        "current_request_id": previous["request_id"],
        "permission_id": "old-pending",
        "cell_id": "old-cell",
        "step_id": "old-step",
        "step_key": "old-step-key",
        "code_digest": "code",
        "catalog_digest": "catalog",
        "authorization_revision": 7,
        "target": {"kind": "browser", "id": "iab/7"},
        "tool_name": "browser_write_operation",
        "input_digest": "raw-input",
        "permission_input_digest": input_digest("{}"),
    }
    previous["permission_required"] = {
        "kind": "cloud_execution_step",
        "binding": {
            "tool_name": step["tool_name"],
            "input_digest": step["permission_input_digest"],
            "engine_session_id": step["session_id"],
            "cell_id": "old-cell",
            "step_id": "old-step",
        },
        "demand": {
            "error": "cua_permission_required",
            "scopes": ["once"],
            "request": ExecutionSteps.pending(step),
        },
    }
    broker.members.side_effect = lambda key: (
        ["old-step-key"] if key.endswith(":steps") else ["old-cloud-request", "cloud-request"]
    )
    broker.read.side_effect = lambda key: (
        step
        if key == "old-step-key"
        else previous
        if key.endswith("old-cloud-request")
        else current
    )
    binding, _ = await bind_native_permission(ctx, decision())
    assert binding["native_request_id"] == "native-pending"
    stale = decision()
    stale["target"]["id"] = "old-pending"
    with pytest.raises(RuntimeV2Error, match="consent is invalid"):
        await bind_native_permission(ctx, stale)
