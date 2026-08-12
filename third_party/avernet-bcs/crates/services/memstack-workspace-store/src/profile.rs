//! Dialect-aware Workspace profile reads and checked domain mutations.

use bcs_db_api::{DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatementBuilder};
use memstack_workspace_service_api::WorkspaceScope;
use serde_json::Value;
use thiserror::Error;

use crate::WorkspaceDomainMutation;

/// Persisted Workspace profile used by application mutation orchestration.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceProfileSnapshot {
    pub workspace_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub group_id: String,
    pub name: String,
    pub created_by: String,
    pub description: Option<String>,
    pub is_archived: bool,
    pub metadata: Value,
    pub office_status: String,
    pub hex_layout_config: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub deleted_at: Option<String>,
    pub deleted_by: Option<String>,
}

impl WorkspaceProfileSnapshot {
    /// Whether the profile has been hidden from active Workspace reads.
    #[must_use]
    pub const fn is_deleted(&self) -> bool {
        self.deleted_at.is_some()
    }
}

/// Invalid or unavailable Workspace profile persistence state.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceProfileStoreError {
    #[error(transparent)]
    Database(#[from] DbError),

    #[error("Workspace profile is missing required data: {0}")]
    InvalidField(&'static str),

    #[error("Workspace profile JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),

    #[error("Workspace authority revision is negative")]
    NegativeRevision,
}

/// Read-side and SQL construction helpers for Workspace profile mutations.
pub struct WorkspaceProfileStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceProfileStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Read one scoped profile, including a tombstoned profile for replay.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_profile(
        &self,
        scope: &WorkspaceScope,
    ) -> Result<Option<WorkspaceProfileSnapshot>, WorkspaceProfileStoreError> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT workspace_id, tenant_id, project_id, group_id, name, created_by, \
                 description, is_archived, metadata_json, office_status, \
                 hex_layout_config_json, created_at, updated_at, deleted_at, deleted_by \
                 FROM workspace_profiles WHERE tenant_id = ",
            )
            .bind(scope.tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .build();
        let rows = self.db.query(statement).await?;
        rows.first().map(profile_from_row).transpose()
    }

    /// Read the current authority revision for one scoped Workspace.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_revision(
        &self,
        scope: &WorkspaceScope,
    ) -> Result<Option<u64>, WorkspaceProfileStoreError> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
            .bind(scope.tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .build();
        let rows = self.db.query(statement).await?;
        let Some(row) = rows.first() else {
            return Ok(None);
        };
        let revision = required_i64(row, "revision")?;
        u64::try_from(revision)
            .map(Some)
            .map_err(|_| WorkspaceProfileStoreError::NegativeRevision)
    }

    /// Build the checked profile update for a resolved legacy patch.
    #[must_use]
    pub fn update_mutation(
        &self,
        profile: &WorkspaceProfileSnapshot,
        persisted_at: &str,
    ) -> WorkspaceDomainMutation {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE workspace_profiles SET name = ")
            .bind(profile.name.as_str())
            .push_static(", description = ")
            .bind(profile.description.clone())
            .push_static(", is_archived = ")
            .bind(profile.is_archived)
            .push_static(", metadata_json = ")
            .bind(profile.metadata.to_string())
            .push_static(", updated_at = ")
            .bind(persisted_at)
            .push_static(" WHERE tenant_id = ")
            .bind(profile.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(profile.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(profile.workspace_id.as_str())
            .push_static(" AND deleted_at IS NULL")
            .build();
        WorkspaceDomainMutation::new(statement, DbCountExpectation::exactly(1))
    }

    /// Build the profile tombstone and BCS Group lifecycle mutations.
    #[must_use]
    pub fn delete_mutations(
        &self,
        profile: &WorkspaceProfileSnapshot,
        actor_id: &str,
        persisted_at: &str,
    ) -> Vec<WorkspaceDomainMutation> {
        let profile_tombstone = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE workspace_profiles SET deleted_at = ")
            .bind(persisted_at)
            .push_static(", deleted_by = ")
            .bind(actor_id)
            .push_static(", updated_at = ")
            .bind(persisted_at)
            .push_static(" WHERE tenant_id = ")
            .bind(profile.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(profile.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(profile.workspace_id.as_str())
            .push_static(" AND deleted_at IS NULL")
            .build();
        let group_close = DbStatementBuilder::new(self.flavor)
            .push_static(
                "UPDATE bcs_groups SET status = 'deleted', record_status = 'deleted', \
                 lifecycle_status = 'deleted', gmt_modified = ",
            )
            .bind(persisted_at)
            .push_static(" WHERE group_id = ")
            .bind(profile.group_id.as_str())
            .push_static(" AND env = 'memstack' AND lifecycle_status <> 'deleted'")
            .build();
        vec![
            WorkspaceDomainMutation::new(profile_tombstone, DbCountExpectation::exactly(1)),
            WorkspaceDomainMutation::new(group_close, DbCountExpectation::exactly(1)),
        ]
    }
}

fn profile_from_row(row: &DbRow) -> Result<WorkspaceProfileSnapshot, WorkspaceProfileStoreError> {
    Ok(WorkspaceProfileSnapshot {
        workspace_id: required_string(row, "workspace_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        group_id: required_string(row, "group_id")?,
        name: required_string(row, "name")?,
        created_by: required_string(row, "created_by")?,
        description: optional_string(row, "description")?,
        is_archived: required_bool(row, "is_archived")?,
        metadata: required_json_object(row, "metadata_json")?,
        office_status: required_string(row, "office_status")?,
        hex_layout_config: required_json_object(row, "hex_layout_config_json")?,
        created_at: required_string(row, "created_at")?,
        updated_at: optional_string(row, "updated_at")?,
        deleted_at: optional_string(row, "deleted_at")?,
        deleted_by: optional_string(row, "deleted_by")?,
    })
}

fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceProfileStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceProfileStoreError::InvalidField(column))
}

fn optional_string(
    row: &DbRow,
    column: &'static str,
) -> Result<Option<String>, WorkspaceProfileStoreError> {
    row.get_string(column)
        .map_err(WorkspaceProfileStoreError::from)
}

fn required_i64(row: &DbRow, column: &'static str) -> Result<i64, WorkspaceProfileStoreError> {
    row.get_i64(column)?
        .ok_or(WorkspaceProfileStoreError::InvalidField(column))
}

fn required_bool(row: &DbRow, column: &'static str) -> Result<bool, WorkspaceProfileStoreError> {
    row.get_bool(column)?
        .ok_or(WorkspaceProfileStoreError::InvalidField(column))
}

fn required_json_object(
    row: &DbRow,
    column: &'static str,
) -> Result<Value, WorkspaceProfileStoreError> {
    let raw = required_string(row, column)?;
    let value: Value =
        serde_json::from_str(&raw).map_err(WorkspaceProfileStoreError::InvalidJson)?;
    if value.is_object() {
        Ok(value)
    } else {
        Err(WorkspaceProfileStoreError::InvalidField(column))
    }
}
