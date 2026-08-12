//! Legacy-compatible Workspace Plan use cases with Agent-first judgment boundaries.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{DateTime, SecondsFormat, Utc};
use memstack_workspace_service_api::{
    WorkspacePlanJudgeContractError, WorkspacePlanJudgePort, WorkspacePlanJudgePortError,
    WorkspacePlanJudgment, WorkspacePlanJudgmentKind, WorkspacePlanJudgmentRequest,
};
use memstack_workspace_store::{
    WorkspacePlanJudgmentAudit, WorkspacePlanNodeRecord, WorkspacePlanRecord, WorkspacePlanScope,
    WorkspacePlanSnapshot, WorkspacePlanSnapshotQuery, WorkspacePlanStore, WorkspacePlanStoreError,
    WorkspacePlanTransition, WorkspacePlanTransitionKind,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use thiserror::Error;

use crate::plan_idempotency::{
    action_idempotency_key, action_request_hash, deterministic_id, transition_ids,
};
use crate::public_plan_snapshot::{PublicWorkspacePlanSnapshot, public_snapshot};

const MAX_REASON_CHARS: usize = 500;
const MAX_EVIDENCE_REFS: usize = 20;

/// Authenticated route context.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspacePlanContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub actor_id: String,
    pub actor_is_superuser: bool,
}

/// Public GET controls.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspacePlanSnapshotInput {
    pub context: PublicWorkspacePlanContext,
    pub plan_id: Option<String>,
    pub include_details: bool,
    pub outbox_limit: u64,
    pub event_limit: u64,
}

/// Public Plan actions represented by the eleven legacy routes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum PublicWorkspacePlanAction {
    RecoverStaleAttempts,
    RetryOutbox,
    PauseIteration,
    ResumeIteration,
    TriggerNextIteration,
    RunPipeline,
    RegenerateDeliveryContract,
    RequestNodeReplan,
    ReopenNode,
    AcceptNodeReview,
}

impl PublicWorkspacePlanAction {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::RecoverStaleAttempts => "recover_stale_attempts",
            Self::RetryOutbox => "retry_outbox",
            Self::PauseIteration => "pause_iteration",
            Self::ResumeIteration => "resume_iteration",
            Self::TriggerNextIteration => "trigger_next_iteration",
            Self::RunPipeline => "run_pipeline",
            Self::RegenerateDeliveryContract => "regenerate_delivery_contract",
            Self::RequestNodeReplan => "request_node_replan",
            Self::ReopenNode => "reopen_node",
            Self::AcceptNodeReview => "accept_node_review",
        }
    }

    const fn transition_kind(self) -> WorkspacePlanTransitionKind {
        match self {
            Self::RecoverStaleAttempts => WorkspacePlanTransitionKind::RecoverStaleAttempts,
            Self::RetryOutbox => WorkspacePlanTransitionKind::RetryOutbox,
            Self::PauseIteration => WorkspacePlanTransitionKind::PauseIteration,
            Self::ResumeIteration => WorkspacePlanTransitionKind::ResumeIteration,
            Self::TriggerNextIteration => WorkspacePlanTransitionKind::TriggerNextIteration,
            Self::RunPipeline => WorkspacePlanTransitionKind::RunPipeline,
            Self::RegenerateDeliveryContract => {
                WorkspacePlanTransitionKind::RegenerateDeliveryContract
            }
            Self::RequestNodeReplan => WorkspacePlanTransitionKind::RequestNodeReplan,
            Self::ReopenNode => WorkspacePlanTransitionKind::ReopenNode,
            Self::AcceptNodeReview => WorkspacePlanTransitionKind::AcceptNodeReview,
        }
    }

    const fn judgment_kind(self) -> Option<WorkspacePlanJudgmentKind> {
        match self {
            Self::RecoverStaleAttempts => Some(WorkspacePlanJudgmentKind::RecoverStaleAttempts),
            Self::TriggerNextIteration => Some(WorkspacePlanJudgmentKind::TriggerNextIteration),
            Self::RunPipeline => Some(WorkspacePlanJudgmentKind::SelectPipelineTarget),
            Self::RegenerateDeliveryContract => {
                Some(WorkspacePlanJudgmentKind::RegenerateDeliveryContract)
            }
            Self::RequestNodeReplan => Some(WorkspacePlanJudgmentKind::RequestNodeReplan),
            Self::AcceptNodeReview => Some(WorkspacePlanJudgmentKind::AcceptNodeReview),
            Self::RetryOutbox | Self::PauseIteration | Self::ResumeIteration | Self::ReopenNode => {
                None
            }
        }
    }
}

