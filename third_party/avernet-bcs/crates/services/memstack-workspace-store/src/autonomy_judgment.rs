//! Durable fencing and independent audit persistence for Workspace Autonomy judgments.

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep,
};
use serde_json::Value;
use thiserror::Error;

use crate::{WorkspaceAutonomyJudgmentAudit, WorkspaceAutonomyScope};

const MAX_CLAIM_ID_CHARS: usize = 191;
const MAX_ACTOR_ID_CHARS: usize = 256;
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;
const MAX_WORKER_ID_CHARS: usize = 191;
const MAX_ERROR_DETAIL_CHARS: usize = 256;

/// Request for one idempotent, fenced semantic judgment claim.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyJudgmentClaimRequest {
    pub claim_id: String,
    pub scope: WorkspaceAutonomyScope,
    pub actor_id: String,
    pub idempotency_key: String,
    pub request_hash: String,
    pub expected_revision: u64,
    pub worker_id: String,
    pub now_ms: i64,
    pub lease_expires_at_ms: i64,
}

/// Exact lease generation owned by one Judge caller.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyJudgmentLease {
    pub claim_id: String,
    pub worker_id: String,
    pub lease_generation: i64,
    pub lease_expires_at_ms: i64,
}

/// Recoverable validated judgment snapshot that has not yet been applied.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceAutonomyJudgedSnapshot {
    pub claim_id: String,
    pub lease_generation: i64,
    pub audit_id: String,
    pub judgment: Value,
}

/// Result of attempting to claim one deterministic judgment key.
#[derive(Debug, Clone, PartialEq)]
pub enum WorkspaceAutonomyJudgmentClaimOutcome {
    Claimed(WorkspaceAutonomyJudgmentLease),
    Busy,
    Judged(WorkspaceAutonomyJudgedSnapshot),
    Applied,
    Superseded,
}

/// Claim identity included in the atomic tick mutation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyJudgmentApply {
    pub claim_id: String,
    pub audit_id: String,
    pub lease_generation: i64,
    pub applied_at_ms: i64,
}

/// Stable judgment-claim persistence failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceAutonomyJudgmentStoreError {
    #[error("invalid Workspace Autonomy judgment claim")]
    InvalidClaim,
    #[error("Workspace Autonomy judgment idempotency key conflicts with the stored request")]
    IdempotencyConflict,
    #[error("Workspace Autonomy judgment lease was lost")]
    LeaseLost,
    #[error("persisted Workspace Autonomy judgment claim is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite judgment claim and audit repository.
pub struct WorkspaceAutonomyJudgmentStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceAutonomyJudgmentStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Win a fresh or expired claim before invoking the semantic Judge.
    pub async fn claim(
        &self,
        request: &WorkspaceAutonomyJudgmentClaimRequest,
    ) -> Result<WorkspaceAutonomyJudgmentClaimOutcome, WorkspaceAutonomyJudgmentStoreError> {
        validate_claim_request(request)?;
        let inserted = self.db.execute(claim_insert(self.flavor, request)).await?;
        if inserted.affected_rows == 1 {
            return Ok(WorkspaceAutonomyJudgmentClaimOutcome::Claimed(
                WorkspaceAutonomyJudgmentLease {
                    claim_id: request.claim_id.clone(),
                    worker_id: request.worker_id.clone(),
                    lease_generation: 1,
                    lease_expires_at_ms: request.lease_expires_at_ms,
                },
            ));
        }
        self.claim_existing(request).await
    }

    /// Persist the complete tool-call audit independently from the later tick CAS.
    pub async fn record_audit(
        &self,
        scope: &WorkspaceAutonomyScope,
        audit: &WorkspaceAutonomyJudgmentAudit,
    ) -> Result<(), WorkspaceAutonomyJudgmentStoreError> {
        let result = self
            .db
            .execute(audit_insert(self.flavor, scope, audit))
            .await?;
        if result.affected_rows == 1 {
            Ok(())
        } else {
            Err(WorkspaceAutonomyJudgmentStoreError::InvalidRecord(
                "audit insert",
            ))
        }
    }

    /// Attach a validated snapshot to the exact still-owned lease.
    pub async fn mark_judged(
        &self,
        lease: &WorkspaceAutonomyJudgmentLease,
        audit_id: &str,
        judgment: &Value,
        judged_at_ms: i64,
    ) -> Result<WorkspaceAutonomyJudgedSnapshot, WorkspaceAutonomyJudgmentStoreError> {
        if audit_id.trim().is_empty()
            || judgment.is_null()
            || judged_at_ms < 0
            || judged_at_ms > lease.lease_expires_at_ms
        {
            return Err(WorkspaceAutonomyJudgmentStoreError::InvalidClaim);
        }
        let result = self
            .db
            .execute(mark_judged_statement(
                self.flavor,
                lease,
                audit_id,
                judgment,
                judged_at_ms,
            ))
            .await?;
        if result.affected_rows != 1 {
            return Err(WorkspaceAutonomyJudgmentStoreError::LeaseLost);
        }
        Ok(WorkspaceAutonomyJudgedSnapshot {
            claim_id: lease.claim_id.clone(),
            lease_generation: lease.lease_generation,
            audit_id: audit_id.to_string(),
            judgment: judgment.clone(),
        })
    }

    /// Persist a failed Judge generation while retaining its independent audit.
    pub async fn mark_failed(
        &self,
        lease: &WorkspaceAutonomyJudgmentLease,
        audit_id: &str,
        error_detail: &str,
        failed_at_ms: i64,
    ) -> Result<(), WorkspaceAutonomyJudgmentStoreError> {
        validate_error_detail(audit_id, error_detail, failed_at_ms)?;
        let result = self
            .db
            .execute(mark_failed_statement(
                self.flavor,
                lease,
                audit_id,
                error_detail,
                failed_at_ms,
            ))
            .await?;
        if result.affected_rows == 1 {
            Ok(())
        } else {
            Err(WorkspaceAutonomyJudgmentStoreError::LeaseLost)
        }
    }

    /// Mark an audit whose lease was lost without deleting the completed call record.
    pub async fn update_audit_status(
        &self,
        audit_id: &str,
        status: &str,
        error_detail: Option<&str>,
    ) -> Result<(), WorkspaceAutonomyJudgmentStoreError> {
        if audit_id.trim().is_empty()
            || !matches!(status, "judged" | "completed" | "failed" | "superseded")
            || error_detail.is_some_and(|value| {
                value.trim().is_empty() || value.chars().count() > MAX_ERROR_DETAIL_CHARS
            })
        {
            return Err(WorkspaceAutonomyJudgmentStoreError::InvalidClaim);
        }
        let result = self
            .db
            .execute(audit_status_update(
                self.flavor,
                audit_id,
                status,
                error_detail,
            ))
            .await?;
        if result.affected_rows == 1 {
            Ok(())
        } else {
            Err(WorkspaceAutonomyJudgmentStoreError::InvalidRecord(
                "audit status",
            ))
        }
    }

    /// Fence a judged snapshot after its authority CAS loses to another mutation.
    pub async fn mark_superseded(
        &self,
        snapshot: &WorkspaceAutonomyJudgedSnapshot,
        error_detail: &str,
        superseded_at_ms: i64,
    ) -> Result<(), WorkspaceAutonomyJudgmentStoreError> {
        validate_error_detail(snapshot.audit_id.as_str(), error_detail, superseded_at_ms)?;
        self.db
            .transaction(vec![
                DbTransactionStep::execute_checked(
                    mark_superseded_statement(
                        self.flavor,
                        snapshot,
                        error_detail,
                        superseded_at_ms,
                    ),
                    DbCountExpectation::exactly(1),
                ),
                DbTransactionStep::execute_checked(
                    audit_status_update(
                        self.flavor,
                        snapshot.audit_id.as_str(),
                        "superseded",
                        Some(error_detail),
                    ),
                    DbCountExpectation::exactly(1),
                ),
            ])
            .await
            .map_err(|error| {
                if matches!(error, DbError::TransactionExpectation { .. }) {
                    WorkspaceAutonomyJudgmentStoreError::LeaseLost
                } else {
                    error.into()
                }
            })?;
        Ok(())
    }

    async fn claim_existing(
        &self,
        request: &WorkspaceAutonomyJudgmentClaimRequest,
    ) -> Result<WorkspaceAutonomyJudgmentClaimOutcome, WorkspaceAutonomyJudgmentStoreError> {
        let rows = self
            .db
            .query(claim_lookup(self.flavor, request.claim_id.as_str()))
            .await?;
        let row = rows
            .first()
            .ok_or(WorkspaceAutonomyJudgmentStoreError::InvalidRecord(
                "claim_id",
            ))?;
        if required_string(row, "request_hash")? != request.request_hash
            || required_i64(row, "expected_revision")?
                != i64::try_from(request.expected_revision)
                    .map_err(|_| WorkspaceAutonomyJudgmentStoreError::InvalidClaim)?
        {
            return Err(WorkspaceAutonomyJudgmentStoreError::IdempotencyConflict);
        }
        let status = required_string(row, "status")?;
        let generation = required_i64(row, "lease_generation")?;
        match status.as_str() {
            "processing" => {
                let expires_at = required_i64(row, "lease_expires_at_ms")?;
                if expires_at > request.now_ms {
                    return Ok(WorkspaceAutonomyJudgmentClaimOutcome::Busy);
                }
                self.reclaim(request, generation).await
            }
            "failed" => self.reclaim(request, generation).await,
            "judged" => Ok(WorkspaceAutonomyJudgmentClaimOutcome::Judged(
                judged_snapshot_from_row(row)?,
            )),
            "applied" => Ok(WorkspaceAutonomyJudgmentClaimOutcome::Applied),
            "superseded" => Ok(WorkspaceAutonomyJudgmentClaimOutcome::Superseded),
            _ => Err(WorkspaceAutonomyJudgmentStoreError::InvalidRecord("status")),
        }
    }

    async fn reclaim(
        &self,
        request: &WorkspaceAutonomyJudgmentClaimRequest,
        previous_generation: i64,
    ) -> Result<WorkspaceAutonomyJudgmentClaimOutcome, WorkspaceAutonomyJudgmentStoreError> {
        let rows = self
            .db
            .query(reclaim_statement(self.flavor, request, previous_generation))
            .await?;
        let Some(row) = rows.first() else {
            return Ok(WorkspaceAutonomyJudgmentClaimOutcome::Busy);
        };
        Ok(WorkspaceAutonomyJudgmentClaimOutcome::Claimed(
            WorkspaceAutonomyJudgmentLease {
                claim_id: request.claim_id.clone(),
                worker_id: request.worker_id.clone(),
                lease_generation: required_i64(row, "lease_generation")?,
                lease_expires_at_ms: request.lease_expires_at_ms,
            },
        ))
    }
}

