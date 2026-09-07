use std::sync::Arc;

use axum::http::StatusCode;
use serde_json::{json, Value};

use crate::conversation_authority::test_support::{
    assert_retired_workspace_tables_absent, repository_pool, shared_reader, visible_scope,
    workspace_fixture, VisibleConversationScope,
};
use crate::workspace_authority::{
    test_support::FixedWorkspaceAuthority, WorkspaceAuthorityProfile, WorkspaceAuthorityScope,
};

use super::{ConversationSessionQuery, PgConversationSessionProjectionService};

fn query(scope: &VisibleConversationScope) -> ConversationSessionQuery {
    ConversationSessionQuery {
        tenant_id: scope.tenant_id.clone(),
        project_id: scope.project_id.clone(),
        workspace_id: scope.workspace_id.clone(),
    }
}

fn profile(scope: &VisibleConversationScope) -> WorkspaceAuthorityProfile {
    WorkspaceAuthorityProfile {
        scope: WorkspaceAuthorityScope {
            tenant_id: scope.tenant_id.clone(),
            project_id: scope.project_id.clone(),
            workspace_id: scope.workspace_id.clone().unwrap(),
            is_archived: false,
        },
        name: "Core authority fixture workspace".into(),
        task_linked: true,
    }
}

fn assert_retired_projection_empty(payload: &Value) {
    assert_eq!(payload["execution"]["attempt_history"], json!([]));
    assert_eq!(payload["execution"]["current_attempt"], Value::Null);
    assert_eq!(payload["workspace_plan_context"], Value::Null);
}

pub(super) async fn assert_standalone_projection_after_workspace_retirement() {
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
    let service = PgConversationSessionProjectionService::new(pool, authority.clone());
    let projection = service
        .get_projection(&scope.user_id, &scope.id, &query(&scope))
        .await
        .expect("standalone session must not query retired Workspace tables")
        .expect("visible standalone session");
    let payload = serde_json::to_value(projection).unwrap();
    assert_eq!(payload["conversation"]["current_mode"], scope.current_mode);
    assert_eq!(payload["conversation"]["workspace_name"], Value::Null);
    assert_retired_projection_empty(&payload);
    assert!(
        authority.requests.lock().unwrap().is_empty(),
        "standalone session must not depend on Core"
    );
    assert_wrong_scopes_denied(&service, &scope).await;
}

async fn assert_wrong_scopes_denied(
    service: &PgConversationSessionProjectionService,
    scope: &VisibleConversationScope,
) {
    for denied_query in [
        ConversationSessionQuery {
            tenant_id: "not-the-visible-tenant".into(),
            ..query(scope)
        },
        ConversationSessionQuery {
            project_id: "not-the-visible-project".into(),
            ..query(scope)
        },
        ConversationSessionQuery {
            workspace_id: Some("not-the-visible-workspace".into()),
            ..query(scope)
        },
    ] {
        assert!(service
            .get_projection(&scope.user_id, &scope.id, &denied_query)
            .await
            .expect("wrong scope must fail closed without a database error")
            .is_none());
    }
    if scope.workspace_id.is_some() {
        assert!(service
            .get_projection(
                &scope.user_id,
                &scope.id,
                &ConversationSessionQuery {
                    workspace_id: None,
                    ..query(scope)
                }
            )
            .await
            .unwrap()
            .is_none());
    }
    assert!(service
        .get_projection("not-the-visible-user", &scope.id, &query(scope))
        .await
        .expect("unknown user must fail closed")
        .is_none());
}

#[tokio::test]
async fn postgres_workspace_projection_reads_core_profile_and_task_link_without_legacy_tables() {
    let Some((pool, scope)) = workspace_fixture().await else {
        return;
    };
    let reader = shared_reader(&pool, &scope).await;
    let mut users = vec![scope.user_id.as_str()];
    if let Some(reader) = reader.as_deref() {
        users.push(reader);
    }
    let authority = Arc::new(FixedWorkspaceAuthority::new(Some(profile(&scope)), &users));
    let service = PgConversationSessionProjectionService::new(pool.clone(), authority.clone());
    let projection = service
        .get_projection(&scope.user_id, &scope.id, &query(&scope))
        .await
        .expect("Core-backed session must not query retired tables")
        .unwrap();
    let payload = serde_json::to_value(projection).unwrap();
    assert_eq!(
        payload["conversation"]["workspace_name"],
        "Core authority fixture workspace"
    );
    assert_eq!(payload["conversation"]["current_mode"], scope.current_mode);
    assert_retired_projection_empty(&payload);
    assert_eq!(
        authority.requests.lock().unwrap().as_slice(),
        &[(
            scope.user_id.clone(),
            scope.workspace_id.clone().unwrap(),
            scope.linked_workspace_task_id.clone(),
        )]
    );
    assert_wrong_scopes_denied(&service, &scope).await;
    if let Some(reader) = reader {
        let shared = service
            .get_projection(&reader, &scope.id, &query(&scope))
            .await
            .expect("Core-authorized shared reader must resolve")
            .unwrap();
        let payload = serde_json::to_value(shared).unwrap();
        assert_eq!(payload["capabilities"]["can_send_message"], false);
        assert_eq!(payload["capabilities"]["can_control_execution"], false);
    } else {
        eprintln!("[skip] shared reader projection: no second platform member fixture");
    }
}

#[tokio::test]
async fn postgres_workspace_projection_rejects_core_scope_archive_task_and_outage() {
    let Some((pool, scope)) = workspace_fixture().await else {
        return;
    };
    let valid = profile(&scope);
    let mut invalid = vec![None];
    for field in ["tenant", "project", "workspace", "archive", "task"] {
        let mut candidate = valid.clone();
        match field {
            "tenant" => candidate.scope.tenant_id = "another-tenant".into(),
            "project" => candidate.scope.project_id = "another-project".into(),
            "workspace" => candidate.scope.workspace_id = "another-workspace".into(),
            "archive" => candidate.scope.is_archived = true,
            "task" => candidate.task_linked = false,
            _ => unreachable!(),
        }
        invalid.push(Some(candidate));
    }
    for candidate in invalid {
        let authority = Arc::new(FixedWorkspaceAuthority::new(candidate, &[&scope.user_id]));
        let service = PgConversationSessionProjectionService::new(pool.clone(), authority);
        assert!(service
            .get_projection(&scope.user_id, &scope.id, &query(&scope))
            .await
            .expect("invalid Core scope must deny")
            .is_none());
    }
    let mut unavailable = FixedWorkspaceAuthority::new(Some(valid), &[&scope.user_id]);
    unavailable.available = false;
    let service = PgConversationSessionProjectionService::new(pool, Arc::new(unavailable));
    let error = service
        .get_projection(&scope.user_id, &scope.id, &query(&scope))
        .await
        .expect_err("Core outage must not allow the conversation owner");
    assert_eq!(error.status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(error.detail, "Workspace Core is unavailable");
}
