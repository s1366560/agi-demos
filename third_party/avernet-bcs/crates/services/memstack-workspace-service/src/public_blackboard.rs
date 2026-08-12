//! Legacy-compatible Workspace blackboard use cases over the Avernet authority.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use memstack_workspace_store::{
    WorkspaceBlackboardDomainWrite, WorkspaceBlackboardPostRecord, WorkspaceBlackboardReplyRecord,
    WorkspaceBlackboardStore, WorkspaceBlackboardStoreError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use thiserror::Error;

#[path = "public_blackboard_commit.rs"]
mod commit;
#[path = "public_blackboard_projection.rs"]
mod projection;

use projection::*;

const MAX_TITLE_CHARS: usize = 255;
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;
const BLACKBOARD_STATUSES: &[&str] = &["open", "archived"];

/// Authenticated public blackboard request scope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceBlackboardContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub expected_revision: Option<u64>,
    pub idempotency_key: Option<String>,
}

/// Public blackboard post response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PublicWorkspaceBlackboardPost {
    pub id: String,
    pub workspace_id: String,
    pub author_id: String,
    pub title: String,
    pub content: String,
    pub status: String,
    pub is_pinned: bool,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Public blackboard reply response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PublicWorkspaceBlackboardReply {
    pub id: String,
    pub post_id: String,
    pub workspace_id: String,
    pub author_id: String,
    pub content: String,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Create-post input after HTTP decoding.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicCreateBlackboardPostInput {
    pub context: PublicWorkspaceBlackboardContext,
    pub title: String,
    pub content: String,
    pub status: String,
    pub is_pinned: bool,
    pub metadata: Value,
}

/// PATCH fields where `None` preserves the persisted value.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct PublicUpdateBlackboardPostFields {
    pub title: Option<String>,
    pub content: Option<String>,
    pub status: Option<String>,
    pub is_pinned: Option<bool>,
    pub metadata: Option<Value>,
}

/// Create-reply input after HTTP decoding.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicCreateBlackboardReplyInput {
    pub context: PublicWorkspaceBlackboardContext,
    pub content: String,
    pub metadata: Value,
}

/// Update-reply input after HTTP decoding.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicUpdateBlackboardReplyInput {
    pub content: String,
    pub metadata: Option<Value>,
}

