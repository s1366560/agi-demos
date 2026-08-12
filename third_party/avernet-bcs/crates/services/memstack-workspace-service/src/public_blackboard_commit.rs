//! Atomic blackboard mutation preparation shared by post and reply use cases.

use memstack_workspace_store::{
    WorkspaceBlackboardDomainWrite, WorkspaceBlackboardMutation, WorkspaceBlackboardMutationOutcome,
};
use serde_json::{Value, json};
use uuid::Uuid;

use super::{
    PublicWorkspaceBlackboardContext, PublicWorkspaceBlackboardError,
    PublicWorkspaceBlackboardPost, PublicWorkspaceBlackboardPostOutcome,
    PublicWorkspaceBlackboardReply, PublicWorkspaceBlackboardReplyOutcome,
    PublicWorkspaceBlackboardService, blackboard_event, blackboard_scope, hash_payload,
    request_hash, validate_idempotency_key,
};

impl<'a> PublicWorkspaceBlackboardService<'a> {
    pub(super) async fn commit_post(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        action: &str,
        domain_write: WorkspaceBlackboardDomainWrite,
        response: PublicWorkspaceBlackboardPost,
        event_type: &str,
        event_action: Option<&str>,
    ) -> Result<PublicWorkspaceBlackboardPostOutcome, PublicWorkspaceBlackboardError> {
        let response_value = serde_json::to_value(&response)?;
        let mut payload = json!({"post": &response_value});
        if event_type == "blackboard_post_created" {
            payload = json!({
                "post": &response_value,
                "workspace_id": &context.workspace_id,
                "post_id": &response.id,
                "author_id": &response.author_id,
                "title": &response.title,
                "status": &response.status,
                "is_pinned": response.is_pinned,
            });
        }
        if let Some(event_action) = event_action {
            payload["action"] = Value::String(event_action.to_string());
        }
        let outcome = self
            .commit_value(
                context,
                action,
                response.id.as_str(),
                domain_write,
                response_value,
                event_type,
                blackboard_event(payload)?,
            )
            .await?;
        Ok(PublicWorkspaceBlackboardPostOutcome {
            post: serde_json::from_value(outcome.response)?,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    pub(super) async fn commit_reply(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        action: &str,
        domain_write: WorkspaceBlackboardDomainWrite,
        response: PublicWorkspaceBlackboardReply,
        event_type: &str,
    ) -> Result<PublicWorkspaceBlackboardReplyOutcome, PublicWorkspaceBlackboardError> {
        let response_value = serde_json::to_value(&response)?;
        let outcome = self
            .commit_value(
                context,
                action,
                response.id.as_str(),
                domain_write,
                response_value.clone(),
                event_type,
                blackboard_event(json!({
                    "reply": response_value,
                    "post_id": &response.post_id,
                }))?,
            )
            .await?;
        Ok(PublicWorkspaceBlackboardReplyOutcome {
            reply: serde_json::from_value(outcome.response)?,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) async fn commit_value(
        &self,
        context: &PublicWorkspaceBlackboardContext,
        action: &str,
        aggregate_id: &str,
        domain_write: WorkspaceBlackboardDomainWrite,
        response: Value,
        event_type: &str,
        event_payload: Value,
    ) -> Result<WorkspaceBlackboardMutationOutcome, PublicWorkspaceBlackboardError> {
        let scope = blackboard_scope(context);
        let expected_revision = match context.expected_revision {
            Some(revision) => revision,
            None => self.store.revision(&scope).await?,
        };
        let idempotency_key = context
            .idempotency_key
            .clone()
            .unwrap_or_else(|| format!("legacy-{action}:{}", Uuid::new_v4()));
        validate_idempotency_key(idempotency_key.as_str())?;
        let domain_hash = request_hash(json!({
            "action": action,
            "scope": {
                "tenant_id": &context.tenant_id,
                "project_id": &context.project_id,
                "workspace_id": &context.workspace_id,
            },
            "actor_id": &context.user_id,
            "aggregate_id": aggregate_id,
            "response": hash_payload(&response),
            "event_payload": hash_payload(&event_payload),
        }))?;
        let payload_hash = self
            .receipt_authority
            .as_ref()
            .map_or(domain_hash, |authority| {
                authority.request_hash().as_str().to_string()
            });
        self.store
            .mutate(&WorkspaceBlackboardMutation {
                scope,
                actor_id: context.user_id.clone(),
                action: action.to_string(),
                idempotency_key,
                payload_hash,
                expected_revision,
                aggregate_id: aggregate_id.to_string(),
                domain_write,
                response,
                event_type: event_type.to_string(),
                event_payload,
                receipt_authority: self.receipt_authority.clone(),
            })
            .await
            .map_err(Into::into)
    }
}