fn validate_claim_request(
    request: &WorkspaceAutonomyJudgmentClaimRequest,
) -> Result<(), WorkspaceAutonomyJudgmentStoreError> {
    let expected_revision = i64::try_from(request.expected_revision)
        .map_err(|_| WorkspaceAutonomyJudgmentStoreError::InvalidClaim)?;
    if request.claim_id.trim().is_empty()
        || request.claim_id.chars().count() > MAX_CLAIM_ID_CHARS
        || request.actor_id.trim().is_empty()
        || request.actor_id.chars().count() > MAX_ACTOR_ID_CHARS
        || request.idempotency_key.trim().is_empty()
        || request.idempotency_key.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS
        || request.request_hash.len() != 64
        || request.worker_id.trim().is_empty()
        || request.worker_id.chars().count() > MAX_WORKER_ID_CHARS
        || request.now_ms < 0
        || request.lease_expires_at_ms <= request.now_ms
        || expected_revision < 0
        || [
            request.scope.tenant_id.as_str(),
            request.scope.project_id.as_str(),
            request.scope.workspace_id.as_str(),
        ]
        .iter()
        .any(|value| value.trim().is_empty())
    {
        return Err(WorkspaceAutonomyJudgmentStoreError::InvalidClaim);
    }
    Ok(())
}

fn validate_error_detail(
    audit_id: &str,
    error_detail: &str,
    occurred_at_ms: i64,
) -> Result<(), WorkspaceAutonomyJudgmentStoreError> {
    if audit_id.trim().is_empty()
        || error_detail.trim().is_empty()
        || error_detail.chars().count() > MAX_ERROR_DETAIL_CHARS
        || occurred_at_ms < 0
    {
        return Err(WorkspaceAutonomyJudgmentStoreError::InvalidClaim);
    }
    Ok(())
}

