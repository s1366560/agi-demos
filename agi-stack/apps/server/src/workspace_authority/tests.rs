use axum::{routing::post, Json, Router};
use serde_json::json;

use super::{CoreWorkspaceAuthority, WorkspaceAuthority};

#[tokio::test]
async fn authorize_accepts_the_current_core_profile_and_task_links_envelope() {
    let app = Router::new().route(
        super::AUTHORITY_QUERY_PATH,
        post(|| async {
            Json(json!({
                "profiles": [{
                    "workspace_id": "workspace-1",
                    "tenant_id": "tenant-1",
                    "project_id": "project-1",
                    "name": "Current Core Workspace",
                    "created_by": "owner-1",
                    "is_archived": false,
                    "metadata": {},
                    "member_role": "viewer"
                }],
                "task_links": []
            }))
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind Core authority fixture");
    let base_url = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move { axum::serve(listener, app).await });
    let authority = CoreWorkspaceAuthority {
        base_url,
        service_token: "test-only-service-token".into(),
        client: reqwest::Client::new(),
    };
    let result = authority.authorize("reader-1", "workspace-1").await;
    server.abort();
    let scope = result
        .expect("the current Core response must decode")
        .expect("visible workspace must be returned");
    assert_eq!(scope.tenant_id, "tenant-1");
    assert_eq!(scope.project_id, "project-1");
    assert_eq!(scope.workspace_id, "workspace-1");
    assert!(!scope.is_archived);
}

fn current_profile() -> serde_json::Value {
    json!({
        "workspace_id": "workspace-1", "tenant_id": "tenant-1", "project_id": "project-1",
        "name": "Core workspace", "created_by": "owner-1", "is_archived": false,
        "metadata": {}, "member_role": "viewer"
    })
}

async fn fixture(
    payload: serde_json::Value,
    status: axum::http::StatusCode,
) -> (CoreWorkspaceAuthority, tokio::task::JoinHandle<()>) {
    let app = Router::new().route(
        super::AUTHORITY_QUERY_PATH,
        post(move || {
            let payload = payload.clone();
            async move { (status, Json(payload)) }
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let authority = CoreWorkspaceAuthority {
        base_url: format!("http://{}", listener.local_addr().unwrap()),
        service_token: "test-only-service-token".into(),
        client: reqwest::Client::new(),
    };
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    (authority, server)
}

#[tokio::test]
async fn profile_lookup_posts_actor_and_exact_task_ref_without_identity_escalation() {
    use std::sync::{Arc, Mutex};
    let requests = Arc::new(Mutex::new(Vec::new()));
    let observed = requests.clone();
    let app = Router::new().route(
        super::AUTHORITY_QUERY_PATH,
        post(
            move |headers: axum::http::HeaderMap, Json(request): Json<serde_json::Value>| {
                let observed = observed.clone();
                async move {
                    assert_eq!(
                        headers.get("authorization").unwrap(),
                        "Bearer test-only-service-token"
                    );
                    observed.lock().unwrap().push(request);
                    Json(json!({"profiles": [current_profile()], "task_links": [{
                        "workspace_id": "workspace-1", "task_id": "task-1", "linked": true
                    }]}))
                }
            },
        ),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let authority = CoreWorkspaceAuthority {
        base_url: format!("http://{}", listener.local_addr().unwrap()),
        service_token: "test-only-service-token".into(),
        client: reqwest::Client::new(),
    };
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    let profile = authority
        .read_profile("reader-1", "workspace-1", Some("task-1"))
        .await
        .unwrap()
        .unwrap();
    server.abort();
    assert_eq!(profile.name, "Core workspace");
    assert!(profile.task_linked);
    assert_eq!(
        requests.lock().unwrap().as_slice(),
        &[json!({
            "actor": {"user_id": "reader-1"}, "workspace_ids": ["workspace-1"],
            "task_refs": [{"workspace_id": "workspace-1", "task_id": "task-1"}]
        })]
    );
}

#[tokio::test]
async fn profile_and_task_decoder_rejects_ambiguous_missing_or_cross_scope_authority() {
    use axum::http::StatusCode;
    let mut other_workspace = current_profile();
    other_workspace["workspace_id"] = json!("another-workspace");
    let mut invalid_tenant = current_profile();
    invalid_tenant["tenant_id"] = json!("");
    for payload in [
        json!({"profiles": [current_profile()]}),
        json!({"profiles": [current_profile(), current_profile()], "task_links": []}),
        json!({"profiles": [other_workspace], "task_links": []}),
        json!({"profiles": [invalid_tenant], "task_links": []}),
        json!({"profiles": [current_profile()], "task_links": [{"workspace_id": "workspace-1", "task_id": "unexpected", "linked": true}]}),
    ] {
        let (authority, server) = fixture(payload, StatusCode::OK).await;
        let result = authority.authorize("reader-1", "workspace-1").await;
        server.abort();
        assert!(result.is_err());
    }
    for links in [
        json!([]),
        json!([{"workspace_id": "another-workspace", "task_id": "task-1", "linked": true}]),
        json!([{"workspace_id": "workspace-1", "task_id": "another-task", "linked": true}]),
        json!([{"workspace_id": "workspace-1", "task_id": "task-1", "linked": "true"}]),
    ] {
        let (authority, server) = fixture(
            json!({"profiles": [current_profile()], "task_links": links}),
            StatusCode::OK,
        )
        .await;
        let result = authority
            .read_profile("reader-1", "workspace-1", Some("task-1"))
            .await;
        server.abort();
        assert!(result.is_err());
    }
    let (authority, server) = fixture(
        json!({"profiles": [], "task_links": []}),
        StatusCode::SERVICE_UNAVAILABLE,
    )
    .await;
    assert!(authority
        .authorize("reader-1", "workspace-1")
        .await
        .is_err());
    server.abort();
}

#[tokio::test]
async fn explicit_core_membership_denial_and_missing_task_are_preserved() {
    let (authority, server) = fixture(
        json!({"profiles": [], "task_links": []}),
        axum::http::StatusCode::OK,
    )
    .await;
    assert!(authority
        .authorize("reader-1", "workspace-1")
        .await
        .unwrap()
        .is_none());
    server.abort();
    let (authority, server) = fixture(
        json!({
            "profiles": [current_profile()], "task_links": [{
                "workspace_id": "workspace-1", "task_id": "task-1", "linked": false
            }]
        }),
        axum::http::StatusCode::OK,
    )
    .await;
    assert!(
        !authority
            .read_profile("reader-1", "workspace-1", Some("task-1"))
            .await
            .unwrap()
            .unwrap()
            .task_linked
    );
    server.abort();
}
