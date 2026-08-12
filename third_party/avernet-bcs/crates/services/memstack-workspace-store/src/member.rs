//! Dialect-aware Workspace member reads and checked roster mutations.

use bcs_db_api::{DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatementBuilder};
use memstack_workspace_service_api::{WorkspaceMemberRole, WorkspaceScope};
use thiserror::Error;

use crate::{WorkspaceDomainMutation, WorkspaceProfileSnapshot};

/// Persisted Workspace member used to build compatible responses and events.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceMemberSnapshot {
    pub member_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub participant_actor_id: String,
    pub role: WorkspaceMemberRole,
    pub invited_by: Option<String>,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Invalid or unavailable Workspace member persistence state.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceMemberStoreError {
    #[error(transparent)]
    Database(#[from] DbError),

    #[error("Workspace member is missing required data: {0}")]
    InvalidField(&'static str),

    #[error("Workspace member role is invalid")]
    InvalidRole,
}

/// Read-side and SQL construction helpers for Workspace ACL and BCS roster writes.
pub struct WorkspaceMemberStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceMemberStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Read one scoped member by its legacy user identifier.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_member(
        &self,
        scope: &WorkspaceScope,
        user_id: &str,
    ) -> Result<Option<WorkspaceMemberSnapshot>, WorkspaceMemberStoreError> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT member_id, workspace_id, user_id, participant_actor_id, role, invited_by, \
                 created_at, updated_at FROM workspace_members WHERE tenant_id = ",
            )
            .bind(scope.tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .push_static(" AND user_id = ")
            .bind(user_id)
            .build();
        let rows = self.db.query(statement).await?;
        rows.first().map(member_from_row).transpose()
    }

    /// Whether the target user is active in the mirrored Project membership authority.
    ///
    /// # Errors
    ///
    /// Returns a database error.
    pub async fn has_project_membership(
        &self,
        scope: &WorkspaceScope,
        user_id: &str,
    ) -> Result<bool, WorkspaceMemberStoreError> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT 1 AS allowed FROM project_principal_memberships WHERE tenant_id = ",
            )
            .bind(scope.tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND user_id = ")
            .bind(user_id)
            .push_static(" AND is_active = TRUE LIMIT 1")
            .build();
        Ok(!self.db.query(statement).await?.is_empty())
    }

    /// Build checked member and human participant inserts.
    #[must_use]
    pub fn add_mutations(
        &self,
        scope: &WorkspaceScope,
        profile: &WorkspaceProfileSnapshot,
        member: &WorkspaceMemberSnapshot,
        persisted_at: &str,
    ) -> Vec<WorkspaceDomainMutation> {
        let member_insert = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, \
                 user_id, participant_actor_id, role, invited_by, created_at, updated_at) SELECT ",
            )
            .bind(member.member_id.as_str())
            .push_static(", ")
            .bind(scope.tenant_id().as_str())
            .push_static(", ")
            .bind(scope.project_id().as_str())
            .push_static(", ")
            .bind(scope.workspace_id().as_str())
            .push_static(", ")
            .bind(member.user_id.as_str())
            .push_static(", ")
            .bind(member.participant_actor_id.as_str())
            .push_static(", ")
            .bind(member.role.as_str())
            .push_static(", ")
            .bind(member.invited_by.clone())
            .push_static(", ")
            .bind(persisted_at)
            .push_static(", ")
            .bind(persisted_at)
            .push_static(
                " WHERE EXISTS (SELECT 1 FROM project_principal_memberships WHERE tenant_id = ",
            )
            .bind(scope.tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND user_id = ")
            .bind(member.user_id.as_str())
            .push_static(" AND is_active = TRUE)")
            .build();
        let participant_insert = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_group_participants \
                 (group_id, bot_uuid, role, env, actor_kind, mode) VALUES (",
            )
            .bind(profile.group_id.as_str())
            .push_static(", ")
            .bind(member.participant_actor_id.as_str())
            .push_static(", ")
            .bind(member.role.as_str())
            .push_static(", 'memstack', 'human', 'auto')")
            .build();
        vec![
            WorkspaceDomainMutation::new(member_insert, DbCountExpectation::exactly(1)),
            WorkspaceDomainMutation::new(participant_insert, DbCountExpectation::exactly(1)),
        ]
    }

    /// Build checked ACL and BCS participant role updates.
    #[must_use]
    pub fn update_role_mutations(
        &self,
        scope: &WorkspaceScope,
        profile: &WorkspaceProfileSnapshot,
        member: &WorkspaceMemberSnapshot,
        actor_id: &str,
        persisted_at: &str,
    ) -> Vec<WorkspaceDomainMutation> {
        let member_update = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE workspace_members SET role = ")
            .bind(member.role.as_str())
            .push_static(", updated_at = ")
            .bind(persisted_at)
            .push_static(" WHERE tenant_id = ")
            .bind(scope.tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .push_static(" AND user_id = ")
            .bind(member.user_id.as_str())
            .push_static(" AND NOT (user_id = ")
            .bind(actor_id)
            .push_static(" AND role = 'owner' AND ")
            .bind(member.role.as_str())
            .push_static(" <> 'owner')")
            .build();
        let participant_update = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_group_participants SET role = ")
            .bind(member.role.as_str())
            .push_static(", gmt_modified = ")
            .bind(persisted_at)
            .push_static(" WHERE group_id = ")
            .bind(profile.group_id.as_str())
            .push_static(" AND env = 'memstack' AND bot_uuid = ")
            .bind(member.participant_actor_id.as_str())
            .push_static(" AND actor_kind = 'human'")
            .build();
        vec![
            WorkspaceDomainMutation::new(member_update, DbCountExpectation::exactly(1)),
            WorkspaceDomainMutation::new(participant_update, DbCountExpectation::exactly(1)),
        ]
    }

    /// Build checked human participant and ACL removal mutations.
    #[must_use]
    pub fn remove_mutations(
        &self,
        scope: &WorkspaceScope,
        profile: &WorkspaceProfileSnapshot,
        member: &WorkspaceMemberSnapshot,
        actor_id: &str,
    ) -> Vec<WorkspaceDomainMutation> {
        let participant_delete = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_group_participants WHERE group_id = ")
            .bind(profile.group_id.as_str())
            .push_static(" AND env = 'memstack' AND bot_uuid = ")
            .bind(member.participant_actor_id.as_str())
            .push_static(" AND actor_kind = 'human'")
            .build();
        let member_delete = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM workspace_members WHERE tenant_id = ")
            .bind(scope.tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .push_static(" AND user_id = ")
            .bind(member.user_id.as_str())
            .push_static(" AND (role <> 'owner' OR (user_id = ")
            .bind(actor_id)
            .push_static(
                " AND EXISTS (SELECT 1 FROM workspace_members other WHERE \
                 other.workspace_id = workspace_members.workspace_id \
                 AND other.role = 'owner' AND other.user_id <> workspace_members.user_id)))",
            )
            .build();
        vec![
            WorkspaceDomainMutation::new(participant_delete, DbCountExpectation::exactly(1)),
            WorkspaceDomainMutation::new(member_delete, DbCountExpectation::exactly(1)),
        ]
    }
}

fn member_from_row(row: &DbRow) -> Result<WorkspaceMemberSnapshot, WorkspaceMemberStoreError> {
    let role = WorkspaceMemberRole::parse(&required_string(row, "role")?)
        .map_err(|_| WorkspaceMemberStoreError::InvalidRole)?;
    Ok(WorkspaceMemberSnapshot {
        member_id: required_string(row, "member_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        user_id: required_string(row, "user_id")?,
        participant_actor_id: required_string(row, "participant_actor_id")?,
        role,
        invited_by: optional_string(row, "invited_by")?,
        created_at: required_string(row, "created_at")?,
        updated_at: optional_string(row, "updated_at")?,
    })
}

fn required_string(row: &DbRow, column: &'static str) -> Result<String, WorkspaceMemberStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceMemberStoreError::InvalidField(column))
}

fn optional_string(
    row: &DbRow,
    column: &'static str,
) -> Result<Option<String>, WorkspaceMemberStoreError> {
    row.get_string(column)
        .map_err(WorkspaceMemberStoreError::from)
}
