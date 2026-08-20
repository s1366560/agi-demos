"""Unit tests for the I5 Python WASM host."""

from __future__ import annotations

import hashlib

import pytest

from src.domain.ports.plugins import ResourceQuota
from src.infrastructure.plugins.governance import (
    PluginQuotaExceededError,
    ResourceQuotaEnforcer,
)
from src.infrastructure.plugins.wasm_host import (
    WasmHostError,
    WasmToolHost,
)

SCORER_WAT = """
(module
  (func (export "score") (param i32) (result i32)
    local.get 0
    i32.const 7
    i32.add))
"""

SPIN_WAT = """
(module
  (func (export "score") (param i32) (result i32)
    (loop $l (br $l))
    i32.const 0))
"""

NO_SCORE_WAT = '(module (func (export "noop") (result i32) i32.const 1))'


@pytest.mark.unit
class TestWasmToolHost:
    def test_call_runs_score_with_audit(self) -> None:
        events: list[dict[str, object]] = []
        host = WasmToolHost("plug", SCORER_WAT.encode(), audit=events.append)

        outcome = host.call("demo", '{"x": 1}')

        assert outcome.score == len('{"x": 1}') + 7
        assert outcome.fuel_consumed > 0
        assert outcome.wall_time_ms >= 0
        assert events[0]["event"] == "wasm_tool_call"
        assert events[0]["result"] == "ok"
        assert events[0]["plugin_id"] == "plug"

    def test_digest_mismatch_rejected(self, tmp_path) -> None:
        artifact = tmp_path / "plugin.wasm"
        raw = SCORER_WAT.encode()
        artifact.write_bytes(raw)
        with pytest.raises(WasmHostError, match="digest mismatch"):
            WasmToolHost.from_path("plug", artifact, expected_sha256="0" * 64)
        host = WasmToolHost.from_path(
            "plug", artifact, expected_sha256=hashlib.sha256(raw).hexdigest()
        )
        assert host.call("demo", "").score == 7

    def test_missing_score_export_rejected(self) -> None:
        with pytest.raises(WasmHostError, match="score"):
            WasmToolHost("plug", NO_SCORE_WAT.encode())

    def test_fuel_quota_trap_isolated(self) -> None:
        host = WasmToolHost("plug", SPIN_WAT.encode(), fuel_budget=1_000)
        with pytest.raises(WasmHostError, match="wasm execution failed"):
            host.call("demo", "")

    def test_fuel_quota_enforcer_blocks_over_budget(self) -> None:
        enforcer = ResourceQuotaEnforcer({"plug": ResourceQuota(max_wasm_fuel=10)})
        events: list[dict[str, object]] = []
        host = WasmToolHost(
            "plug", SCORER_WAT.encode(), quota_enforcer=enforcer, audit=events.append
        )
        with pytest.raises(PluginQuotaExceededError):
            host.call("demo", "")
        assert events[0]["result"] == "error"

    def test_concurrent_quota_release_after_call(self) -> None:
        enforcer = ResourceQuotaEnforcer({"plug": ResourceQuota(max_concurrent_calls=1)})
        host = WasmToolHost("plug", SCORER_WAT.encode(), quota_enforcer=enforcer)
        host.call("demo", "")
        # Second call must not hit the concurrency ceiling: released in finally.
        host.call("demo", "")
