//! Structural scan authority for autonomous Workspace tick scheduling.

use bcs_db_api::{DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder};
use thiserror::Error;

const MAX_SCHEDULE_LIMIT: i64 = 100;

/// One autonomous Workspace that is structurally due for an Agent judgment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyScheduleCandidate {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub actor_id: String,
    pub workspace_revision: u64,
}

/// Stable schedule-scan failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceAutonomyScheduleStoreError {
    #[error("invalid Workspace Autonomy schedule scan")]
    InvalidScan,
    #[error("persisted Workspace Autonomy schedule record is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite structural Autonomy schedule repository.
pub struct WorkspaceAutonomyScheduleStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceAutonomyScheduleStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// List autonomous Workspaces with an open root, active binding, no open child, and no cooldown.
    pub async fn list_due(
        &self,
        tick_cutoff: &str,
        limit: i64,
    ) -> Result<Vec<WorkspaceAutonomyScheduleCandidate>, WorkspaceAutonomyScheduleStoreError> {
        if tick_cutoff.trim().is_empty()
            || tick_cutoff.chars().count() > 64
            || !(1..=MAX_SCHEDULE_LIMIT).contains(&limit)
        {
            return Err(WorkspaceAutonomyScheduleStoreError::InvalidScan);
        }
        let rows = self
            .db
            .query(schedule_statement(self.flavor, tick_cutoff, limit))
            .await?;
        rows.iter().map(candidate_from_row).collect()
    }
}

fn schedule_statement(flavor: DbSqlFlavor, tick_cutoff: &str, limit: i64) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor).push_static(
        "SELECT profile.tenant_id, profile.project_id, profile.workspace_id, \
             member.user_id AS actor_id, authority.revision AS workspace_revision FROM \
             workspace_profiles profile JOIN workspace_authorities authority ON \
             authority.tenant_id = profile.tenant_id AND authority.project_id = \
             profile.project_id AND authority.workspace_id = profile.workspace_id JOIN \
             workspace_members member ON member.tenant_id = profile.tenant_id AND \
             member.project_id = profile.project_id AND member.workspace_id = \
             profile.workspace_id WHERE profile.deleted_at IS NULL AND \
             profile.is_archived = FALSE AND member.role IN ('owner', 'admin', 'editor') AND ",
    );
    let builder = match flavor {
        DbSqlFlavor::Postgres => {
            builder.push_static("profile.metadata_json ->> 'collaboration_mode' = 'autonomous'")
        }
        DbSqlFlavor::Sqlite => builder.push_static(
            "json_extract(profile.metadata_json, '$.collaboration_mode') = 'autonomous'",
        ),
        DbSqlFlavor::Mysql => builder.push_static("1 = 0"),
    };
    let builder = builder.push_static(
        " AND member.user_id = (SELECT preferred.user_id FROM workspace_members preferred \
         WHERE preferred.tenant_id = profile.tenant_id AND preferred.project_id = \
         profile.project_id AND preferred.workspace_id = profile.workspace_id AND \
         preferred.role IN ('owner', 'admin', 'editor') ORDER BY CASE preferred.role WHEN \
         'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, preferred.created_at ASC, \
         preferred.member_id ASC LIMIT 1) AND EXISTS (SELECT 1 FROM \
         workspace_agent_bindings binding WHERE binding.tenant_id = profile.tenant_id AND \
         binding.project_id = profile.project_id AND binding.workspace_id = \
         profile.workspace_id AND binding.is_active = TRUE) AND EXISTS (SELECT 1 FROM \
         workspace_tasks root WHERE root.tenant_id = profile.tenant_id AND root.project_id = \
         profile.project_id AND root.workspace_id = profile.workspace_id AND \
         root.archived_at IS NULL AND root.status NOT IN ('done', 'blocked') AND ",
    );
    let builder = match flavor {
        DbSqlFlavor::Postgres => {
            builder.push_static("root.metadata_json ->> 'task_role' = 'goal_root'")
        }
        DbSqlFlavor::Sqlite => {
            builder.push_static("json_extract(root.metadata_json, '$.task_role') = 'goal_root'")
        }
        DbSqlFlavor::Mysql => builder.push_static("1 = 0"),
    };
    let builder = builder.push_static(
        " AND NOT EXISTS (SELECT 1 FROM workspace_autonomy_attentions attention WHERE \
         attention.tenant_id = root.tenant_id AND attention.project_id = root.project_id AND \
         attention.workspace_id = root.workspace_id AND attention.root_task_id = root.task_id AND \
         attention.status = 'open') AND NOT EXISTS (SELECT 1 FROM \
         workspace_autonomy_progression_outbox progression \
         WHERE progression.tenant_id = root.tenant_id AND progression.project_id = \
         root.project_id AND progression.workspace_id = root.workspace_id AND \
         progression.root_task_id = root.task_id AND progression.status IN ('pending', \
         'processing', 'dead_letter')) AND NOT EXISTS (SELECT 1 FROM workspace_tasks execution WHERE \
         execution.tenant_id = root.tenant_id AND execution.project_id = root.project_id AND \
         execution.workspace_id = root.workspace_id AND execution.archived_at IS NULL AND \
         execution.status NOT IN ('done', 'blocked') AND ",
    );
    let builder = match flavor {
        DbSqlFlavor::Postgres => builder.push_static(
            "execution.metadata_json ->> 'task_role' = 'execution_task' AND \
             execution.metadata_json ->> 'root_goal_task_id' = root.task_id",
        ),
        DbSqlFlavor::Sqlite => builder.push_static(
            "json_extract(execution.metadata_json, '$.task_role') = 'execution_task' AND \
             json_extract(execution.metadata_json, '$.root_goal_task_id') = root.task_id",
        ),
        DbSqlFlavor::Mysql => builder.push_static("1 = 0"),
    };
    builder
        .push_static(
            ")) AND NOT EXISTS (SELECT 1 FROM workspace_autonomy_ticks recent WHERE \
             recent.tenant_id = profile.tenant_id AND recent.project_id = profile.project_id AND \
             recent.workspace_id = profile.workspace_id AND recent.created_at > ",
        )
        .bind(tick_cutoff)
        .push_static(") ORDER BY profile.created_at ASC, profile.workspace_id ASC LIMIT ")
        .bind(limit)
        .build()
}

fn candidate_from_row(
    row: &DbRow,
) -> Result<WorkspaceAutonomyScheduleCandidate, WorkspaceAutonomyScheduleStoreError> {
    let revision = row.get_i64("workspace_revision")?.ok_or(
        WorkspaceAutonomyScheduleStoreError::InvalidRecord("workspace_revision"),
    )?;
    Ok(WorkspaceAutonomyScheduleCandidate {
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        actor_id: required_string(row, "actor_id")?,
        workspace_revision: u64::try_from(revision).map_err(|_| {
            WorkspaceAutonomyScheduleStoreError::InvalidRecord("workspace_revision")
        })?,
    })
}

fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceAutonomyScheduleStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceAutonomyScheduleStoreError::InvalidRecord(column))
}

#[cfg(test)]
#[path = "autonomy_schedule_sql_tests.rs"]
mod sql_tests;
