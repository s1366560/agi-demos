//! Application boundary for structural Workspace Autonomy scheduling.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_store::{
    WorkspaceAutonomyScheduleCandidate, WorkspaceAutonomyScheduleStore,
    WorkspaceAutonomyScheduleStoreError,
};
use thiserror::Error;

/// Public projection of one structurally due autonomous Workspace.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceAutonomyScheduleCandidate {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub actor_id: String,
    pub workspace_revision: u64,
}

/// Stable public schedule-scan failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceAutonomyScheduleError {
    #[error(transparent)]
    Store(#[from] WorkspaceAutonomyScheduleStoreError),
}

/// Read-only structural trigger discovery for the Autonomy scheduler.
pub struct PublicWorkspaceAutonomyScheduleService<'a> {
    store: WorkspaceAutonomyScheduleStore<'a>,
}

impl<'a> PublicWorkspaceAutonomyScheduleService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceAutonomyScheduleStore::new(db, flavor),
        }
    }

    pub async fn list_due(
        &self,
        tick_cutoff: &str,
        limit: i64,
    ) -> Result<Vec<PublicWorkspaceAutonomyScheduleCandidate>, PublicWorkspaceAutonomyScheduleError>
    {
        Ok(self
            .store
            .list_due(tick_cutoff, limit)
            .await?
            .into_iter()
            .map(public_candidate)
            .collect())
    }
}

fn public_candidate(
    candidate: WorkspaceAutonomyScheduleCandidate,
) -> PublicWorkspaceAutonomyScheduleCandidate {
    PublicWorkspaceAutonomyScheduleCandidate {
        tenant_id: candidate.tenant_id,
        project_id: candidate.project_id,
        workspace_id: candidate.workspace_id,
        actor_id: candidate.actor_id,
        workspace_revision: candidate.workspace_revision,
    }
}
