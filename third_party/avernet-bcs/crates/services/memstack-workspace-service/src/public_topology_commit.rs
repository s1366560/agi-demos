//! Atomic topology mutation preparation shared by node and edge use cases.

use memstack_workspace_store::{
    WorkspaceTopologyDomainWrite, WorkspaceTopologyMutation, WorkspaceTopologyMutationOutcome,
};
use serde::Serialize;
use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use uuid::Uuid;

use super::{
    PublicWorkspaceTopologyContext, PublicWorkspaceTopologyEdge, PublicWorkspaceTopologyError,
    PublicWorkspaceTopologyNode, PublicWorkspaceTopologyOutcome, PublicWorkspaceTopologyService,
    hash_payload, request_hash, topology_scope, validate_idempotency_key,
};

impl<'a> PublicWorkspaceTopologyService<'a> {
    pub(super) async fn commit_node(
        &self,
        context: &PublicWorkspaceTopologyContext,
        action: &str,
        domain_write: WorkspaceTopologyDomainWrite,
        response: PublicWorkspaceTopologyNode,
        event_payload: Value,
    ) -> Result<
        PublicWorkspaceTopologyOutcome<PublicWorkspaceTopologyNode>,
        PublicWorkspaceTopologyError,
    > {
        let aggregate_id = response.id.clone();
        self.commit_typed(
            context,
            action,
            aggregate_id.as_str(),
            domain_write,
            response,
            event_payload,
        )
        .await
    }

    pub(super) async fn commit_edge(
        &self,
        context: &PublicWorkspaceTopologyContext,
        action: &str,
        domain_write: WorkspaceTopologyDomainWrite,
        response: PublicWorkspaceTopologyEdge,
        event_payload: Value,
    ) -> Result<
        PublicWorkspaceTopologyOutcome<PublicWorkspaceTopologyEdge>,
        PublicWorkspaceTopologyError,
    > {
        let aggregate_id = response.id.clone();
        self.commit_typed(
            context,
            action,
            aggregate_id.as_str(),
            domain_write,
            response,
            event_payload,
        )
        .await
    }

    async fn commit_typed<T>(
        &self,
        context: &PublicWorkspaceTopologyContext,
        action: &str,
        aggregate_id: &str,
        domain_write: WorkspaceTopologyDomainWrite,
        response: T,
        event_payload: Value,
    ) -> Result<PublicWorkspaceTopologyOutcome<T>, PublicWorkspaceTopologyError>
    where
        T: Serialize + DeserializeOwned,
    {
        let outcome = self
            .commit_value(
                context,
                action,
                aggregate_id,
                domain_write,
                serde_json::to_value(response)?,
                event_payload,
            )
            .await?;
        Ok(PublicWorkspaceTopologyOutcome {
            value: serde_json::from_value(outcome.response)?,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    pub(super) async fn commit_value(
        &self,
        context: &PublicWorkspaceTopologyContext,
        action: &str,
        aggregate_id: &str,
        domain_write: WorkspaceTopologyDomainWrite,
        response: Value,
        event_payload: Value,
    ) -> Result<WorkspaceTopologyMutationOutcome, PublicWorkspaceTopologyError> {
        let scope = topology_scope(context);
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
            .mutate(&WorkspaceTopologyMutation {
                scope,
                actor_id: context.user_id.clone(),
                action: action.to_string(),
                idempotency_key,
                payload_hash,
                expected_revision,
                aggregate_id: aggregate_id.to_string(),
                domain_write,
                response,
                event_payload,
                receipt_authority: self.receipt_authority.clone(),
            })
            .await
            .map_err(Into::into)
    }
}

pub(super) fn outcome_value(
    outcome: WorkspaceTopologyMutationOutcome,
) -> PublicWorkspaceTopologyOutcome<Value> {
    PublicWorkspaceTopologyOutcome {
        value: outcome.response,
        committed_revision: outcome.committed_revision,
        outbox_id: outcome.outbox_id,
        replayed: outcome.replayed,
    }
}
