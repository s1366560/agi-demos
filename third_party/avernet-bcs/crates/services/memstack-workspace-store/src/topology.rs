//! PostgreSQL/SQLite persistence for the Workspace topology authority.

use bcs_db_api::{
    DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStepResult, DbValue,
};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use serde_json::Value;
use thiserror::Error;

use crate::topology_mutation::{mutation_steps, receipt_lookup, receipt_outcome};

/// Tenant/project/workspace scope for one topology operation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceTopologyScope {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
}

/// Canonical topology node projection.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceTopologyNodeRecord {
    pub node_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub node_type: String,
    pub ref_id: Option<String>,
    pub title: String,
    pub position_x: f64,
    pub position_y: f64,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    pub status: String,
    pub tags: Value,
    pub data: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Canonical topology edge projection.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceTopologyEdgeRecord {
    pub edge_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub source_node_id: String,
    pub target_node_id: String,
    pub edge_type: String,
    pub label: Option<String>,
    pub source_hex_q: Option<i64>,
    pub source_hex_r: Option<i64>,
    pub target_hex_q: Option<i64>,
    pub target_hex_r: Option<i64>,
    pub direction: Option<String>,
    pub auto_created: bool,
    pub data: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Checked topology write applied inside one receipt/revision/outbox transaction.
#[derive(Debug, Clone, PartialEq)]
pub enum WorkspaceTopologyDomainWrite {
    CreateNode(WorkspaceTopologyNodeRecord),
    UpdateNode(WorkspaceTopologyNodeRecord),
    DeleteNode { node_id: String },
    CreateEdge(WorkspaceTopologyEdgeRecord),
    UpdateEdge(WorkspaceTopologyEdgeRecord),
    DeleteEdge { edge_id: String },
}

/// Complete topology mutation transaction input.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceTopologyMutation {
    pub scope: WorkspaceTopologyScope,
    pub actor_id: String,
    pub action: String,
    pub idempotency_key: String,
    pub payload_hash: String,
    pub expected_revision: u64,
    pub aggregate_id: String,
    pub domain_write: WorkspaceTopologyDomainWrite,
    pub response: Value,
    pub event_payload: Value,
    pub receipt_authority: Option<WorkspaceMutationAuthority>,
}

