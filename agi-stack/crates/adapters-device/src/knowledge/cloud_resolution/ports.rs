use super::*;

#[async_trait]
impl KnowledgeCloudResolutionRepository for SqliteKnowledgeRepository {
    async fn cloud_resolution_by_key(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        key: &str,
    ) -> KnowledgeResult<Option<KnowledgeCloudResolutionRecord>> {
        self.cloud_resolution_by_key_durable(scope, target, actor, key)
    }
    async fn cloud_conflict_snapshot(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        sequence: u64,
    ) -> KnowledgeResult<Value> {
        self.cloud_conflict_snapshot_durable(scope, target, sequence)
    }
    async fn cloud_conflict_context(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        sequence: u64,
        verified: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionContext> {
        self.cloud_conflict_context_durable(scope, target, sequence, verified)
    }
    async fn prepare_cloud_resolution(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        key: &str,
        command: KnowledgeCloudResolutionCommand,
        verified: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionRecord> {
        self.prepare_cloud_resolution_durable(scope, target, actor, key, command, verified)
    }
    async fn cloud_resolution_record(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        id: &str,
    ) -> KnowledgeResult<KnowledgeCloudResolutionRecord> {
        self.cloud_resolution_record_durable(scope, target, actor, id)
    }
    async fn cloud_resolution_records(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        limit: usize,
    ) -> KnowledgeResult<Vec<KnowledgeCloudResolutionRecord>> {
        self.cloud_resolution_records_durable(scope, target, actor, limit)
    }
    async fn accept_cloud_resolution_receipt(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        id: &str,
        response: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionOutcome> {
        self.accept_cloud_resolution_receipt_durable(scope, target, actor, id, response)
    }
    async fn reject_cloud_resolution_stale(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        id: &str,
        response: Value,
    ) -> KnowledgeResult<KnowledgeCloudResolutionRecord> {
        self.reject_cloud_resolution_stale_durable(scope, target, actor, id, response)
    }
    async fn cloud_reconciliation_context(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        id: &str,
    ) -> KnowledgeResult<KnowledgeCloudResolutionContext> {
        self.cloud_reconciliation_context_durable(scope, target, actor, id)
    }
    async fn reconcile_cloud_resolution(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        id: &str,
        command: KnowledgeCloudReconciliationCommand,
    ) -> KnowledgeResult<KnowledgeCloudResolutionOutcome> {
        self.reconcile_cloud_resolution_durable(scope, target, actor, id, command)
    }
}
