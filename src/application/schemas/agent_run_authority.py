"""Canonical Cloud contracts for run input, summary and changes authority."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _AuthorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _normalize_utc_datetimes(cls, value: object) -> object:
        if not isinstance(value, datetime):
            return value
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class RunInputReference(_AuthorityModel):
    type: Literal["code_range"]
    snapshot_id: str = Field(min_length=1, max_length=255)
    environment_id: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=4096)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    side: Literal["old", "new"]
    patch_digest: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def _validate_line_order(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class RunInputContextItem(_AuthorityModel):
    kind: Literal["attachment", "agent", "skill", "plugin", "command", "thread"]
    resource_id: str = Field(min_length=1, max_length=512)
    label: str = Field(min_length=1, max_length=255)
    metadata: dict[str, str | int | float | bool | None] | None = None


class CreateRunInputRequest(_AuthorityModel):
    expected_run_revision: int = Field(ge=1)
    message: str = Field(min_length=1, max_length=100_000)
    message_id: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=1, max_length=255)
    delivery: Literal["steer_now", "queue_next"]
    references: list[RunInputReference] = Field(default_factory=list, max_length=32)
    context_items: list[RunInputContextItem] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def _validate_unique_authorities(self) -> Self:
        reference_ids = {
            (
                item.snapshot_id,
                item.environment_id,
                item.path,
                item.start_line,
                item.end_line,
                item.side,
                item.patch_digest,
            )
            for item in self.references
        }
        if len(reference_ids) != len(self.references):
            raise ValueError("references cannot contain duplicate ranges")
        context_ids = {(item.kind, item.resource_id) for item in self.context_items}
        if len(context_ids) != len(self.context_items):
            raise ValueError("context_items cannot contain duplicate resources")
        return self


class PromoteRunInputRequest(_AuthorityModel):
    expected_source_run_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255)


class RunInputReceipt(_AuthorityModel):
    id: str
    conversation_id: str
    run_id: str
    expected_run_revision: int
    message_id: str
    idempotency_key: str
    delivery: Literal["steer_now", "queue_next"]
    status: Literal[
        "pending_boundary",
        "queued",
        "applied",
        "ready",
        "blocked",
        "promoted_to_plan",
    ]
    sequence: int = Field(ge=1)
    queue_position: int | None = Field(default=None, ge=1)
    content: str
    references: list[dict[str, Any]]
    context_items: list[dict[str, Any]]
    applied_round: int | None = Field(default=None, ge=0)
    applied_at: datetime | None
    injected_via: str | None
    dispatch_status: Literal["not_required", "dispatching", "dispatched", "failed"]
    dispatch_attempts: int = Field(ge=0)
    dispatch_lease_expires_at: datetime | None
    dispatch_error_code: str | None
    promotion_idempotency_key: str | None
    promoted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RunInputAck(_AuthorityModel):
    accepted: bool
    created: bool
    action: Literal["send_message"] = "send_message"
    conversation_id: str
    message_id: str
    delivery_mode: Literal["steer_now", "queue_next"]
    run_id: str
    run_revision: int
    queue_position: int | None
    input: RunInputReceipt


class RunInputListResponse(_AuthorityModel):
    run_id: str
    run_revision: int
    inputs: list[RunInputReceipt]
    total_count: int


class PromoteRunInputResponse(_AuthorityModel):
    accepted: bool
    created: bool
    action: Literal["start_plan_turn"] = "start_plan_turn"
    input: RunInputReceipt
    conversation: dict[str, Any]
    source_run: dict[str, Any]


class ActiveRunProjection(_AuthorityModel):
    id: str
    turn_id: str
    tenant_id: str
    project_id: str
    conversation_id: str
    status: str
    revision: int
    availability: Literal["available", "unavailable"]
    reason_code: str | None
    allowed_actions: list[Literal["steer_now", "queue_next", "kill_run"]]
    authority_revision: int
    created_at: datetime
    updated_at: datetime


class ActiveRunResponse(_AuthorityModel):
    conversation_id: str
    active_run: ActiveRunProjection | None
    availability: Literal["available", "unavailable"]
    reason_code: str | None
    authority_revision: int


class LatestRunResponse(_AuthorityModel):
    conversation_id: str
    latest_run: ActiveRunProjection | None
    availability: Literal["available", "unavailable"]
    reason_code: str | None
    authority_revision: int


class RunSummaryResponse(_AuthorityModel):
    run_id: str
    tenant_id: str
    project_id: str
    conversation_id: str
    status: str
    revision: int
    summary_state: Literal["recorded", "partial"]
    reason_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    model_breakdown: list[dict[str, Any]]
    completion_summary: str | None
    artifact_count: int | None
    checks_passed: int | None
    checks_failed: int | None
    files_changed: int | None
    lines_added: int | None
    lines_deleted: int | None
    evidence_references: list[dict[str, Any]]


class RunChangeAttribution(_AuthorityModel):
    file_path: str | None
    hunk_id: str | None
    attribution: Literal["attributed", "unattributed"]
    turn_id: str | None
    event_id: str
    event_revision: str
    payload: dict[str, Any]


class ChangeLineResponse(_AuthorityModel):
    kind: Literal["context", "addition", "deletion"]
    old_line: int | None = None
    new_line: int | None = None
    text: str


class ChangeHunkResponse(_AuthorityModel):
    header: str
    old_start: int
    new_start: int
    lines: list[ChangeLineResponse]


class ChangeFileResponse(_AuthorityModel):
    path: str
    old_path: str | None = None
    status: str
    additions: int
    deletions: int
    binary: bool
    untracked: bool
    patch_digest: str
    hunks: list[ChangeHunkResponse]


class RunChangesResponse(_AuthorityModel):
    id: str
    run_id: str
    conversation_id: str
    run_revision: int
    environment_id: str | None
    repository_root: str | None
    workspace_path: str | None
    branch: str | None
    base_revision: str | None
    head_revision: str | None
    status: Literal["ready", "unattributed", "unavailable", "failed"]
    reason: str | None
    additions: int
    deletions: int
    files_changed: int
    truncated: bool
    captured_at: datetime
    files: list[ChangeFileResponse]
    scope: Literal["turn", "run", "session"]
    turn_id: str | None
    snapshot_revision: str
    attribution: list[RunChangeAttribution]


__all__ = [
    "ActiveRunResponse",
    "CreateRunInputRequest",
    "LatestRunResponse",
    "PromoteRunInputRequest",
    "PromoteRunInputResponse",
    "RunChangesResponse",
    "RunInputAck",
    "RunInputListResponse",
    "RunInputReceipt",
    "RunSummaryResponse",
]
