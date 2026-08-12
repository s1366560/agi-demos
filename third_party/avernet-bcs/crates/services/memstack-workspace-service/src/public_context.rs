//! Legacy-compatible Workspace Context application service with Agent-first ambiguity resolution.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{SecondsFormat, Utc};
use memstack_workspace_service_api::{
    IdempotencyKey, ProjectId, TenantId, UserId, WorkspaceCommandError, WorkspaceContextCandidate,
    WorkspaceContextCurrent, WorkspaceContextJudgeContractError, WorkspaceContextJudgePort,
    WorkspaceContextJudgePortError, WorkspaceContextJudgment, WorkspaceContextJudgmentRequest,
};
use memstack_workspace_store::{
    WorkspaceContextAccessSnapshot, WorkspaceContextAuditRecord, WorkspaceContextCandidateSnapshot,
    WorkspaceContextEventReceipt, WorkspaceContextSnapshot, WorkspaceContextStore,
    WorkspaceContextStoreError, WorkspaceContextTransition, WorkspaceContextTransitionKind,
};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

use crate::canonical_json;

const CONTEXT_ID_NAMESPACE: Uuid = Uuid::from_u128(0xe8fc_0b79_6e92_4fa2_9192_36f9_7e95_91be);
const CONTEXT_RETRY_LIMIT: usize = 3;
const MAX_CONTEXT_REVISION: u64 = i64::MAX as u64;
const TOOL_NAME: &str = "select_workspace_context";

/// Legacy Workspace Context response body.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PublicWorkspaceContextSnapshot {
    pub tenant_id: String,
    pub project_id: String,
    pub revision: u64,
    pub updated_at: String,
}

/// GET result including the selected membership role.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PublicWorkspaceContextAccess {
    pub context: PublicWorkspaceContextSnapshot,
    pub membership_role: String,
}

/// Explicit structured user selection supplied by the compatibility adapter.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicSwitchWorkspaceContextInput {
    pub user_id: String,
    pub actor_api_key_id: Option<String>,
    pub tenant_id: String,
    pub project_id: String,
    pub expected_revision: u64,
    pub idempotency_key: String,
}

/// POST switch result preserving exact replay semantics.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PublicWorkspaceContextSwitchOutcome {
    pub context: PublicWorkspaceContextSnapshot,
    pub changed: bool,
}

