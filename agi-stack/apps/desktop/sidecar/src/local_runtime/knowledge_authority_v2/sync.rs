use agistack_core::knowledge::sync::pull::{KnowledgePullReceipt, KnowledgePullRepository};
use agistack_core::knowledge::sync::resolution::{
    KnowledgePullConflictContext, KnowledgePullConflictResolution, KnowledgeResolutionOutcome,
    KnowledgeResolutionRepository,
};
use agistack_core::knowledge::sync::{
    KnowledgeSyncLink, KnowledgeSyncOutboxChange, KnowledgeSyncRepository, KnowledgeSyncStatus,
};

use super::{KnowledgeAuthorityErrorV2, KnowledgeOperationV2};
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
