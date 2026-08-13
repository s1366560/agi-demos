"""Safe constructors for Workspace Plan orchestration.

Only the side-effect-free in-memory orchestrator remains available for domain
tests and CLI experiments. Avernet Workspace Core owns durable Plan, Task,
outbox, and projection state; Python SQL composition is intentionally retired.
"""

from __future__ import annotations

from src.domain.model.workspace_plan import PlanNode
from src.domain.ports.services.iteration_review_port import IterationReviewPort
from src.domain.ports.services.task_allocator_port import Allocation, WorkspaceAgent
from src.domain.ports.services.verifier_port import VerificationContext
from src.domain.ports.services.workspace_supervisor_decision_port import (
    WorkspaceSupervisorDecisionPort,
)
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationJudgePort,
)
from src.infrastructure.agent.workspace_plan.allocator import CapabilityAllocator
from src.infrastructure.agent.workspace_plan.blackboard import InMemoryBlackboard
from src.infrastructure.agent.workspace_plan.orchestrator import (
    OrchestratorConfig,
    WorkspaceOrchestrator,
)
from src.infrastructure.agent.workspace_plan.planner import LLMGoalPlanner, TaskDecomposerProtocol
from src.infrastructure.agent.workspace_plan.progress import ProgressProjector
from src.infrastructure.agent.workspace_plan.repository import InMemoryPlanRepository
from src.infrastructure.agent.workspace_plan.supervisor import WorkspaceSupervisor
from src.infrastructure.agent.workspace_plan.verifier import AcceptanceCriterionVerifier


class LegacyWorkspacePlanRuntimeRetiredError(RuntimeError):
    """Raised when legacy Python SQL Plan composition is requested."""


async def _empty_agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
    return []


async def _noop_dispatcher(
    _workspace_id: str,
    _allocation: Allocation,
    _node: PlanNode,
) -> str | None:
    return None


async def _default_attempt_context(workspace_id: str, node: PlanNode) -> VerificationContext:
    return VerificationContext(workspace_id=workspace_id, node=node)


def build_default_orchestrator(
    *,
    config: OrchestratorConfig | None = None,
    decomposer: TaskDecomposerProtocol | None = None,
    iteration_reviewer: IterationReviewPort | None = None,
    verification_judge: WorkspaceVerificationJudgePort | None = None,
    supervisor_decision_provider: WorkspaceSupervisorDecisionPort | None = None,
) -> WorkspaceOrchestrator:
    """Build a side-effect-free in-memory orchestrator for isolated tests."""
    cfg = config or OrchestratorConfig.from_env()
    plan_repo = InMemoryPlanRepository()
    planner = LLMGoalPlanner(decomposer=decomposer)
    allocator = CapabilityAllocator()
    verifier = AcceptanceCriterionVerifier(verification_judge=verification_judge)
    projector = ProgressProjector()
    blackboard = InMemoryBlackboard()
    supervisor = WorkspaceSupervisor(
        plan_repo=plan_repo,
        allocator=allocator,
        verifier=verifier,
        projector=projector,
        planner=planner,
        agent_pool=_empty_agent_pool,
        dispatcher=_noop_dispatcher,
        attempt_context=_default_attempt_context,
        iteration_reviewer=iteration_reviewer,
        supervisor_decision_provider=supervisor_decision_provider,
        heartbeat_seconds=cfg.heartbeat_seconds,
        max_dispatches_per_tick=cfg.max_dispatches_per_tick,
    )
    return WorkspaceOrchestrator(
        planner=planner,
        allocator=allocator,
        verifier=verifier,
        projector=projector,
        supervisor=supervisor,
        plan_repo=plan_repo,
        blackboard=blackboard,
        config=cfg,
    )


def build_sql_orchestrator(*_args: object, **_kwargs: object) -> WorkspaceOrchestrator:
    """Fail closed instead of composing platform SQL as Workspace authority."""
    raise LegacyWorkspacePlanRuntimeRetiredError(
        "Python SQL Workspace Plan runtime is retired; use Avernet Workspace Core"
    )


__all__ = [
    "LegacyWorkspacePlanRuntimeRetiredError",
    "build_default_orchestrator",
    "build_sql_orchestrator",
]
