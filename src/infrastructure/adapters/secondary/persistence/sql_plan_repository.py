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

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.domain.model.workspace_plan import Plan
from src.domain.model.workspace_plan.acceptance import AcceptanceCriterion, CriterionKind
from src.domain.model.workspace_plan.handoff import FeatureCheckpoint, HandoffPackage
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
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    PlanModel,
    PlanNodeModel,
)


class SqlPlanRepository(PlanRepositoryPort):
    """AsyncSession-backed persistence for :class:`Plan` aggregates.

    Uses per-plan *last writer wins*: :meth:`save` updates the persisted node
    set to match the aggregate. A PostgreSQL transaction-level advisory lock
    serializes concurrent aggregate saves for the same plan, while existing
    nodes are updated in-place to avoid broad delete/reinsert lock conflicts
    with runtime progress writers.

    Callers are responsible for ``await db.commit()`` (follows the repo-layer
    convention documented in ``AGENTS.md``).
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def save(self, plan: Plan) -> None:
        await self._lock_plan_for_save(plan.id)
        existing = await self._get_existing_plan_for_update(plan.id)
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

        existing_nodes = await self._get_existing_node_models(plan.id)
        current_node_ids = {node.id for node in plan.nodes.values()}
        stale_node_ids = set(existing_nodes) - current_node_ids
        if stale_node_ids:
            await self._db.execute(
                delete(PlanNodeModel).where(
                    PlanNodeModel.plan_id == plan.id,
                    PlanNodeModel.id.in_(stale_node_ids),
                )
            )
        for node in plan.nodes.values():
            node_model = existing_nodes.get(node.id)
            if node_model is None:
                self._db.add(_plan_node_to_model(node))
            else:
                _apply_plan_node_to_model(node, node_model)

        await self._db.flush()

    async def _lock_plan_for_save(self, plan_id: str) -> None:
        bind = self._db.get_bind()
        dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
        if dialect_name != "postgresql":
            return
        await self._db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:plan_id, 0))"),
            {"plan_id": f"workspace_plan:{plan_id}"},
        )

    async def _get_existing_plan_for_update(self, plan_id: str) -> PlanModel | None:
        stmt = select(PlanModel).where(PlanModel.id == plan_id).with_for_update()
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_existing_node_models(self, plan_id: str) -> dict[str, PlanNodeModel]:
        stmt = select(PlanNodeModel).where(PlanNodeModel.plan_id == plan_id)
        result = await self._db.execute(refresh_select_statement(stmt))
        return {model.id: model for model in result.scalars().all()}

    async def get(self, plan_id: str) -> Plan | None:
        stmt = (
            select(PlanModel).options(selectinload(PlanModel.nodes)).where(PlanModel.id == plan_id)
        )
        result = await self._db.execute(refresh_select_statement(stmt))
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
        result = await self._db.execute(refresh_select_statement(stmt))
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _plan_from_model(model)

    async def list_by_workspace(self, workspace_id: str, *, limit: int = 50) -> list[Plan]:
        stmt = (
            select(PlanModel)
            .options(selectinload(PlanModel.nodes))
            .where(PlanModel.workspace_id == workspace_id)
            .order_by(PlanModel.created_at.desc(), PlanModel.id.desc())
            .limit(max(1, limit))
        )
        result = await self._db.execute(refresh_select_statement(stmt))
        return [_plan_from_model(model) for model in result.scalars().all()]

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
    model = PlanNodeModel(
        id=node.id,
        plan_id=node.plan_id,
    )
    _apply_plan_node_to_model(node, model)
    return model


def _apply_plan_node_to_model(node: PlanNode, model: PlanNodeModel) -> None:
    model.plan_id = node.plan_id
    model.parent_id = node.parent_id.value if node.parent_id is not None else None
    model.kind = node.kind.value
    model.title = node.title
    model.description = node.description
    model.depends_on = [d.value for d in node.depends_on]
    model.inputs_schema = dict(node.inputs_schema)
    model.outputs_schema = dict(node.outputs_schema)
    model.acceptance_criteria = [_criterion_to_json(c) for c in node.acceptance_criteria]
    model.feature_checkpoint = (
        node.feature_checkpoint.to_json() if node.feature_checkpoint is not None else None
    )
    model.handoff_package = (
        node.handoff_package.to_json() if node.handoff_package is not None else None
    )
    model.recommended_capabilities = [
        {"name": c.name, "weight": c.weight} for c in node.recommended_capabilities
    ]
    model.preferred_agent_id = node.preferred_agent_id
    model.estimated_effort = {
        "minutes": node.estimated_effort.minutes,
        "confidence": node.estimated_effort.confidence,
    }
    model.priority = node.priority
    model.intent = node.intent.value
    model.execution = node.execution.value
    model.progress = {
        "percent": node.progress.percent,
        "confidence": node.progress.confidence,
        "note": node.progress.note,
    }
    model.assignee_agent_id = node.assignee_agent_id
    model.current_attempt_id = node.current_attempt_id
    model.workspace_task_id = node.workspace_task_id
    model.metadata_json = dict(node.metadata)
    model.created_at = node.created_at
    model.updated_at = node.updated_at
    model.completed_at = node.completed_at


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
        feature_checkpoint=_feature_checkpoint_from_json(model.feature_checkpoint),
        handoff_package=_handoff_package_from_json(model.handoff_package),
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


def _feature_checkpoint_from_json(payload: dict[str, Any] | None) -> FeatureCheckpoint | None:
    if not isinstance(payload, dict) or not payload:
        return None
    return FeatureCheckpoint.from_json(payload)


def _handoff_package_from_json(payload: dict[str, Any] | None) -> HandoffPackage | None:
    if not isinstance(payload, dict) or not payload:
        return None
    return HandoffPackage.from_json(payload)


__all__ = ["SqlPlanRepository"]
