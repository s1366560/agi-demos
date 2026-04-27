from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    AUTONOMY_SCHEMA_VERSION_KEY,
    DERIVED_FROM_INTERNAL_PLAN_STEP,
    EXECUTION_STATE,
    REMEDIATION_STATUS,
    REPLAN_ATTEMPT_COUNT,
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)

AUTONOMY_SCHEMA_VERSION = 1

GoalOrigin = Literal["human_defined", "agent_inferred", "existing_objective", "existing_root"]
TaskRole = Literal["goal_root", "execution_task"]
GoalHealth = Literal["healthy", "at_risk", "blocked", "achieved"]
RemediationStatus = Literal["none", "replan_required", "ready_for_completion"]
ExecutionPhase = Literal["todo", "in_progress", "pending_adjudication", "blocked", "done"]
WorkspaceType = Literal["general", "software_development", "research", "operations"]
ExecutionAction = Literal[
    "created",
    "reprioritized",
    "await_leader_adjudication",
    "await_plan_verification",
    "blocked",
    "completed",
    "start",
]
OutcomeStatus = Literal["achieved", "blocked", "partial", "failed"]
VerificationGrade = Literal["pass", "warn", "fail"]
SignalSourceType = Literal[
    "existing_root_task",
    "existing_objective",
    "blackboard_signal",
    "message_signal",
    "converged_signal",
]
HandoffReasonValue = Literal[
    "planned",
    "context_limit",
    "session_end",
    "worker_restart",
    "retry",
    "replan",
    "manual",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    debug: dict[str, Any] | None = None


class RootGoalPolicyModel(ContractModel):
    mutable_by_agent: bool
    completion_requires_external_proof: bool


class CompletionPolicyOverrideModel(ContractModel):
    allow_internal_task_artifacts: bool | None = None
    required_artifact_prefixes: list[str] | None = None
    requires_external_artifact: bool | None = None
    minimum_verification_grade: VerificationGrade | None = None


class AutonomyProfileModel(ContractModel):
    workspace_type: WorkspaceType | None = None
    completion_policy: CompletionPolicyOverrideModel | None = None


class WorkspaceCodeContextModel(ContractModel):
    sandbox_code_root: str | None = None
    loaded_agents_files: list[str] = Field(default_factory=list)
    agents_digest: str | None = None
    agents_excerpt: str | None = None


class FeatureCheckpointMetadataModel(ContractModel):
    feature_id: str
    sequence: int = Field(default=0, ge=0)
    title: str = ""
    init_command: str | None = None
    test_commands: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)
    worktree_path: str | None = None
    branch_name: str | None = None
    base_ref: str | None = None
    commit_ref: str | None = None
    handoff_notes: str = ""


class HandoffPackageMetadataModel(ContractModel):
    reason: HandoffReasonValue
    summary: str
    next_steps: list[str] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    git_head: str | None = None
    git_diff_summary: str = ""
    test_commands: list[str] = Field(default_factory=list)
    verification_notes: str = ""
    created_at: str | None = None


class SourceBreakdownItemModel(ContractModel):
    source_type: SignalSourceType
    score: float = Field(ge=0.0, le=1.0)
    ref: str | None = None
    bonus_applied: float | None = Field(default=None, ge=0.0, le=1.0)


class GoalCandidateRecordModel(ContractModel):
    candidate_id: str
    candidate_text: str
    candidate_kind: Literal["existing", "inferred"]
    source_refs: list[str]
    evidence_strength: float = Field(ge=0.0, le=1.0)
    source_breakdown: list[SourceBreakdownItemModel]
    freshness: float = Field(ge=0.0, le=1.0)
    urgency: float = Field(ge=0.0, le=1.0)
    user_intent_confidence: float = Field(ge=0.0, le=1.0)
    formalizable: bool
    decision: Literal[
        "adopt_existing_goal",
        "formalize_new_goal",
        "defer",
        "reject_as_non_goal",
    ]


class LastMutationActorModel(ContractModel):
    action: str
    actor_type: Literal["human", "agent"]
    actor_user_id: str
    actor_agent_id: str | None = None
    workspace_agent_binding_id: str | None = None
    reason: str


class GoalEvidenceSignalModel(ContractModel):
    source_type: SignalSourceType
    ref: str
    score: float = Field(ge=0.0, le=1.0)


class GoalEvidenceBundleModel(ContractModel):
    score: float = Field(ge=0.0, le=1.0)
    signals: list[GoalEvidenceSignalModel]
    formalized_at: str


class CompletionEvidenceModel(ContractModel):
    goal_task_id: str
    goal_text_snapshot: str
    outcome_status: OutcomeStatus
    summary: str
    artifacts: list[str]
    verifications: list[str] = Field(min_length=1)
    generated_by_agent_id: str
    recorded_at: str
    verification_grade: VerificationGrade


