//! Agent-first Workspace Autonomy tick use case.

use std::collections::HashSet;
use std::time::Instant;

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use memstack_workspace_store::{
    WorkspaceAutonomyAttentionWrite, WorkspaceAutonomyJudgedSnapshot,
    WorkspaceAutonomyJudgmentApply, WorkspaceAutonomyJudgmentAudit,
    WorkspaceAutonomyJudgmentClaimOutcome, WorkspaceAutonomyJudgmentClaimRequest,
    WorkspaceAutonomyJudgmentLease, WorkspaceAutonomyJudgmentStore,
    WorkspaceAutonomyJudgmentStoreError, WorkspaceAutonomyMutation,
    WorkspaceAutonomyProgressionWrite, WorkspaceAutonomyScope, WorkspaceAutonomyStore,
    WorkspaceAutonomyStoreError, WorkspaceTaskRecord, WorkspaceTaskScope, WorkspaceTaskStore,
    WorkspaceTaskStoreError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

use crate::canonical_json;

const AUTONOMY_NAMESPACE: Uuid = Uuid::from_u128(0xd760_426a_5559_49be_a18f_9589_a358_8a13);
pub const WORKSPACE_AUTONOMY_COOLDOWN_SECONDS: i64 = 60;
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;
const MAX_NEXT_ACTION_DESCRIPTION_CHARS: usize = 10_000;
const JUDGMENT_LEASE_SECONDS: i64 = 120;
const DEFAULT_JUDGE_AGENT_ID: &str = "workspace-autonomy-judge";
const DEFAULT_JUDGE_TOOL_NAME: &str = "judge_workspace_autonomy";

/// Authenticated Autonomy route scope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceAutonomyContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub is_superuser: bool,
    pub expected_revision: Option<u64>,
    pub idempotency_key: Option<String>,
}

/// Structurally eligible root Task supplied to the Agent tool call.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PublicWorkspaceAutonomyCandidate {
    pub root_task_id: String,
    pub title: String,
    pub description: Option<String>,
    pub status: String,
    pub metadata: Value,
}

/// Active Workspace Agent binding supplied to the Agent tool call.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PublicWorkspaceAutonomyAgentCandidate {
    pub workspace_agent_binding_id: String,
    pub agent_id: String,
    pub display_name: Option<String>,
    pub description: Option<String>,
    pub status: String,
    pub config: Value,
}

/// Concrete semantic continuation selected exclusively by the structured Judge.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PublicWorkspaceAutonomyNextAction {
    pub title: String,
    pub description: String,
    pub workspace_agent_binding_id: String,
}

/// Valid semantic Autonomy verdicts. Only a Judge may produce these.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PublicWorkspaceAutonomyVerdictKind {
    Continue,
    Block,
    Escalate,
}

impl PublicWorkspaceAutonomyVerdictKind {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Continue => "continue",
            Self::Block => "block",
            Self::Escalate => "escalate",
        }
    }

    #[must_use]
    pub const fn reason(self) -> &'static str {
        match self {
            Self::Continue => "triggered",
            Self::Block => "blocked_by_judge",
            Self::Escalate => "escalated_by_judge",
        }
    }
}

/// Bounded structured request sent to the Autonomy Judge.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceAutonomyJudgmentRequest {
    context: PublicWorkspaceAutonomyContext,
    workspace_revision: u64,
    force: bool,
    candidates: Vec<PublicWorkspaceAutonomyCandidate>,
    agent_candidates: Vec<PublicWorkspaceAutonomyAgentCandidate>,
}

impl PublicWorkspaceAutonomyJudgmentRequest {
    #[must_use]
    pub fn context(&self) -> &PublicWorkspaceAutonomyContext {
        &self.context
    }

    #[must_use]
    pub const fn workspace_revision(&self) -> u64 {
        self.workspace_revision
    }

    #[must_use]
    pub const fn force(&self) -> bool {
        self.force
    }

    #[must_use]
    pub fn candidates(&self) -> &[PublicWorkspaceAutonomyCandidate] {
        &self.candidates
    }

    #[must_use]
    pub fn agent_candidates(&self) -> &[PublicWorkspaceAutonomyAgentCandidate] {
        &self.agent_candidates
    }
}

/// Validated Agent tool-call verdict and mandatory audit fields.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceAutonomyJudgment {
    verdict: PublicWorkspaceAutonomyVerdictKind,
    selected_root_task_id: Option<String>,
    next_action: Option<PublicWorkspaceAutonomyNextAction>,
    rationale: String,
    agent_id: String,
    tool_name: String,
    input: Value,
    output: Value,
    latency_ms: u64,
}

