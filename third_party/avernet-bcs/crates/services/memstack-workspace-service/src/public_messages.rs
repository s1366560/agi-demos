//! Legacy-compatible Workspace chat orchestration over the BCS message authority.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{DateTime, SecondsFormat, Utc};
use memstack_workspace_store::{
    ResolvedWorkspaceMentions, WorkspaceMessageRecord, WorkspaceMessageScope,
    WorkspaceMessageStore, WorkspaceMessageStoreError, WorkspaceMessageWrite,
};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

use crate::canonical_json;

const PUBLIC_MESSAGE_NAMESPACE: Uuid = Uuid::from_u128(0xd1a7_7201_0556_42d9_b6f8_636f_12a8_2c3f);
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 255;

/// Authenticated tenant/project/workspace scope for a public chat request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceMessageContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub user_is_superuser: bool,
    pub authenticated_email: Option<String>,
}

/// Legacy POST message input. Only the human sender type is accepted.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicSendWorkspaceMessageInput {
    pub context: PublicWorkspaceMessageContext,
    pub content: String,
    pub sender_type: String,
    pub parent_message_id: Option<String>,
    pub mentions: Vec<String>,
    pub idempotency_key: Option<String>,
}

/// Stable public Workspace message projection.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PublicWorkspaceMessage {
    pub id: String,
    pub workspace_id: String,
    pub sender_id: String,
    pub sender_type: String,
    pub content: String,
    pub mentions: Vec<String>,
    pub parent_message_id: Option<String>,
    pub metadata: Value,
    pub created_at: String,
}

/// Active Agent target selected by one structured mention request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceMessageDeliveryTarget {
    pub agent_id: String,
    pub bot_uuid: String,
    pub display_name: Option<String>,
}

/// A newly committed or idempotently replayed Workspace message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceMessageOutcome {
    pub message: PublicWorkspaceMessage,
    pub group_id: String,
    pub session_id: String,
    pub correlation_id: String,
    pub delivery_targets: Vec<PublicWorkspaceMessageDeliveryTarget>,
    pub replayed: bool,
}

/// Stable public message error category consumed by delivery adapters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceMessageErrorKind {
    InvalidRequest,
    NotFound,
    AccessRequired,
    EditorAccessRequired,
    Conflict,
    Unavailable,
}

/// Public Workspace chat validation or persistence failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceMessageError {
    #[error("Invalid workspace chat request")]
    InvalidRequest,

    #[error("Workspace principal identity is unavailable")]
    IdentityUnavailable,

    #[error(transparent)]
    Store(#[from] WorkspaceMessageStoreError),

    #[error("Workspace message serialization failed: {0}")]
    Json(#[source] serde_json::Error),

    #[error("Workspace message timestamp is outside the supported range: {0}")]
    InvalidTimestamp(i64),
}

impl PublicWorkspaceMessageError {
    /// Classify the error without exposing persistence details to HTTP callers.
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceMessageErrorKind {
        match self {
            Self::InvalidRequest | Self::Store(WorkspaceMessageStoreError::InvalidMention) => {
                PublicWorkspaceMessageErrorKind::InvalidRequest
            }
            Self::Store(WorkspaceMessageStoreError::NotFound) => {
                PublicWorkspaceMessageErrorKind::NotFound
            }
            Self::Store(WorkspaceMessageStoreError::AccessRequired) => {
                PublicWorkspaceMessageErrorKind::AccessRequired
            }
            Self::Store(WorkspaceMessageStoreError::EditorAccessRequired) => {
                PublicWorkspaceMessageErrorKind::EditorAccessRequired
            }
            Self::Store(WorkspaceMessageStoreError::IdempotencyConflict) => {
                PublicWorkspaceMessageErrorKind::Conflict
            }
            Self::IdentityUnavailable
            | Self::Json(_)
            | Self::InvalidTimestamp(_)
            | Self::Store(_) => PublicWorkspaceMessageErrorKind::Unavailable,
        }
    }
}

/// Public Workspace chat use cases over the atomic message store.
pub struct PublicWorkspaceMessageService<'a> {
    store: WorkspaceMessageStore<'a>,
}