fn claim_insert(
    flavor: DbSqlFlavor,
    request: &WorkspaceAutonomyJudgmentClaimRequest,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_autonomy_judgment_claims (claim_id, tenant_id, project_id, \
             workspace_id, actor_id, idempotency_key, request_hash, expected_revision, status, \
             lease_owner, lease_expires_at_ms, lease_generation, created_at_ms, updated_at_ms) \
             VALUES (",
        )
        .bind(request.claim_id.as_str())
        .push_static(", ")
        .bind(request.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(request.scope.project_id.as_str())
        .push_static(", ")
        .bind(request.scope.workspace_id.as_str())
        .push_static(", ")
        .bind(request.actor_id.as_str())
        .push_static(", ")
        .bind(request.idempotency_key.as_str())
        .push_static(", ")
        .bind(request.request_hash.as_str())
        .push_static(", ")
        .bind(request.expected_revision)
        .push_static(", 'processing', ")
        .bind(request.worker_id.as_str())
        .push_static(", ")
        .bind(request.lease_expires_at_ms)
        .push_static(", 1, ")
        .bind(request.now_ms)
        .push_static(", ")
        .bind(request.now_ms)
        .push_static(")");
    match flavor {
        DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
            .push_static(" ON CONFLICT(claim_id) DO NOTHING")
            .build(),
        DbSqlFlavor::Mysql => builder.build(),
    }
}

fn claim_lookup(flavor: DbSqlFlavor, claim_id: &str) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT claim_id, request_hash, expected_revision, status, lease_expires_at_ms, \
             lease_generation, audit_id, judgment_json FROM \
             workspace_autonomy_judgment_claims WHERE claim_id = ",
        )
        .bind(claim_id)
        .build()
}

fn reclaim_statement(
    flavor: DbSqlFlavor,
    request: &WorkspaceAutonomyJudgmentClaimRequest,
    previous_generation: i64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_judgment_claims SET status = 'processing', \
             lease_owner = ",
        )
        .bind(request.worker_id.as_str())
        .push_static(", lease_expires_at_ms = ")
        .bind(request.lease_expires_at_ms)
        .push_static(
            ", lease_generation = lease_generation + 1, audit_id = NULL, judgment_json = NULL, \
             error_detail = NULL, updated_at_ms = ",
        )
        .bind(request.now_ms)
        .push_static(", judged_at_ms = NULL WHERE claim_id = ")
        .bind(request.claim_id.as_str())
        .push_static(" AND request_hash = ")
        .bind(request.request_hash.as_str())
        .push_static(" AND lease_generation = ")
        .bind(previous_generation)
        .push_static(
            " AND (status = 'failed' OR (status = 'processing' AND lease_expires_at_ms <= ",
        )
        .bind(request.now_ms)
        .push_static(")) RETURNING lease_generation")
        .build()
}

fn audit_insert(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    audit: &WorkspaceAutonomyJudgmentAudit,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_judge_audits (audit_id, tenant_id, project_id, workspace_id, \
             judgment_type, agent_id, tool_name, input_json, output_json, rationale, latency_ms, \
             status, error_detail, created_at) VALUES (",
        )
        .bind(audit.audit_id.as_str())
        .push_static(", ")
        .bind(scope.tenant_id.as_str())
        .push_static(", ")
        .bind(scope.project_id.as_str())
        .push_static(", ")
        .bind(scope.workspace_id.as_str())
        .push_static(", 'autonomy_tick', ")
        .bind(audit.agent_id.as_str())
        .push_static(", ")
        .bind(audit.tool_name.as_str())
        .push_static(", ")
        .bind(audit.input.to_string())
        .push_static(", ")
        .bind(audit.output.to_string())
        .push_static(", ")
        .bind(audit.rationale.as_str())
        .push_static(", ")
        .bind(audit.latency_ms)
        .push_static(", ")
        .bind(audit.status.as_str())
        .push_static(", ")
        .bind(audit.error_detail.clone())
        .push_static(", ")
        .bind(audit.created_at.as_str())
        .push_static(")")
        .build()
}

fn mark_judged_statement(
    flavor: DbSqlFlavor,
    lease: &WorkspaceAutonomyJudgmentLease,
    audit_id: &str,
    judgment: &Value,
    judged_at_ms: i64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_autonomy_judgment_claims SET status = 'judged', audit_id = ")
        .bind(audit_id)
        .push_static(", judgment_json = ")
        .bind(judgment.to_string())
        .push_static(", lease_owner = NULL, lease_expires_at_ms = NULL, updated_at_ms = ")
        .bind(judged_at_ms)
        .push_static(", judged_at_ms = ")
        .bind(judged_at_ms)
        .push_static(" WHERE claim_id = ")
        .bind(lease.claim_id.as_str())
        .push_static(" AND status = 'processing' AND lease_owner = ")
        .bind(lease.worker_id.as_str())
        .push_static(" AND lease_generation = ")
        .bind(lease.lease_generation)
        .push_static(" AND lease_expires_at_ms = ")
        .bind(lease.lease_expires_at_ms)
        .build()
}

