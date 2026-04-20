"""L5 façade: :class:`WorkspaceOrchestrator` wires planner + allocator +
supervisor + verifier + projector + blackboard into a single entry point.

This is what the application layer (``WorkspaceAutonomyOrchestrator`` et al.)
calls — it *replaces* the tangled ``schedule_autonomy_tick`` fire-and-forget
path with a typed, observable flow.

Feature-flagged via ``WORKSPACE_V2_ENABLED`` so the legacy runtime is not
touched until tests confirm behavior parity.
"""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass

from src.domain.model.workspace_plan import (
    GoalProgress,
    Plan,
    PlanStatus,
    TaskExecution,
    TaskIntent,
    transition_execution,
    transition_intent,
)
from src.domain.ports.services.blackboard_port import BlackboardPort
from src.domain.ports.services.goal_planner_port import (
    GoalPlannerPort,
    GoalSpec,
    PlanningContext,
)
from src.domain.ports.services.plan_repository_port import PlanRepositoryPort
from src.domain.ports.services.progress_projector_port import ProgressProjectorPort
from src.domain.ports.services.task_allocator_port import TaskAllocatorPort
from src.domain.ports.services.verifier_port import VerifierPort
from src.domain.ports.services.workspace_supervisor_port import (
    WorkspaceSupervisorPort,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrchestratorConfig:
    enabled: bool = True
    heartbeat_seconds: float = 10.0
    max_planning_depth: int = 2
    max_subtasks: int = 8

    @classmethod
    def from_env(cls) -> OrchestratorConfig:
        return cls(
            enabled=os.getenv("WORKSPACE_V2_ENABLED", "true").lower() == "true",
            heartbeat_seconds=float(os.getenv("WORKSPACE_V2_HEARTBEAT_SEC", "10")),
            max_planning_depth=int(os.getenv("WORKSPACE_V2_MAX_DEPTH", "2")),
            max_subtasks=int(os.getenv("WORKSPACE_V2_MAX_SUBTASKS", "8")),
        )


class WorkspaceOrchestrator:
    """High-level entry point for the multi-agent architecture.

    The existing ``WorkspaceAutonomyOrchestrator`` (pure-forward dataclass)
    should delegate to this class when ``config.enabled`` is True. When
    disabled it is a no-op — legacy runtime continues unchanged.
    """

    def __init__(
        self,
        *,
        planner: GoalPlannerPort,
        allocator: TaskAllocatorPort,
        verifier: VerifierPort,
        projector: ProgressProjectorPort,
        supervisor: WorkspaceSupervisorPort,
        plan_repo: PlanRepositoryPort,
        blackboard: BlackboardPort | None = None,
        config: OrchestratorConfig | None = None,
    ) -> None:
        self._planner = planner
        self._allocator = allocator
        self._verifier = verifier
        self._projector = projector
        self._supervisor = supervisor
        self._repo = plan_repo
        self._blackboard = blackboard
        self._config = config or OrchestratorConfig.from_env()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    # --- lifecycle -----------------------------------------------------

    async def start_goal(
        self,
        *,
        workspace_id: str,
        title: str,
        description: str = "",
        created_by: str = "",
        available_agents: tuple[str, ...] = (),
        conversation_context: str | None = None,
    ) -> Plan:
        """Create or refresh a plan for ``workspace_id`` and start supervision."""
        if not self._config.enabled:
            raise RuntimeError("WorkspaceOrchestrator is disabled (set WORKSPACE_V2_ENABLED=true)")
        existing = await self._repo.get_by_workspace(workspace_id)
        if existing is not None and existing.status in (
            PlanStatus.DRAFT,
            PlanStatus.ACTIVE,
        ):
            logger.info("reusing active plan %s for workspace %s", existing.id, workspace_id)
            await self._supervisor.start(workspace_id)
            return existing

        plan = await self._planner.plan(
            GoalSpec(
                workspace_id=workspace_id,
                title=title,
                description=description,
                created_by=created_by,
            ),
            PlanningContext(
                available_agent_names=available_agents,
                max_subtasks=self._config.max_subtasks,
                max_depth=self._config.max_planning_depth,
                conversation_context=conversation_context,
            ),
        )
        errors = plan.validate()
        if errors:
            logger.warning("plan %s has validation errors: %s", plan.id, errors)
        await self._repo.save(plan)
        await self._supervisor.start(workspace_id)
        return plan

    async def stop_goal(self, workspace_id: str) -> None:
        if not self._config.enabled:
            return
        await self._supervisor.stop(workspace_id)

    async def mark_worker_reported(
        self,
        *,
        workspace_id: str,
        node_id: str,
        attempt_id: str | None = None,
    ) -> None:
        """Called by the worker-report pipeline to push a node into REPORTED.

        The supervisor's next tick will pick it up, verify, and advance the
        intent state machine.
        """
        plan = await self._repo.get_by_workspace(workspace_id)
        if plan is None:
            return
        from src.domain.model.workspace_plan import PlanNodeId

        nid = PlanNodeId(node_id)
        node = plan.nodes.get(nid)
        if node is None:
            return
        try:
            new_exec = transition_execution(node.execution, TaskExecution.REPORTED)
        except Exception:
            # Already past REPORTED; swallow — idempotent.
            return
        # Intent stays IN_PROGRESS until verifier rules it DONE/BLOCKED.
        with contextlib.suppress(Exception):
            transition_intent(node.intent, TaskIntent.IN_PROGRESS)
        from dataclasses import replace

        plan.replace_node(
            replace(
                node,
                execution=new_exec,
                current_attempt_id=attempt_id or node.current_attempt_id,
            )
        )
        await self._repo.save(plan)
        # Kick supervisor so it verifies ASAP rather than waiting for heartbeat.
        kick = getattr(self._supervisor, "kick", None)
        if callable(kick):
            kick(workspace_id)

    async def current_progress(self, workspace_id: str) -> GoalProgress | None:
        plan = await self._repo.get_by_workspace(workspace_id)
        if plan is None:
            return None
        return self._projector.project(plan)