impl<'a> PublicWorkspaceMessageService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceMessageStore::new(db, flavor),
        }
    }

    /// Validate, resolve structured mentions, and atomically persist one human message.
    ///
    /// # Errors
    ///
    /// Returns stable validation, access, conflict, or infrastructure errors.
    pub async fn send(
        &self,
        input: &PublicSendWorkspaceMessageInput,
    ) -> Result<PublicWorkspaceMessageOutcome, PublicWorkspaceMessageError> {
        validate_send_input(input)?;
        let scope = message_scope(&input.context);
        self.store
            .require_access(
                &scope,
                input.context.user_id.as_str(),
                input.context.user_is_superuser,
                true,
            )
            .await?;
        let sender_name = self.sender_name(&scope, &input.context).await?;
        let resolved = self
            .store
            .resolve_mentions(&scope, input.mentions.as_slice())
            .await?;
        let write = message_write(input, &scope, &sender_name, &resolved)?;
        let outcome = self.store.create(&write).await?;
        Ok(PublicWorkspaceMessageOutcome {
            message: public_message(outcome.message)?,
            group_id: outcome.group_id,
            session_id: write.session_id,
            correlation_id: write.correlation_id,
            delivery_targets: outcome
                .delivery_targets
                .into_iter()
                .map(|target| PublicWorkspaceMessageDeliveryTarget {
                    agent_id: target.agent_id,
                    bot_uuid: target.bot_uuid,
                    display_name: target.display_name,
                })
                .collect(),
            replayed: outcome.replayed,
        })
    }

    /// List oldest-first messages using the legacy optional `before` cursor.
    ///
    /// # Errors
    ///
    /// Returns stable access or persistence errors.
    pub async fn list(
        &self,
        context: &PublicWorkspaceMessageContext,
        limit: i64,
        before: Option<&str>,
    ) -> Result<Vec<PublicWorkspaceMessage>, PublicWorkspaceMessageError> {
        let records = self
            .store
            .list(
                &message_scope(context),
                context.user_id.as_str(),
                context.user_is_superuser,
                limit,
                before,
            )
            .await?;
        records.into_iter().map(public_message).collect()
    }

    /// List oldest-first messages mentioning one exact structured target.
    ///
    /// # Errors
    ///
    /// Returns stable access or persistence errors.
    pub async fn mentions(
        &self,
        context: &PublicWorkspaceMessageContext,
        target_id: &str,
        limit: i64,
    ) -> Result<Vec<PublicWorkspaceMessage>, PublicWorkspaceMessageError> {
        let records = self
            .store
            .mentions(
                &message_scope(context),
                context.user_id.as_str(),
                context.user_is_superuser,
                target_id,
                limit,
            )
            .await?;
        records.into_iter().map(public_message).collect()
    }

    async fn sender_name(
        &self,
        scope: &WorkspaceMessageScope,
        context: &PublicWorkspaceMessageContext,
    ) -> Result<String, PublicWorkspaceMessageError> {
        if context.user_is_superuser {
            return context
                .authenticated_email
                .as_deref()
                .map(str::trim)
                .filter(|email| !email.is_empty())
                .map(str::to_string)
                .ok_or(PublicWorkspaceMessageError::IdentityUnavailable);
        }
        self.store
            .sender_email(scope, context.user_id.as_str())
            .await
            .map_err(Into::into)
    }
}

fn validate_send_input(
    input: &PublicSendWorkspaceMessageInput,
) -> Result<(), PublicWorkspaceMessageError> {
    if input.sender_type != "human" || input.content.trim().is_empty() {
        return Err(PublicWorkspaceMessageError::InvalidRequest);
    }
    if let Some(idempotency_key) = &input.idempotency_key
        && (idempotency_key.trim().is_empty()
            || idempotency_key.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS)
    {
        return Err(PublicWorkspaceMessageError::InvalidRequest);
    }
    Ok(())
}

fn message_scope(context: &PublicWorkspaceMessageContext) -> WorkspaceMessageScope {
    WorkspaceMessageScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    }
}

fn message_write(
    input: &PublicSendWorkspaceMessageInput,
    scope: &WorkspaceMessageScope,
    sender_name: &str,
    resolved: &ResolvedWorkspaceMentions,
) -> Result<WorkspaceMessageWrite, PublicWorkspaceMessageError> {
    let idempotency_key = input
        .idempotency_key
        .clone()
        .unwrap_or_else(|| format!("legacy-message:{}", Uuid::new_v4()));
    let request_hash = request_hash(input)?;
    let message_id = deterministic_id("message", scope, &idempotency_key);
    let session_id = deterministic_id("session", scope, "workspace-chat");
    let correlation_id = deterministic_id("correlation", scope, &idempotency_key);
    let outbox_id = deterministic_id("outbox", scope, &idempotency_key);
    let created_at_ms = Utc::now().timestamp_millis();
    let created_at = format_timestamp(created_at_ms)?;
    let metadata = json!({"sender_name": sender_name});
    let message = PublicWorkspaceMessage {
        id: message_id.clone(),
        workspace_id: scope.workspace_id.clone(),
        sender_id: input.context.user_id.clone(),
        sender_type: "human".to_string(),
        content: input.content.clone(),
        mentions: resolved.mention_ids.clone(),
        parent_message_id: input.parent_message_id.clone(),
        metadata: metadata.clone(),
        created_at,
    };
    let event_payload = json!({"message": message});
    let event_metadata = json!({
        "surface_owner": "workspace-chat",
        "surface_boundary": "hosted",
        "authority_class": "non-authoritative",
        "signal_role": "sensing-capable",
    });
    Ok(WorkspaceMessageWrite {
        scope: scope.clone(),
        message_id,
        session_id,
        correlation_id,
        outbox_id,
        sender_id: input.context.user_id.clone(),
        sender_name: sender_name.to_string(),
        sender_is_superuser: input.context.user_is_superuser,
        content_json: serde_json::to_string(&input.content)
            .map_err(PublicWorkspaceMessageError::Json)?,
        mentions_json: serde_json::to_string(&resolved.mention_ids)
            .map_err(PublicWorkspaceMessageError::Json)?,
        parent_message_id: input.parent_message_id.clone(),
        metadata_json: serde_json::to_string(&metadata)
            .map_err(PublicWorkspaceMessageError::Json)?,
        idempotency_key,
        request_hash,
        created_at_ms,
        event_payload_json: serde_json::to_string(&event_payload)
            .map_err(PublicWorkspaceMessageError::Json)?,
        event_metadata_json: serde_json::to_string(&event_metadata)
            .map_err(PublicWorkspaceMessageError::Json)?,
    })
}

