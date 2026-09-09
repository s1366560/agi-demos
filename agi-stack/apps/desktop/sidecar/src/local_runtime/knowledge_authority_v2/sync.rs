use agistack_core::knowledge::sync::graph::{
    GraphPullReceipt, KnowledgeGraphPullRepository, KnowledgeGraphPushReceipt,
    KnowledgeGraphPushRepository, KnowledgeGraphSyncReadRepository, SyncedGraphProjection,
};
use agistack_core::knowledge::sync::graph_resolution::{
    GraphPullConflictContext, GraphPullConflictResolution, GraphResolutionOutcome,
    KnowledgeGraphResolutionRepository,
};
use agistack_core::knowledge::sync::pull::{KnowledgePullReceipt, KnowledgePullRepository};
use agistack_core::knowledge::sync::resolution::{
    KnowledgePullConflictContext, KnowledgePullConflictResolution, KnowledgeResolutionOutcome,
    KnowledgeResolutionRepository,
};
use agistack_core::knowledge::sync::{
    KnowledgeSyncLink, KnowledgeSyncOutboxChange, KnowledgeSyncRepository, KnowledgeSyncStatus,
    KnowledgeUnbindPolicy,
};

use super::{KnowledgeAuthorityErrorV2, KnowledgeOperationV2};
use crate::local_runtime::auth_context::AuthenticatedContext;
use crate::local_runtime::LocalRuntimeState;
use crate::trusted_session::TrustedSessionBroker;
use agistack_core::knowledge::sync::push::{KnowledgePushReceipt, KnowledgePushRepository};

#[path = "cloud_sync.rs"]
mod cloud_sync;
pub(super) use cloud_sync::CloudResolutionDispatch;

impl KnowledgeOperationV2 {
    async fn connect_sync_transport(
        &self,
        broker: &TrustedSessionBroker,
        link: KnowledgeSyncLink,
    ) -> Result<super::sync_transport::VerifiedCloudTransport, KnowledgeAuthorityErrorV2> {
        self.authority.require_sync_release()?;
        let transport =
            super::sync_transport::VerifiedCloudTransport::connect(broker, link).await?;
        let descriptor = &transport.generation.descriptor;
        self.authority.require_sync_cloud_profile(
            &descriptor.profile_id,
            descriptor.generation,
            &descriptor.digest,
        )?;
        transport.with_current_session(|| {
            Ok(self
                .authority
                .repository()?
                .require_verified_sync_target_durable(&self.scope, &transport.target)?)
        })?;
        Ok(transport)
    }