/// Public POST input shared across the action routes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspacePlanActionInput {
    pub context: PublicWorkspacePlanContext,
    pub action: PublicWorkspacePlanAction,
    pub node_id: Option<String>,
    pub outbox_id: Option<String>,
    pub reason: Option<String>,
    pub evidence_refs: Vec<String>,
    pub idempotency_key: Option<String>,
    pub expected_revision: Option<u64>,
}

/// Legacy action result contract.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PublicWorkspacePlanActionResult {
    pub ok: bool,
    pub message: String,
    pub plan_id: String,
    pub node_id: Option<String>,
    pub outbox_id: Option<String>,
}

/// Stable error category consumed by the HTTP adapter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspacePlanErrorKind {
    Validation,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Plan input, authority, judgment, or persistence failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspacePlanError {
    #[error("Workspace Plan input is invalid")]
    InvalidInput,

    #[error("Workspace Plan action was rejected by the Agent authority")]
    JudgmentRejected,

    #[error(transparent)]
    JudgeContract(#[from] WorkspacePlanJudgeContractError),

    #[error(transparent)]
    Judge(#[from] WorkspacePlanJudgePortError),

    #[error(transparent)]
    Store(#[from] WorkspacePlanStoreError),

    #[error("Workspace Plan JSON serialization failed: {0}")]
    Json(#[source] serde_json::Error),
}

impl PublicWorkspacePlanError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspacePlanErrorKind {
        match self {
            Self::InvalidInput | Self::JudgeContract(_) => PublicWorkspacePlanErrorKind::Validation,
            Self::Store(
                WorkspacePlanStoreError::WorkspaceNotFound
                | WorkspacePlanStoreError::PlanNotFound
                | WorkspacePlanStoreError::NodeNotFound
                | WorkspacePlanStoreError::OutboxNotFound,
            ) => PublicWorkspacePlanErrorKind::NotFound,
            Self::Store(
                WorkspacePlanStoreError::AccessDenied
                | WorkspacePlanStoreError::EditorAccessRequired,
            ) => PublicWorkspacePlanErrorKind::Forbidden,
            Self::JudgmentRejected
            | Self::Store(
                WorkspacePlanStoreError::RevisionConflict
                | WorkspacePlanStoreError::InvalidTransition
                | WorkspacePlanStoreError::IdempotencyConflict,
            ) => PublicWorkspacePlanErrorKind::Conflict,
            Self::Judge(_) | Self::Store(_) | Self::Json(_) => {
                PublicWorkspacePlanErrorKind::Unavailable
            }
        }
    }
}

/// Snapshot, deterministic transition, and judged action use cases.
pub struct PublicWorkspacePlanService<'a> {
    store: WorkspacePlanStore<'a>,
    judge: &'a dyn WorkspacePlanJudgePort,
}

impl<'a> PublicWorkspacePlanService<'a> {
    #[must_use]
    pub const fn new(
        db: &'a dyn DbPlugin,
        flavor: DbSqlFlavor,
        judge: &'a dyn WorkspacePlanJudgePort,
    ) -> Self {
        Self {
            store: WorkspacePlanStore::new(db, flavor),
            judge,
        }
    }

    /// Read the durable Plan projection without invoking recovery side effects.
    ///
    /// # Errors
    ///
    /// Returns stable validation, access, not-found, or database errors.
    pub async fn snapshot(
        &self,
        input: &PublicWorkspacePlanSnapshotInput,
    ) -> Result<PublicWorkspacePlanSnapshot, PublicWorkspacePlanError> {
        validate_context(&input.context)?;
        if input.outbox_limit > 100 || input.event_limit > 200 {
            return Err(PublicWorkspacePlanError::InvalidInput);
        }
        let snapshot = self
            .store
            .snapshot(&WorkspacePlanSnapshotQuery {
                scope: store_scope(&input.context),
                plan_id: input.plan_id.clone(),
                include_details: input.include_details,
                outbox_limit: input.outbox_limit,
                event_limit: input.event_limit,
            })
            .await?;
        if snapshot.selected.is_none() {
            return Err(WorkspacePlanStoreError::PlanNotFound.into());
        }
        Ok(public_snapshot(&input.context.workspace_id, snapshot))
    }

    /// Apply one Plan action with CAS, audit, event, and durable outbox in one transaction.
    ///
    /// Subjective actions always call [`WorkspacePlanJudgePort`]. The service uses only
    /// structured fields and exact state membership for deterministic protocol checks.
    ///
    /// # Errors
    ///
    /// Returns stable validation, access, judgment, conflict, or database errors.
    pub async fn act(
        &self,
        input: &PublicWorkspacePlanActionInput,
    ) -> Result<PublicWorkspacePlanActionResult, PublicWorkspacePlanError> {
        validate_action_input(input)?;
        let now = Utc::now();
        let persisted_at = now.to_rfc3339_opts(SecondsFormat::Micros, false);
        let snapshot = self
            .store
            .action_snapshot(&WorkspacePlanSnapshotQuery {
                scope: store_scope(&input.context),
                plan_id: None,
                include_details: true,
                outbox_limit: 100,
                event_limit: 200,
            })
            .await?;
        let plan = snapshot
            .selected
            .as_ref()
            .ok_or(WorkspacePlanStoreError::PlanNotFound)?;
        let request_hash = action_request_hash(input, &plan.plan_id)?;
        if let Some(idempotency_key) = input.idempotency_key.as_deref()
            && let Some(outcome) = self
                .store
                .replay(
                    &store_scope(&input.context),
                    idempotency_key,
                    input.action.transition_kind().event_type(),
                    &request_hash,
                )
                .await?
        {
            return serde_json::from_value(outcome.response)
                .map_err(PublicWorkspacePlanError::Json);
        }
        if input
            .expected_revision
            .is_some_and(|revision| revision != plan.revision)
        {
            return Err(WorkspacePlanStoreError::RevisionConflict.into());
        }
        let prepared = prepare_action(input, &snapshot, &persisted_at)?;
        if matches!(
            input.action,
            PublicWorkspacePlanAction::RecoverStaleAttempts
        ) && prepared.stale_node_ids.is_empty()
        {
            return Ok(PublicWorkspacePlanActionResult {
                ok: true,
                message: "No stale workspace plan attempts needed recovery.".to_string(),
                plan_id: plan.plan_id.clone(),
                node_id: None,
                outbox_id: None,
            });
        }
        let judgment = self
            .resolve_judgment(input, plan, &snapshot, &prepared, &persisted_at)
            .await?;
        let node_id = judgment
            .as_ref()
            .and_then(WorkspacePlanJudgment::selected_node_id)
            .map(str::to_string)
            .or(prepared.node_id.clone());
        let idempotency_key = action_idempotency_key(input, plan.revision, node_id.as_deref());
        let ids = transition_ids(&input.context.workspace_id, &idempotency_key);
        let response = action_result(
            input.action,
            plan,
            node_id,
            prepared.target_outbox_id.clone(),
            &ids.outbox_id,
        );
        let event_payload = json!({
            "workspace_id": &input.context.workspace_id,
            "plan_id": &plan.plan_id,
            "node_id": &response.node_id,
            "outbox_id": &prepared.target_outbox_id,
            "reason": &input.reason,
            "evidence_refs": &input.evidence_refs,
            "actor_id": &input.context.actor_id,
        });
        let transition = WorkspacePlanTransition {
            scope: store_scope(&input.context),
            kind: input.action.transition_kind(),
            plan_id: plan.plan_id.clone(),
            expected_revision: plan.revision,
            node_id: response.node_id.clone(),
            target_outbox_id: prepared.target_outbox_id,
            stale_node_ids: prepared.stale_node_ids,
            idempotency_key,
            request_hash,
            mutation_outbox_id: ids.outbox_id,
            event_id: ids.event_id,
            reason: input.reason.clone(),
            evidence_refs: input.evidence_refs.clone(),
            node_metadata: prepared.node_metadata,
            event_payload,
            public_response: serde_json::to_value(&response)
                .map_err(PublicWorkspacePlanError::Json)?,
            judgment: judgment.map(|judgment| {
                judgment_audit(
                    &ids.audit_id,
                    plan,
                    response.node_id.as_deref(),
                    input.action,
                    &judgment,
                )
            }),
            persisted_at,
        };
        let outcome = self.store.transition(&transition).await?;
        serde_json::from_value(outcome.response).map_err(PublicWorkspacePlanError::Json)
    }

    async fn resolve_judgment(
        &self,
        input: &PublicWorkspacePlanActionInput,
        plan: &WorkspacePlanRecord,
        snapshot: &WorkspacePlanSnapshot,
        prepared: &PreparedAction,
        persisted_at: &str,
    ) -> Result<Option<WorkspacePlanJudgment>, PublicWorkspacePlanError> {
        let Some(kind) = judgment_kind(input, prepared) else {
            return Ok(None);
        };
        let candidates = if kind == WorkspacePlanJudgmentKind::SelectPipelineTarget {
            prepared.pipeline_candidates.clone()
        } else {
            prepared.node_id.iter().cloned().collect()
        };
        let request = WorkspacePlanJudgmentRequest::new(
            input.context.tenant_id.clone(),
            input.context.project_id.clone(),
            input.context.workspace_id.clone(),
            input.context.actor_id.clone(),
            plan.plan_id.clone(),
            plan.revision,
            kind,
            candidates,
            judgment_evidence(input, plan, snapshot, prepared),
        )?;
        let judgment = match self.judge.judge(&request).await {
            Ok(judgment) => judgment,
            Err(error) => {
                let audit_id = deterministic_id(
                    "judge-failed",
                    &format!(
                        "{}:{}:{}:{}",
                        input.context.workspace_id,
                        plan.plan_id,
                        plan.revision,
                        input.action.as_str()
                    ),
                );
                self.store
                    .record_failed_judgment(
                        &store_scope(&input.context),
                        &WorkspacePlanJudgmentAudit {
                            audit_id,
                            plan_id: plan.plan_id.clone(),
                            plan_node_id: prepared.node_id.clone(),
                            judgment_type: kind.as_str().to_string(),
                            agent_id: "unavailable".to_string(),
                            tool_name: "judge_workspace_plan".to_string(),
                            input: request.evidence().clone(),
                            output: json!({"error": "unavailable"}),
                            rationale: "Workspace Plan judge was unavailable".to_string(),
                            latency_ms: 0,
                            status: "failed".to_string(),
                            error_detail: Some("unavailable".to_string()),
                        },
                        persisted_at,
                    )
                    .await?;
                return Err(error.into());
            }
        };
        if !judgment.proceed() {
            let audit_id = deterministic_id(
                "judge-rejected",
                &format!(
                    "{}:{}:{}:{}",
                    input.context.workspace_id,
                    plan.plan_id,
                    plan.revision,
                    input.action.as_str()
                ),
            );
            self.store
                .record_failed_judgment(
                    &store_scope(&input.context),
                    &judgment_audit(
                        &audit_id,
                        plan,
                        prepared.node_id.as_deref(),
                        input.action,
                        &judgment,
                    ),
                    persisted_at,
                )
                .await?;
            return Err(PublicWorkspacePlanError::JudgmentRejected);
        }
        Ok(Some(judgment))
    }
}

#[derive(Debug)]
struct PreparedAction {
    node_id: Option<String>,
    target_outbox_id: Option<String>,
    stale_node_ids: Vec<String>,
    pipeline_candidates: Vec<String>,
    node_metadata: Option<Value>,
}

fn validate_context(context: &PublicWorkspacePlanContext) -> Result<(), PublicWorkspacePlanError> {
    if [
        context.tenant_id.as_str(),
        context.project_id.as_str(),
        context.workspace_id.as_str(),
        context.actor_id.as_str(),
    ]
    .iter()
    .any(|value| value.trim().is_empty())
    {
        return Err(PublicWorkspacePlanError::InvalidInput);
    }
    Ok(())
}

fn validate_action_input(
    input: &PublicWorkspacePlanActionInput,
) -> Result<(), PublicWorkspacePlanError> {
    validate_context(&input.context)?;
    if input
        .reason
        .as_ref()
        .is_some_and(|reason| reason.chars().count() > MAX_REASON_CHARS)
        || input.evidence_refs.len() > MAX_EVIDENCE_REFS
        || input
            .evidence_refs
            .iter()
            .any(|reference| reference.trim().is_empty())
        || input
            .idempotency_key
            .as_ref()
            .is_some_and(|key| key.trim().is_empty() || key.chars().count() > 256)
    {
        return Err(PublicWorkspacePlanError::InvalidInput);
    }
    let node_required = matches!(
        input.action,
        PublicWorkspacePlanAction::RequestNodeReplan
            | PublicWorkspacePlanAction::ReopenNode
            | PublicWorkspacePlanAction::AcceptNodeReview
    );
    let node_allowed =
        node_required || matches!(input.action, PublicWorkspacePlanAction::RunPipeline);
    let outbox_required = matches!(input.action, PublicWorkspacePlanAction::RetryOutbox);
    if (node_required && input.node_id.is_none())
        || (!node_allowed && input.node_id.is_some())
        || outbox_required != input.outbox_id.is_some()
    {
        return Err(PublicWorkspacePlanError::InvalidInput);
    }
    Ok(())
}

fn prepare_action(
    input: &PublicWorkspacePlanActionInput,
    snapshot: &WorkspacePlanSnapshot,
    persisted_at: &str,
) -> Result<PreparedAction, PublicWorkspacePlanError> {
    let target_node = input
        .node_id
        .as_deref()
        .map(|node_id| {
            snapshot
                .nodes
                .iter()
                .find(|node| node.node_id == node_id)
                .ok_or(WorkspacePlanStoreError::NodeNotFound)
        })
        .transpose()?;
    let target_outbox = input
        .outbox_id
        .as_deref()
        .map(|outbox_id| {
            snapshot
                .outbox
                .iter()
                .find(|outbox| outbox.outbox_id == outbox_id)
                .ok_or(WorkspacePlanStoreError::OutboxNotFound)
        })
        .transpose()?;
    if matches!(input.action, PublicWorkspacePlanAction::ReopenNode)
        && target_node.is_some_and(|node| node.status != "blocked")
    {
        return Err(WorkspacePlanStoreError::InvalidTransition.into());
    }
    let node_metadata = target_node.map(|node| {
        operator_node_metadata(
            node,
            &input.context.actor_id,
            input.action,
            input.reason.as_deref(),
            &input.evidence_refs,
            persisted_at,
        )
    });
    let stale_node_ids = if matches!(
        input.action,
        PublicWorkspacePlanAction::RecoverStaleAttempts
    ) {
        snapshot
            .nodes
            .iter()
            .filter(|node| is_structurally_stale(node, persisted_at))
            .map(|node| node.node_id.clone())
            .collect()
    } else {
        Vec::new()
    };
    let pipeline_candidates = if matches!(input.action, PublicWorkspacePlanAction::RunPipeline)
        && input.node_id.is_none()
    {
        snapshot
            .nodes
            .iter()
            .filter(|node| matches!(node.kind.as_str(), "task" | "verify"))
            .map(|node| node.node_id.clone())
            .collect()
    } else {
        Vec::new()
    };
    if matches!(input.action, PublicWorkspacePlanAction::RunPipeline)
        && input.node_id.is_none()
        && pipeline_candidates.is_empty()
    {
        return Err(WorkspacePlanStoreError::NodeNotFound.into());
    }
    Ok(PreparedAction {
        node_id: target_node.map(|node| node.node_id.clone()),
        target_outbox_id: target_outbox.map(|outbox| outbox.outbox_id.clone()),
        stale_node_ids,
        pipeline_candidates,
        node_metadata,
    })
}

fn judgment_kind(
    input: &PublicWorkspacePlanActionInput,
    prepared: &PreparedAction,
) -> Option<WorkspacePlanJudgmentKind> {
    if matches!(input.action, PublicWorkspacePlanAction::RunPipeline) && prepared.node_id.is_some()
    {
        return None;
    }
    input.action.judgment_kind()
}

fn judgment_evidence(
    input: &PublicWorkspacePlanActionInput,
    plan: &WorkspacePlanRecord,
    snapshot: &WorkspacePlanSnapshot,
    prepared: &PreparedAction,
) -> Value {
    json!({
        "action": input.action.as_str(),
        "reason": &input.reason,
        "evidence_refs": &input.evidence_refs,
        "plan": {
            "id": &plan.plan_id,
            "status": &plan.status,
            "revision": plan.revision,
            "goal": &plan.goal,
        },
        "target_node": prepared.node_id.as_ref().and_then(|node_id| {
            snapshot.nodes.iter().find(|node| &node.node_id == node_id)
        }).map(node_evidence),
        "candidate_nodes": prepared.pipeline_candidates.iter().filter_map(|node_id| {
            snapshot.nodes.iter().find(|node| &node.node_id == node_id)
        }).map(node_evidence).collect::<Vec<_>>(),
        "stale_nodes": prepared.stale_node_ids,
    })
}

fn node_evidence(node: &WorkspacePlanNodeRecord) -> Value {
    json!({
        "node_id": &node.node_id,
        "kind": &node.kind,
        "status": &node.status,
        "intent": &node.intent,
        "workspace_task_id": &node.workspace_task_id,
        "current_attempt_id": &node.current_attempt_id,
        "timeout_deadline_at": &node.timeout_deadline_at,
        "acceptance_criteria": &node.acceptance_criteria,
        "progress": &node.progress,
        "metadata": &node.metadata,
    })
}

fn is_structurally_stale(node: &WorkspacePlanNodeRecord, now: &str) -> bool {
    if node.status != "running" {
        return false;
    }
    let Some(deadline) = node.timeout_deadline_at.as_deref() else {
        return false;
    };
    let Ok(deadline) = DateTime::parse_from_rfc3339(deadline) else {
        return false;
    };
    let Ok(now) = DateTime::parse_from_rfc3339(now) else {
        return false;
    };
    deadline <= now
}

fn operator_node_metadata(
    node: &WorkspacePlanNodeRecord,
    actor_id: &str,
    action: PublicWorkspacePlanAction,
    reason: Option<&str>,
    evidence_refs: &[String],
    persisted_at: &str,
) -> Value {
    let mut metadata = node.metadata.as_object().cloned().unwrap_or_default();
    let action_record = json!({
        "action": action.as_str(),
        "actor_id": actor_id,
        "reason": reason,
        "evidence_refs": evidence_refs,
        "created_at": persisted_at,
    });
    metadata.insert("operator_action".to_string(), action_record.clone());
    if matches!(action, PublicWorkspacePlanAction::AcceptNodeReview) {
        metadata.insert("human_review_acceptance".to_string(), action_record);
        metadata.insert("last_verification_passed".to_string(), Value::Bool(true));
        metadata.insert(
            "last_verification_judge_verdict".to_string(),
            Value::String("accepted".to_string()),
        );
        metadata.insert(
            "verification_evidence_refs".to_string(),
            serde_json::to_value(evidence_refs).unwrap_or(Value::Array(Vec::new())),
        );
    }
    Value::Object(metadata)
}

fn action_result(
    action: PublicWorkspacePlanAction,
    plan: &WorkspacePlanRecord,
    node_id: Option<String>,
    target_outbox_id: Option<String>,
    mutation_outbox_id: &str,
) -> PublicWorkspacePlanActionResult {
    let message = match action {
        PublicWorkspacePlanAction::RecoverStaleAttempts => {
            "Workspace plan stale attempt recovery queued."
        }
        PublicWorkspacePlanAction::RetryOutbox => "Outbox job queued for retry.",
        PublicWorkspacePlanAction::PauseIteration => "Automatic iteration loop paused.",
        PublicWorkspacePlanAction::ResumeIteration => "Automatic iteration loop resumed.",
        PublicWorkspacePlanAction::TriggerNextIteration => "Next iteration review requested.",
        PublicWorkspacePlanAction::RunPipeline => "Harness-native pipeline run requested.",
        PublicWorkspacePlanAction::RegenerateDeliveryContract => {
            "Delivery contract regeneration requested."
        }
        PublicWorkspacePlanAction::RequestNodeReplan => {
            "Plan node sent back for supervisor recovery."
        }
        PublicWorkspacePlanAction::ReopenNode => "Blocked plan node reopened.",
        PublicWorkspacePlanAction::AcceptNodeReview => "Plan node accepted after human review.",
    };
    PublicWorkspacePlanActionResult {
        ok: true,
        message: message.to_string(),
        plan_id: plan.plan_id.clone(),
        node_id,
        outbox_id: match action {
            PublicWorkspacePlanAction::RetryOutbox => target_outbox_id,
            PublicWorkspacePlanAction::RunPipeline
            | PublicWorkspacePlanAction::RegenerateDeliveryContract => {
                Some(mutation_outbox_id.to_string())
            }
            _ => None,
        },
    }
}

fn store_scope(context: &PublicWorkspacePlanContext) -> WorkspacePlanScope {
    WorkspacePlanScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
        actor_id: context.actor_id.clone(),
        actor_is_superuser: context.actor_is_superuser,
    }
}

fn judgment_audit(
    audit_id: &str,
    plan: &WorkspacePlanRecord,
    node_id: Option<&str>,
    action: PublicWorkspacePlanAction,
    judgment: &WorkspacePlanJudgment,
) -> WorkspacePlanJudgmentAudit {
    WorkspacePlanJudgmentAudit {
        audit_id: audit_id.to_string(),
        plan_id: plan.plan_id.clone(),
        plan_node_id: node_id.map(str::to_string),
        judgment_type: action.judgment_kind().map_or_else(
            || action.as_str().to_string(),
            |kind| kind.as_str().to_string(),
        ),
        agent_id: judgment.agent_id().to_string(),
        tool_name: judgment.tool_name().to_string(),
        input: judgment.input().clone(),
        output: judgment.output().clone(),
        rationale: judgment.rationale().to_string(),
        latency_ms: judgment.latency_ms(),
        status: if judgment.proceed() {
            "accepted"
        } else {
            "rejected"
        }
        .to_string(),
        error_detail: None,
    }
}
