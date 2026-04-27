"""Workspace-plan domain: typed DAG for multi-agent goal execution.

This package is the M1 foundation of the multi-agent refactor. It introduces:

* :class:`PlanNode`            — a task / milestone / verify node in the goal DAG
* :class:`Plan`                — aggregate root: a DAG of PlanNodes
* :class:`AcceptanceCriterion` — machine-checkable completion criteria
* :class:`FeatureCheckpoint`   — durable feature checklist boundary
* :class:`HandoffPackage`      — context rehydration package for worker rollover
* :class:`VerificationReport`  — result of running acceptance criteria
* :class:`GoalProgress`        — first-class progress projection

Status is split into two orthogonal concerns:

* :class:`TaskIntent`    — user-facing lifecycle (TODO/IN_PROGRESS/BLOCKED/DONE)
* :class:`TaskExecution` — orchestration transient (IDLE/DISPATCHED/RUNNING/...)

Everything here is pure — no DB, no LLM, no I/O. Infrastructure ports and
adapters live under ``src.infrastructure.agent.workspace_plan``.
"""

from src.domain.model.workspace_plan.acceptance import (
    AcceptanceCriterion,
    CriterionKind,
    CriterionResult,
    EvidenceRef,
    VerificationReport,
)
from src.domain.model.workspace_plan.event import WorkspacePlanEvent
from src.domain.model.workspace_plan.goal_progress import GoalProgress
from src.domain.model.workspace_plan.handoff import (
    FeatureCheckpoint,
    HandoffPackage,
    HandoffReason,
)
from src.domain.model.workspace_plan.plan import Plan, PlanStatus
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
from src.domain.model.workspace_plan.state_machine import (
    ExecutionTransitionError,
    IntentTransitionError,
    allowed_execution_next,
    allowed_intent_next,
    can_transition_execution,
    can_transition_intent,
    transition_execution,
    transition_intent,
)

__all__ = [
    "AcceptanceCriterion",
    "Capability",
    "CriterionKind",
    "CriterionResult",
    "Effort",
    "EvidenceRef",
    "ExecutionTransitionError",
    "FeatureCheckpoint",
    "GoalProgress",
    "HandoffPackage",
    "HandoffReason",
    "IntentTransitionError",
    "Plan",
    "PlanNode",
    "PlanNodeId",
    "PlanNodeKind",
    "PlanStatus",
    "Progress",
    "TaskExecution",
    "TaskIntent",
    "VerificationReport",
    "WorkspacePlanEvent",
    "allowed_execution_next",
    "allowed_intent_next",
    "can_transition_execution",
    "can_transition_intent",
    "transition_execution",
    "transition_intent",
]