/// Committed or idempotently replayed topology mutation.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceTopologyMutationOutcome {
    pub committed_revision: u64,
    pub response: Value,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Stable topology persistence failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceTopologyStoreError {
    #[error("Workspace not found")]
    NotFound,
    #[error("Workspace membership required")]
    AccessRequired,
    #[error("Workspace editor access required")]
    EditorAccessRequired,
    #[error("Topology node not found")]
    NodeNotFound,
    #[error("Topology edge not found")]
    EdgeNotFound,
    #[error("Workspace topology mutation conflicted with current authority")]
    Conflict,
    #[error("idempotency key was already used with a different request hash")]
    IdempotencyConflict,
    #[error("Workspace topology receipt is incomplete")]
    IncompleteReceipt,
    #[error("persisted Workspace topology is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error("persisted Workspace topology JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite repository for topology reads and atomic writes.
pub struct WorkspaceTopologyStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceTopologyStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Require scoped membership and optionally editor authority.
    ///
    /// # Errors
    ///
    /// Returns stable not-found/access failures or preserves a database error.
    pub async fn require_access(
        &self,
        scope: &WorkspaceTopologyScope,
        user_id: &str,
        require_editor: bool,
    ) -> Result<(), WorkspaceTopologyStoreError> {
        let profile = self.db.query(workspace_exists(self.flavor, scope)).await?;
        if profile.is_empty() {
            return Err(WorkspaceTopologyStoreError::NotFound);
        }
        let roles = self
            .db
            .query(member_role(self.flavor, scope, user_id))
            .await?;
        let Some(role) = roles.first() else {
            return Err(WorkspaceTopologyStoreError::AccessRequired);
        };
        if require_editor {
            let role = required_string(role, "role")?;
            if !matches!(role.as_str(), "owner" | "editor" | "admin") {
                return Err(WorkspaceTopologyStoreError::EditorAccessRequired);
            }
        }
        Ok(())
    }

    /// Read the current Workspace authority revision.
    ///
    /// # Errors
    ///
    /// Returns a stable invalid-record or database error.
    pub async fn revision(
        &self,
        scope: &WorkspaceTopologyScope,
    ) -> Result<u64, WorkspaceTopologyStoreError> {
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
                    .bind(scope.tenant_id.as_str())
                    .push_static(" AND project_id = ")
                    .bind(scope.project_id.as_str())
                    .push_static(" AND workspace_id = ")
                    .bind(scope.workspace_id.as_str())
                    .build(),
            )
            .await?;
        let row = rows
            .first()
            .ok_or(WorkspaceTopologyStoreError::InvalidRecord("revision"))?;
        let revision = required_i64(row, "revision")?;
        u64::try_from(revision).map_err(|_| WorkspaceTopologyStoreError::InvalidRecord("revision"))
    }

    /// Read one scoped node after access has been checked.
    pub async fn get_node(
        &self,
        scope: &WorkspaceTopologyScope,
        node_id: &str,
    ) -> Result<Option<WorkspaceTopologyNodeRecord>, WorkspaceTopologyStoreError> {
        let rows = self
            .db
            .query(node_select(self.flavor, scope, Some(node_id), 1, 0))
            .await?;
        rows.first().map(node_from_row).transpose()
    }

    /// List scoped nodes in legacy creation order.
    pub async fn list_nodes(
        &self,
        scope: &WorkspaceTopologyScope,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<WorkspaceTopologyNodeRecord>, WorkspaceTopologyStoreError> {
        self.db
            .query(node_select(self.flavor, scope, None, limit, offset))
            .await?
            .iter()
            .map(node_from_row)
            .collect()
    }

    /// Return whether a hex is occupied by another topology node or Agent binding.
    pub async fn is_hex_occupied(
        &self,
        scope: &WorkspaceTopologyScope,
        hex_q: i64,
        hex_r: i64,
        exclude_node_id: Option<&str>,
    ) -> Result<bool, WorkspaceTopologyStoreError> {
        let nodes = self
            .db
            .query(node_hex_occupant(
                self.flavor,
                scope,
                hex_q,
                hex_r,
                exclude_node_id,
            ))
            .await?;
        if !nodes.is_empty() {
            return Ok(true);
        }
        let agents = self
            .db
            .query(agent_hex_occupant(self.flavor, scope, hex_q, hex_r))
            .await?;
        Ok(!agents.is_empty())
    }

    /// Read one scoped edge after access has been checked.
    pub async fn get_edge(
        &self,
        scope: &WorkspaceTopologyScope,
        edge_id: &str,
    ) -> Result<Option<WorkspaceTopologyEdgeRecord>, WorkspaceTopologyStoreError> {
        let rows = self
            .db
            .query(edge_select(self.flavor, scope, Some(edge_id), 1, 0))
            .await?;
        rows.first().map(edge_from_row).transpose()
    }

    /// List scoped edges in legacy creation order.
    pub async fn list_edges(
        &self,
        scope: &WorkspaceTopologyScope,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<WorkspaceTopologyEdgeRecord>, WorkspaceTopologyStoreError> {
        self.db
            .query(edge_select(self.flavor, scope, None, limit, offset))
            .await?
            .iter()
            .map(edge_from_row)
            .collect()
    }

    /// List edges connected to one scoped node.
    pub async fn list_edges_for_node(
        &self,
        scope: &WorkspaceTopologyScope,
        node_id: &str,
    ) -> Result<Vec<WorkspaceTopologyEdgeRecord>, WorkspaceTopologyStoreError> {
        self.db
            .query(edge_for_node_select(self.flavor, scope, node_id))
            .await?
            .iter()
            .map(edge_from_row)
            .collect()
    }

    /// Execute one atomic topology mutation or replay its committed receipt.
    ///
    /// # Errors
    ///
    /// Returns stable access, revision, idempotency, domain, decoding, or database failures.
    pub async fn mutate(
        &self,
        mutation: &WorkspaceTopologyMutation,
    ) -> Result<WorkspaceTopologyMutationOutcome, WorkspaceTopologyStoreError> {
        let lookup = receipt_lookup(self.flavor, mutation);
        if let Some(outcome) = self.read_receipt(mutation, lookup.clone(), true).await? {
            return Ok(outcome);
        }
        let (steps, domain_range) = mutation_steps(self.flavor, mutation)?;
        let transaction = self.db.transaction(steps).await;
        let results = match transaction {
            Ok(results) => results,
            Err(error) => {
                if error.is_duplicate_key()
                    && let Some(outcome) = self.read_receipt(mutation, lookup, true).await?
                {
                    return Ok(outcome);
                }
                return Err(classify_mutation_error(error, domain_range));
            }
        };
        let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
            return Err(WorkspaceTopologyStoreError::InvalidRecord("receipt result"));
        };
        let row = rows
            .first()
            .ok_or(WorkspaceTopologyStoreError::InvalidRecord("receipt"))?;
        receipt_outcome(mutation, row, false)?.ok_or(WorkspaceTopologyStoreError::InvalidRecord(
            "committed receipt",
        ))
    }

    async fn read_receipt(
        &self,
        mutation: &WorkspaceTopologyMutation,
        statement: DbStatement,
        replayed: bool,
    ) -> Result<Option<WorkspaceTopologyMutationOutcome>, WorkspaceTopologyStoreError> {
        let rows = self.db.query(statement).await?;
        rows.first()
            .map(|row| receipt_outcome(mutation, row, replayed))
            .transpose()
            .map(Option::flatten)
    }
}

