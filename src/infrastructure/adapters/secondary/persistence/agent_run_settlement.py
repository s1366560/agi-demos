"""Atomic persistence for plan-run terminal projections."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentPlanRunModel,
    AgentRunAuthorityModel,
    AgentRunInputModel,
    AgentRunSummaryModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_plan_run_authority,
)


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _parse_run_input_applied_event(
    event_data: dict[str, Any],
) -> tuple[str, str, int, str, str, int, datetime, str] | None:
    """Fail closed unless every receipt authority field is structurally valid."""

    values = (
        event_data.get("run_input_id"),
        event_data.get("run_id"),
        event_data.get("run_revision"),
        event_data.get("message_id"),
        event_data.get("idempotency_key"),
        event_data.get("applied_round"),
        event_data.get("applied_at"),
        event_data.get("injected_via"),
    )
    run_input_id, run_id, run_revision, message_id, idempotency_key, applied_round = values[:6]
    applied_at_raw, injected_via = values[6:]
    if (
        not isinstance(run_input_id, str)
        or not run_input_id
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(run_revision, int)
        or isinstance(run_revision, bool)
        or run_revision < 1
        or not isinstance(message_id, str)
        or not message_id
        or not isinstance(idempotency_key, str)
        or not idempotency_key
        or event_data.get("delivery_mode") != "steer_now"
        or not isinstance(applied_round, int)
        or isinstance(applied_round, bool)
        or applied_round < 0
        or not isinstance(applied_at_raw, str)
        or injected_via != "control_channel_observe_boundary"
    ):
        return None
    try:
        applied_at = datetime.fromisoformat(applied_at_raw)
    except ValueError:
        return None
    if applied_at.tzinfo is None:
        return None
    return (
        run_input_id,
        run_id,
        run_revision,
        message_id,
        idempotency_key,
        applied_round,
        applied_at,
        injected_via,
    )


async def apply_run_input_applied_projection(
    db: AsyncSession,
    *,
    event_data: dict[str, Any],
) -> bool:
    """Apply one structured Observe-boundary receipt to its persisted run input."""

    parsed = _parse_run_input_applied_event(event_data)
    if parsed is None:
        return False
    (
        run_input_id,
        run_id,
        run_revision,
        message_id,
        idempotency_key,
        applied_round,
        applied_at,
        injected_via,
    ) = parsed

    result = await db.execute(
        refresh_select_statement(
            select(AgentRunInputModel)
            .where(
                AgentRunInputModel.id == run_input_id,
                AgentRunInputModel.run_id == run_id,
                AgentRunInputModel.expected_run_revision == run_revision,
                AgentRunInputModel.message_id == message_id,
                AgentRunInputModel.idempotency_key == idempotency_key,
                AgentRunInputModel.delivery == "steer_now",
            )
            .with_for_update()
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    if row.status == "applied":
        return bool(
            row.applied_round == applied_round
            and row.applied_at == applied_at
            and row.injected_via == injected_via
        )
    if row.status != "pending_boundary":
        return False

    row.status = "applied"
    row.applied_round = applied_round
    row.applied_at = applied_at
    row.injected_via = injected_via
    row.updated_at = applied_at
    return True


def _structured_model_breakdown(
    events: Sequence[AgentExecutionEvent],
    execution_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    """Aggregate only explicitly attributed model usage records."""

    supplied = execution_summary.get("model_breakdown")
    if isinstance(supplied, list):
        validated = [
            dict(item)
            for item in supplied
            if isinstance(item, dict) and isinstance(item.get("model"), str)
        ]
        if validated:
            return validated

    by_model: dict[str, dict[str, int | float | str]] = {}
    for event in reversed(events):
        data = event.event_data if isinstance(event.event_data, dict) else {}
        if event.event_type != "cost_update":
            continue
        model = data.get("model") or data.get("model_name")
        tokens = data.get("tokens")
        if not isinstance(model, str) or not model.strip() or not isinstance(tokens, dict):
            continue
        normalized_model = model.strip()
        item = by_model.setdefault(
            normalized_model,
            {
                "model": normalized_model,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "call_count": 0,
            },
        )
        input_tokens = _integer(tokens.get("input")) or 0
        output_tokens = _integer(tokens.get("output")) or 0
        cost_usd = _number(data.get("cost")) or 0.0
        item["input_tokens"] = int(item["input_tokens"]) + input_tokens
        item["output_tokens"] = int(item["output_tokens"]) + output_tokens
        item["cost_usd"] = float(item["cost_usd"]) + cost_usd
        item["call_count"] = int(item["call_count"]) + 1
    return [by_model[model] for model in sorted(by_model)]


async def settle_agent_run(
    db: AsyncSession,
    *,
    run: AgentRunAuthorityModel,
    started_at: datetime,
    succeeded: bool,
    completed_at: datetime,
) -> None:
    """Settle queued inputs and persist an explicit current-run summary."""

    input_result = await db.execute(
        refresh_select_statement(
            select(AgentRunInputModel)
            .where(
                AgentRunInputModel.run_id == run.id,
                AgentRunInputModel.tenant_id == run.tenant_id,
                AgentRunInputModel.project_id == run.project_id,
                AgentRunInputModel.conversation_id == run.conversation_id,
                AgentRunInputModel.status.in_(["queued", "pending_boundary"]),
            )
            .with_for_update()
        )
    )
    for item in input_result.scalars().all():
        item.status = "ready" if succeeded and item.status == "queued" else "blocked"
        item.updated_at = completed_at

    event_result = await db.execute(
        refresh_select_statement(
            select(AgentExecutionEvent)
            .where(
                AgentExecutionEvent.conversation_id == run.conversation_id,
                AgentExecutionEvent.message_id == run.message_id,
            )
            .order_by(
                AgentExecutionEvent.event_time_us.desc(),
                AgentExecutionEvent.event_counter.desc(),
            )
        )
    )
    events = event_result.scalars().all()
    execution_summary: dict[str, Any] = {}
    completion_summary: str | None = None
    evidence_references: list[dict[str, Any]] = []
    for event in events:
        data = event.event_data if isinstance(event.event_data, dict) else {}
        if not execution_summary and isinstance(data.get("execution_summary"), dict):
            execution_summary = dict(data["execution_summary"])
        if completion_summary is None and event.event_type == "assistant_message":
            content = data.get("content")
            if isinstance(content, str) and content.strip():
                completion_summary = content.strip()
        trace_url = data.get("trace_url")
        if isinstance(trace_url, str) and trace_url:
            evidence_references.append({"kind": "trace", "value": trace_url})
        artifacts = data.get("artifacts")
        if isinstance(artifacts, list):
            evidence_references.extend(
                {"kind": "artifact", "value": item} for item in artifacts if isinstance(item, str)
            )

    token_usage = execution_summary.get("total_tokens")
    token_usage = token_usage if isinstance(token_usage, dict) else {}
    model_breakdown = _structured_model_breakdown(events, execution_summary)
    existing_result = await db.execute(
        refresh_select_statement(
            select(AgentRunSummaryModel)
            .where(AgentRunSummaryModel.run_id == run.id)
            .with_for_update()
        )
    )
    summary = existing_result.scalar_one_or_none()
    if summary is None:
        summary = AgentRunSummaryModel(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            conversation_id=run.conversation_id,
            run_id=run.id,
            status=run.status,
            revision=run.revision,
            summary_state="recorded",
            reason_code=None,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=max(0, int((completed_at - started_at).total_seconds() * 1000)),
            input_tokens=_integer(token_usage.get("input")),
            output_tokens=_integer(token_usage.get("output")),
            cost_usd=_number(execution_summary.get("total_cost")),
            model_breakdown_json=model_breakdown,
            completion_summary=completion_summary,
            artifact_count=_integer(execution_summary.get("artifact_count")),
            checks_passed=_integer(execution_summary.get("checks_passed")),
            checks_failed=_integer(execution_summary.get("checks_failed")),
            files_changed=_integer(execution_summary.get("files_changed")),
            lines_added=_integer(execution_summary.get("lines_added")),
            lines_deleted=_integer(execution_summary.get("lines_deleted")),
            evidence_references_json=evidence_references,
            created_at=completed_at,
            updated_at=completed_at,
        )
        db.add(summary)
        return

    summary.status = run.status
    summary.revision = run.revision
    summary.summary_state = "recorded"
    summary.reason_code = None
    summary.started_at = started_at
    summary.completed_at = completed_at
    summary.duration_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
    summary.input_tokens = _integer(token_usage.get("input"))
    summary.output_tokens = _integer(token_usage.get("output"))
    summary.cost_usd = _number(execution_summary.get("total_cost"))
    summary.model_breakdown_json = model_breakdown
    summary.completion_summary = completion_summary
    summary.artifact_count = _integer(execution_summary.get("artifact_count"))
    summary.checks_passed = _integer(execution_summary.get("checks_passed"))
    summary.checks_failed = _integer(execution_summary.get("checks_failed"))
    summary.files_changed = _integer(execution_summary.get("files_changed"))
    summary.lines_added = _integer(execution_summary.get("lines_added"))
    summary.lines_deleted = _integer(execution_summary.get("lines_deleted"))
    summary.evidence_references_json = evidence_references
    summary.updated_at = datetime.now(UTC)


async def settle_agent_plan_run(
    db: AsyncSession,
    *,
    run: AgentPlanRunModel,
    tenant_id: str,
    started_at: datetime,
    succeeded: bool,
    completed_at: datetime,
) -> None:
    """Mirror and settle a plan run through the canonical authority."""

    authority = await ensure_plan_run_authority(db, run=run, tenant_id=tenant_id)
    authority.status = run.status
    authority.revision = run.revision
    authority.updated_at = run.updated_at
    authority.completed_at = run.completed_at
    authority.error = run.error
    await settle_agent_run(
        db,
        run=authority,
        started_at=started_at,
        succeeded=succeeded,
        completed_at=completed_at,
    )


__all__ = [
    "apply_run_input_applied_projection",
    "settle_agent_plan_run",
    "settle_agent_run",
]
