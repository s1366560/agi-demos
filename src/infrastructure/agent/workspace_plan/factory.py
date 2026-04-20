"""Default-wiring factory for :class:`WorkspaceOrchestrator`.

Returns an orchestrator configured with in-memory adapters (:class:`InMemoryPlanRepository`,
:class:`InMemoryBlackboard`) and stub supervisor callables (no-op dispatcher /
empty agent pool). The DI container uses this as the initial singleton; future
milestones swap in SQL repositories and real dispatchers.
"""

from __future__ import annotations

import logging

from src.domain.model.workspace_plan import PlanNode
from src.domain.ports.services.task_allocator_port import Allocation, WorkspaceAgent
from src.domain.ports.services.verifier_port import VerificationContext
from src.infrastructure.agent.workspace_plan.allocator import CapabilityAllocator
from src.infrastructure.agent.workspace_plan.blackboard import InMemoryBlackboard
from src.infrastructure.agent.workspace_plan.orchestrator import (
    OrchestratorConfig,
    WorkspaceOrchestrator,
)
from src.infrastructure.agent.workspace_plan.planner import LLMGoalPlanner
from src.infrastructure.agent.workspace_plan.progress import ProgressProjector
from src.infrastructure.agent.workspace_plan.repository import InMemoryPlanRepository
from src.infrastructure.agent.workspace_plan.supervisor import WorkspaceSupervisor
from src.infrastructure.agent.workspace_plan.verifier import AcceptanceCriterionVerifier

logger = logging.getLogger(__name__)


async def _empty_agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
    return []


async def _noop_dispatcher(workspace_id: str, allocation: Allocation, node: PlanNode) -> str | None:
    logger.info(
        "workspace_plan.dispatcher.noop workspace=%s node=%s agent=%s",
        workspace_id,
        node.id,
        getattr(allocation, "agent_id", None),
    )
    return None


async def _default_attempt_context(workspace_id: str, node: PlanNode) -> VerificationContext:
    return VerificationContext(workspace_id=workspace_id, node=node)


def build_default_orchestrator(
    *,
    config: OrchestratorConfig | None = None,
) -> WorkspaceOrchestrator:
    """Wire a default, side-effect-free :class:`WorkspaceOrchestrator`.

    Suitable for unit tests, CLI tools, and the initial DI singleton. Real
    production wiring will replace the stub callables with the worker-launch
    dispatcher and SQL-backed repositories.
    """
    cfg = config or OrchestratorConfig.from_env()
    plan_repo = InMemoryPlanRepository()
    planner = LLMGoalPlanner(decomposer=None)
    allocator = CapabilityAllocator()
    verifier = AcceptanceCriterionVerifier()
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
        heartbeat_seconds=cfg.heartbeat_seconds,
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


__all__ = ["build_default_orchestrator"]
