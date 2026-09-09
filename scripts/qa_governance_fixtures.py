"""Seed or remove populated governance samples inside an isolated QA tenant/project.

Covers the governance surfaces audited as empty-state-only: tenant event logs,
the admin dead-letter queue (Redis), trust decision records (approvals),
reflection playbooks with verdict history, and audit log entries. Every row is
deterministically identified (uuid5 on a QA namespace) and tagged so seeding is
idempotent and cleanup removes exactly the rows this fixture owns.

Usage:
    uv run python scripts/qa_governance_fixtures.py seed [--owner-email admin@memstack.ai]
    uv run python scripts/qa_governance_fixtures.py status
    uv run python scripts/qa_governance_fixtures.py cleanup

The script never touches rows outside the ``qa-governance`` scope and refuses
to run when the target rows are not owned by this fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import NAMESPACE_DNS, uuid5

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.orm import InstrumentedAttribute

import redis.asyncio as aioredis
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.configuration.config import get_settings
from src.domain.ports.services.dead_letter_queue_port import (
    DeadLetterMessage,
    DLQMessageStatus,
)
from src.infrastructure.adapters.secondary.messaging.redis_dlq import RedisDLQAdapter
from src.infrastructure.adapters.secondary.persistence.models import (
    AuditLog,
    Base,
    DecisionRecordModel,
    Playbook,
    Project,
    ReflectionVerdictRecord,
    Tenant,
    TenantEventLogModel,
    TrustPolicyModel,
    User,
    UserProject,
    UserTenant,
)

FIXTURE_VERSION = "qa-governance-v1"
QA_MARKER = f"qa-governance:{FIXTURE_VERSION}"

_NAMESPACE = uuid5(NAMESPACE_DNS, f"memstack.{QA_MARKER}")


def qa_id(name: str) -> str:
    """Return the deterministic UUID for one fixture-owned record."""
    return str(uuid5(_NAMESPACE, name))


QA_TENANT_ID = qa_id("tenant")
QA_PROJECT_ID = qa_id("project")
QA_WORKSPACE_ID = qa_id("workspace")
QA_TENANT_SLUG = f"qa-governance-{_NAMESPACE.hex[:8]}"
QA_TENANT_NAME = "QA Governance Tenant"
QA_PROJECT_NAME = "QA Governance Project"
QA_AGENT_INSTANCE_ID = qa_id("agent-instance")

_DLQ_MESSAGE_IDS = tuple(f"qa-governance-dlq-{index}" for index in range(1, 5))


@dataclass(frozen=True, kw_only=True)
class QaGovernanceSamples:
    """Immutable description of every fixture-owned record."""

    owner_id: str
    tenant_id: str = QA_TENANT_ID
    project_id: str = QA_PROJECT_ID
    workspace_id: str = QA_WORKSPACE_ID
    event_logs: tuple[dict[str, Any], ...] = ()
    decision_records: tuple[dict[str, Any], ...] = ()
    trust_policies: tuple[dict[str, Any], ...] = ()
    playbooks: tuple[dict[str, Any], ...] = ()
    verdicts: tuple[dict[str, Any], ...] = ()
    audit_logs: tuple[dict[str, Any], ...] = ()
    dlq_messages: tuple[DeadLetterMessage, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


def build_qa_governance_samples(
    owner_id: str, *, base_time: datetime | None = None
) -> QaGovernanceSamples:
    """Build the populated sample set; pure function, safe for tests to reuse."""
    base = base_time or datetime(2026, 9, 9, 9, 0, tzinfo=UTC)

    def at(hours: float) -> datetime:
        return base + timedelta(hours=hours)

    event_logs = (
        {
            "id": qa_id("event-login"),
            "event_type": "user.login",
            "message": "QA governance sample: member signed in via API key",
            "source": "system",
            "metadata": {"qa_fixture": QA_MARKER, "auth_method": "api_key"},
            "created_at": at(0),
        },
        {
            "id": qa_id("event-deploy"),
            "event_type": "deploy.started",
            "message": "QA governance sample: deployment started for instance qa-governance",
            "source": "agent",
            "metadata": {"qa_fixture": QA_MARKER, "instance": "qa-governance-instance"},
            "created_at": at(1),
        },
        {
            "id": qa_id("event-gene"),
            "event_type": "gene.installed",
            "message": "QA governance sample: gene capsule installed into QA scope",
            "source": "user",
            "metadata": {"qa_fixture": QA_MARKER, "capsule": "qa-governance-capsule"},
            "created_at": at(2),
        },
        {
            "id": qa_id("event-sync"),
            "event_type": "deploy.started",
            "message": "QA governance sample: second deployment for filter verification",
            "source": "system",
            "metadata": {"qa_fixture": QA_MARKER, "instance": "qa-governance-instance-2"},
            "created_at": at(3),
        },
    )
    decision_records = (
        {
            "id": qa_id("decision-pending"),
            "decision_type": "shell.execute",
            "context_summary": "QA governance sample: pending approval for a shell command",
            "proposal": {"command": "ls qa-governance", "reason": "inspect fixture outputs"},
            "outcome": "pending",
            "reviewer_id": None,
            "review_type": None,
            "review_comment": None,
            "resolved_at": None,
            "created_at": at(0),
        },
        {
            "id": qa_id("decision-approved"),
            "decision_type": "file.write",
            "context_summary": "QA governance sample: approved file write inside QA scratch dir",
            "proposal": {"path": "qa-governance/report.txt"},
            "outcome": "success",
            "reviewer_id": owner_id,
            "review_type": "human",
            "review_comment": "Allowed once",
            "resolved_at": at(2),
            "created_at": at(1),
        },
        {
            "id": qa_id("decision-rejected"),
            "decision_type": "network.egress",
            "context_summary": "QA governance sample: rejected egress outside QA allowlist",
            "proposal": {"url": "https://qa-governance.invalid/egress"},
            "outcome": "rejected",
            "reviewer_id": owner_id,
            "review_type": "human",
            "review_comment": "Denied by reviewer",
            "resolved_at": at(3),
            "created_at": at(2),
        },
    )
    trust_policies = (
        {
            "id": qa_id("policy-memory-read"),
            "action_type": "memory.read",
            "granted_by": owner_id,
            "grant_type": "always",
            "scope": "agent",
            "created_at": at(2),
        },
    )
    playbooks = (
        {
            "id": qa_id("playbook-retry"),
            "name": "QA Governance Retry Runbook",
            "status": "active",
            "trigger": {
                "description": "A DLQ retry keeps failing for the same routing key",
                "friction_kinds": ["dlq_retry_failure"],
                "lane_transitions": [["triage", "retry"]],
            },
            "steps": [
                {
                    "order": 1,
                    "instruction": "Open the DLQ detail view",
                    "rationale": "Confirm the error type",
                },
                {
                    "order": 2,
                    "instruction": "Retry the dead letter once",
                    "rationale": "Validate the fix",
                },
            ],
            "hit_count": 2,
            "created_at": at(1),
        },
        {
            "id": qa_id("playbook-approval"),
            "name": "QA Governance Approval Runbook",
            "status": "active",
            "trigger": {
                "description": "An approval request stays pending beyond one review window",
                "friction_kinds": ["approval_stalled"],
                "lane_transitions": [["review", "resolve"]],
            },
            "steps": [
                {
                    "order": 1,
                    "instruction": "List pending decision records",
                    "rationale": "Find stalled approvals",
                },
                {
                    "order": 2,
                    "instruction": "Resolve with allow_once or deny",
                    "rationale": "Close the loop",
                },
            ],
            "hit_count": 1,
            "created_at": at(2),
        },
    )
    verdicts = (
        {
            "id": qa_id("verdict-reinforce"),
            "action": "reinforce",
            "playbook_id": qa_id("playbook-retry"),
            "rationale": "QA governance sample: retry runbook resolved the dead letter",
            "proposed_payload": None,
            "created_at": at(2),
        },
        {
            "id": qa_id("verdict-create"),
            "action": "create",
            "playbook_id": qa_id("playbook-approval"),
            "rationale": "QA governance sample: approval stalls recurred, distilled a runbook",
            "proposed_payload": {"name": "QA Governance Approval Runbook"},
            "created_at": at(3),
        },
    )
    audit_logs = (
        {
            "id": qa_id("audit-policy-create"),
            "timestamp": at(2),
            "actor": owner_id,
            "action": "trust.policy_created",
            "resource_type": "trust_policy",
            "resource_id": qa_id("policy-memory-read"),
            "details": {"qa_fixture": QA_MARKER, "grant_type": "always"},
            "ip_address": "127.0.0.1",
            "user_agent": "qa-governance-fixture",
        },
        {
            "id": qa_id("audit-approval-approve"),
            "timestamp": at(2) + timedelta(minutes=5),
            "actor": owner_id,
            "action": "trust.approval_resolved",
            "resource_type": "decision_record",
            "resource_id": qa_id("decision-approved"),
            "details": {"qa_fixture": QA_MARKER, "decision": "allow_once"},
            "ip_address": "127.0.0.1",
            "user_agent": "qa-governance-fixture",
        },
        {
            "id": qa_id("audit-approval-deny"),
            "timestamp": at(3),
            "actor": owner_id,
            "action": "trust.approval_resolved",
            "resource_type": "decision_record",
            "resource_id": qa_id("decision-rejected"),
            "details": {"qa_fixture": QA_MARKER, "decision": "deny"},
            "ip_address": "127.0.0.1",
            "user_agent": "qa-governance-fixture",
        },
        {
            "id": qa_id("audit-dlq-discard"),
            "timestamp": at(4),
            "actor": owner_id,
            "action": "admin.dlq_discarded",
            "resource_type": "dlq_message",
            "resource_id": _DLQ_MESSAGE_IDS[3],
            "details": {"qa_fixture": QA_MARKER, "reason": "superseded by retry runbook"},
            "ip_address": "127.0.0.1",
            "user_agent": "qa-governance-fixture",
        },
    )

    def dlq_message(
        index: int,
        *,
        status: DLQMessageStatus,
        event_type: str,
        error_type: str,
        retry_count: int,
    ) -> DeadLetterMessage:
        failed_at = at(index)
        return DeadLetterMessage(
            id=_DLQ_MESSAGE_IDS[index - 1],
            event_id=qa_id(f"dlq-event-{index}"),
            event_type=event_type,
            event_data=json.dumps(
                {
                    "event_id": qa_id(f"dlq-event-{index}"),
                    "event_type": event_type,
                    "payload": {"qa_fixture": QA_MARKER, "sample": index},
                }
            ),
            routing_key=f"qa.governance.{event_type}",
            error=f"QA governance sample error {index}: simulated consumer failure",
            error_type=error_type,
            error_traceback=None,
            retry_count=retry_count,
            max_retries=3,
            first_failed_at=failed_at,
            last_failed_at=failed_at,
            next_retry_at=failed_at + timedelta(minutes=5)
            if status == DLQMessageStatus.PENDING
            else None,
            status=status,
            metadata={"qa_fixture": QA_MARKER, "consumer": "qa-governance-consumer"},
        )

    dlq_messages = (
        dlq_message(
            1,
            status=DLQMessageStatus.PENDING,
            event_type="memory.created",
            error_type="TimeoutError",
            retry_count=0,
        ),
        dlq_message(
            2,
            status=DLQMessageStatus.PENDING,
            event_type="episode.ingested",
            error_type="ValidationError",
            retry_count=1,
        ),
        dlq_message(
            3,
            status=DLQMessageStatus.RETRYING,
            event_type="memory.created",
            error_type="ConnectionError",
            retry_count=1,
        ),
        dlq_message(
            4,
            status=DLQMessageStatus.RESOLVED,
            event_type="gene.installed",
            error_type="TimeoutError",
            retry_count=2,
        ),
    )

    return QaGovernanceSamples(
        owner_id=owner_id,
        event_logs=event_logs,
        decision_records=decision_records,
        trust_policies=trust_policies,
        playbooks=playbooks,
        verdicts=verdicts,
        audit_logs=audit_logs,
        dlq_messages=dlq_messages,
    )


# ---------------------------------------------------------------------------
# SQL seed / cleanup
# ---------------------------------------------------------------------------


async def _exists(
    session: AsyncSession, id_column: InstrumentedAttribute[str], record_id: str
) -> bool:
    result = await session.execute(sa.select(id_column).where(id_column == record_id))
    return result.scalar_one_or_none() is not None


async def seed_qa_scope(session: AsyncSession, samples: QaGovernanceSamples) -> dict[str, int]:
    """Insert the QA tenant/project/memberships and all SQL samples (idempotent)."""
    created = {"tenant": 0, "project": 0, "memberships": 0}

    if not await _exists(session, Tenant.id, samples.tenant_id):
        session.add(
            Tenant(
                id=samples.tenant_id,
                name=QA_TENANT_NAME,
                slug=QA_TENANT_SLUG,
                description="Isolated QA scope for governance acceptance samples",
                owner_id=samples.owner_id,
                plan="free",
                max_projects=10,
                max_users=5,
                max_storage=1073741824,
            )
        )
        created["tenant"] = 1
    if not await _exists(session, Project.id, samples.project_id):
        session.add(
            Project(
                id=samples.project_id,
                tenant_id=samples.tenant_id,
                name=QA_PROJECT_NAME,
                description="Isolated QA project for governance acceptance samples",
                owner_id=samples.owner_id,
                memory_rules={},
                graph_config={},
            )
        )
        created["project"] = 1
    membership_id = qa_id("membership-owner-tenant")
    if not await _exists(session, UserTenant.id, membership_id):
        session.add(
            UserTenant(
                id=membership_id,
                user_id=samples.owner_id,
                tenant_id=samples.tenant_id,
                role="owner",
                permissions={"read": True, "write": True, "admin": True},
            )
        )
        created["memberships"] += 1
    project_membership_id = qa_id("membership-owner-project")
    if not await _exists(session, UserProject.id, project_membership_id):
        session.add(
            UserProject(
                id=project_membership_id,
                user_id=samples.owner_id,
                project_id=samples.project_id,
                role="owner",
            )
        )
        created["memberships"] += 1

    counts = await seed_qa_governance_rows(session, samples)
    await session.commit()
    return {**created, **counts}


async def _insert_missing(
    session: AsyncSession,
    id_column: InstrumentedAttribute[str],
    specs: tuple[dict[str, Any], ...],
    build: Callable[[dict[str, Any]], Any],
    label: str,
    counts: dict[str, int],
) -> None:
    for spec in specs:
        if not await _exists(session, id_column, spec["id"]):
            session.add(build(spec))
            counts[label] = counts.get(label, 0) + 1


async def seed_qa_governance_rows(
    session: AsyncSession, samples: QaGovernanceSamples
) -> dict[str, int]:
    """Insert the per-surface rows; caller owns the transaction."""
    counts: dict[str, int] = {}
    await _insert_missing(
        session,
        TenantEventLogModel.id,
        samples.event_logs,
        lambda spec: TenantEventLogModel(
            id=spec["id"],
            tenant_id=samples.tenant_id,
            event_type=spec["event_type"],
            message=spec["message"],
            source=spec["source"],
            metadata_=spec["metadata"],
            created_at=spec["created_at"],
        ),
        "event_logs",
        counts,
    )
    await _insert_missing(
        session,
        DecisionRecordModel.id,
        samples.decision_records,
        lambda spec: DecisionRecordModel(
            id=spec["id"],
            tenant_id=samples.tenant_id,
            workspace_id=samples.workspace_id,
            agent_instance_id=QA_AGENT_INSTANCE_ID,
            decision_type=spec["decision_type"],
            context_summary=spec["context_summary"],
            proposal=spec["proposal"],
            outcome=spec["outcome"],
            reviewer_id=spec["reviewer_id"],
            review_type=spec["review_type"],
            review_comment=spec["review_comment"],
            resolved_at=spec["resolved_at"],
            created_at=spec["created_at"],
        ),
        "decision_records",
        counts,
    )
    await _insert_missing(
        session,
        TrustPolicyModel.id,
        samples.trust_policies,
        lambda spec: TrustPolicyModel(
            id=spec["id"],
            tenant_id=samples.tenant_id,
            workspace_id=samples.workspace_id,
            agent_instance_id=QA_AGENT_INSTANCE_ID,
            action_type=spec["action_type"],
            granted_by=spec["granted_by"],
            grant_type=spec["grant_type"],
            scope=spec["scope"],
            created_at=spec["created_at"],
        ),
        "trust_policies",
        counts,
    )
    await _insert_missing(
        session,
        Playbook.id,
        samples.playbooks,
        lambda spec: Playbook(
            id=spec["id"],
            project_id=samples.project_id,
            name=spec["name"],
            status=spec["status"],
            trigger=spec["trigger"],
            steps=spec["steps"],
            hit_count=spec["hit_count"],
            created_at=spec["created_at"],
            updated_at=spec["created_at"],
        ),
        "playbooks",
        counts,
    )
    await _insert_missing(
        session,
        ReflectionVerdictRecord.id,
        samples.verdicts,
        lambda spec: ReflectionVerdictRecord(
            id=spec["id"],
            project_id=samples.project_id,
            action=spec["action"],
            playbook_id=spec["playbook_id"],
            rationale=spec["rationale"],
            proposed_payload=spec["proposed_payload"],
            created_at=spec["created_at"],
        ),
        "verdicts",
        counts,
    )
    await _insert_missing(
        session,
        AuditLog.id,
        samples.audit_logs,
        lambda spec: AuditLog(
            id=spec["id"],
            timestamp=spec["timestamp"],
            actor=spec["actor"],
            action=spec["action"],
            resource_type=spec["resource_type"],
            resource_id=spec["resource_id"],
            tenant_id=samples.tenant_id,
            details=spec["details"],
            ip_address=spec["ip_address"],
            user_agent=spec["user_agent"],
        ),
        "audit_logs",
        counts,
    )
    return counts


async def cleanup_qa_scope(session: AsyncSession, samples: QaGovernanceSamples) -> dict[str, int]:
    """Delete exactly the rows this fixture owns, children before parents."""
    removed: dict[str, int] = {}

    async def delete(
        model: type[Base], id_column: InstrumentedAttribute[str], ids: list[str], label: str
    ) -> None:
        if not ids:
            return
        result = cast(
            "CursorResult[Any]",
            await session.execute(sa.delete(model).where(id_column.in_(ids))),
        )
        removed[label] = int(result.rowcount or 0)

    await delete(
        ReflectionVerdictRecord,
        ReflectionVerdictRecord.id,
        [v["id"] for v in samples.verdicts],
        "verdicts",
    )
    await delete(Playbook, Playbook.id, [p["id"] for p in samples.playbooks], "playbooks")
    await delete(
        DecisionRecordModel,
        DecisionRecordModel.id,
        [d["id"] for d in samples.decision_records],
        "decision_records",
    )
    await delete(
        TrustPolicyModel,
        TrustPolicyModel.id,
        [p["id"] for p in samples.trust_policies],
        "trust_policies",
    )
    await delete(
        TenantEventLogModel,
        TenantEventLogModel.id,
        [e["id"] for e in samples.event_logs],
        "event_logs",
    )
    await delete(AuditLog, AuditLog.id, [a["id"] for a in samples.audit_logs], "audit_logs")
    await delete(
        UserProject,
        UserProject.id,
        [qa_id("membership-owner-project")],
        "project_memberships",
    )
    await delete(
        UserTenant,
        UserTenant.id,
        [qa_id("membership-owner-tenant")],
        "tenant_memberships",
    )
    await delete(Project, Project.id, [samples.project_id], "project")
    await delete(Tenant, Tenant.id, [samples.tenant_id], "tenant")
    await session.commit()
    return removed


# ---------------------------------------------------------------------------
# DLQ (Redis) seed / cleanup
# ---------------------------------------------------------------------------


async def seed_qa_dlq(redis_client: aioredis.Redis, samples: QaGovernanceSamples) -> dict[str, int]:
    """Store DLQ samples through the production Redis layout; idempotent by owner tag."""
    stored = 0
    for message in samples.dlq_messages:
        key = f"{RedisDLQAdapter.MESSAGE_PREFIX}{message.id}"
        existing = await cast("Awaitable[Any]", redis_client.hget(key, "data"))
        if existing is not None:
            payload = json.loads(
                existing.decode("utf-8") if isinstance(existing, bytes) else existing
            )
            if payload.get("metadata", {}).get("qa_fixture") != QA_MARKER:
                raise ValueError(
                    f"DLQ message {message.id} exists and is not owned by this fixture"
                )
            continue
        score = message.first_failed_at.timestamp()
        unresolved = message.status in (DLQMessageStatus.PENDING, DLQMessageStatus.RETRYING)
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping={"data": json.dumps(message.to_dict())})
            pipe.expire(key, 168 * 3600)
            pipe.zadd(RedisDLQAdapter.PENDING_INDEX, {message.id: score})
            pipe.zadd(
                f"{RedisDLQAdapter.ERROR_TYPE_INDEX_PREFIX}{message.error_type}",
                {message.id: score},
            )
            pipe.zadd(
                f"{RedisDLQAdapter.EVENT_TYPE_INDEX_PREFIX}{message.event_type}",
                {message.id: score},
            )
            pipe.hincrby(RedisDLQAdapter.STATS_KEY, "total_messages", 1)
            pipe.hincrby(
                RedisDLQAdapter.STATS_KEY,
                "pending_count" if unresolved else "resolved_count",
                1,
            )
            pipe.hincrby(RedisDLQAdapter.STATS_KEY, f"error:{message.error_type}", 1)
            pipe.hincrby(RedisDLQAdapter.STATS_KEY, f"event:{message.event_type}", 1)
            await pipe.execute()
        stored += 1
    return {"dlq_messages": stored}


async def cleanup_qa_dlq(
    redis_client: aioredis.Redis, samples: QaGovernanceSamples
) -> dict[str, int]:
    """Remove fixture-owned DLQ messages and roll back their stats contribution."""
    removed = 0
    status_counter = {
        DLQMessageStatus.PENDING.value: "pending_count",
        DLQMessageStatus.RETRYING.value: "pending_count",
        DLQMessageStatus.RESOLVED.value: "resolved_count",
        DLQMessageStatus.DISCARDED.value: "discarded_count",
        DLQMessageStatus.EXPIRED.value: "expired_count",
    }
    for message in samples.dlq_messages:
        key = f"{RedisDLQAdapter.MESSAGE_PREFIX}{message.id}"
        existing = await cast("Awaitable[Any]", redis_client.hget(key, "data"))
        if existing is None:
            continue
        payload = json.loads(existing.decode("utf-8") if isinstance(existing, bytes) else existing)
        if payload.get("metadata", {}).get("qa_fixture") != QA_MARKER:
            raise ValueError(f"DLQ message {message.id} is not owned by this fixture")
        current_status = payload.get("status", "pending")
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            pipe.zrem(RedisDLQAdapter.PENDING_INDEX, message.id)
            pipe.zrem(f"{RedisDLQAdapter.ERROR_TYPE_INDEX_PREFIX}{message.error_type}", message.id)
            pipe.zrem(f"{RedisDLQAdapter.EVENT_TYPE_INDEX_PREFIX}{message.event_type}", message.id)
            pipe.hincrby(RedisDLQAdapter.STATS_KEY, "total_messages", -1)
            pipe.hincrby(RedisDLQAdapter.STATS_KEY, f"error:{message.error_type}", -1)
            pipe.hincrby(RedisDLQAdapter.STATS_KEY, f"event:{message.event_type}", -1)
            pipe.hincrby(
                RedisDLQAdapter.STATS_KEY,
                status_counter.get(current_status, "pending_count"),
                -1,
            )
            await pipe.execute()
        removed += 1
    # Retried QA messages are republished onto routing-key streams; drop those too.
    stream_keys = [
        key async for key in redis_client.scan_iter(match="events:qa.governance.*", count=100)
    ]
    if stream_keys:
        await redis_client.delete(*stream_keys)
    return {"dlq_messages": removed, "dlq_streams": len(stream_keys)}


# ---------------------------------------------------------------------------
# Status / CLI
# ---------------------------------------------------------------------------


async def collect_qa_status(
    session: AsyncSession, redis_client: aioredis.Redis, samples: QaGovernanceSamples
) -> dict[str, Any]:
    """Report how many fixture rows exist per surface."""

    async def count(
        model: type[Base], id_column: InstrumentedAttribute[str], ids: list[str]
    ) -> int:
        if not ids:
            return 0
        result = await session.execute(
            sa.select(sa.func.count()).select_from(model).where(id_column.in_(ids))
        )
        return int(result.scalar_one())

    dlq_present = 0
    for message in samples.dlq_messages:
        key = f"{RedisDLQAdapter.MESSAGE_PREFIX}{message.id}"
        if await redis_client.exists(key):
            dlq_present += 1
    return {
        "fixture": QA_MARKER,
        "tenant_id": samples.tenant_id,
        "project_id": samples.project_id,
        "workspace_id": samples.workspace_id,
        "tenant_present": await count(Tenant, Tenant.id, [samples.tenant_id]),
        "project_present": await count(Project, Project.id, [samples.project_id]),
        "event_logs": await count(
            TenantEventLogModel, TenantEventLogModel.id, [e["id"] for e in samples.event_logs]
        ),
        "decision_records": await count(
            DecisionRecordModel,
            DecisionRecordModel.id,
            [d["id"] for d in samples.decision_records],
        ),
        "trust_policies": await count(
            TrustPolicyModel, TrustPolicyModel.id, [p["id"] for p in samples.trust_policies]
        ),
        "playbooks": await count(Playbook, Playbook.id, [p["id"] for p in samples.playbooks]),
        "verdicts": await count(
            ReflectionVerdictRecord, ReflectionVerdictRecord.id, [v["id"] for v in samples.verdicts]
        ),
        "audit_logs": await count(AuditLog, AuditLog.id, [a["id"] for a in samples.audit_logs]),
        "dlq_messages": dlq_present,
    }


async def _resolve_owner_id(session: AsyncSession, owner_email: str) -> str:
    result = await session.execute(sa.select(User.id).where(User.email == owner_email))
    owner_id = result.scalar_one_or_none()
    if owner_id is None:
        raise ValueError(f"Owner user {owner_email} does not exist; create it first")
    if not owner_email.endswith("@memstack.ai"):
        raise ValueError("QA governance fixtures require a memstack.ai service owner")
    return str(owner_id)


async def run(operation: str, *, owner_email: str) -> dict[str, Any]:
    settings = get_settings()
    engine = create_async_engine(settings.postgres_url)
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    redis_client: aioredis.Redis = aioredis.from_url(  # type: ignore[no-untyped-call]  # redis stubs incomplete
        redis_url
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with sessions() as session:
            owner_id = await _resolve_owner_id(session, owner_email)
            samples = build_qa_governance_samples(owner_id)
            if operation == "seed":
                sql_summary = await seed_qa_scope(session, samples)
                dlq_summary = await seed_qa_dlq(redis_client, samples)
            elif operation == "cleanup":
                sql_summary = await cleanup_qa_scope(session, samples)
                dlq_summary = await cleanup_qa_dlq(redis_client, samples)
            else:
                sql_summary, dlq_summary = {}, {}
            status = await collect_qa_status(session, redis_client, samples)
        return {
            "operation": operation,
            "applied": {**sql_summary, **dlq_summary},
            "status": status,
        }
    finally:
        await redis_client.aclose()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("operation", choices=["seed", "cleanup", "status"])
    _ = parser.add_argument("--owner-email", default="admin@memstack.ai")
    args = parser.parse_args()
    result = asyncio.run(run(args.operation, owner_email=args.owner_email))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
