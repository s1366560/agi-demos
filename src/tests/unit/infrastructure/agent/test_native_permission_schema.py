"""Schema portability must preserve the cooperative native consent boundary."""

from types import SimpleNamespace

import pytest

from src.infrastructure.agent.native_computer_use.permission import (
    _target_permission,
    native_permission_tool,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


async def test_native_permission_cannot_execute_outside_the_cooperative_processor():
    with pytest.raises(RuntimeV2Error) as error:
        await native_permission_tool().execute(SimpleNamespace())
    assert error.value.code == "native_permission_processor_required"


async def test_missing_host_permission_record_cannot_create_consent():
    assert await _target_permission(SimpleNamespace(), {}, "unbound-target") is None


async def test_malformed_host_permission_record_is_rejected_without_echoing_input():
    with pytest.raises(RuntimeV2Error) as error:
        await _target_permission(
            SimpleNamespace(), {"permission_required": {"untrusted": "fixture-private"}}, "target"
        )
    assert error.value.code == "computer_use_pending_invalid"
    assert "fixture-private" not in str(error.value)
