use agistack_core::knowledge::sync::{
    KnowledgeSyncLink, KnowledgeSyncOutboxChange, KnowledgeSyncRepository, KnowledgeSyncStatus,
};

use super::{KnowledgeAuthorityErrorV2, KnowledgeOperationV2};
use crate::trusted_session::TrustedSessionBroker;
use agistack_core::knowledge::sync::push::{KnowledgePushReceipt, KnowledgePushRepository};

impl KnowledgeOperationV2 {
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
        let transport =
            super::sync_transport::VerifiedCloudTransport::connect(broker, link).await?;
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