impl PublicWorkspaceAutonomyJudgment {
    /// Validate one structured verdict against the exact candidate set.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        request: &PublicWorkspaceAutonomyJudgmentRequest,
        verdict: PublicWorkspaceAutonomyVerdictKind,
        selected_root_task_id: Option<String>,
        next_action: Option<PublicWorkspaceAutonomyNextAction>,
        rationale: String,
        agent_id: String,
        tool_name: String,
        input: Value,
        output: Value,
        latency_ms: u64,
    ) -> Result<Self, PublicWorkspaceAutonomyJudgeContractError> {
        if rationale.trim().is_empty() || agent_id.trim().is_empty() || tool_name.trim().is_empty()
        {
            return Err(PublicWorkspaceAutonomyJudgeContractError::BlankAuditField);
        }
        if let Some(selected) = selected_root_task_id.as_deref()
            && !request
                .candidates()
                .iter()
                .any(|candidate| candidate.root_task_id == selected)
        {
            return Err(PublicWorkspaceAutonomyJudgeContractError::InvalidSelection);
        }
        if selected_root_task_id.is_none() {
            return Err(PublicWorkspaceAutonomyJudgeContractError::MissingSelection);
        }
        if verdict == PublicWorkspaceAutonomyVerdictKind::Continue && next_action.is_none() {
            return Err(PublicWorkspaceAutonomyJudgeContractError::MissingNextAction);
        }
        if verdict != PublicWorkspaceAutonomyVerdictKind::Continue && next_action.is_some() {
            return Err(PublicWorkspaceAutonomyJudgeContractError::UnexpectedNextAction);
        }
        if let Some(action) = &next_action
            && (action.title.trim().is_empty()
                || action.title.chars().count() > 255
                || action.description.trim().is_empty()
                || action.description.chars().count() > MAX_NEXT_ACTION_DESCRIPTION_CHARS
                || action.workspace_agent_binding_id.trim().is_empty()
                || !request.agent_candidates().iter().any(|candidate| {
                    candidate.workspace_agent_binding_id == action.workspace_agent_binding_id
                }))
        {
            return Err(PublicWorkspaceAutonomyJudgeContractError::InvalidNextAction);
        }
        Ok(Self {
            verdict,
            selected_root_task_id,
            next_action,
            rationale,
            agent_id,
            tool_name,
            input,
            output,
            latency_ms,
        })
    }

    #[must_use]
    pub const fn verdict(&self) -> PublicWorkspaceAutonomyVerdictKind {
        self.verdict
    }

    #[must_use]
    pub fn selected_root_task_id(&self) -> Option<&str> {
        self.selected_root_task_id.as_deref()
    }

    #[must_use]
    pub const fn next_action(&self) -> Option<&PublicWorkspaceAutonomyNextAction> {
        self.next_action.as_ref()
    }

    #[must_use]
    pub fn rationale(&self) -> &str {
        &self.rationale
    }

    #[must_use]
    pub fn agent_id(&self) -> &str {
        &self.agent_id
    }

    #[must_use]
    pub fn tool_name(&self) -> &str {
        &self.tool_name
    }

    #[must_use]
    pub const fn input(&self) -> &Value {
        &self.input
    }

    #[must_use]
    pub const fn output(&self) -> &Value {
        &self.output
    }

    #[must_use]
    pub const fn latency_ms(&self) -> u64 {
        self.latency_ms
    }
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PersistedWorkspaceAutonomyJudgment {
    verdict: PublicWorkspaceAutonomyVerdictKind,
    selected_root_task_id: Option<String>,
    next_action: Option<PublicWorkspaceAutonomyNextAction>,
    rationale: String,
    agent_id: String,
    tool_name: String,
    input: Value,
    output: Value,
    latency_ms: u64,
}

impl From<&PublicWorkspaceAutonomyJudgment> for PersistedWorkspaceAutonomyJudgment {
    fn from(judgment: &PublicWorkspaceAutonomyJudgment) -> Self {
        Self {
            verdict: judgment.verdict(),
            selected_root_task_id: judgment.selected_root_task_id().map(str::to_string),
            next_action: judgment.next_action().cloned(),
            rationale: judgment.rationale().to_string(),
            agent_id: judgment.agent_id().to_string(),
            tool_name: judgment.tool_name().to_string(),
            input: judgment.input().clone(),
            output: judgment.output().clone(),
            latency_ms: judgment.latency_ms(),
        }
    }
}