    pub(super) async fn resolve_pull_conflicts(
        &self,
        broker: &TrustedSessionBroker,
        key: &str,
        resolution: KnowledgePullConflictResolution,
    ) -> Result<KnowledgeResolutionOutcome, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        let repository = self.authority.repository()?;
        let link = repository
            .sync_status(&self.scope)
            .await?
            .link
            .ok_or(KnowledgeAuthorityErrorV2::ScopeMismatch)?;
        let transport = self.connect_sync_transport(broker, link).await?;
        transport.with_current_session(|| {
            Ok(repository.resolve_pull_conflicts_durable(
                &self.scope,
                &transport.target,
                &self.actor_id,
                key,
                resolution,
            )?)
        })
    }

    pub(super) async fn pull_conflict_context(
        &self,
        id: &str,
    ) -> Result<Option<KnowledgePullConflictContext>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .pull_conflict_context(&self.scope, id)
            .await?)
    }

    pub(super) async fn resolution_history(
        &self,
        id: &str,
        limit: usize,
    ) -> Result<Vec<serde_json::Value>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .resolution_history(&self.scope, id, limit)
            .await?)
    }

    pub(super) async fn pull_once(
        &self,
        broker: &TrustedSessionBroker,
    ) -> Result<KnowledgePullReceipt, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        let repository = self.authority.repository()?;
        let link = repository
            .sync_status(&self.scope)
            .await?
            .link
            .ok_or(KnowledgeAuthorityErrorV2::ScopeMismatch)?;
        let transport = self.connect_sync_transport(broker, link).await?;
        let after = repository
            .pull_cursor(&self.scope, &transport.target)
            .await?;
        let response = transport.pull(after).await?;
        transport.with_current_session(|| {
            Ok(repository.accept_pull_page_durable(
                &self.scope,
                &transport.target,
                after,
                response,
            )?)
        })
    }

    pub(super) async fn pull_conflicts(
        &self,
        limit: usize,
    ) -> Result<Vec<serde_json::Value>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .pull_conflicts(&self.scope, limit)
            .await?)
    }

    pub(super) async fn push_once(
        &self,
        broker: &TrustedSessionBroker,
    ) -> Result<Option<KnowledgePushReceipt>, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        let repository = self.authority.repository()?;
        let link = repository
            .sync_status(&self.scope)
            .await?
            .link
            .ok_or(KnowledgeAuthorityErrorV2::ScopeMismatch)?;
        let transport = self.connect_sync_transport(broker, link).await?;
        let Some(prepared) = repository
            .prepare_push(&self.scope, &transport.target)
            .await?
        else {
            return Ok(None);
        };
        let (response, conflict) = transport.push(&prepared).await?;
        transport.with_current_session(|| {
            Ok(Some(repository.accept_push_receipt_durable(
                &self.scope,
                &transport.target,
                prepared.local_sequence,
                response,
                conflict,
            )?))
        })
    }

    pub(super) async fn graph_push_once(
        &self,
        broker: &TrustedSessionBroker,
    ) -> Result<Option<KnowledgeGraphPushReceipt>, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        let repository = self.authority.repository()?;
        let link = repository
            .sync_status(&self.scope)
            .await?
            .link
            .ok_or(KnowledgeAuthorityErrorV2::ScopeMismatch)?;
        let transport = self.connect_sync_transport(broker, link).await?;
        let Some(prepared) = repository
            .prepare_graph_push(&self.scope, &transport.target)
            .await?
        else {
            return Ok(None);
        };
        let (response, conflict) = transport.graph_push(&prepared).await?;
        transport.with_current_session(|| {
            Ok(Some(repository.accept_graph_push_receipt_durable(
                &self.scope,
                &transport.target,
                prepared.local_sequence,
                response,
                conflict,
            )?))
        })
    }

    pub(super) async fn graph_pull_once(
        &self,
        broker: &TrustedSessionBroker,
    ) -> Result<GraphPullReceipt, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        let repository = self.authority.repository()?;
        let link = repository
            .sync_status(&self.scope)
            .await?
            .link
            .ok_or(KnowledgeAuthorityErrorV2::ScopeMismatch)?;
        let transport = self.connect_sync_transport(broker, link).await?;
        let after = repository
            .graph_pull_cursor(&self.scope, &transport.target)
            .await?;
        let response = transport.graph_pull(after).await?;
        transport.with_current_session(|| {
            Ok(repository.accept_graph_pull_page_durable(
                &self.scope,
                &transport.target,
                after,
                response,
            )?)
        })
    }

    pub(super) async fn graph_pull_conflicts(
        &self,
        limit: usize,
    ) -> Result<Vec<serde_json::Value>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .graph_pull_conflicts(&self.scope, limit)
            .await?)
    }

    pub(super) async fn graph_push_conflicts(
        &self,
        limit: usize,
    ) -> Result<Vec<serde_json::Value>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .graph_push_conflicts(&self.scope, limit)
            .await?)
    }

    pub(super) async fn graph_pull_conflict_context(
        &self,
        id: &str,
    ) -> Result<Option<GraphPullConflictContext>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .graph_pull_conflict_context(&self.scope, id)
            .await?)
    }

    pub(super) async fn graph_resolution_history(
        &self,
        id: &str,
        limit: usize,
    ) -> Result<Vec<serde_json::Value>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .graph_resolution_history(&self.scope, id, limit)
            .await?)
    }

    pub(super) async fn remote_graph_baseline(
        &self,
        id: &str,
    ) -> Result<Option<serde_json::Value>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .remote_graph_baseline(&self.scope, id)
            .await?)
    }

    pub(super) async fn synced_graph_projection(
        &self,
        id: &str,
    ) -> Result<Option<SyncedGraphProjection>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .synced_graph_projection(&self.scope, id)
            .await?)
    }

    pub(super) async fn synced_graph_projections(
        &self,
        limit: usize,
        offset: usize,
    ) -> Result<Vec<SyncedGraphProjection>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .synced_graph_projections(&self.scope, limit, offset)
            .await?)
    }

    pub(super) async fn resolve_graph_pull_conflicts(
        &self,
        broker: &TrustedSessionBroker,
        key: &str,
        resolution: GraphPullConflictResolution,
    ) -> Result<GraphResolutionOutcome, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        let repository = self.authority.repository()?;
        let link = repository
            .sync_status(&self.scope)
            .await?
            .link
            .ok_or(KnowledgeAuthorityErrorV2::ScopeMismatch)?;
        let transport = self.connect_sync_transport(broker, link).await?;
        transport.with_current_session(|| {
            Ok(repository.resolve_graph_pull_conflicts_durable(
                &self.scope,
                &transport.target,
                &self.actor_id,
                key,
                resolution,
            )?)
        })
    }

    /// Resolve a cloud-detected graph push conflict: the cloud decides with a
    /// revision re-check, then the durable local settle verifies the receipt
    /// against the paused push before any local state moves.
    pub(super) async fn resolve_graph_push(
        &self,
        broker: &TrustedSessionBroker,
        request: super::contracts::GraphResolvePushRequest,
    ) -> Result<serde_json::Value, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        if !matches!(
            request.decision.as_str(),
            "keep_current" | "use_proposed" | "merged" | "keep_both"
        ) || request.expected_current_revision < 0.0
            || request.expected_current_revision > i32::MAX as f64
            || request.expected_current_revision.fract() != 0.0
            || (request.decision == "merged") != request.content.is_some()
        {
            return Err(KnowledgeAuthorityErrorV2::Knowledge(
                agistack_core::knowledge::KnowledgeError::InvalidInput,
            ));
        }
        let repository = self.authority.repository()?;
        let link = repository
            .sync_status(&self.scope)
            .await?
            .link
            .ok_or(KnowledgeAuthorityErrorV2::ScopeMismatch)?;
        let transport = self.connect_sync_transport(broker, link).await?;
        // A conflict lookup first: the cloud resolve body is only sent for a
        // conflict the cloud still reports for this actor.
        let conflict = transport.graph_conflict(&request.conflict_id).await?;
        if conflict["resolved_change_id"].is_string() {
            return Err(KnowledgeAuthorityErrorV2::RemoteRejected);
        }
        let body = serde_json::json!({
            "change_id": request.change_id,
            "expected_current_revision": request.expected_current_revision as u64,
            "decision": request.decision,
            "content": request.content,
        });
        let response = transport
            .graph_resolve(&request.conflict_id, body)
            .await?;
        let receipt = transport.with_current_session(|| {
            Ok(repository.settle_graph_push_resolution_durable(
                &self.scope,
                &transport.target,
                &request.conflict_id,
                &request.change_id,
                &request.decision,
                response,
            )?)
        })?;
        Ok(serde_json::json!({"receipt": receipt, "replayed": false}))
    }

    pub(super) async fn remote_baseline(
        &self,
        id: &str,
    ) -> Result<Option<serde_json::Value>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .remote_baseline(&self.scope, id)
            .await?)
    }

    pub(super) async fn push_conflicts(
        &self,
        limit: usize,
    ) -> Result<Vec<serde_json::Value>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .push_conflicts(&self.scope, limit)
            .await?)
    }
    pub(super) async fn sync_status(
        &self,
    ) -> Result<KnowledgeSyncStatus, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .sync_status(&self.scope)
            .await?)
    }

    pub(super) async fn configure_sync_link(
        &self,
        link: KnowledgeSyncLink,
    ) -> Result<KnowledgeSyncStatus, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        Ok(self
            .authority
            .repository()?
            .configure_sync_link(&self.scope, link)
            .await?)
    }

    /// Local-only unbind: fencing, the explicit keep/delete choice, and the
    /// association removal commit atomically while the caller's session,
    /// membership, and generation fences are held through commit. No cloud
    /// operation is attempted and downloaded copies are never wiped remotely.
    pub(super) async fn sync_unbind(
        &self,
        state: &LocalRuntimeState,
        auth: &AuthenticatedContext,
        policy: KnowledgeUnbindPolicy,
    ) -> Result<serde_json::Value, KnowledgeAuthorityErrorV2> {
        self.authority.require_sync_release()?;
        let repository = self.authority.repository()?;
        let receipt = super::processing_context::with_read_current_checked(
            self,
            state,
            auth,
            true,
            |_| Ok(()),
            |clock| repository.unbind_sync_target_durable(&self.scope, policy, clock()?),
        )?;
        Ok(serde_json::json!({
            "status": repository.sync_status(&self.scope).await?,
            "association_state": "unbound",
            "policy": policy,
            "fenced_outbox": receipt.fenced_outbox,
            "removed_local_copies": receipt.removed_local_copies,
        }))
    }

    pub(super) async fn sync_outbox(
        &self,
        after_sequence: u64,
        limit: usize,
    ) -> Result<Vec<KnowledgeSyncOutboxChange>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .sync_outbox(&self.scope, after_sequence, limit)
            .await?)
    }
}
