//! PostgreSQL operation-store adapter for the cron worker core.

use agistack_adapters_postgres::{
    CronOperationFailure, CronOperationRecord, CronOperationScope, CronOperationStatus,
    PgCronOperationRepository,
};
use agistack_core::ports::CoreResult;
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::Value;

use super::{CronOperationHandlerFailure, CronOperationStore, CronWorkerScope};

impl CronWorkerScope {
    fn as_repository_scope(&self) -> CronOperationScope<'_> {
        CronOperationScope {
            tenant_id: &self.tenant_id,
            project_id: &self.project_id,
        }
    }
}

#[async_trait]
impl CronOperationStore for PgCronOperationRepository {
    async fn claim_due(
        &self,
        scope: &CronWorkerScope,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<CronOperationRecord>> {
        PgCronOperationRepository::claim_due(
            self,
            scope.as_repository_scope(),
            limit,
            lease_owner,
            lease_seconds,
            now,
        )
        .await
    }

    async fn complete(
        &self,
        scope: &CronWorkerScope,
        operation_id: &str,
        lease_owner: &str,
        lease_token: &str,
        result_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        PgCronOperationRepository::complete(
            self,
            scope.as_repository_scope(),
            operation_id,
            lease_owner,
            lease_token,
            result_json,
            now,
        )
        .await
        .map(|record| record.is_some())
    }

    async fn mark_waiting_runtime(
        &self,
        scope: &CronWorkerScope,
        operation_id: &str,
        lease_owner: &str,
        lease_token: &str,
        dispatch_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<CronOperationStatus>> {
        PgCronOperationRepository::mark_waiting_runtime(
            self,
            scope.as_repository_scope(),
            operation_id,
            lease_owner,
            lease_token,
            dispatch_json,
            now,
        )
        .await
        .map(|record| record.map(|record| record.status))
    }

    async fn fail(
        &self,
        scope: &CronWorkerScope,
        operation_id: &str,
        lease_owner: &str,
        lease_token: &str,
        failure: &CronOperationHandlerFailure,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<CronOperationStatus>> {
        PgCronOperationRepository::fail(
            self,
            scope.as_repository_scope(),
            operation_id,
            lease_owner,
            lease_token,
            CronOperationFailure::new(
                failure.code,
                &failure.redacted_text,
                failure.retry_after_seconds,
            ),
            now,
        )
        .await
        .map(|record| record.map(|record| record.status))
    }
}
