from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AUTONOMY_SCHEMA_VERSION = 1

GoalOrigin = Literal["human_defined", "agent_inferred", "existing_objective", "existing_root"]
TaskRole = Literal["goal_root", "execution_task"]
GoalHealth = Literal["healthy", "at_risk", "blocked", "achieved"]
RemediationStatus = Literal["none", "replan_required", "ready_for_completion"]
ExecutionPhase = Literal["todo", "in_progress", "pending_adjudication", "blocked", "done"]
ExecutionAction = Literal[
    "created",
    "reprioritized",
    "await_leader_adjudication",
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


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    debug: dict[str, Any] | None = None


class RootGoalPolicyModel(ContractModel):
    mutable_by_agent: bool
    completion_requires_external_proof: bool


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
    last_mutation_actor: LastMutationActorModel | None = None


def has_autonomy_metadata(metadata: dict[str, Any] | None) -> bool:
    if not metadata:
        return False
    return any(
        key in metadata
        for key in (
            "autonomy_schema_version",
            "task_role",
            "goal_origin",
            "goal_source_refs",
            "goal_formalization_reason",
            "goal_evidence_bundle",
            "goal_health",
            "remediation_status",
            "blocked_child_task_ids",
            "replan_attempt_count",
            "execution_state",
            "root_goal_task_id",
            "objective_id",
            "root_goal_policy",
            "derived_from_internal_plan_step",
        )
    )
