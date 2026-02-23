"""Unit tests for mutation audit ledger and loop guard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.infrastructure.agent.tools.mutation_ledger import MutationLedger


@pytest.mark.unit
def test_mutation_ledger_append_and_loop_guard_blocking(tmp_path) -> None:
    """Loop guard should block when fingerprint repeats within configured window."""
    ledger = MutationLedger(tmp_path / "mutation-ledger.json", max_records=100)
    fingerprint = "tool=plugin_manager|action=disable|plugin_name=demo"

    ledger.append(
        {
            "mutation_fingerprint": fingerprint,
            "status": "applied",
            "action": "disable",
        }
    )
    ledger.append(
        {
            "mutation_fingerprint": fingerprint,
            "status": "failed",
            "action": "disable",
        }
    )
    result = ledger.evaluate_loop_guard(fingerprint, threshold=2, window_seconds=300)

    assert result["blocked"] is True
    assert result["recent_count"] == 2


@pytest.mark.unit
def test_mutation_ledger_loop_guard_ignores_stale_and_dry_run(tmp_path) -> None:
    """Loop guard should ignore stale records and dry-run status entries."""
    ledger = MutationLedger(tmp_path / "mutation-ledger.json", max_records=100)
    fingerprint = "tool=plugin_manager|action=reload"
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=3600)).isoformat()
    ledger.append(
        {
            "timestamp": stale_time,
            "mutation_fingerprint": fingerprint,
            "status": "applied",
            "action": "reload",
        }
    )
    ledger.append(
        {
            "mutation_fingerprint": fingerprint,
            "status": "dry_run",
            "action": "reload",
        }
    )

    result = ledger.evaluate_loop_guard(fingerprint, threshold=1, window_seconds=120)
    assert result["blocked"] is False
    assert result["recent_count"] == 0