/// Successful post write with authority metadata.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceBlackboardPostOutcome {
    pub post: PublicWorkspaceBlackboardPost,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Successful reply write with authority metadata.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceBlackboardReplyOutcome {
    pub reply: PublicWorkspaceBlackboardReply,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Successful delete response with retained receipt and authority metadata.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceBlackboardDeleteOutcome {
    pub response: Value,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Stable blackboard application failure categories.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceBlackboardErrorKind {
    InvalidRequest,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Stable blackboard application failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceBlackboardError {
    #[error("invalid Workspace blackboard request")]
    InvalidRequest,
    #[error("Blackboard post not found")]
    PostNotFound,
    #[error("Blackboard reply not found")]
    ReplyNotFound,
    #[error("Workspace blackboard access denied")]
    Forbidden,
    #[error("Workspace blackboard authority conflict")]
    Conflict,
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Store(#[from] WorkspaceBlackboardStoreError),
}

impl PublicWorkspaceBlackboardError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceBlackboardErrorKind {
        match self {
            Self::InvalidRequest => PublicWorkspaceBlackboardErrorKind::InvalidRequest,
            Self::PostNotFound | Self::ReplyNotFound => {
                PublicWorkspaceBlackboardErrorKind::NotFound
            }
            Self::Forbidden => PublicWorkspaceBlackboardErrorKind::Forbidden,
            Self::Conflict => PublicWorkspaceBlackboardErrorKind::Conflict,
            Self::Json(_) => PublicWorkspaceBlackboardErrorKind::Unavailable,
            Self::Store(error) => match error {
                WorkspaceBlackboardStoreError::NotFound
                | WorkspaceBlackboardStoreError::PostNotFound
                | WorkspaceBlackboardStoreError::ReplyNotFound => {
                    PublicWorkspaceBlackboardErrorKind::NotFound
                }
                WorkspaceBlackboardStoreError::AccessRequired
                | WorkspaceBlackboardStoreError::EditorAccessRequired => {
                    PublicWorkspaceBlackboardErrorKind::Forbidden
                }
                WorkspaceBlackboardStoreError::Conflict
                | WorkspaceBlackboardStoreError::IdempotencyConflict
                | WorkspaceBlackboardStoreError::IncompleteReceipt => {
                    PublicWorkspaceBlackboardErrorKind::Conflict
                }
                WorkspaceBlackboardStoreError::InvalidRecord(_)
                | WorkspaceBlackboardStoreError::InvalidJson(_)
                | WorkspaceBlackboardStoreError::Database(_) => {
                    PublicWorkspaceBlackboardErrorKind::Unavailable
                }
                _ => PublicWorkspaceBlackboardErrorKind::Unavailable,
            },
        }
    }
}

/// Workspace blackboard application service.
pub struct PublicWorkspaceBlackboardService<'a> {
    store: WorkspaceBlackboardStore<'a>,
    receipt_authority: Option<WorkspaceMutationAuthority>,
}

impl<'a> PublicWorkspaceBlackboardService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceBlackboardStore::new(db, flavor),
            receipt_authority: None,
        }
    }

    /// Persist a collaboration receipt envelope with the blackboard write.
    #[must_use]
    pub fn with_mutation_authority(mut self, authority: WorkspaceMutationAuthority) -> Self {
        self.receipt_authority = Some(authority);
        self
    }

    /// Create a blackboard post atomically with its outbox event.
    pub async fn create_post(
        &self,
        input: &PublicCreateBlackboardPostInput,
    ) -> Result<PublicWorkspaceBlackboardPostOutcome, PublicWorkspaceBlackboardError> {
        validate_title(input.title.as_str())?;
        validate_content(input.content.as_str())?;
        validate_status(input.status.as_str())?;
        let metadata = owned_metadata(&input.metadata)?;
        let context = prepared_context(&input.context, "create_blackboard_post");
        self.store
            .require_access(&blackboard_scope(&context), context.user_id.as_str(), true)
            .await?;
        let now = timestamp();
        let record = WorkspaceBlackboardPostRecord {
            post_id: deterministic_id(&context, "post", "root"),
            tenant_id: context.tenant_id.clone(),
            project_id: context.project_id.clone(),
            workspace_id: context.workspace_id.clone(),
            author_actor_id: context.user_id.clone(),
            title: input.title.clone(),
            content: input.content.clone(),
            status: input.status.clone(),
            is_pinned: input.is_pinned,
            metadata,
            created_at: now.clone(),
            updated_at: Some(now),
        };
        let response = public_post(&record)?;
        self.commit_post(
            &context,
            "create_blackboard_post",
            WorkspaceBlackboardDomainWrite::CreatePost(record),
            response,
            "blackboard_post_created",
            None,
        )
        .await
    }

    /// List visible blackboard posts.
    pub async fn list_posts(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<PublicWorkspaceBlackboardPost>, PublicWorkspaceBlackboardError> {
        validate_page(limit, offset, 200)?;
        let scope = blackboard_scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), false)
            .await?;
        self.store
            .list_posts(&scope, limit, offset)
            .await?
            .iter()
            .map(public_post)
            .collect()
    }

    /// Read one visible blackboard post.
    pub async fn get_post(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
    ) -> Result<PublicWorkspaceBlackboardPost, PublicWorkspaceBlackboardError> {
        let scope = blackboard_scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), false)
            .await?;
        let record = self
            .store
            .get_post(&scope, post_id)
            .await?
            .ok_or(PublicWorkspaceBlackboardError::PostNotFound)?;
        public_post(&record)
    }

    /// Update a blackboard post atomically.
    pub async fn update_post(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
        fields: &PublicUpdateBlackboardPostFields,
    ) -> Result<PublicWorkspaceBlackboardPostOutcome, PublicWorkspaceBlackboardError> {
        let mut record = self.require_post_for_write(context, post_id).await?;
        if let Some(title) = &fields.title {
            validate_title(title)?;
            record.title.clone_from(title);
        }
        if let Some(content) = &fields.content {
            validate_content(content)?;
            record.content.clone_from(content);
        }
        if let Some(status) = &fields.status {
            validate_status(status)?;
            record.status.clone_from(status);
        }
        if let Some(is_pinned) = fields.is_pinned {
            record.is_pinned = is_pinned;
        }
        if let Some(metadata) = &fields.metadata {
            record.metadata = owned_metadata(metadata)?;
        }
        record.updated_at = Some(timestamp());
        let response = public_post(&record)?;
        self.commit_post(
            context,
            "update_blackboard_post",
            WorkspaceBlackboardDomainWrite::UpdatePost(record),
            response,
            "blackboard_post_updated",
            None,
        )
        .await
    }

    /// Pin or unpin a blackboard post using the same atomic update contract.
    pub async fn set_post_pinned(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
        is_pinned: bool,
    ) -> Result<PublicWorkspaceBlackboardPostOutcome, PublicWorkspaceBlackboardError> {
        let mut record = self.require_post_for_write(context, post_id).await?;
        record.is_pinned = is_pinned;
        record.updated_at = Some(timestamp());
        let response = public_post(&record)?;
        let action = if is_pinned { "pin" } else { "unpin" };
        self.commit_post(
            context,
            format!("{action}_blackboard_post").as_str(),
            WorkspaceBlackboardDomainWrite::UpdatePost(record),
            response,
            "blackboard_post_updated",
            Some(action),
        )
        .await
    }

    /// Delete a blackboard post and its replies atomically.
    pub async fn delete_post(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
    ) -> Result<Value, PublicWorkspaceBlackboardError> {
        self.delete_post_with_outcome(context, post_id)
            .await
            .map(|outcome| outcome.response)
    }

    /// Delete a post while retaining authority metadata for compatibility facades.
    pub async fn delete_post_with_outcome(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
    ) -> Result<PublicWorkspaceBlackboardDeleteOutcome, PublicWorkspaceBlackboardError> {
        let _record = self.require_post_for_write(context, post_id).await?;
        let outcome = self
            .commit_value(
                context,
                "delete_blackboard_post",
                post_id,
                WorkspaceBlackboardDomainWrite::DeletePost {
                    post_id: post_id.to_string(),
                },
                json!({"success": true}),
                "blackboard_post_deleted",
                blackboard_event(json!({"post_id": post_id}))?,
            )
            .await?;
        Ok(PublicWorkspaceBlackboardDeleteOutcome {
            response: outcome.response,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    /// Create a reply under an existing post.
    pub async fn create_reply(
        &self,
        post_id: &str,
        input: &PublicCreateBlackboardReplyInput,
    ) -> Result<PublicWorkspaceBlackboardReplyOutcome, PublicWorkspaceBlackboardError> {
        validate_content(input.content.as_str())?;
        let context = prepared_context(&input.context, "create_blackboard_reply");
        let _post = self.require_post_for_write(&context, post_id).await?;
        let now = timestamp();
        let record = WorkspaceBlackboardReplyRecord {
            reply_id: deterministic_id(&context, "reply", post_id),
            tenant_id: context.tenant_id.clone(),
            project_id: context.project_id.clone(),
            workspace_id: context.workspace_id.clone(),
            post_id: post_id.to_string(),
            author_actor_id: context.user_id.clone(),
            content: input.content.clone(),
            metadata: owned_metadata(&input.metadata)?,
            created_at: now.clone(),
            updated_at: Some(now),
        };
        let response = public_reply(&record)?;
        self.commit_reply(
            &context,
            "create_blackboard_reply",
            WorkspaceBlackboardDomainWrite::CreateReply(record),
            response,
            "blackboard_reply_created",
        )
        .await
    }

    /// List replies under one visible post.
    pub async fn list_replies(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<PublicWorkspaceBlackboardReply>, PublicWorkspaceBlackboardError> {
        validate_page(limit, offset, 500)?;
        let _post = self.get_post(context, post_id).await?;
        self.store
            .list_replies(&blackboard_scope(context), post_id, limit, offset)
            .await?
            .iter()
            .map(public_reply)
            .collect()
    }

    /// Update one scoped reply atomically.
    pub async fn update_reply(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
        reply_id: &str,
        input: &PublicUpdateBlackboardReplyInput,
    ) -> Result<PublicWorkspaceBlackboardReplyOutcome, PublicWorkspaceBlackboardError> {
        validate_content(input.content.as_str())?;
        let mut record = self
            .require_reply_for_write(context, post_id, reply_id)
            .await?;
        record.content.clone_from(&input.content);
        if let Some(metadata) = &input.metadata {
            record.metadata = owned_metadata(metadata)?;
        }
        record.updated_at = Some(timestamp());
        let response = public_reply(&record)?;
        self.commit_reply(
            context,
            "update_blackboard_reply",
            WorkspaceBlackboardDomainWrite::UpdateReply(record),
            response,
            "blackboard_reply_updated",
        )
        .await
    }

    /// Delete one scoped reply atomically.
    pub async fn delete_reply(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
        reply_id: &str,
    ) -> Result<Value, PublicWorkspaceBlackboardError> {
        self.delete_reply_with_outcome(context, post_id, reply_id)
            .await
            .map(|outcome| outcome.response)
    }

    /// Delete a reply while retaining authority metadata for compatibility facades.
    pub async fn delete_reply_with_outcome(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
        reply_id: &str,
    ) -> Result<PublicWorkspaceBlackboardDeleteOutcome, PublicWorkspaceBlackboardError> {
        let _record = self
            .require_reply_for_write(context, post_id, reply_id)
            .await?;
        let outcome = self
            .commit_value(
                context,
                "delete_blackboard_reply",
                reply_id,
                WorkspaceBlackboardDomainWrite::DeleteReply {
                    post_id: post_id.to_string(),
                    reply_id: reply_id.to_string(),
                },
                json!({"success": true}),
                "blackboard_reply_deleted",
                blackboard_event(json!({"reply_id": reply_id, "post_id": post_id}))?,
            )
            .await?;
        Ok(PublicWorkspaceBlackboardDeleteOutcome {
            response: outcome.response,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    async fn require_post_for_write(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
    ) -> Result<WorkspaceBlackboardPostRecord, PublicWorkspaceBlackboardError> {
        let scope = blackboard_scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true)
            .await?;
        self.store
            .get_post(&scope, post_id)
            .await?
            .ok_or(PublicWorkspaceBlackboardError::PostNotFound)
    }

    async fn require_reply_for_write(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        post_id: &str,
        reply_id: &str,
    ) -> Result<WorkspaceBlackboardReplyRecord, PublicWorkspaceBlackboardError> {
        let _post = self.require_post_for_write(context, post_id).await?;
        self.store
            .get_reply(&blackboard_scope(context), post_id, reply_id)
            .await?
            .ok_or(PublicWorkspaceBlackboardError::ReplyNotFound)
    }
}
