use super::*;
use axum::body::{to_bytes, Body};
use axum::http::{Method, Request as HttpRequest};
use tower::ServiceExt;

pub(super) fn example() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../../plugins/marketplace-examples")
}
pub(super) fn fixture() -> (Arc<LocalRuntimeState>, AuthenticatedContext, PathBuf) {
    let mut state = super::super::tests::test_state("market-v3-test");
    let directory = std::env::temp_dir().join(format!("market-v3-test-{}", uuid::Uuid::new_v4()));
    Arc::get_mut(&mut state)
        .expect("unique test state")
        .app_data_dir = Some(directory.clone());
    let auth = state
        .session_store
        .validate_session_credential("market-v3-test", chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    (state, auth, directory)
}
pub(super) async fn request(
    state: Arc<LocalRuntimeState>,
    auth: &AuthenticatedContext,
    method: Method,
    path: &str,
    body: Value,
) -> (StatusCode, Value) {
    let app = router().layer(Extension(auth.clone())).with_state(state);
    let response = app
        .oneshot(
            HttpRequest::builder()
                .method(method)
                .uri(path)
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
    (status, serde_json::from_slice(&bytes).unwrap())
}
#[test]
fn snapshot_is_independent_and_rejects_traversal() {
    let source = example().join("plugins/marketplace-demo");
    let snapshot = std::env::temp_dir().join(format!("market-snapshot-{}", uuid::Uuid::new_v4()));
    package::snapshot(&source, &snapshot).unwrap();
    assert_eq!(
        package::digest(&source).unwrap(),
        package::digest(&snapshot).unwrap()
    );
    assert!(package::child(&snapshot, "../outside").is_err());
    let package = package::parse(&snapshot, "source").unwrap();
    assert!(
        package.descriptor.compatible,
        "{:?}",
        package.descriptor.reasons
    );
    assert_eq!(
        package.descriptor.capabilities,
        vec!["skills", "mcp", "hooks", "apps"]
    );
    assert_eq!(package.hooks.len(), 3);
    std::fs::remove_dir_all(snapshot).unwrap();
}
#[cfg(unix)]
#[test]
fn package_rejects_symbolic_links() {
    let root = std::env::temp_dir().join(format!("market-link-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&root).unwrap();
    std::os::unix::fs::symlink("/etc/passwd", root.join("secret")).unwrap();
    assert!(package::digest(&root).is_err());
    std::fs::remove_dir_all(root).unwrap();
}
#[tokio::test]
async fn local_marketplace_installs_real_mcp_hooks_skills_and_removes_owned_resources() {
    let (state, auth, directory) = fixture();
    let (status, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Examples","kind":"local","location":example(),"trusted":true}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{source}");
    let (_, catalog) = request(
        state.clone(),
        &auth,
        Method::GET,
        "/api/v1/plugin-marketplace/v3/catalog",
        json!({}),
    )
    .await;
    assert_eq!(catalog["items"].as_array().unwrap().len(), 1, "{catalog}");
    let (status, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preflight}");
    let body = json!({"preflight_id":preflight["id"],"approved_permissions":preflight["permissions"],"idempotency_key":"install-1"});
    let (status, installed) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/installations",
        body.clone(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{installed}");
    assert_eq!(installed["status"], "enabled");
    let (_, duplicate) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/installations",
        body,
    )
    .await;
    assert_eq!(installed, duplicate);
    let hooks = hooks::Hooks::capture(
        &state,
        &auth.workspace.tenant_id,
        &auth.workspace.project_id,
    )
    .unwrap();
    for event in ["session_start", "before_request", "after_tool_execute"] {
        hooks.run(event).await.unwrap();
    }
    let id = installed["id"].as_str().unwrap();
    let (status, verified) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/verify"),
        json!({"idempotency_key":"verify-1"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{verified}");
    assert_eq!(verified["status"], "enabled", "{verified}");
    let scope = super::super::mcp_supervisor::McpScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    let servers = state.mcp_supervisor.list_servers(&scope).unwrap();
    assert_eq!(servers.len(), 1);
    let tools = state
        .mcp_supervisor
        .list_tools(&scope, &servers[0].id)
        .await
        .unwrap();
    assert!(!tools.is_empty());
    let outcome = state
        .mcp_supervisor
        .call_tool(
            &scope,
            &servers[0].id,
            "echo",
            json!({"text":"MARKETPLACE_NATIVE_OK"}),
            "market-echo",
        )
        .await
        .unwrap();
    assert!(!outcome.is_error);
    assert_eq!(outcome.content[0]["text"], "MARKETPLACE_NATIVE_OK");
    let apps = state.mcp_supervisor.list_apps(&scope).unwrap();
    assert_eq!(apps.len(), 1);
    let resource = state
        .mcp_supervisor
        .read_resource(&scope, &servers[0].id, "ui://demo/example.html")
        .await
        .unwrap();
    assert!(serde_json::to_string(&resource)
        .unwrap()
        .contains("Marketplace Demo"));
    let (_, disabled) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/disable"),
        json!({"idempotency_key":"disable-1"}),
    )
    .await;
    assert_eq!(disabled["status"], "disabled");
    assert!(!state.mcp_supervisor.list_servers(&scope).unwrap()[0].enabled);
    let mut old = state.mcp_supervisor.list_servers(&scope).unwrap().remove(0);
    old.command[0] = "python3".into();
    state
        .mcp_supervisor
        .update_server(
            &scope,
            &old.id,
            super::super::mcp_supervisor::McpServerDefinitionInput {
                name: old.name,
                description: old.description,
                transport: old.transport,
                command: old.command,
                cwd: old.cwd,
                vault_env_refs: old.vault_env_refs,
                enabled: false,
            },
            old.revision,
            "simulate-older-installation",
        )
        .unwrap();
    let (_, recovered) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/enable"),
        json!({"idempotency_key":"recover-portable-command"}),
    )
    .await;
    assert_eq!(recovered["status"], "enabled", "{recovered}");
    assert!(std::path::Path::new(
        &state.mcp_supervisor.list_servers(&scope).unwrap()[0].command[0]
    )
    .is_absolute());
    let (_, uninstalled) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/uninstall"),
        json!({"idempotency_key":"remove-1"}),
    )
    .await;
    assert_eq!(uninstalled["status"], "uninstalled");
    assert!(state
        .mcp_supervisor
        .list_servers(&scope)
        .unwrap()
        .is_empty());
    assert!(state.mcp_supervisor.list_apps(&scope).unwrap().is_empty());
    assert!(state
        .mcp_supervisor
        .call_tool(
            &scope,
            &servers[0].id,
            "echo",
            json!({"text":"removed"}),
            "after-remove"
        )
        .await
        .is_err());
    let skills = state
        .session_store
        .list_managed_resources(
            super::super::ManagedResourceKind::Skill,
            "project",
            &auth.workspace.project_id,
        )
        .unwrap();
    assert!(!skills.iter().any(|s| s["plugin_id"] == "marketplace-demo"));
    std::fs::remove_dir_all(directory).unwrap();
}
#[tokio::test]
async fn rejects_cross_scope_untrusted_source_and_missing_permission() {
    let (state, auth, directory) = fixture();
    let (status,_)=request(state.clone(),&auth,Method::POST,"/api/v1/plugin-marketplace/v3/sources",json!({"tenant_id":"other","name":"Examples","kind":"local","location":example(),"trusted":true})).await;
    assert_ne!(status, StatusCode::OK);
    let (_, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Examples","kind":"local","location":example(),"trusted":false}),
    )
    .await;
    let (status, _) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    assert_ne!(status, StatusCode::OK);
    std::fs::remove_dir_all(directory).unwrap();
}
