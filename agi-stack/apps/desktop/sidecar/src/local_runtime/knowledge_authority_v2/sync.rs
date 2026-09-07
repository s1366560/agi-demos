use agistack_core::knowledge::sync::{
    KnowledgeSyncLink, KnowledgeSyncOutboxChange, KnowledgeSyncRepository, KnowledgeSyncStatus,
};

use super::{KnowledgeAuthorityErrorV2, KnowledgeOperationV2};

impl KnowledgeOperationV2 {
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