/// Invalid structured Judge response.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceAutonomyJudgeContractError {
    #[error("Workspace Autonomy Judge audit fields must not be blank")]
    BlankAuditField,
    #[error("Workspace Autonomy Judge selected a root outside the candidate set")]
    InvalidSelection,
    #[error("Workspace Autonomy verdict requires a selected root")]
    MissingSelection,
    #[error("Workspace Autonomy continue verdict requires a next action")]
    MissingNextAction,
    #[error("Workspace Autonomy non-continue verdict cannot include a next action")]
    UnexpectedNextAction,
    #[error("Workspace Autonomy Judge next action is invalid")]
    InvalidNextAction,
}

/// Autonomy Judge transport failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceAutonomyJudgePortError {
    #[error("Workspace Autonomy Judge is unavailable")]
    Unavailable,
}

/// Agent-first boundary for semantic Autonomy verdicts.
#[async_trait]
pub trait PublicWorkspaceAutonomyJudgePort: Send + Sync {
    /// Stable audit identity used when a transport failure has no response payload.
    fn audit_agent_id(&self) -> &str {
        DEFAULT_JUDGE_AGENT_ID
    }

    /// Stable tool identity used when a transport failure has no response payload.
    fn audit_tool_name(&self) -> &str {
        DEFAULT_JUDGE_TOOL_NAME
    }

    /// Return one validated structured verdict.
    async fn judge(
        &self,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
    ) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyJudgePortError>;
}

/// Exact legacy tick response.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PublicWorkspaceAutonomyTickResponse {
    pub triggered: bool,
    pub root_task_id: Option<String>,
    pub reason: String,
}

/// Durable tick outcome used by direct mutation callers.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceAutonomyTickOutcome {
    pub response: PublicWorkspaceAutonomyTickResponse,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub receipt_id: String,
    pub replayed: bool,
}

