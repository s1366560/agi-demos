"""Startup cutover gate tests for platform-plugin agent V2 modes."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

import src.infrastructure.plugins.cutover_gate as cutover_gate_module
from src.infrastructure.plugins.cutover_gate import (
    CutoverGateError,
    ensure_agent_v2_cutover_ready,
)


class FakeSession:
    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeRepository:
    def __init__(self, session: object) -> None:
        _ = session
        self.summary: list[dict[str, object]] = []
        self.scope_counts: list[dict[str, object]] = []
        self.apply_events: list[SimpleNamespace] = []

    async def shadow_rollout_summary(self) -> list[dict[str, object]]:
        return self.summary

    async def shadow_rollout_scope_counts(self) -> list[dict[str, object]]:
        return self.scope_counts

    async def list_apply_state_events(self, *, limit: int) -> list[SimpleNamespace]:
        _ = limit
        return self.apply_events


def settings(*, v2: bool) -> SimpleNamespace:
    return SimpleNamespace(
        platform_plugin_agent_events_v2=v2,
        platform_plugin_agent_tools_v2=v2,
    )


def complete_evidence(now: datetime) -> FakeRepository:
    repository = FakeRepository(FakeSession())
    repository.summary = [
        {
            "capability": capability,
            "event_name": event_name,
            "total_count": 100,
            "equal_count": 100,
            "diff_count": 0,
            "last_occurred_at": now,
        }
        for capability, event_name in (
            *[
                ("agent_events", event)
                for event in (
                    "agent.before_step",
                    "agent.before_request",
                    "tools.before_execute",
                    "tools.after_execute",
                    "agent.after_turn",
                )
            ],
            ("agent_tools", "agent.tool_generation"),
        )
    ]
    repository.scope_counts = [
        {"capability": "agent_events", "distinct_scope_count": 10},
        {"capability": "agent_tools", "distinct_scope_count": 10},
    ]
    repository.apply_events = [
        SimpleNamespace(
            id="receipt-1",
            data_plane_id="desktop-local",
            snapshot_digest="a" * 64,
            requested_version=101,
            applied_version=101,
            status="ack",
            error_message=None,
            recorded_at=now,
        ),
        SimpleNamespace(
            id="receipt-2",
            data_plane_id="desktop-local",
            snapshot_digest="b" * 64,
            requested_version=102,
            applied_version=101,
            status="nack",
            error_message="invalid artifact digest",
            recorded_at=now,
        ),
        SimpleNamespace(
            id="receipt-3",
            data_plane_id="desktop-local",
            snapshot_digest="c" * 64,
            requested_version=103,
            applied_version=103,
            status="ack",
            error_message=None,
            recorded_at=now,
        ),
    ]
    return repository


@pytest.mark.unit
async def test_cutover_gate_skips_database_when_agent_v2_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: settings(v2=False),
    )

    def fail_factory() -> Any:
        raise AssertionError("disabled V2 modes must not query cutover evidence")

    assert await ensure_agent_v2_cutover_ready(fail_factory) is None


@pytest.mark.unit
async def test_cutover_gate_rejects_v2_without_durable_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(FakeSession())
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: settings(v2=True),
    )
    monkeypatch.setattr(cutover_gate_module, "PlatformPluginRepository", lambda _s: repository)

    with pytest.raises(CutoverGateError) as error:
        await ensure_agent_v2_cutover_ready(FakeSession)

    reasons = error.value.readiness.reasons
    assert any(reason.startswith("shadow:agent_events:missing_event:") for reason in reasons)
    assert "rollback_drill:insufficient_rollback_drills:0:1" in reasons


@pytest.mark.unit
async def test_cutover_gate_accepts_complete_shadow_and_rollback_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    repository = complete_evidence(now)
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: settings(v2=True),
    )
    monkeypatch.setattr(cutover_gate_module, "PlatformPluginRepository", lambda _s: repository)

    readiness = await ensure_agent_v2_cutover_ready(FakeSession)

    assert readiness is not None
    assert readiness.ready is True
    assert readiness.shadow.ready is True
    assert readiness.rollback_drill.ready is True
