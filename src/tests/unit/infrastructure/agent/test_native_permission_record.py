"""Strict wire parsing and exact stored-step provenance, independent of tool text."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.native_computer_use.permission_result import (
    decode_record,
    input_digest,
    validate_claim,
)
from src.infrastructure.agent.native_computer_use.steps import SCOPE_FIELDS, ExecutionSteps
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError

pytestmark = pytest.mark.unit


def wire():
    return {
        "kind": "native_consent",
        "binding": {
            "tool_name": "computer_get_app_state",
            "input_digest": input_digest("{}"),
            "engine_session_id": "engine",
            "cell_id": None,
            "step_id": None,
        },
        "demand": {
            "error": "cua_permission_required",
            "scopes": ["once"],
            "request": {
                "request_id": "pending",
                "session_id": "physical",
                "engine_session_id": "engine",
                "tool_name": "computer_get_app_state",
                "input_digest": "native-digest",
                "app": "fixture",
                "identity_digest": "identity",
                "capability": "observe",
            },
        },
    }


def test_jcs_digest_matches_rust_vector_and_rejects_ambiguous_numbers():
    expected = "735951eb0cfbd0f8bb1dc38e0816a770481161da378d6dbff078a4596ff19c7e"
    assert input_digest('{"z":1,"a":{"中文":"值","items":[true,null,1]}}') == expected
    assert input_digest('{ "a": {"items":[true,null,1.0],"中文":"值"},"z":1.0 }') == expected
    for raw in ["{", '{"n":9007199254740992}', '{"n":NaN}', '{"n":Infinity}']:
        with pytest.raises(DeviceBridgeError, match="input_invalid"):
            input_digest(raw)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(kind=[]),
        lambda value: value.update(demand=[]),
        lambda value: value["demand"].update(scopes=[[]]),
        lambda value: value["demand"]["request"].update(capability="execution_step"),
        lambda value: value["demand"].update(untrusted=float("nan")),
        lambda value: value["binding"].update(cell_id="cell"),
    ],
)
def test_malformed_separate_records_fail_closed(change):
    value = wire()
    change(value)
    with pytest.raises(DeviceBridgeError):
        decode_record(value)


async def test_inner_native_requires_exact_released_row_and_retains_immutable_demand():
    record = {key: key for key in SCOPE_FIELDS}
    record.update(
        request_id="outer", session_id="engine", tool_name="cua_repl_js", authorization_revision=3
    )
    value = wire()
    value["binding"].update(cell_id="cell", step_id="step")
    permission = decode_record(value)
    step = {
        **record,
        "current_request_id": "outer",
        "cell_id": "cell",
        "step_id": "step",
        "tool_name": "computer_get_app_state",
        "permission_input_digest": input_digest("{}"),
        "status": "released",
        "last_outcome": "not_sent",
    }
    broker = SimpleNamespace(
        members=AsyncMock(return_value=["gone", "row"]),
        read=AsyncMock(side_effect=lambda key: None if key == "gone" else step),
    )
    await validate_claim(broker, record, permission)
    value["demand"]["request"]["request_id"] = "mutated"
    assert permission.demand["request"]["request_id"] == "pending"
    copy = permission.demand
    copy["request"]["request_id"] = "mutated"
    assert permission.demand["request"]["request_id"] == "pending"
    for field, changed in [
        ("status", "consumed"),
        ("last_outcome", "unknown"),
        ("authorization_revision", 4),
        ("current_request_id", "foreign"),
    ]:
        original = step[field]
        step[field] = changed
        with pytest.raises(DeviceBridgeError):
            await validate_claim(broker, record, permission)
        step[field] = original
    broker.members.return_value = []
    with pytest.raises(DeviceBridgeError, match="step_missing"):
        await validate_claim(broker, record, permission)


async def test_inner_cloud_requires_pending_exact_demand_and_single_matching_row():
    record = {key: key for key in SCOPE_FIELDS}
    record.update(
        request_id="outer", session_id="engine", tool_name="cua_repl_js", authorization_revision=3
    )
    step = {
        **record,
        "current_request_id": "outer",
        "origin_request_id": "outer",
        "cell_id": "cell",
        "step_id": "step",
        "tool_name": "browser_write_operation",
        "permission_input_digest": input_digest("{}"),
        "input_digest": "raw",
        "status": "pending",
        "permission_id": "pending",
        "step_key": "key",
        "code_digest": "code",
        "catalog_digest": "catalog",
        "target": {"kind": "browser", "id": "iab/7"},
    }
    value = wire()
    value.update(kind="cloud_execution_step")
    value["binding"].update(cell_id="cell", step_id="step", tool_name=step["tool_name"])
    value["demand"]["request"] = ExecutionSteps.pending(step)
    permission = decode_record(value)
    broker = SimpleNamespace(
        members=AsyncMock(return_value=["row"]), read=AsyncMock(return_value=step)
    )
    await validate_claim(broker, record, permission)
    changed = deepcopy(value)
    changed["demand"]["request"]["execution_step"]["target"]["id"] = "foreign"
    with pytest.raises(DeviceBridgeError, match="step_changed"):
        await validate_claim(broker, record, decode_record(changed))
    broker.members.return_value = ["row", "duplicate"]
    with pytest.raises(DeviceBridgeError, match="step_missing"):
        await validate_claim(broker, record, permission)
    value["binding"].update(cell_id=None, step_id=None)
    with pytest.raises(DeviceBridgeError, match="source_invalid"):
        decode_record(value)
