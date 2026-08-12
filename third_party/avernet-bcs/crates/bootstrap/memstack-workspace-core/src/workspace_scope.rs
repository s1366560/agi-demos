//! Trusted Workspace scope resolution for legacy paths that carry only `workspace_id`.

use bcs_db_api::{DbError, DbRow, DbStatementBuilder};
use thiserror::Error;

use super::WorkspaceCoreState;

/// Tenant/project scope resolved from the Workspace authority, never request headers.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct ResolvedWorkspaceScope {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) workspace_id: String,
}

/// Stable resolution failures mapped by each legacy surface to its own envelope.
#[derive(Debug, Error)]
pub(super) enum WorkspaceScopeError {
    #[error("Workspace not found")]
    NotFound,

    #[error("Workspace access required")]
    AccessRequired,

    #[error("Workspace scope record is invalid: {0}")]
    InvalidRecord(&'static str),

    #[error(transparent)]
    Database(#[from] DbError),
}

/// Resolve tenant/project from the persisted Workspace and require caller membership.
///
/// # Errors
///
/// Returns not-found, access, record-decoding, or database failures without
/// accepting tenant/project values from the untrusted compatibility request.
pub(super) async fn resolve_workspace_scope(
    state: &WorkspaceCoreState,
    workspace_id: &str,
    user_id: &str,
) -> Result<ResolvedWorkspaceScope, WorkspaceScopeError> {
    let profiles = state
        .db
        .query(profile_statement(state, workspace_id))
        .await?;
    let profile = exactly_one(profiles.as_slice())?;
    let tenant_id = required_string(profile, "tenant_id")?;
    let project_id = required_string(profile, "project_id")?;
    let membership = state
        .db
        .query(membership_statement(
            state,
            tenant_id.as_str(),
            project_id.as_str(),
            workspace_id,
            user_id,
        ))
        .await?;
    if membership.is_empty() {
        return Err(WorkspaceScopeError::AccessRequired);
    }
    if membership.len() != 1 {
        return Err(WorkspaceScopeError::InvalidRecord("workspace_members"));
    }
    Ok(ResolvedWorkspaceScope {
        tenant_id,
        project_id,
        workspace_id: workspace_id.to_string(),
    })
}

fn profile_statement(state: &WorkspaceCoreState, workspace_id: &str) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(state.sql_flavor)
        .push_static("SELECT tenant_id, project_id FROM workspace_profiles WHERE workspace_id = ")
        .bind(workspace_id)
        .push_static(" AND deleted_at IS NULL")
        .build()
}

fn membership_statement(
    state: &WorkspaceCoreState,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    user_id: &str,
) -> bcs_db_api::DbStatement {
    DbStatementBuilder::new(state.sql_flavor)
        .push_static("SELECT user_id FROM workspace_members WHERE tenant_id = ")
        .bind(tenant_id)
        .push_static(" AND project_id = ")
        .bind(project_id)
        .push_static(" AND workspace_id = ")
        .bind(workspace_id)
        .push_static(" AND user_id = ")
        .bind(user_id)
        .build()
}

fn exactly_one(rows: &[DbRow]) -> Result<&DbRow, WorkspaceScopeError> {
    match rows {
        [] => Err(WorkspaceScopeError::NotFound),
        [row] => Ok(row),
        _ => Err(WorkspaceScopeError::InvalidRecord("workspace_profiles")),
    }
}

fn required_string(row: &DbRow, column: &'static str) -> Result<String, WorkspaceScopeError> {
    row.get_string(column)?
        .filter(|value| !value.trim().is_empty())
        .ok_or(WorkspaceScopeError::InvalidRecord(column))
}