fn classify_mutation_error(
    error: DbError,
    domain_range: std::ops::Range<usize>,
) -> WorkspaceTopologyStoreError {
    if let DbError::TransactionExpectation { step_index, .. } = &error {
        return match *step_index {
            0 => WorkspaceTopologyStoreError::EditorAccessRequired,
            1 | 2 => WorkspaceTopologyStoreError::Conflict,
            index if domain_range.contains(&index) => WorkspaceTopologyStoreError::Conflict,
            _ => WorkspaceTopologyStoreError::Database(error),
        };
    }
    if error.is_duplicate_key() {
        WorkspaceTopologyStoreError::Conflict
    } else {
        WorkspaceTopologyStoreError::Database(error)
    }
}

fn workspace_exists(flavor: DbSqlFlavor, scope: &WorkspaceTopologyScope) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT workspace_id FROM workspace_profiles WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND deleted_at IS NULL")
        .build()
}

fn member_role(flavor: DbSqlFlavor, scope: &WorkspaceTopologyScope, user_id: &str) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT role FROM workspace_members WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND user_id = ")
        .bind(user_id)
        .build()
}

fn node_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceTopologyScope,
    node_id: Option<&str>,
    limit: i64,
    offset: i64,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT node_id, tenant_id, project_id, workspace_id, node_type, ref_id, title, \
             position_x, position_y, hex_q, hex_r, status, tags_json, data_json, created_at, \
             updated_at FROM workspace_topology_nodes WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str());
    if let Some(node_id) = node_id {
        builder = builder.push_static(" AND node_id = ").bind(node_id);
    }
    builder
        .push_static(" ORDER BY created_at ASC, node_id ASC LIMIT ")
        .bind(limit)
        .push_static(" OFFSET ")
        .bind(offset)
        .build()
}

fn edge_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceTopologyScope,
    edge_id: Option<&str>,
    limit: i64,
    offset: i64,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT edge_id, tenant_id, project_id, workspace_id, source_node_id, \
             target_node_id, edge_type, label, source_hex_q, source_hex_r, target_hex_q, \
             target_hex_r, direction, auto_created, data_json, created_at, updated_at \
             FROM workspace_topology_edges WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str());
    if let Some(edge_id) = edge_id {
        builder = builder.push_static(" AND edge_id = ").bind(edge_id);
    }
    builder
        .push_static(" ORDER BY created_at ASC, edge_id ASC LIMIT ")
        .bind(limit)
        .push_static(" OFFSET ")
        .bind(offset)
        .build()
}

fn node_hex_occupant(
    flavor: DbSqlFlavor,
    scope: &WorkspaceTopologyScope,
    hex_q: i64,
    hex_r: i64,
    exclude_node_id: Option<&str>,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static("SELECT node_id FROM workspace_topology_nodes WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND hex_q = ")
        .bind(hex_q)
        .push_static(" AND hex_r = ")
        .bind(hex_r);
    if let Some(node_id) = exclude_node_id {
        builder = builder.push_static(" AND node_id <> ").bind(node_id);
    }
    builder.push_static(" LIMIT 1").build()
}

fn agent_hex_occupant(
    flavor: DbSqlFlavor,
    scope: &WorkspaceTopologyScope,
    hex_q: i64,
    hex_r: i64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT binding_id FROM workspace_agent_bindings WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND hex_q = ")
        .bind(hex_q)
        .push_static(" AND hex_r = ")
        .bind(hex_r)
        .push_static(" LIMIT 1")
        .build()
}

