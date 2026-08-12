//! Receipt, revision-CAS, topology write, and durable outbox transaction.

use std::ops::Range;

use bcs_db_api::{
    DbCountExpectation, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder, DbTransactionStep,
    DbValue,
};
use serde_json::json;
use sha2::{Digest, Sha256};

use crate::topology::{required_json_object, required_string};
use crate::{
    WorkspaceTopologyDomainWrite, WorkspaceTopologyEdgeRecord, WorkspaceTopologyMutation,
    WorkspaceTopologyMutationOutcome, WorkspaceTopologyNodeRecord, WorkspaceTopologyStoreError,
};

pub(super) fn mutation_steps(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTopologyMutation,
) -> Result<(Vec<DbTransactionStep>, Range<usize>), WorkspaceTopologyStoreError> {
    let committed_revision = mutation
        .expected_revision
        .checked_add(1)
        .ok_or(WorkspaceTopologyStoreError::Conflict)?;
    let receipt_id = deterministic_id("topology-receipt", mutation);
    let outbox_id = deterministic_id("topology-outbox", mutation);
    let domain = domain_steps(flavor, mutation);
    let domain_range = 3..(3 + domain.len());
    let mut steps = Vec::with_capacity(domain.len() + 7);
    steps.push(DbTransactionStep::query_checked(
        access_check(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::execute_checked(
        receipt_insert(flavor, mutation, receipt_id.as_str()),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::query_checked(
        revision_check(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    steps.extend(domain);
    steps.push(DbTransactionStep::execute_checked(
        authority_cas(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::execute_checked(
        outbox_insert(
            flavor,
            mutation,
            outbox_id.as_str(),
            committed_revision,
            receipt_id.as_str(),
        ),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::execute_checked(
        receipt_finalize(flavor, mutation, receipt_id.as_str(), committed_revision),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::query_checked(
        receipt_lookup(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    Ok((steps, domain_range))
}

fn domain_steps(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTopologyMutation,
) -> Vec<DbTransactionStep> {
    match &mutation.domain_write {
        WorkspaceTopologyDomainWrite::CreateNode(node) => vec![DbTransactionStep::execute_checked(
            insert_node(flavor, node),
            DbCountExpectation::exactly(1),
        )],
        WorkspaceTopologyDomainWrite::UpdateNode(node) => vec![
            DbTransactionStep::execute_checked(
                update_node(flavor, node),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                sync_source_coordinates(flavor, node),
                DbCountExpectation::at_least(0),
            ),
            DbTransactionStep::execute_checked(
                sync_target_coordinates(flavor, node),
                DbCountExpectation::at_least(0),
            ),
        ],
        WorkspaceTopologyDomainWrite::DeleteNode { node_id } => {
            vec![DbTransactionStep::execute_checked(
                delete_node(flavor, &mutation.scope, node_id),
                DbCountExpectation::exactly(1),
            )]
        }
        WorkspaceTopologyDomainWrite::CreateEdge(edge) => vec![DbTransactionStep::execute_checked(
            insert_edge(flavor, edge),
            DbCountExpectation::exactly(1),
        )],
        WorkspaceTopologyDomainWrite::UpdateEdge(edge) => vec![DbTransactionStep::execute_checked(
            update_edge(flavor, edge),
            DbCountExpectation::exactly(1),
        )],
        WorkspaceTopologyDomainWrite::DeleteEdge { edge_id } => {
            vec![DbTransactionStep::execute_checked(
                delete_edge(flavor, &mutation.scope, edge_id),
                DbCountExpectation::exactly(1),
            )]
        }
    }
}

fn access_check(flavor: DbSqlFlavor, mutation: &WorkspaceTopologyMutation) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT p.workspace_id FROM workspace_profiles p JOIN workspace_members m \
             ON m.tenant_id = p.tenant_id AND m.project_id = p.project_id \
             AND m.workspace_id = p.workspace_id WHERE p.tenant_id = ",
        )
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND p.workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND p.deleted_at IS NULL AND m.user_id = ")
        .bind(mutation.actor_id.as_str())
        .push_static(" AND m.role IN ('owner', 'editor', 'admin')")
        .build()
}

pub(super) fn receipt_lookup(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTopologyMutation,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT request_hash, committed_revision, response_json FROM \
             workspace_mutation_receipts WHERE tenant_id = ",
        )
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND actor_id = ")
        .bind(mutation.actor_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(mutation.idempotency_key.as_str())
        .build()
}

fn receipt_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTopologyMutation,
    receipt_id: &str,
) -> DbStatement {
    let (contract_version, surface, action) = mutation.receipt_authority.as_ref().map_or(
        ("v1", "topology", mutation.action.as_str()),
        |authority| {
            (
                authority.contract_version().as_str(),
                authority.surface().as_str(),
                authority.action().as_str(),
            )
        },
    );
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_mutation_receipts (receipt_id, tenant_id, project_id, \
             workspace_id, actor_id, contract_version, surface, action, idempotency_key, \
             request_hash, expected_revision) VALUES (",
        )
        .bind(receipt_id)
        .push_static(", ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(", ")
        .bind(mutation.actor_id.as_str())
        .push_static(", ")
        .bind(contract_version)
        .push_static(", ")
        .bind(surface)
        .push_static(", ")
        .bind(action)
        .push_static(", ")
        .bind(mutation.idempotency_key.as_str())
        .push_static(", ")
        .bind(mutation.payload_hash.as_str())
        .push_static(", ")
        .bind(mutation.expected_revision)
        .push_static(")");
    match flavor {
        DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
            .push_static(" ON CONFLICT(workspace_id, actor_id, idempotency_key) DO NOTHING")
            .build(),
        DbSqlFlavor::Mysql => builder.build(),
    }
}

fn revision_check(flavor: DbSqlFlavor, mutation: &WorkspaceTopologyMutation) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND revision = ")
        .bind(mutation.expected_revision);
    if flavor == DbSqlFlavor::Postgres {
        builder.push_static(" FOR UPDATE").build()
    } else {
        builder.build()
    }
}

fn authority_cas(flavor: DbSqlFlavor, mutation: &WorkspaceTopologyMutation) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_authorities SET revision = revision + 1, updated_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE tenant_id = ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND revision = ")
        .bind(mutation.expected_revision)
        .build()
}

fn insert_node(flavor: DbSqlFlavor, node: &WorkspaceTopologyNodeRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_topology_nodes (node_id, tenant_id, project_id, workspace_id, \
             node_type, ref_id, title, position_x, position_y, hex_q, hex_r, status, tags_json, \
             data_json, created_at, updated_at) VALUES (",
        )
        .bind(node.node_id.as_str())
        .push_static(", ")
        .bind(node.tenant_id.as_str())
        .push_static(", ")
        .bind(node.project_id.as_str())
        .push_static(", ")
        .bind(node.workspace_id.as_str())
        .push_static(", ")
        .bind(node.node_type.as_str())
        .push_static(", ")
        .bind(node.ref_id.clone())
        .push_static(", ")
        .bind(node.title.as_str())
        .push_static(", ")
        .bind(node.position_x)
        .push_static(", ")
        .bind(node.position_y)
        .push_static(", ")
        .bind(optional_i64_value(node.hex_q))
        .push_static(", ")
        .bind(optional_i64_value(node.hex_r))
        .push_static(", ")
        .bind(node.status.as_str())
        .push_static(", ")
        .bind(node.tags.to_string())
        .push_static(", ")
        .bind(node.data.to_string())
        .push_static(", ")
        .bind(node.created_at.as_str())
        .push_static(", ")
        .bind(node.updated_at.clone())
        .push_static(")")
        .build()
}

fn update_node(flavor: DbSqlFlavor, node: &WorkspaceTopologyNodeRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_topology_nodes SET node_type = ")
        .bind(node.node_type.as_str())
        .push_static(", ref_id = ")
        .bind(node.ref_id.clone())
        .push_static(", title = ")
        .bind(node.title.as_str())
        .push_static(", position_x = ")
        .bind(node.position_x)
        .push_static(", position_y = ")
        .bind(node.position_y)
        .push_static(", hex_q = ")
        .bind(optional_i64_value(node.hex_q))
        .push_static(", hex_r = ")
        .bind(optional_i64_value(node.hex_r))
        .push_static(", status = ")
        .bind(node.status.as_str())
        .push_static(", tags_json = ")
        .bind(node.tags.to_string())
        .push_static(", data_json = ")
        .bind(node.data.to_string())
        .push_static(", updated_at = ")
        .bind(node.updated_at.clone())
        .push_static(" WHERE tenant_id = ")
        .bind(node.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(node.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(node.workspace_id.as_str())
        .push_static(" AND node_id = ")
        .bind(node.node_id.as_str())
        .build()
}

fn sync_source_coordinates(flavor: DbSqlFlavor, node: &WorkspaceTopologyNodeRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_topology_edges SET source_hex_q = ")
        .bind(optional_i64_value(node.hex_q))
        .push_static(", source_hex_r = ")
        .bind(optional_i64_value(node.hex_r))
        .push_static(", updated_at = ")
        .bind(node.updated_at.clone())
        .push_static(" WHERE tenant_id = ")
        .bind(node.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(node.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(node.workspace_id.as_str())
        .push_static(" AND source_node_id = ")
        .bind(node.node_id.as_str())
        .build()
}

fn sync_target_coordinates(flavor: DbSqlFlavor, node: &WorkspaceTopologyNodeRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_topology_edges SET target_hex_q = ")
        .bind(optional_i64_value(node.hex_q))
        .push_static(", target_hex_r = ")
        .bind(optional_i64_value(node.hex_r))
        .push_static(", updated_at = ")
        .bind(node.updated_at.clone())
        .push_static(" WHERE tenant_id = ")
        .bind(node.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(node.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(node.workspace_id.as_str())
        .push_static(" AND target_node_id = ")
        .bind(node.node_id.as_str())
        .build()
}

fn delete_node(
    flavor: DbSqlFlavor,
    scope: &crate::WorkspaceTopologyScope,
    node_id: &str,
) -> DbStatement {
    scoped_delete(
        flavor,
        "workspace_topology_nodes",
        "node_id",
        scope,
        node_id,
    )
}

fn insert_edge(flavor: DbSqlFlavor, edge: &WorkspaceTopologyEdgeRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_topology_edges (edge_id, tenant_id, project_id, workspace_id, \
             source_node_id, target_node_id, edge_type, label, source_hex_q, source_hex_r, \
             target_hex_q, target_hex_r, direction, auto_created, data_json, created_at, updated_at) \
             VALUES (",
        )
        .bind(edge.edge_id.as_str())
        .push_static(", ")
        .bind(edge.tenant_id.as_str())
        .push_static(", ")
        .bind(edge.project_id.as_str())
        .push_static(", ")
        .bind(edge.workspace_id.as_str())
        .push_static(", ")
        .bind(edge.source_node_id.as_str())
        .push_static(", ")
        .bind(edge.target_node_id.as_str())
        .push_static(", ")
        .bind(edge.edge_type.as_str())
        .push_static(", ")
        .bind(edge.label.clone())
        .push_static(", ")
        .bind(optional_i64_value(edge.source_hex_q))
        .push_static(", ")
        .bind(optional_i64_value(edge.source_hex_r))
        .push_static(", ")
        .bind(optional_i64_value(edge.target_hex_q))
        .push_static(", ")
        .bind(optional_i64_value(edge.target_hex_r))
        .push_static(", ")
        .bind(edge.direction.clone())
        .push_static(", ")
        .bind(edge.auto_created)
        .push_static(", ")
        .bind(edge.data.to_string())
        .push_static(", ")
        .bind(edge.created_at.as_str())
        .push_static(", ")
        .bind(edge.updated_at.clone())
        .push_static(")")
        .build()
}

fn update_edge(flavor: DbSqlFlavor, edge: &WorkspaceTopologyEdgeRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_topology_edges SET source_node_id = ")
        .bind(edge.source_node_id.as_str())
        .push_static(", target_node_id = ")
        .bind(edge.target_node_id.as_str())
        .push_static(", edge_type = ")
        .bind(edge.edge_type.as_str())
        .push_static(", label = ")
        .bind(edge.label.clone())
        .push_static(", source_hex_q = ")
        .bind(optional_i64_value(edge.source_hex_q))
        .push_static(", source_hex_r = ")
        .bind(optional_i64_value(edge.source_hex_r))
        .push_static(", target_hex_q = ")
        .bind(optional_i64_value(edge.target_hex_q))
        .push_static(", target_hex_r = ")
        .bind(optional_i64_value(edge.target_hex_r))
        .push_static(", direction = ")
        .bind(edge.direction.clone())
        .push_static(", auto_created = ")
        .bind(edge.auto_created)
        .push_static(", data_json = ")
        .bind(edge.data.to_string())
        .push_static(", updated_at = ")
        .bind(edge.updated_at.clone())
        .push_static(" WHERE tenant_id = ")
        .bind(edge.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(edge.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(edge.workspace_id.as_str())
        .push_static(" AND edge_id = ")
        .bind(edge.edge_id.as_str())
        .build()
}

fn delete_edge(
    flavor: DbSqlFlavor,
    scope: &crate::WorkspaceTopologyScope,
    edge_id: &str,
) -> DbStatement {
    scoped_delete(
        flavor,
        "workspace_topology_edges",
        "edge_id",
        scope,
        edge_id,
    )
}

fn scoped_delete(
    flavor: DbSqlFlavor,
    table: &'static str,
    id_column: &'static str,
    scope: &crate::WorkspaceTopologyScope,
    id: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("DELETE FROM ")
        .push_static(table)
        .push_static(" WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND ")
        .push_static(id_column)
        .push_static(" = ")
        .bind(id)
        .build()
}

fn outbox_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTopologyMutation,
    outbox_id: &str,
    committed_revision: u64,
    receipt_id: &str,
) -> DbStatement {
    let (contract_version, action) =
        mutation
            .receipt_authority
            .as_ref()
            .map_or(("v1", mutation.action.as_str()), |authority| {
                (
                    authority.contract_version().as_str(),
                    authority.action().as_str(),
                )
            });
    let metadata = json!({
        "action": action,
        "contract_version": contract_version,
        "receipt_id": receipt_id,
        "request_hash": &mutation.payload_hash,
    });
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, \
             aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, \
             metadata_json, correlation_id, idempotency_key) VALUES (",
        )
        .bind(outbox_id)
        .push_static(", ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(", 'topology', ")
        .bind(mutation.aggregate_id.as_str())
        .push_static(", 'topology_updated', ")
        .bind(format!("workspace:{}", mutation.scope.workspace_id))
        .push_static(", ")
        .bind(committed_revision)
        .push_static(", ")
        .bind(mutation.event_payload.to_string())
        .push_static(", ")
        .bind(metadata.to_string())
        .push_static(", ")
        .bind(outbox_id)
        .push_static(", ")
        .bind(mutation.idempotency_key.as_str())
        .push_static(")")
        .build()
}

fn receipt_finalize(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTopologyMutation,
    receipt_id: &str,
    committed_revision: u64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_mutation_receipts SET committed_revision = ")
        .bind(committed_revision)
        .push_static(", response_json = ")
        .bind(mutation.response.to_string())
        .push_static(", committed_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE receipt_id = ")
        .bind(receipt_id)
        .push_static(" AND request_hash = ")
        .bind(mutation.payload_hash.as_str())
        .push_static(" AND committed_revision IS NULL")
        .build()
}

pub(super) fn receipt_outcome(
    mutation: &WorkspaceTopologyMutation,
    row: &DbRow,
    replayed: bool,
) -> Result<Option<WorkspaceTopologyMutationOutcome>, WorkspaceTopologyStoreError> {
    let request_hash = required_string(row, "request_hash")?;
    if request_hash != mutation.payload_hash {
        return Err(WorkspaceTopologyStoreError::IdempotencyConflict);
    }
    let Some(committed_revision) = row.get_i64("committed_revision")? else {
        return Err(WorkspaceTopologyStoreError::IncompleteReceipt);
    };
    let committed_revision = u64::try_from(committed_revision)
        .map_err(|_| WorkspaceTopologyStoreError::InvalidRecord("committed_revision"))?;
    let response = required_json_object(row, "response_json")?;
    Ok(Some(WorkspaceTopologyMutationOutcome {
        committed_revision,
        response,
        outbox_id: deterministic_id("topology-outbox", mutation),
        replayed,
    }))
}

fn deterministic_id(namespace: &str, mutation: &WorkspaceTopologyMutation) -> String {
    let mut digest = Sha256::new();
    let (surface, action) = mutation
        .receipt_authority
        .as_ref()
        .map_or(("topology", mutation.action.as_str()), |authority| {
            (authority.surface().as_str(), authority.action().as_str())
        });
    for part in [
        namespace,
        mutation.scope.tenant_id.as_str(),
        mutation.scope.project_id.as_str(),
        mutation.scope.workspace_id.as_str(),
        mutation.actor_id.as_str(),
        surface,
        action,
        mutation.idempotency_key.as_str(),
        mutation.payload_hash.as_str(),
    ] {
        digest.update(u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        digest.update(part.as_bytes());
    }
    format!("{namespace}-{}", hex::encode(digest.finalize()))
}

fn optional_i64_value(value: Option<i64>) -> DbValue {
    value.map_or(DbValue::Null, DbValue::I64)
}
