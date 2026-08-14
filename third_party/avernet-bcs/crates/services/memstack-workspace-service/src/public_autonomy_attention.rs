//! Editor-authorized resolution and retry operations for Workspace Autonomy attentions.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_store::{
    WorkspaceAutonomyAttentionRecord, WorkspaceAutonomyAttentionResolution,
    WorkspaceAutonomyAttentionStore, WorkspaceAutonomyAttentionStoreError, WorkspaceAutonomyScope,
};
use serde::Serialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::{PublicWorkspaceAutonomyContext, canonical_json};

const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;

/// Stable public attention-operation failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceAutonomyAttentionError {
    #[error("invalid Workspace Autonomy attention request")]
    InvalidRequest,
    #[error(transparent)]
    Store(#[from] WorkspaceAutonomyAttentionStoreError),
    #[error("Workspace Autonomy attention JSON serialization failed: {0}")]
    Json(#[from] serde_json::Error),
}

/// Stable error category consumed by the Workspace Core HTTP adapter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceAutonomyAttentionErrorKind {
    InvalidRequest,
    Forbidden,
    Conflict,
    Unavailable,
}

impl PublicWorkspaceAutonomyAttentionError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceAutonomyAttentionErrorKind {
        match self {
            Self::InvalidRequest => PublicWorkspaceAutonomyAttentionErrorKind::InvalidRequest,
            Self::Store(WorkspaceAutonomyAttentionStoreError::InvalidRequest) => {
                PublicWorkspaceAutonomyAttentionErrorKind::InvalidRequest
            }
            Self::Store(WorkspaceAutonomyAttentionStoreError::EditorAccessRequired) => {
                PublicWorkspaceAutonomyAttentionErrorKind::Forbidden
            }
            Self::Store(
                WorkspaceAutonomyAttentionStoreError::Conflict
                | WorkspaceAutonomyAttentionStoreError::IdempotencyConflict
                | WorkspaceAutonomyAttentionStoreError::IncompleteReceipt,
            ) => PublicWorkspaceAutonomyAttentionErrorKind::Conflict,
            Self::Store(
                WorkspaceAutonomyAttentionStoreError::InvalidRecord(_)
                | WorkspaceAutonomyAttentionStoreError::Database(_),
            )
            | Self::Json(_) => PublicWorkspaceAutonomyAttentionErrorKind::Unavailable,
            Self::Store(_) => PublicWorkspaceAutonomyAttentionErrorKind::Unavailable,
        }
    }
}

/// One open durable Autonomy attention visible to a Workspace member.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PublicWorkspaceAutonomyAttention {
    pub attention_id: String,
    pub root_task_id: Option<String>,
    pub source_kind: String,
    pub source_id: String,
    pub reason: String,
    pub status: String,
    pub created_at_ms: i64,
}

/// Revision-guarded response after an editor closes one Judge attention.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PublicWorkspaceAutonomyAttentionResolveResponse {
    pub attention_id: String,
    pub status: &'static str,
    pub committed_revision: u64,
    pub replayed: bool,
}

impl From<WorkspaceAutonomyAttentionRecord> for PublicWorkspaceAutonomyAttention {
    fn from(record: WorkspaceAutonomyAttentionRecord) -> Self {
        Self {
            attention_id: record.attention_id,
            root_task_id: record.root_task_id,
            source_kind: record.source_kind,
            source_id: record.source_id,
            reason: record.reason,
            status: record.status,
            created_at_ms: record.created_at_ms,
        }
    }
}

/// Application boundary for editor-reviewed attention resolution and retries.
pub struct PublicWorkspaceAutonomyAttentionService<'a> {
    store: WorkspaceAutonomyAttentionStore<'a>,
}

