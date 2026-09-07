use std::sync::Arc;

use agistack_adapters_postgres::PgAgentExecutionEventRepository;
use axum::http::StatusCode;

use crate::conversation_authority::test_support::{
    assert_retired_workspace_tables_absent, repository_pool, shared_reader, visible_scope,
    workspace_fixture,
};
use crate::workspace_authority::{
    test_support::FixedWorkspaceAuthority, WorkspaceAuthorityProfile, WorkspaceAuthorityScope,
};

use super::{AgentEventReplayService, PgAgentEventReplayService, ValidatedEventReplayQuery};

fn cursor() -> ValidatedEventReplayQuery {
    ValidatedEventReplayQuery {
        from_time_us: 0,
        from_counter: 0,
        limit: 1,
        event_types: Vec::new(),
    }
}

#[tokio::test]
async fn postgres_standalone_replay_does_not_depend_on_core_or_legacy_tables() {
    let Some(pool) = repository_pool().await else {
        return;
    };
    assert_retired_workspace_tables_absent(&pool).await;
    let Some(scope) = visible_scope(&pool, false).await else {
        return;
    };
    let mut authority = FixedWorkspaceAuthority::new(None, &[]);
    authority.available = false;
    let authority = Arc::new(authority);
    let service = PgAgentEventReplayService::new(
        PgAgentExecutionEventRepository::new(pool),
        authority.clone(),
    );
    service
        .replay_events(&scope.user_id, &scope.id, cursor())
        .await
        .expect("standalone replay must not require Workspace Core");
    assert!(authority.requests.lock().unwrap().is_empty());
    assert_eq!(
        service
            .replay_events("not-a-member", &scope.id, cursor())
            .await
            .unwrap_err()
            .status,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        service
            .replay_events(&scope.user_id, "missing-conversation", cursor())
            .await
            .unwrap_err()
            .status,
        StatusCode::NOT_FOUND
    );
}

#[tokio::test]
async fn postgres_workspace_replay_requires_core_for_owner_and_shared_reader() {
    let Some((pool, scope)) = workspace_fixture().await else {
        return;
    };
    let profile = WorkspaceAuthorityProfile {
        scope: WorkspaceAuthorityScope {
            tenant_id: scope.tenant_id.clone(),
            project_id: scope.project_id.clone(),
            workspace_id: scope.workspace_id.clone().unwrap(),
            is_archived: false,
        },
        name: "Core replay workspace".into(),
        task_linked: true,
    };
    let reader = shared_reader(&pool, &scope).await;
    let mut users = vec![scope.user_id.as_str()];
    if let Some(reader) = reader.as_deref() {
        users.push(reader);
    }
    let authority = Arc::new(FixedWorkspaceAuthority::new(Some(profile.clone()), &users));
    let service = PgAgentEventReplayService::new(
        PgAgentExecutionEventRepository::new(pool.clone()),
        authority.clone(),
    );
    service
        .replay_events(&scope.user_id, &scope.id, cursor())
        .await
        .unwrap();
    if let Some(reader) = reader.as_deref() {
        service
            .replay_events(reader, &scope.id, cursor())
            .await
            .expect("Core-authorized shared reader must replay events");
    } else {
        eprintln!("[skip] shared event reader: no second platform member fixture");
    }
    assert!(
        !authority.requests.lock().unwrap().is_empty(),
        "owner cannot bypass Core"
    );
    for field in [
        "tenant",
        "project",
        "workspace",
        "archive",
        "membership",
        "outage",
    ] {
        let mut candidate = profile.clone();
        match field {
            "tenant" => candidate.scope.tenant_id = "another-tenant".into(),
            "project" => candidate.scope.project_id = "another-project".into(),
            "workspace" => candidate.scope.workspace_id = "another-workspace".into(),
            "archive" => candidate.scope.is_archived = true,
            _ => {}
        }
        let mut authority = FixedWorkspaceAuthority::new(Some(candidate), &users);
        if field == "membership" {
            authority.users.clear();
        }
        if field == "outage" {
            authority.available = false;
        }
        let service = PgAgentEventReplayService::new(
            PgAgentExecutionEventRepository::new(pool.clone()),
            Arc::new(authority),
        );
        let error = service
            .replay_events(&scope.user_id, &scope.id, cursor())
            .await
            .expect_err("invalid Core authority must not replay events");
        assert_eq!(
            error.status,
            if field == "outage" {
                StatusCode::SERVICE_UNAVAILABLE
            } else {
                StatusCode::FORBIDDEN
            }
        );
    }
}