fn mark_failed_statement(
    flavor: DbSqlFlavor,
    lease: &WorkspaceAutonomyJudgmentLease,
    audit_id: &str,
    error_detail: &str,
    failed_at_ms: i64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_autonomy_judgment_claims SET status = 'failed', audit_id = ")
        .bind(audit_id)
        .push_static(", judgment_json = NULL, error_detail = ")
        .bind(error_detail)
        .push_static(", lease_owner = NULL, lease_expires_at_ms = NULL, updated_at_ms = ")
        .bind(failed_at_ms)
        .push_static(" WHERE claim_id = ")
        .bind(lease.claim_id.as_str())
        .push_static(" AND status = 'processing' AND lease_owner = ")
        .bind(lease.worker_id.as_str())
        .push_static(" AND lease_generation = ")
        .bind(lease.lease_generation)
        .push_static(" AND lease_expires_at_ms = ")
        .bind(lease.lease_expires_at_ms)
        .build()
}

fn mark_superseded_statement(
    flavor: DbSqlFlavor,
    snapshot: &WorkspaceAutonomyJudgedSnapshot,
    error_detail: &str,
    superseded_at_ms: i64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_judgment_claims SET status = 'superseded', \
             judgment_json = NULL, error_detail = ",
        )
        .bind(error_detail)
        .push_static(", updated_at_ms = ")
        .bind(superseded_at_ms)
        .push_static(" WHERE claim_id = ")
        .bind(snapshot.claim_id.as_str())
        .push_static(" AND status = 'judged' AND audit_id = ")
        .bind(snapshot.audit_id.as_str())
        .push_static(" AND lease_generation = ")
        .bind(snapshot.lease_generation)
        .build()
}

fn audit_status_update(
    flavor: DbSqlFlavor,
    audit_id: &str,
    status: &str,
    error_detail: Option<&str>,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_judge_audits SET status = ")
        .bind(status)
        .push_static(", error_detail = ")
        .bind(error_detail.map(str::to_string))
        .push_static(" WHERE audit_id = ")
        .bind(audit_id)
        .build()
}

pub(crate) fn claim_apply_statement(
    flavor: DbSqlFlavor,
    apply: &WorkspaceAutonomyJudgmentApply,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_judgment_claims SET status = 'applied', \
             applied_at_ms = ",
        )
        .bind(apply.applied_at_ms)
        .push_static(", updated_at_ms = ")
        .bind(apply.applied_at_ms)
        .push_static(" WHERE claim_id = ")
        .bind(apply.claim_id.as_str())
        .push_static(" AND status = 'judged' AND audit_id = ")
        .bind(apply.audit_id.as_str())
        .push_static(" AND lease_generation = ")
        .bind(apply.lease_generation)
        .build()
}

pub(crate) fn audit_complete_statement(flavor: DbSqlFlavor, audit_id: &str) -> DbStatement {
    audit_status_update(flavor, audit_id, "completed", None)
}

fn judged_snapshot_from_row(
    row: &DbRow,
) -> Result<WorkspaceAutonomyJudgedSnapshot, WorkspaceAutonomyJudgmentStoreError> {
    let judgment = serde_json::from_str(&required_string(row, "judgment_json")?)
        .map_err(|_| WorkspaceAutonomyJudgmentStoreError::InvalidRecord("judgment_json"))?;
    Ok(WorkspaceAutonomyJudgedSnapshot {
        claim_id: required_string(row, "claim_id")?,
        lease_generation: required_i64(row, "lease_generation")?,
        audit_id: required_string(row, "audit_id")?,
        judgment,
    })
}

fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceAutonomyJudgmentStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceAutonomyJudgmentStoreError::InvalidRecord(column))
}

fn required_i64(
    row: &DbRow,
    column: &'static str,
) -> Result<i64, WorkspaceAutonomyJudgmentStoreError> {
    row.get_i64(column)?
        .ok_or(WorkspaceAutonomyJudgmentStoreError::InvalidRecord(column))
}
