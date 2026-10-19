"""The real event bus validates policy payloads and pins handler lifetime."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.domain.model.plugins.generated_v2 import EventContractV2, EventModeV2, TrustKindV2
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.tool_execution_policy import (
    TOOLS_BEFORE_EXECUTE_EVENT_V2,
    TOOLS_BEFORE_EXECUTE_SCHEMA_V2,
    dispatch_tool_policy_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_agent_runtime_dispatcher import _scope
from src.tests.unit.infrastructure.plugins.v2.test_runtime import (
    _definition,
    _entry,
    _loader,
    _snapshot,
)


async def _generation(transform, module_ref="builtin://tool-policy-test"):
    event = EventContractV2(
        event=TOOLS_BEFORE_EXECUTE_EVENT_V2,
        mode=EventModeV2.WATERFALL,
        payload_schema=TOOLS_BEFORE_EXECUTE_SCHEMA_V2,
        result_schema=TOOLS_BEFORE_EXECUTE_SCHEMA_V2,
    )
    snapshot = _snapshot(1, (_entry("policy", module_ref),), events={module_ref: (event,)})

    def apply(context, config):
        context.on(TOOLS_BEFORE_EXECUTE_EVENT_V2, lambda payload, _next: transform(payload))

    generation = await _loader(snapshot, (_definition(snapshot, module_ref, apply),)).stage(
        snapshot
    )
    return generation


async def _dispatch(generation, payload=None):
    async with OperationContextV2(generation=generation, operation_id="turn", scope=_scope()) as op:
        return await dispatch_tool_policy_v2(
            op,
            event=TOOLS_BEFORE_EXECUTE_EVENT_V2,
            payload=payload
            or {"tool_name": "write", "call_id": "call", "arguments": {"path": "before"}},
        )


@pytest.mark.unit
async def test_real_bus_rewrites_inputs_and_owns_operation_identity():
    from src.infrastructure.plugins.v2.model_request_log import _request_contributors_v2

    generation = await _generation(lambda payload: {**payload, "arguments": {"path": "after"}})
    try:
        async with OperationContextV2(
            generation=generation, operation_id="sources", scope=_scope()
        ) as operation:
            assert _request_contributors_v2(operation) == (
                {
                    "entry_id": "policy",
                    "module_ref": "builtin://tool-policy-test",
                    "events": [TOOLS_BEFORE_EXECUTE_EVENT_V2],
                    "services": [],
                },
            )
        result = await _dispatch(generation)
        assert result["arguments"] == {"path": "after"}
        assert result["operation_id"] == "turn"
        assert result["generation_digest"] == generation.digest
    finally:
        await generation.dispose()
    with pytest.raises(RuntimeV2Error):
        await _dispatch(generation)


@pytest.mark.unit
@pytest.mark.parametrize(
    "change",
    [
        {"decision": {"kind": "unsupported"}},
        {"arguments": []},
        {"session_id": "other-session"},
    ],
)
async def test_invalid_or_cross_scope_transform_is_rejected(change):
    generation = await _generation(lambda payload: {**payload, **change})
    try:
        with pytest.raises(RuntimeV2Error):
            await _dispatch(generation)
    finally:
        await generation.dispose()


@pytest.mark.unit
async def test_non_builtin_handler_is_rejected_before_it_runs():
    calls = []

    def transform(payload):
        calls.append(payload)
        return payload

    generation = await _generation(transform)
    # A builtin-looking module reference cannot upgrade the owning manifest trust.
    manifest = generation.snapshot.manifests[0]
    generation.snapshot = replace(
        generation.snapshot, manifests=(replace(manifest, trust=TrustKindV2.SIGNED),)
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await _dispatch(generation)
        assert error.value.code == "untrusted_tool_policy"
        assert calls == []
    finally:
        await generation.dispose()