fn edge_for_node_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceTopologyScope,
    node_id: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT edge_id, tenant_id, project_id, workspace_id, source_node_id, \
             target_node_id, edge_type, label, source_hex_q, source_hex_r, target_hex_q, \
             target_hex_r, direction, auto_created, data_json, created_at, updated_at \
             FROM workspace_topology_edges WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND (source_node_id = ")
        .bind(node_id)
        .push_static(" OR target_node_id = ")
        .bind(node_id)
        .push_static(") ORDER BY created_at ASC, edge_id ASC")
        .build()
}

fn node_from_row(row: &DbRow) -> Result<WorkspaceTopologyNodeRecord, WorkspaceTopologyStoreError> {
    Ok(WorkspaceTopologyNodeRecord {
        node_id: required_string(row, "node_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        node_type: required_string(row, "node_type")?,
        ref_id: row.get_string("ref_id")?,
        title: required_string(row, "title")?,
        position_x: required_f64(row, "position_x")?,
        position_y: required_f64(row, "position_y")?,
        hex_q: row.get_i64("hex_q")?,
        hex_r: row.get_i64("hex_r")?,
        status: required_string(row, "status")?,
        tags: required_json_array(row, "tags_json")?,
        data: required_json_object(row, "data_json")?,
        created_at: required_string(row, "created_at")?,
        updated_at: row.get_string("updated_at")?,
    })
}

fn edge_from_row(row: &DbRow) -> Result<WorkspaceTopologyEdgeRecord, WorkspaceTopologyStoreError> {
    Ok(WorkspaceTopologyEdgeRecord {
        edge_id: required_string(row, "edge_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        source_node_id: required_string(row, "source_node_id")?,
        target_node_id: required_string(row, "target_node_id")?,
        edge_type: required_string(row, "edge_type")?,
        label: row.get_string("label")?,
        source_hex_q: row.get_i64("source_hex_q")?,
        source_hex_r: row.get_i64("source_hex_r")?,
        target_hex_q: row.get_i64("target_hex_q")?,
        target_hex_r: row.get_i64("target_hex_r")?,
        direction: row.get_string("direction")?,
        auto_created: required_bool(row, "auto_created")?,
        data: required_json_object(row, "data_json")?,
        created_at: required_string(row, "created_at")?,
        updated_at: row.get_string("updated_at")?,
    })
}

pub(super) fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceTopologyStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceTopologyStoreError::InvalidRecord(column))
}

fn required_i64(row: &DbRow, column: &'static str) -> Result<i64, WorkspaceTopologyStoreError> {
    row.get_i64(column)?
        .ok_or(WorkspaceTopologyStoreError::InvalidRecord(column))
}

fn required_bool(row: &DbRow, column: &'static str) -> Result<bool, WorkspaceTopologyStoreError> {
    row.get_bool(column)?
        .ok_or(WorkspaceTopologyStoreError::InvalidRecord(column))
}

fn required_f64(row: &DbRow, column: &'static str) -> Result<f64, WorkspaceTopologyStoreError> {
    match row.get(column) {
        Some(DbValue::F64(value)) => Ok(*value),
        Some(DbValue::I64(value)) => Ok(*value as f64),
        Some(DbValue::U64(value)) => Ok(*value as f64),
        _ => Err(WorkspaceTopologyStoreError::InvalidRecord(column)),
    }
}

pub(super) fn required_json_object(
    row: &DbRow,
    column: &'static str,
) -> Result<Value, WorkspaceTopologyStoreError> {
    let encoded = required_string(row, column)?;
    let value: Value =
        serde_json::from_str(&encoded).map_err(WorkspaceTopologyStoreError::InvalidJson)?;
    value
        .is_object()
        .then_some(value)
        .ok_or(WorkspaceTopologyStoreError::InvalidRecord(column))
}

fn required_json_array(
    row: &DbRow,
    column: &'static str,
) -> Result<Value, WorkspaceTopologyStoreError> {
    let encoded = required_string(row, column)?;
    let value: Value =
        serde_json::from_str(&encoded).map_err(WorkspaceTopologyStoreError::InvalidJson)?;
    value
        .is_array()
        .then_some(value)
        .ok_or(WorkspaceTopologyStoreError::InvalidRecord(column))
}
