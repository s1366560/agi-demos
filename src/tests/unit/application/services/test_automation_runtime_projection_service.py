from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.services.automation_runtime_projection_service import (
    AutomationRuntimeIdentity,
    AutomationRuntimeOutcome,
    AutomationRuntimeProjection,
    AutomationRuntimeProjectionService,
    AutomationRuntimeTerminal,
)

pytestmark = pytest.mark.unit


class _FakeRepository:
    def __init__(self) -> None:
        self.running_calls = 0
        self.waiting_calls = 0
        self.terminal_calls = 0

    async def mark_running(self, **_kwargs) -> AutomationRuntimeProjection:
        self.running_calls += 1
        return AutomationRuntimeProjection(matched=True, run_status="running")

    async def project_terminal(self, **_kwargs) -> AutomationRuntimeProjection:
        self.terminal_calls += 1
        return AutomationRuntimeProjection(matched=True, run_status="success")

    async def mark_waiting_human(self, **_kwargs) -> AutomationRuntimeProjection:
        self.waiting_calls += 1
        return AutomationRuntimeProjection(matched=True, run_status="waiting_human")


def _identity(**overrides: str) -> AutomationRuntimeIdentity:
    values = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "runtime_execution_id": "run-1",
        "conversation_id": "conversation-1",
    }
    values.update(overrides)
    return AutomationRuntimeIdentity(**values)


async def test_projection_service_accepts_only_structured_runtime_facts() -> None:
    repository = _FakeRepository()
    service = AutomationRuntimeProjectionService(repository)
    observed_at = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)

    running = await service.mark_running(identity=_identity(), observed_at=observed_at)
    waiting = await service.mark_waiting_human(identity=_identity(), observed_at=observed_at)
    terminal = await service.project_terminal(
        identity=_identity(),
        terminal=AutomationRuntimeTerminal(
            outcome=AutomationRuntimeOutcome.SUCCESS,
            observed_at=observed_at,
            execution_time_ms=123.5,
            event_count=4,
        ),
    )

    assert running.run_status == "running"
    assert waiting.run_status == "waiting_human"
    assert terminal.run_status == "success"
    assert repository.running_calls == 1
    assert repository.waiting_calls == 1
    assert repository.terminal_calls == 1


@pytest.mark.parametrize(
    ("identity", "terminal"),
    [
        (_identity(runtime_execution_id=" "), None),
        (
            _identity(),
            AutomationRuntimeTerminal(
                outcome=AutomationRuntimeOutcome.FAILED,
                observed_at=datetime(2026, 7, 14, 12, 0),
                execution_time_ms=1,
                event_count=1,
            ),
        ),
        (
            _identity(),
            AutomationRuntimeTerminal(
                outcome=AutomationRuntimeOutcome.FAILED,
                observed_at=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
                execution_time_ms=-1,
                event_count=1,
            ),
        ),
    ],
)
async def test_projection_service_rejects_invalid_structural_facts(
    identity: AutomationRuntimeIdentity,
    terminal: AutomationRuntimeTerminal | None,
) -> None:
    service = AutomationRuntimeProjectionService(_FakeRepository())

    with pytest.raises(ValueError):
        if terminal is None:
            await service.mark_running(
                identity=identity,
                observed_at=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
            )
        else:
            await service.project_terminal(identity=identity, terminal=terminal)


def test_runtime_outcomes_expose_stable_codes_without_free_form_errors() -> None:
    assert AutomationRuntimeOutcome.SUCCESS.error_code is None
    assert AutomationRuntimeOutcome.FAILED.error_code == "agent_execution_failed"
    assert AutomationRuntimeOutcome.CANCELLED.error_code == "agent_execution_cancelled"
    assert AutomationRuntimeOutcome.TIMEOUT.error_code == "agent_execution_timed_out"
