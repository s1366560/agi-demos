use super::tests::{example, fixture, request};
use super::*;
use crate::local_runtime::mcp_supervisor::McpScope;
use axum::http::Method;

#[tokio::test]
async fn candidate_verification_collects_all_pages_without_publishing_the_generation() {
    let (state, auth, directory) = fixture();
    let source = directory.join("candidate-source");
    package::snapshot(&example().join("plugins/marketplace-demo"), &source).unwrap();
    let script = include_str!("../mcp_supervisor/protocol_fixture.py")
        .replace("mode = sys.argv[1]", "mode = 'normal'")
        .replace(
            "root = Path(__file__).parent",
            &format!("root = Path({})", json!(directory)),
        )
        .replace(
            "\"annotations\": {\"readOnlyHint\": True}",
            "\"annotations\": {\"readOnlyHint\": True}, \"_meta\": {\"ui\": {\"resourceUri\": \"ui://candidate/view.html\"}}",
        );
    std::fs::write(source.join("scripts/demo_mcp.py"), script).unwrap();
    let (status, registered) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Candidate","kind":"local","location":source,"trusted":true}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{registered}");
    let (status, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":registered["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preflight}");
    let package = load(&auth_root(&state, &auth).unwrap())
        .unwrap()
        .preflights
        .remove(preflight["id"].as_str().unwrap())
        .unwrap()
        .package;
    let descriptor = &package.descriptor;
    let mut installation = Installation {
        id: uuid::Uuid::new_v4().to_string(),
        plugin_id: descriptor.id.clone(),
        source_id: descriptor.source_id.clone(),
        name: descriptor.name.clone(),
        version: descriptor.version.clone(),
        status: "downloaded".into(),
        capabilities: descriptor.capabilities.clone(),
        error: None,
        permissions: descriptor.permissions.clone(),
        package,
        server_ids: vec![],
        skill_ids: vec![],
        oauth_services: vec![],
    };
    resources::register(&state, &auth, &mut installation).unwrap();
    resources::set_enabled(&state, &auth, &mut installation, true).unwrap();
    let scope = McpScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    let id = &installation.server_ids[0];
    assert!(state
        .mcp_supervisor
        .list_servers(&scope)
        .unwrap()
        .is_empty());
    assert_eq!(
        state
            .mcp_supervisor
            .list_tools(&scope, id)
            .await
            .unwrap_err()
            .reason_code(),
        "local_mcp_generation_inactive"
    );

    let snapshot_digest = package::digest(&installation.package.root).unwrap();
    resources::verify(&state, &auth, &installation)
        .await
        .unwrap();
    assert_eq!(
        package::digest(&installation.package.root).unwrap(),
        snapshot_digest
    );

    let server = state.mcp_supervisor.server(&scope, id).unwrap().unwrap();
    assert_eq!(
        server
            .discovered_tools
            .iter()
            .map(|tool| tool["name"].as_str().unwrap())
            .collect::<Vec<_>>(),
        ["read_record", "write_record"]
    );
    assert!(!state.mcp_supervisor.marketplace_server_active(id));
    assert!(state
        .mcp_supervisor
        .list_servers(&scope)
        .unwrap()
        .is_empty());
    let (servers, lease) = state.mcp_supervisor.acquire_catalog(&scope).unwrap();
    assert!(servers.is_empty());
    assert!(state
        .mcp_supervisor
        .apps_pinned(&lease, &scope)
        .unwrap()
        .is_empty());
    drop(lease);
    resources::publish(&state, &auth, &installation, None).unwrap();
    let (servers, lease) = state.mcp_supervisor.acquire_catalog(&scope).unwrap();
    assert_eq!(servers.len(), 1);
    assert_eq!(
        state
            .mcp_supervisor
            .apps_pinned(&lease, &scope)
            .unwrap()
            .len(),
        1
    );
    drop(lease);
    resources::remove(&state, &auth, &mut installation).unwrap();
    std::fs::remove_dir_all(directory).unwrap();
}
