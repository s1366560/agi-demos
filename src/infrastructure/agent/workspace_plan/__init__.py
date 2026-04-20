"""Infrastructure adapters for the multi-agent workspace_plan architecture.

Submodules:

* :mod:`planner`    — LLM-backed :class:`GoalPlannerPort` implementation
* :mod:`allocator`  — capability-scored :class:`TaskAllocatorPort`
* :mod:`verifier`   — :class:`VerifierPort` with cmd/schema/file_exists/regex runners
* :mod:`progress`   — :class:`ProgressProjectorPort`
* :mod:`blackboard` — in-memory / redis-backed :class:`BlackboardPort`
* :mod:`supervisor` — async single-writer :class:`WorkspaceSupervisorPort`
* :mod:`repository` — in-memory and SQL :class:`PlanRepositoryPort` impls
* :mod:`adapter`    — bi-directional ``PlanNode`` ↔ ``WorkspaceTask`` mapping
* :mod:`orchestrator` — the L5 façade wiring everything together

Gated behind the ``WORKSPACE_V2_*`` feature flags so legacy runtime is untouched.
"""

from src.infrastructure.agent.workspace_plan.allocator import CapabilityAllocator
from src.infrastructure.agent.workspace_plan.blackboard import InMemoryBlackboard
from src.infrastructure.agent.workspace_plan.factory import build_default_orchestrator
from src.infrastructure.agent.workspace_plan.orchestrator import (
    OrchestratorConfig,
    WorkspaceOrchestrator,
)
from src.infrastructure.agent.workspace_plan.planner import LLMGoalPlanner
from src.infrastructure.agent.workspace_plan.progress import ProgressProjector
from src.infrastructure.agent.workspace_plan.repository import InMemoryPlanRepository
from src.infrastructure.agent.workspace_plan.supervisor import WorkspaceSupervisor
from src.infrastructure.agent.workspace_plan.verifier import (
    AcceptanceCriterionVerifier,
    CmdCriterionRunner,
    FileExistsCriterionRunner,
    RegexCriterionRunner,
    SchemaCriterionRunner,
)

__all__ = [
    "AcceptanceCriterionVerifier",
    "CapabilityAllocator",
    "CmdCriterionRunner",
    "FileExistsCriterionRunner",
    "InMemoryBlackboard",
    "InMemoryPlanRepository",
    "LLMGoalPlanner",
    "OrchestratorConfig",
    "ProgressProjector",
    "RegexCriterionRunner",
    "SchemaCriterionRunner",
    "WorkspaceOrchestrator",
    "WorkspaceSupervisor",
    "build_default_orchestrator",
]