/// Stable Autonomy error categories.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceAutonomyErrorKind {
    InvalidRequest,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Stable Autonomy application failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceAutonomyError {
    #[error("invalid Workspace Autonomy request")]
    InvalidRequest,
    #[error(transparent)]
    JudgeContract(#[from] PublicWorkspaceAutonomyJudgeContractError),
    #[error(transparent)]
    Judge(#[from] PublicWorkspaceAutonomyJudgePortError),
    #[error(transparent)]
    Store(#[from] WorkspaceAutonomyStoreError),
    #[error(transparent)]
    JudgmentStore(#[from] WorkspaceAutonomyJudgmentStoreError),
    #[error("Workspace Autonomy judgment is already in progress")]
    JudgmentInProgress,
    #[error("Workspace Autonomy judgment was superseded by newer authority")]
    JudgmentSuperseded,
    #[error(transparent)]
    TaskStore(#[from] WorkspaceTaskStoreError),
    #[error("Workspace Autonomy JSON serialization failed: {0}")]
    Json(#[from] serde_json::Error),
}

impl PublicWorkspaceAutonomyError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceAutonomyErrorKind {
        match self {
            Self::InvalidRequest | Self::JudgeContract(_) => {
                PublicWorkspaceAutonomyErrorKind::InvalidRequest
            }
            Self::Store(WorkspaceAutonomyStoreError::NotFound) => {
                PublicWorkspaceAutonomyErrorKind::NotFound
            }
            Self::Store(WorkspaceAutonomyStoreError::EditorAccessRequired) => {
                PublicWorkspaceAutonomyErrorKind::Forbidden
            }
            Self::Store(
                WorkspaceAutonomyStoreError::Conflict
                | WorkspaceAutonomyStoreError::IdempotencyConflict
                | WorkspaceAutonomyStoreError::IncompleteReceipt,
            ) => PublicWorkspaceAutonomyErrorKind::Conflict,
            Self::JudgmentStore(
                WorkspaceAutonomyJudgmentStoreError::IdempotencyConflict
                | WorkspaceAutonomyJudgmentStoreError::LeaseLost,
            )
            | Self::JudgmentInProgress
            | Self::JudgmentSuperseded => PublicWorkspaceAutonomyErrorKind::Conflict,
            Self::TaskStore(WorkspaceTaskStoreError::NotFound) => {
                PublicWorkspaceAutonomyErrorKind::NotFound
            }
            Self::TaskStore(
                WorkspaceTaskStoreError::AccessRequired
                | WorkspaceTaskStoreError::EditorAccessRequired,
            ) => PublicWorkspaceAutonomyErrorKind::Forbidden,
            Self::Judge(_)
            | Self::Store(_)
            | Self::JudgmentStore(_)
            | Self::TaskStore(_)
            | Self::Json(_) => PublicWorkspaceAutonomyErrorKind::Unavailable,
        }
    }
}

/// Deterministic trigger plus Agent-judged verdict service.
pub struct PublicWorkspaceAutonomyService<'a> {
    store: WorkspaceAutonomyStore<'a>,
    judgments: WorkspaceAutonomyJudgmentStore<'a>,
    tasks: WorkspaceTaskStore<'a>,
    judge: &'a dyn PublicWorkspaceAutonomyJudgePort,
}

impl<'a> PublicWorkspaceAutonomyService<'a> {
    #[must_use]
    pub const fn new(
        db: &'a dyn DbPlugin,
        flavor: DbSqlFlavor,
        judge: &'a dyn PublicWorkspaceAutonomyJudgePort,
    ) -> Self {
        Self {
            store: WorkspaceAutonomyStore::new(db, flavor),
            judgments: WorkspaceAutonomyJudgmentStore::new(db, flavor),
            tasks: WorkspaceTaskStore::new(db, flavor),
            judge,
        }
    }

    /// Trigger one tick. Semantic action is accepted only from the structured Judge port.
    pub async fn tick(
        &self,
        context: &PublicWorkspaceAutonomyContext,
        force: bool,
    ) -> Result<PublicWorkspaceAutonomyTickOutcome, PublicWorkspaceAutonomyError> {
        validate_context(context)?;
        let scope = autonomy_scope(context);
        self.store
            .require_editor(&scope, context.user_id.as_str(), context.is_superuser)
            .await?;
        let idempotency_key = context
            .idempotency_key
            .clone()
            .unwrap_or_else(|| format!("legacy-autonomy-tick:{}", Uuid::new_v4()));
        validate_idempotency_key(idempotency_key.as_str())?;
        let request_hash = hash_value(json!({
            "tenant_id": &context.tenant_id,
            "project_id": &context.project_id,
            "workspace_id": &context.workspace_id,
            "actor_id": &context.user_id,
            "force": force,
            "expected_revision": context.expected_revision,
        }))?;
        if let Some(replayed) = self
            .store
            .replay(
                &scope,
                context.user_id.as_str(),
                idempotency_key.as_str(),
                request_hash.as_str(),
            )
            .await?
        {
            return outcome_from_store(replayed);
        }
        let revision = match context.expected_revision {
            Some(revision) => revision,
            None => self.store.revision(&scope).await?,
        };
        let candidates = self.open_root_candidates(context).await?;
        let agent_candidates = if candidates.is_empty() {
            Vec::new()
        } else {
            self.active_agent_candidates(&scope).await?
        };

        if candidates.is_empty() {
            return self
                .commit(
                    context,
                    revision,
                    idempotency_key,
                    request_hash,
                    force,
                    "not_applicable",
                    "no_open_root",
                    None,
                    None,
                    None,
                )
                .await;
        }

        if agent_candidates.is_empty() {
            return self
                .commit(
                    context,
                    revision,
                    idempotency_key,
                    request_hash,
                    force,
                    "not_applicable",
                    "no_active_agent",
                    None,
                    None,
                    None,
                )
                .await;
        }

        if !force
            && self
                .all_candidates_cooling_down(&scope, &candidates)
                .await?
        {
            return self
                .commit(
                    context,
                    revision,
                    idempotency_key,
                    request_hash,
                    false,
                    "not_applicable",
                    "cooling_down",
                    None,
                    None,
                    None,
                )
                .await;
        }

        let request = PublicWorkspaceAutonomyJudgmentRequest {
            context: context.clone(),
            workspace_revision: revision,
            force,
            candidates,
            agent_candidates,
        };
        let tick_id = deterministic_tick_id(context, idempotency_key.as_str());
        let claim_id = deterministic_judgment_claim_id(tick_id.as_str());
        let now_ms = Utc::now().timestamp_millis();
        let lease_expires_at_ms = now_ms
            .checked_add(JUDGMENT_LEASE_SECONDS * 1_000)
            .ok_or(PublicWorkspaceAutonomyError::InvalidRequest)?;
        let claim = self
            .judgments
            .claim(&WorkspaceAutonomyJudgmentClaimRequest {
                claim_id,
                scope: scope.clone(),
                actor_id: context.user_id.clone(),
                idempotency_key: idempotency_key.clone(),
                request_hash: request_hash.clone(),
                expected_revision: revision,
                worker_id: format!("autonomy-judge:{}", Uuid::new_v4()),
                now_ms,
                lease_expires_at_ms,
            })
            .await?;
        let judged = match claim {
            WorkspaceAutonomyJudgmentClaimOutcome::Claimed(lease) => {
                self.invoke_and_record_judgment(&scope, &request, &lease)
                    .await?
            }
            WorkspaceAutonomyJudgmentClaimOutcome::Judged(snapshot) => snapshot,
            WorkspaceAutonomyJudgmentClaimOutcome::Busy => {
                return Err(PublicWorkspaceAutonomyError::JudgmentInProgress);
            }
            WorkspaceAutonomyJudgmentClaimOutcome::Superseded => {
                return Err(PublicWorkspaceAutonomyError::JudgmentSuperseded);
            }
            WorkspaceAutonomyJudgmentClaimOutcome::Applied => {
                let replayed = self
                    .store
                    .replay(
                        &scope,
                        context.user_id.as_str(),
                        idempotency_key.as_str(),
                        request_hash.as_str(),
                    )
                    .await?
                    .ok_or(PublicWorkspaceAutonomyError::JudgmentInProgress)?;
                return outcome_from_store(replayed);
            }
        };
        let judgment = judgment_from_snapshot(&request, &judged.judgment)?;
        let verdict = judgment.verdict();
        let root_task_id = judgment.selected_root_task_id().map(str::to_string);
        let result = self
            .commit(
                context,
                revision,
                idempotency_key,
                request_hash,
                force,
                verdict.as_str(),
                verdict.reason(),
                root_task_id,
                Some(judgment),
                Some(WorkspaceAutonomyJudgmentApply {
                    claim_id: judged.claim_id.clone(),
                    audit_id: judged.audit_id.clone(),
                    lease_generation: judged.lease_generation,
                    applied_at_ms: Utc::now().timestamp_millis(),
                }),
            )
            .await;
        if matches!(
            result,
            Err(PublicWorkspaceAutonomyError::Store(
                WorkspaceAutonomyStoreError::Conflict
            ))
        ) {
            self.judgments
                .mark_superseded(
                    &judged,
                    "Workspace authority changed before the judged tick could be applied",
                    Utc::now().timestamp_millis(),
                )
                .await?;
        }
        result
    }

    async fn invoke_and_record_judgment(
        &self,
        scope: &WorkspaceAutonomyScope,
        request: &PublicWorkspaceAutonomyJudgmentRequest,
        lease: &WorkspaceAutonomyJudgmentLease,
    ) -> Result<WorkspaceAutonomyJudgedSnapshot, PublicWorkspaceAutonomyError> {
        let started_at = Instant::now();
        let call = self.judge.judge(request).await;
        let recorded_at = Utc::now();
        let latency_ms = u64::try_from(started_at.elapsed().as_millis()).unwrap_or(u64::MAX);
        let audit_id =
            deterministic_judgment_audit_id(lease.claim_id.as_str(), lease.lease_generation);
        match call {
            Ok(judgment) => {
                let snapshot =
                    serde_json::to_value(PersistedWorkspaceAutonomyJudgment::from(&judgment))?;
                let audit = WorkspaceAutonomyJudgmentAudit {
                    audit_id: audit_id.clone(),
                    agent_id: judgment.agent_id().to_string(),
                    tool_name: judgment.tool_name().to_string(),
                    input: judgment.input().clone(),
                    output: judgment.output().clone(),
                    rationale: judgment.rationale().to_string(),
                    latency_ms: judgment.latency_ms(),
                    status: "judged".to_string(),
                    error_detail: None,
                    created_at: recorded_at.to_rfc3339_opts(SecondsFormat::Micros, false),
                };
                self.judgments.record_audit(scope, &audit).await?;
                match self
                    .judgments
                    .mark_judged(
                        lease,
                        audit_id.as_str(),
                        &snapshot,
                        recorded_at.timestamp_millis(),
                    )
                    .await
                {
                    Ok(snapshot) => Ok(snapshot),
                    Err(error) => {
                        self.judgments
                            .update_audit_status(
                                audit_id.as_str(),
                                "superseded",
                                Some("judgment lease was lost before snapshot persistence"),
                            )
                            .await?;
                        Err(error.into())
                    }
                }
            }
            Err(error) => {
                let error_detail = "Workspace Autonomy Judge transport failed";
                let audit = WorkspaceAutonomyJudgmentAudit {
                    audit_id: audit_id.clone(),
                    agent_id: self.judge.audit_agent_id().to_string(),
                    tool_name: self.judge.audit_tool_name().to_string(),
                    input: judgment_request_audit_value(request),
                    output: json!({"error": "unavailable"}),
                    rationale: "The required structured Judge call did not return a verdict"
                        .to_string(),
                    latency_ms,
                    status: "failed".to_string(),
                    error_detail: Some(error_detail.to_string()),
                    created_at: recorded_at.to_rfc3339_opts(SecondsFormat::Micros, false),
                };
                self.judgments.record_audit(scope, &audit).await?;
                self.judgments
                    .mark_failed(
                        lease,
                        audit_id.as_str(),
                        error_detail,
                        recorded_at.timestamp_millis(),
                    )
                    .await?;
                Err(error.into())
            }
        }
    }

    async fn open_root_candidates(
        &self,
        context: &PublicWorkspaceAutonomyContext,
    ) -> Result<Vec<PublicWorkspaceAutonomyCandidate>, PublicWorkspaceAutonomyError> {
        let scope = autonomy_scope(context);
        let eligible_root_ids = self
            .store
            .eligible_root_task_ids(&scope, 500)
            .await?
            .into_iter()
            .collect::<HashSet<_>>();
        let records = self
            .tasks
            .list(
                &WorkspaceTaskScope {
                    tenant_id: context.tenant_id.clone(),
                    project_id: context.project_id.clone(),
                    workspace_id: context.workspace_id.clone(),
                },
                None,
                500,
                0,
            )
            .await?;
        Ok(records
            .into_iter()
            .filter(|record| {
                is_open_root(record) && eligible_root_ids.contains(record.task_id.as_str())
            })
            .map(|record| PublicWorkspaceAutonomyCandidate {
                root_task_id: record.task_id,
                title: record.title,
                description: record.description,
                status: record.status,
                metadata: record.metadata,
            })
            .collect())
    }

    async fn active_agent_candidates(
        &self,
        scope: &WorkspaceAutonomyScope,
    ) -> Result<Vec<PublicWorkspaceAutonomyAgentCandidate>, PublicWorkspaceAutonomyError> {
        Ok(self
            .store
            .active_agent_bindings(scope, 500)
            .await?
            .into_iter()
            .map(|binding| PublicWorkspaceAutonomyAgentCandidate {
                workspace_agent_binding_id: binding.binding_id,
                agent_id: binding.agent_id,
                display_name: binding.display_name,
                description: binding.description,
                status: binding.status,
                config: binding.config,
            })
            .collect())
    }

    async fn all_candidates_cooling_down(
        &self,
        scope: &WorkspaceAutonomyScope,
        candidates: &[PublicWorkspaceAutonomyCandidate],
    ) -> Result<bool, PublicWorkspaceAutonomyError> {
        let cutoff = Utc::now() - Duration::seconds(WORKSPACE_AUTONOMY_COOLDOWN_SECONDS);
        for candidate in candidates {
            let Some(last_tick) = self
                .store
                .last_tick_at(scope, candidate.root_task_id.as_str())
                .await?
            else {
                return Ok(false);
            };
            let Ok(last_tick) = DateTime::parse_from_rfc3339(last_tick.as_str()) else {
                return Ok(false);
            };
            if last_tick.with_timezone(&Utc) <= cutoff {
                return Ok(false);
            }
        }
        Ok(true)
    }

    #[allow(clippy::too_many_arguments)]
    async fn commit(
        &self,
        context: &PublicWorkspaceAutonomyContext,
        revision: u64,
        idempotency_key: String,
        request_hash: String,
        force: bool,
        verdict: &str,
        reason: &str,
        root_task_id: Option<String>,
        judgment: Option<PublicWorkspaceAutonomyJudgment>,
        judgment_apply: Option<WorkspaceAutonomyJudgmentApply>,
    ) -> Result<PublicWorkspaceAutonomyTickOutcome, PublicWorkspaceAutonomyError> {
        let response = PublicWorkspaceAutonomyTickResponse {
            triggered: verdict == "continue",
            root_task_id: root_task_id.clone(),
            reason: reason.to_string(),
        };
        let response_value = serde_json::to_value(&response)?;
        let tick_id = deterministic_tick_id(context, idempotency_key.as_str());
        let progression = if verdict == "continue" {
            let judgment = judgment
                .as_ref()
                .ok_or(PublicWorkspaceAutonomyJudgeContractError::MissingNextAction)?;
            let action = judgment
                .next_action()
                .ok_or(PublicWorkspaceAutonomyJudgeContractError::MissingNextAction)?;
            Some(WorkspaceAutonomyProgressionWrite {
                progression_id: Uuid::new_v5(
                    &AUTONOMY_NAMESPACE,
                    format!("progression\0{tick_id}").as_bytes(),
                )
                .to_string(),
                root_task_id: root_task_id
                    .clone()
                    .ok_or(PublicWorkspaceAutonomyJudgeContractError::MissingSelection)?,
                judge_agent_id: judgment.agent_id().to_string(),
                workspace_agent_binding_id: action.workspace_agent_binding_id.clone(),
                task_title: action.title.clone(),
                task_description: action.description.clone(),
                created_at_ms: Utc::now().timestamp_millis(),
            })
        } else {
            None
        };
        let attention = match verdict {
            "block" | "escalate" => {
                let judgment = judgment
                    .as_ref()
                    .ok_or(PublicWorkspaceAutonomyJudgeContractError::MissingSelection)?;
                let source_kind = if verdict == "block" {
                    "judge_block"
                } else {
                    "judge_escalate"
                };
                Some(WorkspaceAutonomyAttentionWrite {
                    attention_id: Uuid::new_v5(
                        &AUTONOMY_NAMESPACE,
                        format!("attention\0{source_kind}\0{tick_id}").as_bytes(),
                    )
                    .to_string(),
                    root_task_id: root_task_id
                        .clone()
                        .ok_or(PublicWorkspaceAutonomyJudgeContractError::MissingSelection)?,
                    source_kind: source_kind.to_string(),
                    source_id: tick_id.clone(),
                    reason: judgment.rationale().to_string(),
                    created_at_ms: Utc::now().timestamp_millis(),
                })
            }
            _ => None,
        };
        let audit = judgment.map(|judgment| WorkspaceAutonomyJudgmentAudit {
            audit_id: judgment_apply
                .as_ref()
                .map(|apply| apply.audit_id.clone())
                .unwrap_or_else(|| {
                    Uuid::new_v5(
                        &AUTONOMY_NAMESPACE,
                        format!("legacy-audit\0{tick_id}").as_bytes(),
                    )
                    .to_string()
                }),
            agent_id: judgment.agent_id().to_string(),
            tool_name: judgment.tool_name().to_string(),
            input: judgment.input().clone(),
            output: judgment.output().clone(),
            rationale: judgment.rationale().to_string(),
            latency_ms: judgment.latency_ms(),
            status: "judged".to_string(),
            error_detail: None,
            created_at: Utc::now().to_rfc3339_opts(SecondsFormat::Micros, false),
        });
        outcome_from_store(
            self.store
                .mutate(&WorkspaceAutonomyMutation {
                    tick_id,
                    scope: autonomy_scope(context),
                    actor_id: context.user_id.clone(),
                    actor_is_superuser: context.is_superuser,
                    idempotency_key,
                    request_hash,
                    expected_revision: revision,
                    root_task_id,
                    verdict: verdict.to_string(),
                    reason: reason.to_string(),
                    force,
                    judgment: audit,
                    judgment_apply,
                    progression,
                    attention,
                    response: response_value,
                    created_at: Utc::now().to_rfc3339_opts(SecondsFormat::Micros, false),
                })
                .await?,
        )
    }
}

fn is_open_root(record: &WorkspaceTaskRecord) -> bool {
    record.archived_at.is_none()
        && !matches!(record.status.as_str(), "done" | "blocked")
        && record.metadata.get("task_role").and_then(Value::as_str) == Some("goal_root")
}

fn autonomy_scope(context: &PublicWorkspaceAutonomyContext) -> WorkspaceAutonomyScope {
    WorkspaceAutonomyScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    }
}

fn validate_context(
    context: &PublicWorkspaceAutonomyContext,
) -> Result<(), PublicWorkspaceAutonomyError> {
    if [
        context.tenant_id.as_str(),
        context.project_id.as_str(),
        context.workspace_id.as_str(),
        context.user_id.as_str(),
    ]
    .iter()
    .any(|value| value.trim().is_empty())
    {
        return Err(PublicWorkspaceAutonomyError::InvalidRequest);
    }
    Ok(())
}

fn validate_idempotency_key(value: &str) -> Result<(), PublicWorkspaceAutonomyError> {
    if value.trim().is_empty() || value.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS {
        return Err(PublicWorkspaceAutonomyError::InvalidRequest);
    }
    Ok(())
}

fn deterministic_tick_id(
    context: &PublicWorkspaceAutonomyContext,
    idempotency_key: &str,
) -> String {
    Uuid::new_v5(
        &AUTONOMY_NAMESPACE,
        format!(
            "tick\0{}\0{}\0{}\0{}\0{idempotency_key}",
            context.tenant_id, context.project_id, context.workspace_id, context.user_id
        )
        .as_bytes(),
    )
    .to_string()
}

fn deterministic_judgment_claim_id(tick_id: &str) -> String {
    Uuid::new_v5(
        &AUTONOMY_NAMESPACE,
        format!("judgment-claim\0{tick_id}").as_bytes(),
    )
    .to_string()
}

fn deterministic_judgment_audit_id(claim_id: &str, lease_generation: i64) -> String {
    Uuid::new_v5(
        &AUTONOMY_NAMESPACE,
        format!("judgment-audit\0{claim_id}\0{lease_generation}").as_bytes(),
    )
    .to_string()
}

fn judgment_from_snapshot(
    request: &PublicWorkspaceAutonomyJudgmentRequest,
    snapshot: &Value,
) -> Result<PublicWorkspaceAutonomyJudgment, PublicWorkspaceAutonomyError> {
    let persisted: PersistedWorkspaceAutonomyJudgment = serde_json::from_value(snapshot.clone())?;
    Ok(PublicWorkspaceAutonomyJudgment::new(
        request,
        persisted.verdict,
        persisted.selected_root_task_id,
        persisted.next_action,
        persisted.rationale,
        persisted.agent_id,
        persisted.tool_name,
        persisted.input,
        persisted.output,
        persisted.latency_ms,
    )?)
}

fn judgment_request_audit_value(request: &PublicWorkspaceAutonomyJudgmentRequest) -> Value {
    json!({
        "tenant_id": &request.context().tenant_id,
        "project_id": &request.context().project_id,
        "workspace_id": &request.context().workspace_id,
        "actor_id": &request.context().user_id,
        "workspace_revision": request.workspace_revision(),
        "force": request.force(),
        "candidate_root_task_ids": request
            .candidates()
            .iter()
            .map(|candidate| candidate.root_task_id.as_str())
            .collect::<Vec<_>>(),
        "candidate_workspace_agent_binding_ids": request
            .agent_candidates()
            .iter()
            .map(|candidate| candidate.workspace_agent_binding_id.as_str())
            .collect::<Vec<_>>(),
    })
}

fn hash_value(value: Value) -> Result<String, serde_json::Error> {
    Ok(hex::encode(Sha256::digest(serde_json::to_vec(
        &canonical_json(&value),
    )?)))
}

fn outcome_from_store(
    outcome: memstack_workspace_store::WorkspaceAutonomyMutationOutcome,
) -> Result<PublicWorkspaceAutonomyTickOutcome, PublicWorkspaceAutonomyError> {
    Ok(PublicWorkspaceAutonomyTickOutcome {
        response: serde_json::from_value(outcome.response)?,
        committed_revision: outcome.committed_revision,
        outbox_id: outcome.outbox_id,
        receipt_id: outcome.receipt_id,
        replayed: outcome.replayed,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn judgment_request() -> PublicWorkspaceAutonomyJudgmentRequest {
        PublicWorkspaceAutonomyJudgmentRequest {
            context: PublicWorkspaceAutonomyContext {
                tenant_id: "tenant-1".to_string(),
                project_id: "project-1".to_string(),
                workspace_id: "workspace-1".to_string(),
                user_id: "user-1".to_string(),
                is_superuser: false,
                expected_revision: Some(1),
                idempotency_key: Some("autonomy-1".to_string()),
            },
            workspace_revision: 1,
            force: false,
            candidates: vec![PublicWorkspaceAutonomyCandidate {
                root_task_id: "root-1".to_string(),
                title: "Root".to_string(),
                description: None,
                status: "todo".to_string(),
                metadata: json!({"task_role": "goal_root"}),
            }],
            agent_candidates: vec![PublicWorkspaceAutonomyAgentCandidate {
                workspace_agent_binding_id: "binding-1".to_string(),
                agent_id: "agent-1".to_string(),
                display_name: None,
                description: None,
                status: "idle".to_string(),
                config: json!({}),
            }],
        }
    }

    #[test]
    fn next_action_deserialization_rejects_nested_extra_fields() {
        assert!(
            serde_json::from_value::<PublicWorkspaceAutonomyNextAction>(json!({
                "title": "Next",
                "description": "Continue",
                "workspace_agent_binding_id": "binding-1",
                "unexpected": true,
            }))
            .is_err()
        );
    }

    #[test]
    fn judgment_rejects_overlong_next_action_description() {
        let result = PublicWorkspaceAutonomyJudgment::new(
            &judgment_request(),
            PublicWorkspaceAutonomyVerdictKind::Continue,
            Some("root-1".to_string()),
            Some(PublicWorkspaceAutonomyNextAction {
                title: "Next".to_string(),
                description: "x".repeat(MAX_NEXT_ACTION_DESCRIPTION_CHARS + 1),
                workspace_agent_binding_id: "binding-1".to_string(),
            }),
            "Continue".to_string(),
            "judge-1".to_string(),
            "judge_workspace_autonomy".to_string(),
            json!({}),
            json!({}),
            1,
        );
        assert!(matches!(
            result,
            Err(PublicWorkspaceAutonomyJudgeContractError::InvalidNextAction)
        ));
    }
}