/// Stable error category consumed by the HTTP adapter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceContextErrorKind {
    Validation,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Workspace Context validation, authority, judgment, or persistence failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceContextError {
    #[error(transparent)]
    Command(#[from] WorkspaceCommandError),

    #[error(transparent)]
    JudgeContract(#[from] WorkspaceContextJudgeContractError),

    #[error("Workspace Context input is invalid")]
    InvalidInput,

    #[error("Workspace Context is unavailable")]
    Unavailable,

    #[error("Workspace Context tenant membership is required")]
    MembershipRequired,

    #[error("Workspace Context Project is unavailable")]
    ProjectUnavailable,

    #[error("Workspace Context revision conflict")]
    RevisionConflict { expected: u64, actual: u64 },

    #[error("Workspace Context idempotency conflict")]
    IdempotencyConflict,

    #[error("Workspace Context revision is exhausted")]
    RevisionExhausted,

    #[error(transparent)]
    Judge(#[from] WorkspaceContextJudgePortError),

    #[error(transparent)]
    Store(#[from] WorkspaceContextStoreError),

    #[error("Workspace Context JSON serialization failed: {0}")]
    Json(#[source] serde_json::Error),

    #[error("Workspace Context authority changed too frequently")]
    AuthorityBusy,
}

impl PublicWorkspaceContextError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceContextErrorKind {
        match self {
            Self::Command(_) | Self::JudgeContract(_) | Self::InvalidInput => {
                PublicWorkspaceContextErrorKind::Validation
            }
            Self::Unavailable => PublicWorkspaceContextErrorKind::NotFound,
            Self::MembershipRequired | Self::ProjectUnavailable => {
                PublicWorkspaceContextErrorKind::Forbidden
            }
            Self::RevisionConflict { .. } | Self::IdempotencyConflict | Self::RevisionExhausted => {
                PublicWorkspaceContextErrorKind::Conflict
            }
            Self::Judge(_) | Self::Store(_) | Self::Json(_) | Self::AuthorityBusy => {
                PublicWorkspaceContextErrorKind::Unavailable
            }
        }
    }
}

/// Context projection and explicit switch use cases.
pub struct PublicWorkspaceContextService<'a> {
    store: WorkspaceContextStore<'a>,
    judge: &'a dyn WorkspaceContextJudgePort,
}

impl<'a> PublicWorkspaceContextService<'a> {
    #[must_use]
    pub const fn new(
        db: &'a dyn DbPlugin,
        flavor: DbSqlFlavor,
        judge: &'a dyn WorkspaceContextJudgePort,
    ) -> Self {
        Self {
            store: WorkspaceContextStore::new(db, flavor),
            judge,
        }
    }

    /// Load an accessible Context or initialize/repair it from mirrored memberships.
    ///
    /// Exactly one candidate is deterministic. More than one candidate always
    /// requires the structured Agent judge; no names, priorities, or text
    /// heuristics participate in selection.
    ///
    /// # Errors
    ///
    /// Returns stable unavailable, judgment, revision, or persistence errors.
    pub async fn get_or_initialize(
        &self,
        user_id: &str,
    ) -> Result<PublicWorkspaceContextAccess, PublicWorkspaceContextError> {
        let user_id = UserId::parse(user_id.to_string())?;
        for _attempt in 0..CONTEXT_RETRY_LIMIT {
            if let Some(access) = self.store.read_accessible(user_id.as_str()).await? {
                return Ok(public_access(access));
            }
            let current = self.store.read_current(user_id.as_str()).await?;
            let candidates = self.store.list_candidates(user_id.as_str()).await?;
            let Some(first_candidate) = candidates.first() else {
                return Err(PublicWorkspaceContextError::Unavailable);
            };
            let (selected, audit) = if candidates.len() == 1 {
                (first_candidate.clone(), None)
            } else {
                self.judged_candidate(&user_id, current.as_ref(), &candidates)
                    .await?
            };
            let committed_revision = match &current {
                Some(context) => next_revision(context.revision)?,
                None => 0,
            };
            let kind = if current.is_some() {
                WorkspaceContextTransitionKind::Repair
            } else {
                WorkspaceContextTransitionKind::Initialize
            };
            let idempotency_key = match kind {
                WorkspaceContextTransitionKind::Initialize => {
                    "system:workspace-context-initialize:v1".to_string()
                }
                WorkspaceContextTransitionKind::Repair => {
                    format!("system:workspace-context-repair:{committed_revision}")
                }
                WorkspaceContextTransitionKind::Switch => {
                    return Err(PublicWorkspaceContextError::InvalidInput);
                }
            };
            let transition = context_transition(
                kind,
                user_id.as_str(),
                None,
                current,
                selected.clone(),
                committed_revision,
                idempotency_key,
                audit,
            )?;
            match self.store.transition(&transition).await {
                Ok(context) => {
                    return Ok(PublicWorkspaceContextAccess {
                        context: public_snapshot(context),
                        membership_role: selected.membership_role,
                    });
                }
                Err(
                    WorkspaceContextStoreError::MembershipUnavailable
                    | WorkspaceContextStoreError::RevisionChanged
                    | WorkspaceContextStoreError::TransitionConflict,
                ) => continue,
                Err(error) => return Err(error.into()),
            }
        }
        Err(PublicWorkspaceContextError::AuthorityBusy)
    }

    /// Apply an explicit structured user-selected Context switch.
    ///
    /// # Errors
    ///
    /// Returns stable validation, membership, CAS, idempotency, or persistence errors.
    pub async fn switch(
        &self,
        input: &PublicSwitchWorkspaceContextInput,
    ) -> Result<PublicWorkspaceContextSwitchOutcome, PublicWorkspaceContextError> {
        let user_id = UserId::parse(input.user_id.clone())?;
        let tenant_id = TenantId::parse(input.tenant_id.clone())?;
        let project_id = ProjectId::parse(input.project_id.clone())?;
        if input.idempotency_key.chars().count() > 255 {
            return Err(PublicWorkspaceContextError::InvalidInput);
        }
        let idempotency_key = IdempotencyKey::parse(input.idempotency_key.clone())?;
        let request_hash = switch_request_hash(input)?;
        if let Some(receipt) = self
            .store
            .read_event(user_id.as_str(), idempotency_key.as_str())
            .await?
        {
            return replay_switch(receipt, &request_hash);
        }

        let candidate = self
            .store
            .read_candidate(user_id.as_str(), tenant_id.as_str(), project_id.as_str())
            .await?;
        let Some(candidate) = candidate else {
            if self
                .store
                .has_tenant_membership(user_id.as_str(), tenant_id.as_str())
                .await?
            {
                return Err(PublicWorkspaceContextError::ProjectUnavailable);
            }
            return Err(PublicWorkspaceContextError::MembershipRequired);
        };

        let current = self.store.read_current(user_id.as_str()).await?;
        let actual_revision = current.as_ref().map_or(0, |context| context.revision);
        if input.expected_revision != actual_revision {
            return Err(PublicWorkspaceContextError::RevisionConflict {
                expected: input.expected_revision,
                actual: actual_revision,
            });
        }
        let committed_revision = next_revision(actual_revision)?;
        let transition = context_transition_with_hash(
            WorkspaceContextTransitionKind::Switch,
            user_id.as_str(),
            input.actor_api_key_id.clone(),
            current,
            candidate,
            committed_revision,
            idempotency_key.as_str().to_string(),
            request_hash.clone(),
            None,
        )?;
        match self.store.transition(&transition).await {
            Ok(context) => Ok(PublicWorkspaceContextSwitchOutcome {
                context: public_snapshot(context),
                changed: true,
            }),
            Err(WorkspaceContextStoreError::MembershipUnavailable) => {
                Err(PublicWorkspaceContextError::ProjectUnavailable)
            }
            Err(
                WorkspaceContextStoreError::RevisionChanged
                | WorkspaceContextStoreError::TransitionConflict,
            ) => {
                if let Some(receipt) = self
                    .store
                    .read_event(user_id.as_str(), idempotency_key.as_str())
                    .await?
                {
                    return replay_switch(receipt, &request_hash);
                }
                let actual = self
                    .store
                    .read_current(user_id.as_str())
                    .await?
                    .map_or(0, |context| context.revision);
                Err(PublicWorkspaceContextError::RevisionConflict {
                    expected: input.expected_revision,
                    actual,
                })
            }
            Err(error) => Err(error.into()),
        }
    }

    async fn judged_candidate(
        &self,
        user_id: &UserId,
        current: Option<&WorkspaceContextSnapshot>,
        candidates: &[WorkspaceContextCandidateSnapshot],
    ) -> Result<
        (
            WorkspaceContextCandidateSnapshot,
            Option<WorkspaceContextAuditRecord>,
        ),
        PublicWorkspaceContextError,
    > {
        let request = judgment_request(user_id, current, candidates)?;
        let judgment = match self.judge.select(&request).await {
            Ok(judgment) => judgment,
            Err(error) => {
                self.store
                    .record_audit(&failed_judgment_audit(&request))
                    .await?;
                return Err(error.into());
            }
        };
        let selected = candidates
            .get(judgment.selected_index())
            .filter(|candidate| candidate_matches_judgment(candidate, &judgment))
            .cloned()
            .ok_or(WorkspaceContextJudgeContractError::InvalidSelection)?;
        let audit = successful_judgment_audit(user_id.as_str(), &judgment, &selected);
        Ok((selected, Some(audit)))
    }
}

fn judgment_request(
    user_id: &UserId,
    current: Option<&WorkspaceContextSnapshot>,
    candidates: &[WorkspaceContextCandidateSnapshot],
) -> Result<WorkspaceContextJudgmentRequest, PublicWorkspaceContextError> {
    let current = current
        .map(
            |context| -> Result<WorkspaceContextCurrent, WorkspaceCommandError> {
                Ok(WorkspaceContextCurrent::new(
                    TenantId::parse(context.tenant_id.clone())?,
                    ProjectId::parse(context.project_id.clone())?,
                    context.revision,
                ))
            },
        )
        .transpose()?;
    let candidates = candidates
        .iter()
        .map(|candidate| {
            WorkspaceContextCandidate::parse(
                candidate.tenant_id.clone(),
                candidate.project_id.clone(),
                candidate.membership_role.clone(),
            )
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(WorkspaceContextJudgmentRequest::new(
        UserId::parse(user_id.as_str())?,
        current,
        candidates,
    )?)
}

fn candidate_matches_judgment(
    candidate: &WorkspaceContextCandidateSnapshot,
    judgment: &WorkspaceContextJudgment,
) -> bool {
    candidate.tenant_id == judgment.selected().tenant_id().as_str()
        && candidate.project_id == judgment.selected().project_id().as_str()
        && candidate.membership_role == judgment.selected().membership_role().as_str()
}

#[allow(clippy::too_many_arguments)]
fn context_transition(
    kind: WorkspaceContextTransitionKind,
    user_id: &str,
    actor_api_key_id: Option<String>,
    previous: Option<WorkspaceContextSnapshot>,
    selected: WorkspaceContextCandidateSnapshot,
    committed_revision: u64,
    idempotency_key: String,
    audit: Option<WorkspaceContextAuditRecord>,
) -> Result<WorkspaceContextTransition, PublicWorkspaceContextError> {
    let request_hash = transition_request_hash(
        kind,
        user_id,
        previous.as_ref(),
        &selected,
        committed_revision,
    )?;
    context_transition_with_hash(
        kind,
        user_id,
        actor_api_key_id,
        previous,
        selected,
        committed_revision,
        idempotency_key,
        request_hash,
        audit,
    )
}

#[allow(clippy::too_many_arguments)]
fn context_transition_with_hash(
    kind: WorkspaceContextTransitionKind,
    user_id: &str,
    actor_api_key_id: Option<String>,
    previous: Option<WorkspaceContextSnapshot>,
    selected: WorkspaceContextCandidateSnapshot,
    committed_revision: u64,
    idempotency_key: String,
    request_hash: String,
    audit: Option<WorkspaceContextAuditRecord>,
) -> Result<WorkspaceContextTransition, PublicWorkspaceContextError> {
    let persisted_at = Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true);
    let event_type = match kind {
        WorkspaceContextTransitionKind::Initialize => "workspace_context.initialized",
        WorkspaceContextTransitionKind::Repair => "workspace_context.repaired",
        WorkspaceContextTransitionKind::Switch => "workspace_context.switched",
    }
    .to_string();
    let payload = json!({
        "tenant_id": &selected.tenant_id,
        "project_id": &selected.project_id,
        "revision": committed_revision,
        "updated_at": &persisted_at,
    });
    let metadata = json!({
        "user_id": user_id,
        "request_hash": &request_hash,
        "idempotency_key": &idempotency_key,
    });
    let event_id = (kind != WorkspaceContextTransitionKind::Initialize)
        .then(|| deterministic_id("context-event", user_id, &idempotency_key));
    Ok(WorkspaceContextTransition {
        kind,
        user_id: user_id.to_string(),
        actor_api_key_id,
        previous,
        selected,
        committed_revision,
        idempotency_key: idempotency_key.clone(),
        request_hash,
        event_id,
        outbox_id: deterministic_id("context-outbox", user_id, &idempotency_key),
        event_type,
        payload,
        metadata,
        audit,
        persisted_at,
    })
}

fn successful_judgment_audit(
    user_id: &str,
    judgment: &WorkspaceContextJudgment,
    selected: &WorkspaceContextCandidateSnapshot,
) -> WorkspaceContextAuditRecord {
    let created_at = Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true);
    WorkspaceContextAuditRecord {
        audit_id: deterministic_id("context-judge", user_id, &created_at),
        user_id: user_id.to_string(),
        tenant_id: Some(selected.tenant_id.clone()),
        project_id: Some(selected.project_id.clone()),
        agent_id: judgment.agent_id().to_string(),
        tool_name: judgment.tool_name().to_string(),
        input: judgment.input().clone(),
        output: judgment.output().clone(),
        rationale: judgment.rationale().to_string(),
        latency_ms: judgment.latency_ms(),
        status: "succeeded".to_string(),
        error_detail: None,
        created_at,
    }
}

fn failed_judgment_audit(request: &WorkspaceContextJudgmentRequest) -> WorkspaceContextAuditRecord {
    let created_at = Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true);
    let input = json!({
        "user_id": request.user_id().as_str(),
        "current": request.current().map(|current| json!({
            "tenant_id": current.tenant_id().as_str(),
            "project_id": current.project_id().as_str(),
            "revision": current.revision(),
        })),
        "candidates": request.candidates().iter().map(|candidate| json!({
            "tenant_id": candidate.tenant_id().as_str(),
            "project_id": candidate.project_id().as_str(),
            "membership_role": candidate.membership_role().as_str(),
        })).collect::<Vec<_>>(),
    });
    WorkspaceContextAuditRecord {
        audit_id: deterministic_id(
            "context-judge-failed",
            request.user_id().as_str(),
            &created_at,
        ),
        user_id: request.user_id().as_str().to_string(),
        tenant_id: None,
        project_id: None,
        agent_id: "unavailable".to_string(),
        tool_name: TOOL_NAME.to_string(),
        input,
        output: json!({}),
        rationale: "structured Workspace Context judgment unavailable".to_string(),
        latency_ms: 0,
        status: "failed".to_string(),
        error_detail: Some("Workspace Context judge is unavailable".to_string()),
        created_at,
    }
}

fn transition_request_hash(
    kind: WorkspaceContextTransitionKind,
    user_id: &str,
    previous: Option<&WorkspaceContextSnapshot>,
    selected: &WorkspaceContextCandidateSnapshot,
    committed_revision: u64,
) -> Result<String, PublicWorkspaceContextError> {
    hash_json(&json!({
        "kind": format!("{kind:?}"),
        "user_id": user_id,
        "previous": previous.map(|context| json!({
            "tenant_id": &context.tenant_id,
            "project_id": &context.project_id,
            "revision": context.revision,
        })),
        "selected": {
            "tenant_id": &selected.tenant_id,
            "project_id": &selected.project_id,
            "membership_role": &selected.membership_role,
        },
        "committed_revision": committed_revision,
    }))
}

fn switch_request_hash(
    input: &PublicSwitchWorkspaceContextInput,
) -> Result<String, PublicWorkspaceContextError> {
    hash_json(&json!({
        "user_id": &input.user_id,
        "tenant_id": &input.tenant_id,
        "project_id": &input.project_id,
        "expected_revision": input.expected_revision,
    }))
}

fn hash_json(value: &Value) -> Result<String, PublicWorkspaceContextError> {
    let bytes =
        serde_json::to_vec(&canonical_json(value)).map_err(PublicWorkspaceContextError::Json)?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

fn deterministic_id(kind: &str, user_id: &str, key: &str) -> String {
    Uuid::new_v5(
        &CONTEXT_ID_NAMESPACE,
        format!("{kind}\0{user_id}\0{key}").as_bytes(),
    )
    .to_string()
}

fn next_revision(revision: u64) -> Result<u64, PublicWorkspaceContextError> {
    if revision >= MAX_CONTEXT_REVISION {
        return Err(PublicWorkspaceContextError::RevisionExhausted);
    }
    Ok(revision + 1)
}

fn public_access(access: WorkspaceContextAccessSnapshot) -> PublicWorkspaceContextAccess {
    PublicWorkspaceContextAccess {
        context: public_snapshot(access.context),
        membership_role: access.membership_role,
    }
}

fn public_snapshot(context: WorkspaceContextSnapshot) -> PublicWorkspaceContextSnapshot {
    PublicWorkspaceContextSnapshot {
        tenant_id: context.tenant_id,
        project_id: context.project_id,
        revision: context.revision,
        updated_at: context.updated_at,
    }
}

fn replay_switch(
    receipt: WorkspaceContextEventReceipt,
    request_hash: &str,
) -> Result<PublicWorkspaceContextSwitchOutcome, PublicWorkspaceContextError> {
    if receipt.request_hash != request_hash {
        return Err(PublicWorkspaceContextError::IdempotencyConflict);
    }
    Ok(PublicWorkspaceContextSwitchOutcome {
        context: PublicWorkspaceContextSnapshot {
            tenant_id: receipt.tenant_id,
            project_id: receipt.project_id,
            revision: receipt.revision,
            updated_at: receipt.created_at,
        },
        changed: false,
    })
}