fn request_hash(
    input: &PublicSendWorkspaceMessageInput,
) -> Result<String, PublicWorkspaceMessageError> {
    let payload = canonical_json(&json!({
        "action": "send_workspace_message",
        "tenant_id": &input.context.tenant_id,
        "project_id": &input.context.project_id,
        "workspace_id": &input.context.workspace_id,
        "sender_id": &input.context.user_id,
        "sender_type": &input.sender_type,
        "content": &input.content,
        "parent_message_id": &input.parent_message_id,
        "mentions": &input.mentions,
    }));
    let bytes = serde_json::to_vec(&payload).map_err(PublicWorkspaceMessageError::Json)?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

fn deterministic_id(label: &str, scope: &WorkspaceMessageScope, key: &str) -> String {
    let material = format!(
        "{label}:{}:{}:{}:{key}",
        scope.tenant_id, scope.project_id, scope.workspace_id
    );
    Uuid::new_v5(&PUBLIC_MESSAGE_NAMESPACE, material.as_bytes()).to_string()
}

pub(crate) fn public_message(
    record: WorkspaceMessageRecord,
) -> Result<PublicWorkspaceMessage, PublicWorkspaceMessageError> {
    Ok(PublicWorkspaceMessage {
        id: record.id,
        workspace_id: record.workspace_id,
        sender_id: record.sender_id,
        sender_type: record.sender_type,
        content: record.content,
        mentions: record.mentions,
        parent_message_id: record.parent_message_id,
        metadata: record.metadata,
        created_at: format_timestamp(record.created_at_ms)?,
    })
}

fn format_timestamp(timestamp_ms: i64) -> Result<String, PublicWorkspaceMessageError> {
    DateTime::<Utc>::from_timestamp_millis(timestamp_ms)
        .map(|timestamp| timestamp.to_rfc3339_opts(SecondsFormat::Millis, true))
        .ok_or(PublicWorkspaceMessageError::InvalidTimestamp(timestamp_ms))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input() -> PublicSendWorkspaceMessageInput {
        PublicSendWorkspaceMessageInput {
            context: PublicWorkspaceMessageContext {
                tenant_id: "tenant-1".to_string(),
                project_id: "project-1".to_string(),
                workspace_id: "workspace-1".to_string(),
                user_id: "user-1".to_string(),
                user_is_superuser: false,
                authenticated_email: None,
            },
            content: "Hello".to_string(),
            sender_type: "human".to_string(),
            parent_message_id: None,
            mentions: Vec::new(),
            idempotency_key: Some("request-1".to_string()),
        }
    }

    #[test]
    fn deterministic_ids_and_request_hash_are_stable() -> Result<(), Box<dyn std::error::Error>> {
        let input = input();
        let scope = message_scope(&input.context);
        assert_eq!(request_hash(&input)?, request_hash(&input)?);
        assert_eq!(
            deterministic_id("message", &scope, "request-1"),
            deterministic_id("message", &scope, "request-1")
        );
        assert_ne!(
            deterministic_id("message", &scope, "request-1"),
            deterministic_id("outbox", &scope, "request-1")
        );
        Ok(())
    }

    #[test]
    fn human_non_blank_content_is_required() {
        let mut value = input();
        value.sender_type = "agent".to_string();
        assert!(matches!(
            validate_send_input(&value),
            Err(PublicWorkspaceMessageError::InvalidRequest)
        ));

        value.sender_type = "human".to_string();
        value.content = "  \n".to_string();
        assert!(matches!(
            validate_send_input(&value),
            Err(PublicWorkspaceMessageError::InvalidRequest)
        ));
    }

    #[test]
    fn public_timestamp_is_utc_z() -> Result<(), PublicWorkspaceMessageError> {
        assert_eq!(format_timestamp(0)?, "1970-01-01T00:00:00.000Z");
        Ok(())
    }
}
