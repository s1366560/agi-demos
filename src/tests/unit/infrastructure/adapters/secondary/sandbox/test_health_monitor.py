from typing import Any, cast

import pytest

from src.infrastructure.adapters.secondary.sandbox.health_monitor import (
    EnhancedHealthMonitor,
    HealthCheckLevel,
    HealthCheckResult,
)


class RebuildCapableAdapter:
    def __init__(self, recovered: bool) -> None:
        self.recovered = recovered
        self.rebuild_calls: list[str] = []

    async def _ensure_sandbox_healthy(self, sandbox_id: str) -> bool:
        self.rebuild_calls.append(sandbox_id)
        return self.recovered


class NoRebuildAdapter:
    pass


@pytest.mark.unit
async def test_attempt_recovery_rebuilds_stopped_container() -> None:
    adapter = RebuildCapableAdapter(recovered=True)
    monitor = EnhancedHealthMonitor(
        sandbox_adapter=cast(Any, adapter),
        recovery_backoff_base=0,
    )
    recovered_callbacks: list[tuple[str, bool]] = []

    async def on_recovered(sandbox_id: str, result: HealthCheckResult) -> None:
        recovered_callbacks.append((sandbox_id, result.recovery_succeeded))

    monitor.on_recovered(on_recovered)
    result = HealthCheckResult(
        sandbox_id="sandbox-1",
        healthy=False,
        level=HealthCheckLevel.MCP,
        container_running=False,
    )

    recovered = await monitor._attempt_recovery("sandbox-1", result)

    assert recovered is True
    assert adapter.rebuild_calls == ["sandbox-1"]
    assert result.recovery_attempted is True
    assert result.recovery_succeeded is True
    assert recovered_callbacks == [("sandbox-1", True)]
    assert await monitor._recovery_attempts.get("sandbox-1") is None


@pytest.mark.unit
async def test_attempt_recovery_reports_failure_when_rebuild_unavailable() -> None:
    monitor = EnhancedHealthMonitor(
        sandbox_adapter=cast(Any, NoRebuildAdapter()),
        recovery_backoff_base=0,
    )
    result = HealthCheckResult(
        sandbox_id="sandbox-1",
        healthy=False,
        level=HealthCheckLevel.MCP,
        container_running=False,
    )

    recovered = await monitor._attempt_recovery("sandbox-1", result)

    assert recovered is False
    assert result.recovery_attempted is True
    assert result.recovery_succeeded is False
