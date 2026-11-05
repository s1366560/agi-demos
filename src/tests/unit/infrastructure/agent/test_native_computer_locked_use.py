"""Locked Use remains a closed, mutating, exact-input first-party capability."""

from __future__ import annotations

import hashlib
import json

import pytest

from src.infrastructure.agent.native_computer_use.catalog import validate_tool_definition
from src.infrastructure.agent.native_computer_use.contracts import READ_TOOL_NAMES, TOOL_NAMES
from src.infrastructure.agent.native_computer_use.effects import (
    tool_effect,
    validate_registered_call,
)
from src.infrastructure.agent.native_computer_use.steps import _next_state
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError

pytestmark = pytest.mark.unit
NAME = "computer_locked_use"
SCHEMA = {
    "type": "object",
    "properties": {"enabled": {"type": "boolean"}},
    "required": ["enabled"],
    "additionalProperties": False,
}
DEVICE = {"tool_definitions": [{"name": NAME, "description": "Locked Use", "inputSchema": SCHEMA}]}


@pytest.mark.parametrize("enabled", [True, False])
def test_locked_use_is_accepted_only_as_declared_mutation(enabled):
    validate_tool_definition(NAME, SCHEMA)
    assert NAME in TOOL_NAMES
    assert NAME not in READ_TOOL_NAMES
    assert tool_effect(NAME, SCHEMA, {"enabled": enabled}) == "mutate"


@pytest.mark.parametrize("name", ["computer_locked_use_other", "computer_new_tool"])
def test_unknown_computer_names_remain_closed(name):
    with pytest.raises(DeviceBridgeError, match="computer_use_invalid_catalog"):
        validate_tool_definition(name, SCHEMA)


def call(enabled, *, profile="read_only", approved=()):
    return {
        "tool_name": NAME,
        "input_json": json.dumps({"enabled": enabled}),
        "tool_effect": "mutate",
        "permission_profile": profile,
        "approved_tools": approved,
    }


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("profile", ["read_only", "workspace_write"])
def test_enable_and_release_both_require_outer_mutation_authority(enabled, profile):
    with pytest.raises(DeviceBridgeError, match="computer_use_run_permission_denied"):
        validate_registered_call(DEVICE, call(enabled, profile=profile))


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("profile,approved", [("full_access", ()), ("read_only", (NAME,))])
def test_exact_outer_authority_accepts_mutation_without_changing_native_consent(
    enabled, profile, approved
):
    assert (
        validate_registered_call(DEVICE, call(enabled, profile=profile, approved=approved))
        == "mutate"
    )


@pytest.mark.parametrize(
    "arguments",
    [{}, {"enabled": 1}, {"enabled": "false"}, {"enabled": False, "generation": "forged"}],
)
def test_locked_use_schema_rejects_missing_nonboolean_and_forged_generation(arguments):
    value = {**call(True, profile="full_access"), "input_json": json.dumps(arguments)}
    with pytest.raises(DeviceBridgeError, match="computer_use_invalid_params"):
        validate_registered_call(DEVICE, value)


@pytest.mark.parametrize("enabled", [True, False])
def test_release_is_not_reclassified_as_read(enabled):
    value = {**call(enabled, profile="full_access"), "tool_effect": "read"}
    with pytest.raises(DeviceBridgeError, match="computer_use_tool_effect_changed"):
        validate_registered_call(DEVICE, value)


def binding(enabled):
    return {
        "tool_name": NAME,
        "input_digest": hashlib.sha256(json.dumps({"enabled": enabled}).encode()).hexdigest(),
        "effect": "mutate",
        "run_id": "run",
        "session_id": "session",
        "cell_id": "cell",
        "step_id": "step",
    }


@pytest.mark.parametrize("enabled", [True, False])
def test_locked_use_step_still_waits_for_mutation_approval(enabled):
    parent = {
        "request_id": "parent",
        "permission_profile": "read_only",
        "authorization_revision": 1,
    }
    value = _next_state(None, binding(enabled), parent, "parent", "key", None)
    assert value["status"] == "pending"
    assert value["effect"] == "mutate"


@pytest.mark.parametrize(
    "field,value", [("run_id", "other"), ("session_id", "other"), ("input_digest", "other")]
)
def test_locked_use_step_receipt_rejects_changed_identity_or_input_and_replay(field, value):
    parent = {
        "request_id": "parent",
        "permission_profile": "full_access",
        "authorization_revision": 1,
    }
    original = binding(False)
    ready = _next_state(None, original, parent, "parent", "key", None)
    assert ready["status"] == "ready"
    with pytest.raises(DeviceBridgeError, match="computer_use_step_identity_changed"):
        _next_state(ready, {**original, field: value}, parent, "parent", "key", ready["receipt"])
    consumed = _next_state(ready, original, parent, "parent", "key", ready["receipt"])
    with pytest.raises(DeviceBridgeError, match="computer_use_step_already_consumed"):
        _next_state(consumed, original, parent, "parent", "key", ready["receipt"])
