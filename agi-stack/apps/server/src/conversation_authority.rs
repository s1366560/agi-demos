//! Compose platform conversation facts with the sole Workspace Core authority.

use agistack_adapters_postgres::ConversationReplayAccess;

use crate::workspace_authority::{
    WorkspaceAuthority, WorkspaceAuthorityError, WorkspaceAuthorityProfile,
};

pub(crate) async fn resolve_replay_access(
    access: ConversationReplayAccess,
    authority: &dyn WorkspaceAuthority,
    user_id: &str,
) -> Result<ConversationReplayAccess, WorkspaceAuthorityError> {
    match access {
        ConversationReplayAccess::WorkspaceAuthorityRequired {
            tenant_id,
            project_id,
            workspace_id,
        } => {
            let profile = read_scoped_workspace_profile(
                authority,
                user_id,
                &tenant_id,
                &project_id,
                &workspace_id,
                None,
            )
            .await?;
            Ok(if profile.is_some() {
                ConversationReplayAccess::Allowed
            } else {
                ConversationReplayAccess::Denied
            })
        }
        access => Ok(access),
    }
}

pub(crate) async fn read_scoped_workspace_profile(
    authority: &dyn WorkspaceAuthority,
    user_id: &str,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    task_id: Option<&str>,
) -> Result<Option<WorkspaceAuthorityProfile>, WorkspaceAuthorityError> {
    let Some(profile) = authority
        .read_profile(user_id, workspace_id, task_id)
        .await?
    else {
        return Ok(None);
    };
    if profile.scope.tenant_id != tenant_id
        || profile.scope.project_id != project_id
        || profile.scope.workspace_id != workspace_id
        || profile.scope.is_archived
        || !profile.task_linked
    {
        return Ok(None);
    }
    Ok(Some(profile))
}

#[cfg(test)]
mod tests;

#[cfg(test)]
pub(crate) mod test_support;
