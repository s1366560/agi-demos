//! Replay-safe Workspace Plan idempotency reads.

use bcs_db_api::{DbStatement, DbStatementBuilder};

use crate::plan_records::{WorkspacePlanStoreError, replay_from_rows};
use crate::{
    WorkspacePlanScope, WorkspacePlanStore, WorkspacePlanTransition, WorkspacePlanTransitionOutcome,
};

impl WorkspacePlanStore<'_> {
    /// Read a prior idempotent result and reject key reuse for another request.
    ///
    /// # Errors
    ///
    /// Returns an idempotency, row-decoding, or database error.
    pub async fn replay(
        &self,
        scope: &WorkspacePlanScope,
        idempotency_key: &str,
        event_type: &str,
        request_hash: &str,
    ) -> Result<Option<WorkspacePlanTransitionOutcome>, WorkspacePlanStoreError> {
        let rows = self
            .db
            .query(self.replay_select(scope, idempotency_key))
            .await?;
        if rows.is_empty() {
            return Ok(None);
        }
        replay_from_rows(&rows, true, event_type, request_hash).map(Some)
    }

    pub(crate) async fn read_replay(
        &self,
        transition: &WorkspacePlanTransition,
    ) -> Result<Option<WorkspacePlanTransitionOutcome>, WorkspacePlanStoreError> {
        self.replay(
            &transition.scope,
            &transition.idempotency_key,
            transition.kind.event_type(),
            &transition.request_hash,
        )
        .await
    }

    pub(crate) fn replay_select(
        &self,
        scope: &WorkspacePlanScope,
        idempotency_key: &str,
    ) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT event_type, metadata_json FROM workspace_outbox WHERE tenant_id = ",
            )
            .bind(scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id.as_str())
            .push_static(" AND idempotency_key = ")
            .bind(idempotency_key)
            .build()
    }
}
