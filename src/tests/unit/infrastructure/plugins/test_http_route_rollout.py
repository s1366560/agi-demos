"""HTTP route inventory shadow rollout tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.infrastructure.plugins.http_route_rollout import (
    HTTP_ROUTE_INVENTORY_EVENT,
    record_http_route_inventory_shadow,
)
from src.infrastructure.plugins.rollout_readiness import evaluate_shadow_rollout_readiness
from src.infrastructure.plugins.shadow_rollout import (
    QueuedShadowRolloutEvent,
    queued_event_count,
    reset_shadow_rollout_queue_for_test,
)


def settings(
    *,
    shadow: bool = True,
    percent: int = 100,
    v2: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        platform_plugin_http_route_v2=v2,
        platform_plugin_http_route_shadow=shadow,
        platform_plugin_http_route_shadow_percent=percent,
        platform_plugin_shadow_scope_allowlist=None,
    )


@pytest.mark.unit
def test_http_route_inventory_records_equal_global_shadow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_shadow_rollout_queue_for_test()
    registry = {"example-plugin": [{"method": "get", "path": "/api/v1/plugins/example/hello"}]}
    desired = [
        SimpleNamespace(
            plugin_id="example-plugin",
            method="GET",
            path="/api/v1/plugins/example/hello",
            enabled=True,
        )
    ]
    captured: list[QueuedShadowRolloutEvent] = []

    def capture(event: QueuedShadowRolloutEvent) -> bool:
        captured.append(event)
        return True

    monkeypatch.setattr(
        "src.infrastructure.plugins.http_route_rollout.enqueue_shadow_rollout_event",
        capture,
    )

    assert record_http_route_inventory_shadow(
        registry_routes=registry,
        desired_rows=desired,
        settings=settings(),
    )

    assert len(captured) == 1
    record = captured[0]
    assert record.capability == "http_routes"
    assert record.event_name == HTTP_ROUTE_INVENTORY_EVENT
    assert record.scope_type == "global"
    assert record.scope_id == "global"
    assert record.equal is True
    assert record.legacy_payload == record.typed_payload
    assert queued_event_count() == 0


@pytest.mark.unit
def test_http_route_inventory_records_missing_desired_route_as_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_shadow_rollout_queue_for_test()
    registry = {"example-plugin": [{"method": "GET", "path": "/api/v1/plugins/example/hello"}]}
    captured: list[QueuedShadowRolloutEvent] = []

    def capture(event: QueuedShadowRolloutEvent) -> bool:
        captured.append(event)
        return True

    monkeypatch.setattr(
        "src.infrastructure.plugins.http_route_rollout.enqueue_shadow_rollout_event",
        capture,
    )

    assert record_http_route_inventory_shadow(
        registry_routes=registry,
        desired_rows=[],
        settings=settings(),
    )

    assert len(captured) == 1
    assert captured[0].equal is False
    assert captured[0].legacy_payload != captured[0].typed_payload
    assert queued_event_count() == 0


@pytest.mark.unit
def test_http_route_inventory_respects_cohort_and_v2_mode() -> None:
    reset_shadow_rollout_queue_for_test()
    registry = {"example-plugin": [{"method": "GET", "path": "/api/v1/plugins/example/hello"}]}
    desired = [
        SimpleNamespace(
            plugin_id="example-plugin",
            method="GET",
            path="/api/v1/plugins/example/hello",
            enabled=True,
        )
    ]

    assert not record_http_route_inventory_shadow(
        registry_routes=registry,
        desired_rows=desired,
        settings=settings(percent=0),
    )
    assert not record_http_route_inventory_shadow(
        registry_routes=registry,
        desired_rows=desired,
        settings=settings(v2=True),
    )
    assert queued_event_count() == 0


@pytest.mark.unit
def test_http_route_readiness_uses_one_global_complete_inventory_scope() -> None:
    now = datetime.now(UTC)
    readiness = evaluate_shadow_rollout_readiness(
        summary=[
            {
                "capability": "http_routes",
                "event_name": HTTP_ROUTE_INVENTORY_EVENT,
                "total_count": 1,
                "equal_count": 1,
                "diff_count": 0,
                "last_occurred_at": now,
            }
        ],
        scope_counts=[
            {"capability": "http_routes", "distinct_scope_count": 1},
        ],
        checked_at=now,
        minimum_samples_per_event=1,
        minimum_distinct_scopes=10,
    )

    capability = {item.capability: item for item in readiness.capabilities}["http_routes"]

    assert capability.ready is True
    assert capability.distinct_scope_count == 1
