import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import (
    get_db,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    CircuitStateModel,
    EventLogModel,
    MessageQueueItemModel,
    NodeCardModel,
    ObservabilityDeadLetterModel,
)

PREFIX = "/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/observability"

router = APIRouter(tags=["observability"])


def _ws_filter(model: type, tenant_id: str, workspace_id: str) -> tuple[Any, ...]:
    return (
        model.tenant_id == tenant_id,
        model.workspace_id == workspace_id,
        model.deleted_at.is_(None),
    )


@router.get(PREFIX + "/messages/trace/{trace_id}")
async def get_message_trace(
    tenant_id: str,
    workspace_id: str,
    trace_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    q = (
        select(EventLogModel)
        .where(*_ws_filter(EventLogModel, tenant_id, workspace_id))
        .where(EventLogModel.trace_id == trace_id)
        .order_by(EventLogModel.created_at.asc())
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "trace_id": r.trace_id,
            "event_type": r.event_type,
            "source_node_id": r.source_node_id,
            "target_node_id": r.target_node_id,
            "message_id": r.message_id,
            "payload": r.payload,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get(PREFIX + "/messages/metrics")
async def get_message_metrics(
    tenant_id: str,
    workspace_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    wf = _ws_filter(MessageQueueItemModel, tenant_id, workspace_id)
    queue_q = select(func.count()).select_from(select(MessageQueueItemModel).where(*wf).subquery())
    queue_depth = (await db.execute(queue_q)).scalar() or 0

    dl_wf = _ws_filter(ObservabilityDeadLetterModel, tenant_id, workspace_id)
    dl_q = select(func.count()).select_from(
        select(ObservabilityDeadLetterModel).where(*dl_wf).subquery()
    )
    dead_letter_count = (await db.execute(dl_q)).scalar() or 0

    return {
        "queue_depth": queue_depth,
        "dead_letter_count": dead_letter_count,
    }


@router.get(PREFIX + "/messages/metrics/nodes/{node_id}")
async def get_node_metrics(
    tenant_id: str,
    workspace_id: str,
    node_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    wf = _ws_filter(EventLogModel, tenant_id, workspace_id)
    sent_q = select(func.count()).select_from(
        select(EventLogModel).where(*wf, EventLogModel.source_node_id == node_id).subquery()
    )
    sent = (await db.execute(sent_q)).scalar() or 0

    recv_q = select(func.count()).select_from(
        select(EventLogModel).where(*wf, EventLogModel.target_node_id == node_id).subquery()
    )
    received = (await db.execute(recv_q)).scalar() or 0

    dl_wf = _ws_filter(ObservabilityDeadLetterModel, tenant_id, workspace_id)
    err_q = select(func.count()).select_from(
        select(ObservabilityDeadLetterModel)
        .where(
            *dl_wf,
            (
                (ObservabilityDeadLetterModel.source_node_id == node_id)
                | (ObservabilityDeadLetterModel.target_node_id == node_id)
            ),
        )
        .subquery()
    )
    errors = (await db.execute(err_q)).scalar() or 0

    return {
        "node_id": node_id,
        "messages_sent": sent,
        "messages_received": received,
        "errors": errors,
    }


@router.get(PREFIX + "/messages/heatmap")
async def get_message_heatmap(
    tenant_id: str,
    workspace_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    wf = _ws_filter(EventLogModel, tenant_id, workspace_id)
    q = (
        select(
            EventLogModel.source_node_id,
            EventLogModel.target_node_id,
            func.count().label("count"),
        )
        .where(*wf)
        .group_by(
            EventLogModel.source_node_id,
            EventLogModel.target_node_id,
        )
    )
    rows = (await db.execute(q)).all()
    return [
        {
            "source_node_id": r.source_node_id,
            "target_node_id": r.target_node_id,
            "count": r.count,
        }
        for r in rows
    ]


@router.get(PREFIX + "/messages/dead-letters")
async def list_dead_letters(
    tenant_id: str,
    workspace_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
) -> list[dict[str, Any]]:
    wf = _ws_filter(ObservabilityDeadLetterModel, tenant_id, workspace_id)
    q = (
        select(ObservabilityDeadLetterModel)
        .where(*wf)
        .order_by(ObservabilityDeadLetterModel.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "original_message_id": r.original_message_id,
            "source_node_id": r.source_node_id,
            "target_node_id": r.target_node_id,
            "error_reason": r.error_reason,
            "payload": r.payload,
            "retry_count": r.retry_count,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "retried_at": r.retried_at.isoformat() if r.retried_at else None,
        }
        for r in rows
    ]


@router.post(PREFIX + "/messages/dead-letters/{dead_letter_id}/retry")
async def retry_dead_letter(
    tenant_id: str,
    workspace_id: str,
    dead_letter_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    q = select(ObservabilityDeadLetterModel).where(
        ObservabilityDeadLetterModel.id == dead_letter_id,
        *_ws_filter(
            ObservabilityDeadLetterModel,
            tenant_id,
            workspace_id,
        ),
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dead letter not found",
        )
    now = datetime.now(UTC)
    stmt = (
        update(ObservabilityDeadLetterModel)
        .where(ObservabilityDeadLetterModel.id == dead_letter_id)
        .values(
            status="retrying",
            retry_count=row.retry_count + 1,
            retried_at=now,
        )
    )
    await db.execute(stmt)
    return {"id": dead_letter_id, "status": "retrying"}


@router.get(PREFIX + "/messages/circuit-breakers")
async def list_circuit_breakers(
    tenant_id: str,
    workspace_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    wf = _ws_filter(CircuitStateModel, tenant_id, workspace_id)
    q = select(CircuitStateModel).where(*wf)
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "node_id": r.node_id,
            "state": r.state,
            "failure_count": r.failure_count,
            "last_failure_at": r.last_failure_at.isoformat() if r.last_failure_at else None,
            "last_success_at": r.last_success_at.isoformat() if r.last_success_at else None,
        }
        for r in rows
    ]


@router.get(PREFIX + "/messages/events")
async def list_events(
    tenant_id: str,
    workspace_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    event_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    wf = _ws_filter(EventLogModel, tenant_id, workspace_id)
    q = select(EventLogModel).where(*wf)
    if event_type:
        q = q.where(EventLogModel.event_type == event_type)
    q = q.order_by(EventLogModel.created_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "trace_id": r.trace_id,
            "event_type": r.event_type,
            "source_node_id": r.source_node_id,
            "target_node_id": r.target_node_id,
            "message_id": r.message_id,
            "payload": r.payload,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get(PREFIX + "/messages/{message_id}/reconstruct")
async def reconstruct_message(
    tenant_id: str,
    workspace_id: str,
    message_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    wf = _ws_filter(EventLogModel, tenant_id, workspace_id)
    events_q = (
        select(EventLogModel)
        .where(*wf, EventLogModel.message_id == message_id)
        .order_by(EventLogModel.created_at.asc())
    )
    events = (await db.execute(events_q)).scalars().all()

    dl_wf = _ws_filter(ObservabilityDeadLetterModel, tenant_id, workspace_id)
    dl_q = select(ObservabilityDeadLetterModel).where(
        *dl_wf,
        ObservabilityDeadLetterModel.original_message_id == message_id,
    )
    dead_letters = (await db.execute(dl_q)).scalars().all()

    mq_wf = _ws_filter(MessageQueueItemModel, tenant_id, workspace_id)
    mq_q = select(MessageQueueItemModel).where(
        *mq_wf,
        MessageQueueItemModel.message_id == message_id,
    )
    queue_items = (await db.execute(mq_q)).scalars().all()

    return {
        "message_id": message_id,
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "source_node_id": e.source_node_id,
                "target_node_id": e.target_node_id,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
        "dead_letters": [
            {
                "id": d.id,
                "error_reason": d.error_reason,
                "status": d.status,
                "retry_count": d.retry_count,
            }
            for d in dead_letters
        ],
        "queue_items": [
            {
                "id": qi.id,
                "status": qi.status,
                "priority": qi.priority,
                "created_at": qi.created_at.isoformat() if qi.created_at else None,
                "processed_at": qi.processed_at.isoformat() if qi.processed_at else None,
            }
            for qi in queue_items
        ],
    }


@router.get(PREFIX + "/messages/queue-stats")
async def get_queue_stats(
    tenant_id: str,
    workspace_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    wf = _ws_filter(MessageQueueItemModel, tenant_id, workspace_id)
    q = (
        select(
            MessageQueueItemModel.status,
            func.count().label("count"),
        )
        .where(*wf)
        .group_by(MessageQueueItemModel.status)
    )
    rows = (await db.execute(q)).all()
    return {r.status: r.count for r in rows}


@router.get(PREFIX + "/nodes/{node_id}/card")
async def get_node_card(
    tenant_id: str,
    workspace_id: str,
    node_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    wf = _ws_filter(NodeCardModel, tenant_id, workspace_id)
    q = select(NodeCardModel).where(*wf, NodeCardModel.node_id == node_id)
    row = (await db.execute(q)).scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node card not found",
        )
    return {
        "id": row.id,
        "node_id": row.node_id,
        "node_type": row.node_type,
        "name": row.name,
        "description": row.description,
        "tags": row.tags,
        "status": row.status,
        "metadata": row.metadata_,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get(PREFIX + "/nodes/discover")
async def discover_nodes(
    tenant_id: str,
    workspace_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    node_type: str | None = None,
    tag: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    wf = _ws_filter(NodeCardModel, tenant_id, workspace_id)
    q = select(NodeCardModel).where(*wf)
    if node_type:
        q = q.where(NodeCardModel.node_type == node_type)
    q = q.order_by(NodeCardModel.created_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    results = []
    for r in rows:
        if tag and tag not in (r.tags or []):
            continue
        results.append(
            {
                "id": r.id,
                "node_id": r.node_id,
                "node_type": r.node_type,
                "name": r.name,
                "tags": r.tags,
                "status": r.status,
            }
        )
    return results


@router.put(PREFIX + "/nodes/{node_id}/card")
async def update_node_card(
    tenant_id: str,
    workspace_id: str,
    node_id: str,
    body: dict[str, Any],
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    wf = _ws_filter(NodeCardModel, tenant_id, workspace_id)
    q = select(NodeCardModel).where(*wf, NodeCardModel.node_id == node_id)
    row = (await db.execute(q)).scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node card not found",
        )
    allowed = {
        "name",
        "description",
        "tags",
        "status",
        "node_type",
        "metadata",
    }
    values = {}
    for key, val in body.items():
        if key not in allowed:
            continue
        col = "metadata_" if key == "metadata" else key
        values[col] = val
    if values:
        values["updated_at"] = datetime.now(UTC)
        stmt = update(NodeCardModel).where(NodeCardModel.id == row.id).values(**values)
        await db.execute(stmt)
    return {"id": row.id, "node_id": node_id, "updated": True}


@router.post(PREFIX + "/nodes/{node_id}/messages")
async def post_node_message(
    tenant_id: str,
    workspace_id: str,
    node_id: str,
    body: dict[str, Any],
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    item = MessageQueueItemModel(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        message_id=body.get("message_id", str(uuid.uuid4())),
        source_node_id=body.get("source_node_id"),
        target_node_id=node_id,
        status="queued",
        priority=body.get("priority", 0),
        payload=body.get("payload", {}),
    )
    db.add(item)
    await db.flush()
    return {"id": item.id, "status": "queued"}


@router.get(PREFIX + "/nodes/types")
async def list_node_types(
    tenant_id: str,
    workspace_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
) -> list[dict[str, str]]:
    return [
        {"type": "agent", "label": "Agent"},
        {"type": "tool", "label": "Tool"},
        {"type": "skill", "label": "Skill"},
        {"type": "subagent", "label": "SubAgent"},
        {"type": "memory", "label": "Memory Store"},
        {"type": "external", "label": "External Service"},
    ]


@router.get(PREFIX + "/messages/alerts")
async def get_alerts(
    tenant_id: str,
    workspace_id: str,
    _user_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cb_wf = _ws_filter(CircuitStateModel, tenant_id, workspace_id)
    open_cb_q = select(func.count()).select_from(
        select(CircuitStateModel).where(*cb_wf, CircuitStateModel.state == "open").subquery()
    )
    open_circuits = (await db.execute(open_cb_q)).scalar() or 0

    dl_wf = _ws_filter(ObservabilityDeadLetterModel, tenant_id, workspace_id)
    pending_dl_q = select(func.count()).select_from(
        select(ObservabilityDeadLetterModel)
        .where(
            *dl_wf,
            ObservabilityDeadLetterModel.status == "pending",
        )
        .subquery()
    )
    pending_dead_letters = (await db.execute(pending_dl_q)).scalar() or 0

    alerts = []
    if open_circuits > 0:
        alerts.append(
            {
                "severity": "critical",
                "type": "circuit_breaker_open",
                "message": (f"{open_circuits} circuit breaker(s) open"),
                "count": open_circuits,
            }
        )
    if pending_dead_letters > 0:
        alerts.append(
            {
                "severity": "warning",
                "type": "pending_dead_letters",
                "message": (f"{pending_dead_letters} unresolved dead letter(s)"),
                "count": pending_dead_letters,
            }
        )
    return {"alerts": alerts, "total": len(alerts)}
