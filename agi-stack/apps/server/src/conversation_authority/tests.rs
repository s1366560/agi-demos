use agistack_adapters_postgres::ConversationReplayAccess;

use crate::workspace_authority::{
    test_support::FixedWorkspaceAuthority, WorkspaceAuthorityProfile, WorkspaceAuthorityScope,
};

use super::{read_scoped_workspace_profile, resolve_replay_access};

fn profile() -> WorkspaceAuthorityProfile {
    WorkspaceAuthorityProfile {
        scope: WorkspaceAuthorityScope {
            tenant_id: "tenant-1".into(),
            project_id: "project-1".into(),
            workspace_id: "workspace-1".into(),
            is_archived: false,
        },
        name: "Core workspace".into(),
        task_linked: true,
    }
}

fn pending_access() -> ConversationReplayAccess {
    ConversationReplayAccess::WorkspaceAuthorityRequired {
        tenant_id: "tenant-1".into(),
        project_id: "project-1".into(),
        workspace_id: "workspace-1".into(),
    }
}

#[tokio::test]
async fn workspace_replay_requires_exact_live_core_scope() {
    let mut rejected_profiles = vec![None];
    for field in ["tenant", "project", "workspace", "archived", "task"] {
        let mut candidate = profile();
        match field {
            "tenant" => candidate.scope.tenant_id = "another-tenant".into(),
            "project" => candidate.scope.project_id = "another-project".into(),
            "workspace" => candidate.scope.workspace_id = "another-workspace".into(),
            "archived" => candidate.scope.is_archived = true,
            "task" => candidate.task_linked = false,
            _ => unreachable!(),
        }
        rejected_profiles.push(Some(candidate));
    }
    for candidate in rejected_profiles {
        let authority = FixedWorkspaceAuthority::new(candidate, &["member-1"]);
        assert_eq!(
            resolve_replay_access(pending_access(), &authority, "member-1")
                .await
                .unwrap(),
            ConversationReplayAccess::Denied,
        );
    }
    let authority = FixedWorkspaceAuthority::new(Some(profile()), &["member-1"]);
    assert_eq!(
        resolve_replay_access(pending_access(), &authority, "member-1")
            .await
            .unwrap(),
        ConversationReplayAccess::Allowed,
    );
    assert_eq!(
        resolve_replay_access(pending_access(), &authority, "outsider")
            .await
            .unwrap(),
        ConversationReplayAccess::Denied,
    );
}

#[tokio::test]
async fn core_outage_fails_closed_but_standalone_and_denied_access_do_not_call_core() {
    let mut authority = FixedWorkspaceAuthority::new(Some(profile()), &["member-1"]);
    authority.available = false;
    for access in [
        ConversationReplayAccess::Allowed,
        ConversationReplayAccess::Denied,
        ConversationReplayAccess::NotFound,
    ] {
        assert_eq!(
            resolve_replay_access(access.clone(), &authority, "member-1")
                .await
                .unwrap(),
            access,
        );
    }
    assert!(authority.requests.lock().unwrap().is_empty());
    assert!(
        resolve_replay_access(pending_access(), &authority, "member-1")
            .await
            .is_err()
    );
    assert_eq!(authority.requests.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn session_task_link_is_requested_in_the_same_authority_read() {
    let authority = FixedWorkspaceAuthority::new(Some(profile()), &["member-1"]);
    let result = read_scoped_workspace_profile(
        &authority,
        "member-1",
        "tenant-1",
        "project-1",
        "workspace-1",
        Some("task-1"),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(result.name, "Core workspace");
    assert_eq!(
        authority.requests.lock().unwrap().as_slice(),
        &[(
            "member-1".into(),
            "workspace-1".into(),
            Some("task-1".into())
        )],
    );
}
