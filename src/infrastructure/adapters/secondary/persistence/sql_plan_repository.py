"""SQL-backed :class:`PlanRepositoryPort` implementation.

Mirrors :class:`InMemoryPlanRepository` semantics but persists :class:`Plan`
aggregates into ``workspace_plans`` / ``workspace_plan_nodes`` tables (added
by Alembic migration ``n1a2b3c4d5e6``).

Value objects (``depends_on``, ``acceptance_criteria``, ``capabilities``,
``progress``, ``estimated_effort``) are serialized as JSON per-column. The
serialization contract is owned here and covered by round-trip unit tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.domain.model.workspace_plan import Plan
from src.domain.model.workspace_plan.acceptance import AcceptanceCriterion, CriterionKind
from src.domain.model.workspace_plan.plan import PlanStatus
from src.domain.model.workspace_plan.plan_node import (
    Capability,
    Effort,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    Progress,
    TaskExecution,
    TaskIntent,
)
from src.domain.ports.services.plan_repository_port import PlanRepositoryPort
from src.infrastructure.adapters.secondary.persistence.models import (
    PlanModel,
    PlanNodeModel,
)


class SqlPlanRepository(PlanRepositoryPort):
    """AsyncSession-backed persistence for :class:`Plan` aggregates.

    Uses per-workspace *last writer wins*: :meth:`save` replaces the entire
    node set for the plan id. The supervisor enforces single-writer-per-
    workspace so this is safe in practice.

    Callers are responsible for ``await db.commit()`` (follows the repo-layer
    convention documented in ``AGENTS.md``).
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def save(self, plan: Plan) -> None:
        existing = await self._db.get(PlanModel, plan.id)
        if existing is None:
            model = PlanModel(
                id=plan.id,
                workspace_id=plan.workspace_id,
                goal_id=plan.goal_id.value,
                status=plan.status.value,
                created_at=plan.created_at,
                updated_at=plan.updated_at,
            )
            self._db.add(model)
        else:
            existing.workspace_id = plan.workspace_id
            existing.goal_id = plan.goal_id.value
            existing.status = plan.status.value
            existing.updated_at = plan.updated_at or datetime.now(UTC)
            # Drop stale nodes; replacement happens below via fresh inserts.
            await self._db.execute(delete(PlanNodeModel).where(PlanNodeModel.plan_id == plan.id))

        for node in plan.nodes.values():
            self._db.add(_plan_node_to_model(node))

        await self._db.flush()

    async def get(self, plan_id: str) -> Plan | None:
        stmt = (
            select(PlanModel).options(selectinload(PlanModel.nodes)).where(PlanModel.id == plan_id)
        )
        result = await self._db.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _plan_from_model(model)

    async def get_by_workspace(self, workspace_id: str) -> Plan | None:
        stmt = (
            select(PlanModel)
            .options(selectinload(PlanModel.nodes))
            .where(PlanModel.workspace_id == workspace_id)
            .order_by(PlanModel.created_at.desc())
            .limit(1)
        )
        result = await self._db.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _plan_from_model(model)

    async def delete(self, plan_id: str) -> None:
        existing = await self._db.get(PlanModel, plan_id)
        if existing is not None:
            await self._db.delete(existing)
            await self._db.flush()


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _plan_from_model(model: PlanModel) -> Plan:
    plan = Plan(
        id=model.id,
        workspace_id=model.workspace_id,
        goal_id=PlanNodeId(value=model.goal_id),
        status=PlanStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
    # Bypass add_node() invariants so we can load in arbitrary order; the
    # aggregate was validated when it was originally saved.
    for node_model in model.nodes:
        plan.nodes[PlanNodeId(value=node_model.id)] = _plan_node_from_model(node_model)
    return plan


def _plan_node_to_model(node: PlanNode) -> PlanNodeModel:
    return PlanNodeModel(
        id=node.id,
        plan_id=node.plan_id,
        parent_id=node.parent_id.value if node.parent_id is not None else None,
        kind=node.kind.value,
        title=node.title,
        description=node.description,
        depends_on=[d.value for d in node.depends_on],
        inputs_schema=dict(node.inputs_schema),
        outputs_schema=dict(node.outputs_schema),
        acceptance_criteria=[_criterion_to_json(c) for c in node.acceptance_criteria],
        recommended_capabilities=[
            {"name": c.name, "weight": c.weight} for c in node.recommended_capabilities
        ],
        preferred_agent_id=node.preferred_agent_id,
        estimated_effort={
            "minutes": node.estimated_effort.minutes,
            "confidence": node.estimated_effort.confidence,
        },
        priority=node.priority,
        intent=node.intent.value,
        execution=node.execution.value,
        progress={
            "percent": node.progress.percent,
            "confidence": node.progress.confidence,
            "note": node.progress.note,
        },
        assignee_agent_id=node.assignee_agent_id,
        current_attempt_id=node.current_attempt_id,
        workspace_task_id=node.workspace_task_id,
        metadata_json=dict(node.metadata),
        created_at=node.created_at,
        updated_at=node.updated_at,
        completed_at=node.completed_at,
    )


def _plan_node_from_model(model: PlanNodeModel) -> PlanNode:
    return PlanNode(
        id=model.id,
        plan_id=model.plan_id,
        parent_id=PlanNodeId(value=model.parent_id) if model.parent_id else None,
        kind=PlanNodeKind(model.kind),
        title=model.title,
        description=model.description or "",
        depends_on=frozenset(PlanNodeId(value=d) for d in (model.depends_on or [])),
        inputs_schema=dict(model.inputs_schema or {}),
        outputs_schema=dict(model.outputs_schema or {}),
        acceptance_criteria=tuple(
            _criterion_from_json(c) for c in (model.acceptance_criteria or [])
        ),
        recommended_capabilities=tuple(
            Capability(name=c["name"], weight=float(c.get("weight", 1.0)))
            for c in (model.recommended_capabilities or [])
            if isinstance(c, dict) and c.get("name")
        ),
        preferred_agent_id=model.preferred_agent_id,
        estimated_effort=Effort(
            minutes=int((model.estimated_effort or {}).get("minutes", 0)),
            confidence=float((model.estimated_effort or {}).get("confidence", 0.5)),
        ),
        priority=model.priority,
        intent=TaskIntent(model.intent),
        execution=TaskExecution(model.execution),
        progress=Progress(
            percent=float((model.progress or {}).get("percent", 0.0)),
            confidence=float((model.progress or {}).get("confidence", 1.0)),
            note=str((model.progress or {}).get("note", "")),
        ),
        assignee_agent_id=model.assignee_agent_id,
        current_attempt_id=model.current_attempt_id,
        workspace_task_id=model.workspace_task_id,
        metadata=dict(model.metadata_json or {}),
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


def _criterion_to_json(c: AcceptanceCriterion) -> dict[str, Any]:
    return {
        "kind": c.kind.value,
        "spec": dict(c.spec),
        "required": c.required,
        "description": c.description,
    }


def _criterion_from_json(payload: dict[str, Any]) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        kind=CriterionKind(payload["kind"]),
        spec=dict(payload.get("spec") or {}),
        required=bool(payload.get("required", True)),
        description=str(payload.get("description", "")),
    )


__all__ = ["SqlPlanRepository"]