class ExecutionStateModel(ContractModel):
    phase: ExecutionPhase
    last_agent_reason: str
    last_agent_action: ExecutionAction
    updated_by_actor_type: Literal["agent", "human"]
    updated_by_actor_id: str
    updated_at: str


class RootGoalMetadataModel(ContractModel):
    autonomy_schema_version: Literal[1]
    task_role: Literal["goal_root"]
    goal_origin: GoalOrigin
    workspace_type: WorkspaceType | None = None
    autonomy_profile: AutonomyProfileModel | None = None
    sandbox_code_root: str | None = None
    code_context: WorkspaceCodeContextModel | None = None
    goal_source_refs: list[str] = Field(default_factory=list)
    goal_formalization_reason: str | None = None
    objective_id: str | None = None
    root_goal_policy: RootGoalPolicyModel | None = None
    goal_evidence_bundle: GoalEvidenceBundleModel | None = None
    goal_progress_summary: str | None = None
    last_progress_at: str | None = None
    active_child_task_ids: list[str] = Field(default_factory=list)
    blocked_child_task_ids: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    goal_health: GoalHealth | None = None
    remediation_status: RemediationStatus | None = None
    remediation_summary: str | None = None
    replan_attempt_count: int | None = Field(default=None, ge=0)
    last_replan_at: str | None = None
    goal_evidence: CompletionEvidenceModel | None = None
    last_mutation_actor: LastMutationActorModel | None = None

    @model_validator(mode="after")
    def _validate_origin_specific_fields(self) -> RootGoalMetadataModel:
        if self.goal_origin == "existing_objective" and not self.objective_id:
            raise ValueError("existing_objective root goals require objective_id")
        if self.goal_origin == "agent_inferred" and self.goal_evidence_bundle is None:
            raise ValueError("agent_inferred root goals require goal_evidence_bundle")
        return self


class ExecutionTaskMetadataModel(ContractModel):
    autonomy_schema_version: Literal[1]
    task_role: Literal["execution_task"]
    root_goal_task_id: str
    parent_task_id: str | None = None
    lineage_source: Literal["human", "agent"]
    derived_from_internal_plan_step: str | None = None
    workspace_agent_binding_id: str | None = None
    workspace_plan_id: str | None = None
    workspace_plan_node_id: str | None = None
    code_context: WorkspaceCodeContextModel | None = None
    feature_checkpoint: FeatureCheckpointMetadataModel | None = None
    handoff_package: HandoffPackageMetadataModel | None = None
    write_set: list[str] = Field(default_factory=list)
    verification_commands: list[str] = Field(default_factory=list)
    launch_state: str | None = None
    current_attempt_id: str | None = None
    last_attempt_id: str | None = None
    current_attempt_number: int | None = Field(default=None, ge=1)
    current_attempt_conversation_id: str | None = None
    current_attempt_worker_agent_id: str | None = None
    current_attempt_worker_binding_id: str | None = None
    delegated_subagent_name: str | None = None
    delegated_subagent_id: str | None = None
    delegated_task_text: str | None = None
    last_attempt_status: str | None = None
    execution_state: ExecutionStateModel | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    execution_verifications: list[str] = Field(default_factory=list)
    last_worker_report_type: str | None = None
    last_worker_report_summary: str | None = None
    last_worker_report_artifacts: list[str] = Field(default_factory=list)
    last_worker_report_verifications: list[str] = Field(default_factory=list)
    last_worker_reported_at: str | None = None
    last_worker_report_fingerprint: str | None = None
    last_worker_report_id: str | None = None
    pending_leader_adjudication: bool | None = None
    durable_plan_verdict: str | None = None
    durable_plan_verification_summary: str | None = None
    durable_plan_verified_at: str | None = None
    last_leader_adjudication_status: str | None = None
    last_leader_adjudicated_at: str | None = None
    last_mutation_actor: LastMutationActorModel | None = None


def has_autonomy_metadata(metadata: dict[str, Any] | None) -> bool:
    if not metadata:
        return False
    return any(
        key in metadata
        for key in (
            AUTONOMY_SCHEMA_VERSION_KEY,
            TASK_ROLE,
            "goal_origin",
            "goal_source_refs",
            "goal_formalization_reason",
            "goal_evidence_bundle",
            "goal_health",
            "workspace_type",
            "autonomy_profile",
            REMEDIATION_STATUS,
            "blocked_child_task_ids",
            REPLAN_ATTEMPT_COUNT,
            EXECUTION_STATE,
            ROOT_GOAL_TASK_ID,
            "objective_id",
            "root_goal_policy",
            DERIVED_FROM_INTERNAL_PLAN_STEP,
            WORKSPACE_PLAN_ID,
            WORKSPACE_PLAN_NODE_ID,
        )
    )
