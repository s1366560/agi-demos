//! Atomic revision and idempotency handling for Judge-attention resolution.

use bcs_db_api::{
    DbCountExpectation, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder, DbTransactionStep,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use super::{
    WorkspaceAutonomyAttentionResolution, WorkspaceAutonomyAttentionResolutionOutcome,
    WorkspaceAutonomyAttentionStoreError, editor_access_statement, required_string,
    resolve_judge_attention_statement,
};

pub(super) fn judge_resolution_steps(
    flavor: DbSqlFlavor,
    resolution: &WorkspaceAutonomyAttentionResolution,
) -> Result<Vec<DbTransactionStep>, WorkspaceAutonomyAttentionStoreError> {
    let committed_revision = resolution
        .expected_revision
        .checked_add(1)
        .ok_or(WorkspaceAutonomyAttentionStoreError::Conflict)?;
    let receipt_id = resolution_deterministic_id("autonomy-attention-receipt", resolution);
    let outbox_id = resolution_deterministic_id("autonomy-attention-outbox", resolution);
    Ok(vec![
        DbTransactionStep::query_checked(
            editor_access_statement(
                flavor,
                &resolution.scope,
                resolution.actor_id.as_str(),
                resolution.actor_is_superuser,
            ),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            resolution_receipt_insert(flavor, resolution, receipt_id.as_str()),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            resolution_revision_check(flavor, resolution),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            resolve_judge_attention_statement(
                flavor,
                &resolution.scope,
                resolution.actor_id.as_str(),
                resolution.attention_id.as_str(),
                resolution.resolved_at_ms,
            ),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            resolution_authority_cas(flavor, resolution),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            resolution_outbox_insert(flavor, resolution, outbox_id.as_str(), committed_revision),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            resolution_receipt_finalize(
                flavor,
                resolution,
                receipt_id.as_str(),
                committed_revision,
            ),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            resolution_receipt_lookup(flavor, resolution),
            DbCountExpectation::exactly(1),
        ),
    ])
}

pub(super) fn resolution_receipt_lookup(
    flavor: DbSqlFlavor,
    resolution: &WorkspaceAutonomyAttentionResolution,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT receipt_id, request_hash, committed_revision, response_json FROM \
             workspace_mutation_receipts WHERE tenant_id = ",
        )
        .bind(resolution.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(resolution.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(resolution.scope.workspace_id.as_str())
        .push_static(" AND actor_id = ")
        .bind(resolution.actor_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(resolution.idempotency_key.as_str())
        .build()
}

pub(super) fn resolution_outcome(
    resolution: &WorkspaceAutonomyAttentionResolution,
    row: &DbRow,
    replayed: bool,
) -> Result<Option<WorkspaceAutonomyAttentionResolutionOutcome>, WorkspaceAutonomyAttentionStoreError>
{
    if required_string(row, "request_hash")? != resolution.request_hash {
        return Err(WorkspaceAutonomyAttentionStoreError::IdempotencyConflict);
    }
    let Some(committed_revision) = row.get_i64("committed_revision")? else {
        return Err(WorkspaceAutonomyAttentionStoreError::IncompleteReceipt);
    };
    let committed_revision = u64::try_from(committed_revision)
        .map_err(|_| WorkspaceAutonomyAttentionStoreError::InvalidRecord("committed_revision"))?;
    let response: Value = serde_json::from_str(&required_string(row, "response_json")?)
        .map_err(|_| WorkspaceAutonomyAttentionStoreError::InvalidRecord("response_json"))?;
    if response != resolution_response(resolution, committed_revision) {
        return Err(WorkspaceAutonomyAttentionStoreError::InvalidRecord(
            "response_json",
        ));
    }
    Ok(Some(WorkspaceAutonomyAttentionResolutionOutcome {
        committed_revision,
        outbox_id: resolution_deterministic_id("autonomy-attention-outbox", resolution),
        receipt_id: required_string(row, "receipt_id")?,
        replayed,
    }))
}

fn resolution_receipt_insert(
    flavor: DbSqlFlavor,
    resolution: &WorkspaceAutonomyAttentionResolution,
    receipt_id: &str,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_mutation_receipts (receipt_id, tenant_id, project_id, \
             workspace_id, actor_id, contract_version, surface, action, idempotency_key, \
             request_hash, expected_revision) VALUES (",
        )
        .bind(receipt_id)
        .push_static(", ")
        .bind(resolution.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(resolution.scope.project_id.as_str())
        .push_static(", ")
        .bind(resolution.scope.workspace_id.as_str())
        .push_static(", ")
        .bind(resolution.actor_id.as_str())
        .push_static(", 'v1', 'autonomy_attention', 'resolve', ")
        .bind(resolution.idempotency_key.as_str())
        .push_static(", ")
        .bind(resolution.request_hash.as_str())
        .push_static(", ")
        .bind(resolution.expected_revision)
        .push_static(")");
    match flavor {
        DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
            .push_static(" ON CONFLICT(workspace_id, actor_id, idempotency_key) DO NOTHING")
            .build(),
        DbSqlFlavor::Mysql => builder.build(),
    }
}

fn resolution_revision_check(
    flavor: DbSqlFlavor,
    resolution: &WorkspaceAutonomyAttentionResolution,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
        .bind(resolution.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(resolution.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(resolution.scope.workspace_id.as_str())
        .push_static(" AND revision = ")
        .bind(resolution.expected_revision);
    if flavor == DbSqlFlavor::Postgres {
        builder.push_static(" FOR UPDATE").build()
    } else {
        builder.build()
    }
}

fn resolution_authority_cas(
    flavor: DbSqlFlavor,
    resolution: &WorkspaceAutonomyAttentionResolution,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_authorities SET revision = revision + 1, updated_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE tenant_id = ")
        .bind(resolution.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(resolution.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(resolution.scope.workspace_id.as_str())
        .push_static(" AND revision = ")
        .bind(resolution.expected_revision)
        .build()
}

fn resolution_outbox_insert(
    flavor: DbSqlFlavor,
    resolution: &WorkspaceAutonomyAttentionResolution,
    outbox_id: &str,
    committed_revision: u64,
) -> DbStatement {
    let response = resolution_response(resolution, committed_revision);
    let metadata = json!({
        "action": "resolve",
        "request_hash": &resolution.request_hash,
        "surface": "autonomy_attention",
    });
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, \
             aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, \
             metadata_json, correlation_id, idempotency_key) VALUES (",
        )
        .bind(outbox_id)
        .push_static(", ")
        .bind(resolution.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(resolution.scope.project_id.as_str())
        .push_static(", ")
        .bind(resolution.scope.workspace_id.as_str())
        .push_static(", 'workspace_autonomy_attention', ")
        .bind(resolution.attention_id.as_str())
        .push_static(", 'workspace_autonomy_attention_resolved', ")
        .bind(format!("workspace:{}", resolution.scope.workspace_id))
        .push_static(", ")
        .bind(committed_revision)
        .push_static(", ")
        .bind(response.to_string())
        .push_static(", ")
        .bind(metadata.to_string())
        .push_static(", ")
        .bind(outbox_id)
        .push_static(", ")
        .bind(resolution.idempotency_key.as_str())
        .push_static(")")
        .build()
}

fn resolution_receipt_finalize(
    flavor: DbSqlFlavor,
    resolution: &WorkspaceAutonomyAttentionResolution,
    receipt_id: &str,
    committed_revision: u64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_mutation_receipts SET committed_revision = ")
        .bind(committed_revision)
        .push_static(", response_json = ")
        .bind(resolution_response(resolution, committed_revision).to_string())
        .push_static(", committed_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE receipt_id = ")
        .bind(receipt_id)
        .push_static(" AND request_hash = ")
        .bind(resolution.request_hash.as_str())
        .push_static(" AND committed_revision IS NULL")
        .build()
}

fn resolution_response(
    resolution: &WorkspaceAutonomyAttentionResolution,
    committed_revision: u64,
) -> Value {
    json!({
        "attention_id": &resolution.attention_id,
        "committed_revision": committed_revision,
        "status": "resolved",
    })
}

fn resolution_deterministic_id(
    namespace: &str,
    resolution: &WorkspaceAutonomyAttentionResolution,
) -> String {
    let mut digest = Sha256::new();
    for part in [
        namespace,
        resolution.scope.tenant_id.as_str(),
        resolution.scope.project_id.as_str(),
        resolution.scope.workspace_id.as_str(),
        resolution.actor_id.as_str(),
        resolution.idempotency_key.as_str(),
        resolution.request_hash.as_str(),
    ] {
        digest.update(u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        digest.update(part.as_bytes());
    }
    format!("{namespace}-{}", hex::encode(digest.finalize()))
}
