//! Agent-first Workspace Autonomy tick use case.

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use memstack_workspace_store::{
    WorkspaceAutonomyJudgmentAudit, WorkspaceAutonomyMutation, WorkspaceAutonomyScope,
    WorkspaceAutonomyStore, WorkspaceAutonomyStoreError, WorkspaceTaskRecord, WorkspaceTaskScope,
    WorkspaceTaskStore, WorkspaceTaskStoreError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

use crate::canonical_json;

const AUTONOMY_NAMESPACE: Uuid = Uuid::from_u128(0xd760_426a_5559_49be_a18f_9589_a358_8a13);
const COOLDOWN_SECONDS: i64 = 60;
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;

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
}

/// Validated Agent tool-call verdict and mandatory audit fields.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceAutonomyJudgment {
    verdict: PublicWorkspaceAutonomyVerdictKind,
    selected_root_task_id: Option<String>,
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
        if verdict == PublicWorkspaceAutonomyVerdictKind::Continue
            && selected_root_task_id.is_none()
        {
            return Err(PublicWorkspaceAutonomyJudgeContractError::MissingSelection);
        }
        Ok(Self {
            verdict,
            selected_root_task_id,
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

/// Invalid structured Judge response.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceAutonomyJudgeContractError {
    #[error("Workspace Autonomy Judge audit fields must not be blank")]
    BlankAuditField,
    #[error("Workspace Autonomy Judge selected a root outside the candidate set")]
    InvalidSelection,
    #[error("Workspace Autonomy continue verdict requires a selected root")]
    MissingSelection,
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
            Self::TaskStore(WorkspaceTaskStoreError::NotFound) => {
                PublicWorkspaceAutonomyErrorKind::NotFound
            }
            Self::TaskStore(
                WorkspaceTaskStoreError::AccessRequired
                | WorkspaceTaskStoreError::EditorAccessRequired,
            ) => PublicWorkspaceAutonomyErrorKind::Forbidden,
            Self::Judge(_) | Self::Store(_) | Self::TaskStore(_) | Self::Json(_) => {
                PublicWorkspaceAutonomyErrorKind::Unavailable
            }
        }
    }
}

/// Deterministic trigger plus Agent-judged verdict service.
pub struct PublicWorkspaceAutonomyService<'a> {
    store: WorkspaceAutonomyStore<'a>,
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
        let revision = match context.expected_revision {
            Some(revision) => revision,
            None => self.store.revision(&scope).await?,
        };
        let idempotency_key = context
            .idempotency_key
            .clone()
            .unwrap_or_else(|| format!("legacy-autonomy-tick:{}", Uuid::new_v4()));
        validate_idempotency_key(idempotency_key.as_str())?;
        let candidates = self.open_root_candidates(context).await?;
        let request_hash = hash_value(json!({
            "tenant_id": &context.tenant_id,
            "project_id": &context.project_id,
            "workspace_id": &context.workspace_id,
            "actor_id": &context.user_id,
            "force": force,
            "workspace_revision": revision,
            "candidate_root_task_ids": candidates
                .iter()
                .map(|candidate| candidate.root_task_id.as_str())
                .collect::<Vec<_>>(),
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
                )
                .await;
        }

        let request = PublicWorkspaceAutonomyJudgmentRequest {
            context: context.clone(),
            workspace_revision: revision,
            force,
            candidates,
        };
        let judgment = self.judge.judge(&request).await?;
        let verdict = judgment.verdict();
        let root_task_id = judgment.selected_root_task_id().map(str::to_string);
        self.commit(
            context,
            revision,
            idempotency_key,
            request_hash,
            force,
            verdict.as_str(),
            verdict.reason(),
            root_task_id,
            Some(judgment),
        )
        .await
    }

    async fn open_root_candidates(
        &self,
        context: &PublicWorkspaceAutonomyContext,
    ) -> Result<Vec<PublicWorkspaceAutonomyCandidate>, PublicWorkspaceAutonomyError> {
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
            .filter(is_open_root)
            .map(|record| PublicWorkspaceAutonomyCandidate {
                root_task_id: record.task_id,
                title: record.title,
                description: record.description,
                status: record.status,
                metadata: record.metadata,
            })
            .collect())
    }

    async fn all_candidates_cooling_down(
        &self,
        scope: &WorkspaceAutonomyScope,
        candidates: &[PublicWorkspaceAutonomyCandidate],
    ) -> Result<bool, PublicWorkspaceAutonomyError> {
        let cutoff = Utc::now() - Duration::seconds(COOLDOWN_SECONDS);
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
    ) -> Result<PublicWorkspaceAutonomyTickOutcome, PublicWorkspaceAutonomyError> {
        let response = PublicWorkspaceAutonomyTickResponse {
            triggered: verdict == "continue",
            root_task_id: root_task_id.clone(),
            reason: reason.to_string(),
        };
        let response_value = serde_json::to_value(&response)?;
        let tick_id = deterministic_tick_id(context, idempotency_key.as_str());
        let audit = judgment.map(|judgment| WorkspaceAutonomyJudgmentAudit {
            audit_id: Uuid::new_v5(&AUTONOMY_NAMESPACE, format!("audit\0{tick_id}").as_bytes())
                .to_string(),
            agent_id: judgment.agent_id().to_string(),
            tool_name: judgment.tool_name().to_string(),
            input: judgment.input().clone(),
            output: judgment.output().clone(),
            rationale: judgment.rationale().to_string(),
            latency_ms: judgment.latency_ms(),
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