impl<'a> PublicWorkspaceAutonomyAttentionService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceAutonomyAttentionStore::new(db, flavor),
        }
    }

    /// List the durable open attention projection for one authenticated Workspace scope.
    pub async fn list_open(
        &self,
        context: &PublicWorkspaceAutonomyContext,
    ) -> Result<Vec<PublicWorkspaceAutonomyAttention>, PublicWorkspaceAutonomyAttentionError> {
        Ok(self
            .store
            .list_open(&scope(context))
            .await?
            .into_iter()
            .map(PublicWorkspaceAutonomyAttention::from)
            .collect())
    }

    /// Resolve a Judge block or escalation without creating a new semantic verdict.
    pub async fn resolve_judge_attention(
        &self,
        context: &PublicWorkspaceAutonomyContext,
        attention_id: &str,
        resolved_at_ms: i64,
    ) -> Result<
        PublicWorkspaceAutonomyAttentionResolveResponse,
        PublicWorkspaceAutonomyAttentionError,
    > {
        let expected_revision = context
            .expected_revision
            .ok_or(PublicWorkspaceAutonomyAttentionError::InvalidRequest)?;
        let idempotency_key = context
            .idempotency_key
            .as_deref()
            .ok_or(PublicWorkspaceAutonomyAttentionError::InvalidRequest)?;
        validate_idempotency_key(idempotency_key)?;
        let request_hash = resolution_request_hash(context, attention_id, expected_revision)?;
        let outcome = self
            .store
            .resolve_judge_attention(&WorkspaceAutonomyAttentionResolution {
                scope: scope(context),
                actor_id: context.user_id.clone(),
                actor_is_superuser: context.is_superuser,
                attention_id: attention_id.to_string(),
                expected_revision,
                idempotency_key: idempotency_key.to_string(),
                request_hash,
                resolved_at_ms,
            })
            .await?;
        Ok(PublicWorkspaceAutonomyAttentionResolveResponse {
            attention_id: attention_id.to_string(),
            status: "resolved",
            committed_revision: outcome.committed_revision,
            replayed: outcome.replayed,
        })
    }

    /// Retry the original dead-letter progression rather than creating a replacement row.
    pub async fn retry_dead_letter(
        &self,
        context: &PublicWorkspaceAutonomyContext,
        attention_id: &str,
        retry_at_ms: i64,
    ) -> Result<(), PublicWorkspaceAutonomyAttentionError> {
        self.store
            .retry_dead_letter(
                &scope(context),
                context.user_id.as_str(),
                context.is_superuser,
                attention_id,
                retry_at_ms,
            )
            .await?;
        Ok(())
    }

    /// Retry a workspace-level bootstrap dead letter after editor review.
    pub async fn retry_bootstrap_dead_letter(
        &self,
        context: &PublicWorkspaceAutonomyContext,
        attention_id: &str,
        retry_at_ms: i64,
    ) -> Result<(), PublicWorkspaceAutonomyAttentionError> {
        self.store
            .retry_bootstrap_dead_letter(
                &scope(context),
                context.user_id.as_str(),
                context.is_superuser,
                attention_id,
                retry_at_ms,
            )
            .await?;
        Ok(())
    }

    /// Retry the exact dead-letter source addressed by an open attention.
    pub async fn retry(
        &self,
        context: &PublicWorkspaceAutonomyContext,
        attention_id: &str,
        retry_at_ms: i64,
    ) -> Result<(), PublicWorkspaceAutonomyAttentionError> {
        let scope = scope(context);
        let attention = self.store.open_attention(&scope, attention_id).await?;
        match attention.source_kind.as_str() {
            "progression_dead_letter" => {
                self.store
                    .retry_dead_letter(
                        &scope,
                        context.user_id.as_str(),
                        context.is_superuser,
                        attention_id,
                        retry_at_ms,
                    )
                    .await?;
            }
            "bootstrap_dead_letter" => {
                self.store
                    .retry_bootstrap_dead_letter(
                        &scope,
                        context.user_id.as_str(),
                        context.is_superuser,
                        attention_id,
                        retry_at_ms,
                    )
                    .await?;
            }
            "task_dispatch_dead_letter" => {
                self.store
                    .retry_task_dispatch_dead_letter(
                        &scope,
                        context.user_id.as_str(),
                        context.is_superuser,
                        attention_id,
                        retry_at_ms,
                    )
                    .await?;
            }
            "judge_block" | "judge_escalate" => {
                return Err(WorkspaceAutonomyAttentionStoreError::Conflict.into());
            }
            _ => {
                return Err(
                    WorkspaceAutonomyAttentionStoreError::InvalidRecord("source_kind").into(),
                );
            }
        }
        Ok(())
    }
}

fn scope(context: &PublicWorkspaceAutonomyContext) -> WorkspaceAutonomyScope {
    WorkspaceAutonomyScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    }
}

fn validate_idempotency_key(
    idempotency_key: &str,
) -> Result<(), PublicWorkspaceAutonomyAttentionError> {
    if idempotency_key.trim().is_empty()
        || idempotency_key.trim() != idempotency_key
        || idempotency_key.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS
    {
        return Err(PublicWorkspaceAutonomyAttentionError::InvalidRequest);
    }
    Ok(())
}

fn resolution_request_hash(
    context: &PublicWorkspaceAutonomyContext,
    attention_id: &str,
    expected_revision: u64,
) -> Result<String, PublicWorkspaceAutonomyAttentionError> {
    let value = json!({
        "action": "resolve",
        "actor_id": &context.user_id,
        "attention_id": attention_id,
        "expected_revision": expected_revision,
        "project_id": &context.project_id,
        "tenant_id": &context.tenant_id,
        "workspace_id": &context.workspace_id,
    });
    let encoded = serde_json::to_vec(&canonical_json(&value))?;
    Ok(hex::encode(Sha256::digest(encoded)))
}
