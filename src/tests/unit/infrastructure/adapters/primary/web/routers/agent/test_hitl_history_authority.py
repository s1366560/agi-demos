"""History projection tests for HITL-owned authority revisions."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from src.domain.model.agent.hitl_request import HITLRequestStatus
from src.infrastructure.adapters.primary.web.routers.agent.messages import (
    _build_hitl_status_map,
    _build_timeline,
)


@dataclass
class _Event:
    event_type: str
    event_data: dict[str, Any]
    event_time_us: int = 1_000
    event_counter: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    message_id: str = "msg-1"


def _timeline(event: _Event, hitl_status_map: dict[str, Any]) -> list[dict[str, Any]]:
    return _build_timeline(
        events=[event],
        tool_exec_map={},
        hitl_answered_map={},
        hitl_status_map=hitl_status_map,
        artifact_ready_map={},
        artifact_error_map={},
        completion_map={},
    )


def test_a2ui_history_revision_comes_from_hitl_status_not_run_revision() -> None:
    status_map = _build_hitl_status_map(
        [
            SimpleNamespace(
                id="req-1",
                status=HITLRequestStatus.PENDING,
                response=None,
                response_metadata=None,
            )
        ]
    )

    timeline = _timeline(
        _Event(
            event_type="a2ui_action_asked",
            event_data={
                "request_id": "req-1",
                "block_id": "block-1",
                "run_revision": 99,
            },
        ),
        status_map,
    )

    assert timeline[0]["authority_revision"] == 1
    assert timeline[0]["authority_revision"] != 99


def test_a2ui_answered_history_has_settled_authority_revision() -> None:
    status_map = _build_hitl_status_map(
        [
            SimpleNamespace(
                id="req-1",
                status=HITLRequestStatus.COMPLETED,
                response="approve",
                response_metadata={},
            )
        ]
    )

    timeline = _timeline(
        _Event(
            event_type="a2ui_action_asked",
            event_data={"request_id": "req-1", "block_id": "block-1"},
        ),
        status_map,
    )

    assert timeline[0]["answered"] is True
    assert timeline[0]["authority_revision"] == 2


def test_a2ui_processing_history_remains_read_only_answered() -> None:
    status_map = _build_hitl_status_map(
        [
            SimpleNamespace(
                id="req-1",
                status=HITLRequestStatus.PROCESSING,
                response="approve",
                response_metadata={},
            )
        ]
    )

    timeline = _timeline(
        _Event(
            event_type="a2ui_action_asked",
            event_data={"request_id": "req-1", "block_id": "block-1"},
        ),
        status_map,
    )

    assert timeline[0]["answered"] is True
    assert timeline[0]["authority_revision"] == 2


def test_env_var_history_never_replays_response_values() -> None:
    status_map = _build_hitl_status_map(
        [
            SimpleNamespace(
                id="req-env",
                status=HITLRequestStatus.ANSWERED,
                response="[redacted env var response]",
                response_metadata={
                    "variable_names": ["API_KEY"],
                    "values": {"API_KEY": "must-never-replay"},
                },
            )
        ]
    )

    timeline = _timeline(
        _Event(
            event_type="env_var_requested",
            event_data={
                "request_id": "req-env",
                "tool_name": "web_search",
                "fields": [{"name": "API_KEY", "label": "API Key"}],
            },
        ),
        status_map,
    )

    encoded = json.dumps(timeline)
    assert "must-never-replay" not in encoded
    assert timeline[0]["variableNames"] == ["API_KEY"]
