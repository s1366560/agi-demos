use super::tests::{example, fixture, request};
use super::*;
use axum::http::Method;

#[tokio::test]
async fn reopening_runtime_restores_installed_resources_and_hooks() {
    use super::super::{DesktopSessionStore, LocalToolHost, SqliteCheckpointStore};
    let directory = std::env::temp_dir().join(format!("market-restart-{}", uuid::Uuid::new_v4()));
    let create = || {
        let workspace = directory.join("workspace");
        let tool_host = LocalToolHost::new(&workspace).unwrap();
        let sessions = DesktopSessionStore::open(&directory.join("sessions.db")).unwrap();
        let mut state = LocalRuntimeState::new(
            workspace,
            tool_host,
            Arc::new(SqliteCheckpointStore::in_memory().unwrap()),
            "restart-token".into(),
            sessions,
        )
        .unwrap();
        state.app_data_dir = Some(directory.clone());
        Arc::new(state)
    };
    let state = create();
    state
        .session_store
        .seed_test_session("restart-token")
        .unwrap();
    let auth = state
        .session_store
        .validate_session_credential("restart-token", chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let (_, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Example","kind":"local","location":example(),"trusted":true}),
    )
    .await;
    let (_, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    let (_,installation)=request(state.clone(),&auth,Method::POST,"/api/v1/plugin-marketplace/v3/installations",json!({"preflight_id":preflight["id"],"approved_permissions":preflight["permissions"],"idempotency_key":"install"})).await;
    assert_eq!(installation["status"], "enabled", "{installation}");
    let skills = state
        .session_store
        .list_managed_resources(
            super::super::ManagedResourceKind::Skill,
            "project",
            &auth.workspace.project_id,
        )
        .unwrap();
    let mut legacy = skills
        .into_iter()
        .find(|skill| skill["plugin_id"] == "marketplace-demo")
        .unwrap();
    assert_eq!(legacy["tenant_id"], auth.workspace.tenant_id);
    assert_eq!(legacy["project_id"], auth.workspace.project_id);
    assert_eq!(legacy["is_system_skill"], false);
    let skill_id = legacy["id"].as_str().unwrap().to_owned();
    let revision = legacy["revision"].as_u64();
    for key in ["tenant_id", "project_id", "is_system_skill"] {
        legacy.as_object_mut().unwrap().remove(key);
    }
    state
        .session_store
        .put_managed_resource(
            super::super::ManagedResourceKind::Skill,
            "project",
            &auth.workspace.project_id,
            &skill_id,
            "active",
            revision,
            legacy,
            chrono::Utc::now().timestamp_millis(),
        )
        .unwrap();
    drop(state);
    let reopened = create();
    recovery::recover(&reopened).unwrap();
    let repaired = reopened
        .session_store
        .managed_resource(
            super::super::ManagedResourceKind::Skill,
            "project",
            &auth.workspace.project_id,
            &skill_id,
        )
        .unwrap()
        .unwrap();
    assert_eq!(repaired["tenant_id"], auth.workspace.tenant_id);
    assert_eq!(repaired["project_id"], auth.workspace.project_id);
    assert_eq!(repaired["is_system_skill"], false);
    let (_, restored) = request(
        reopened.clone(),
        &auth,
        Method::GET,
        "/api/v1/plugin-marketplace/v3/installations",
        json!({}),
    )
    .await;
    assert_eq!(restored["items"][0]["id"], installation["id"]);
    let id = installation["id"].as_str().unwrap();
    let (_, verified) = request(
        reopened.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/verify"),
        json!({"idempotency_key":"after-restart"}),
    )
    .await;
    assert_eq!(verified["status"], "enabled", "{verified}");
    hooks::Hooks::capture(
        &reopened,
        &auth.workspace.tenant_id,
        &auth.workspace.project_id,
    )
    .unwrap()
    .run("session_start")
    .await
    .unwrap();
    request(
        reopened.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/uninstall"),
        json!({"idempotency_key":"cleanup"}),
    )
    .await;
    drop(reopened);
    std::fs::remove_dir_all(directory).unwrap();
}

#[tokio::test]
async fn credentials_use_application_vault_and_are_retired_on_uninstall() {
    let (state, auth, directory) = fixture();
    let vault = crate::application_vault::ApplicationCredentialVault::open(&directory).unwrap();
    state
        .mcp_supervisor
        .install_credential_vault(vault.clone())
        .unwrap();
    let source_root = directory.join("source");
    package::snapshot(&example().join("plugins/marketplace-demo"), &source_root).unwrap();
    let mcp = source_root.join(".mcp.json");
    let mut config = package::bounded_json(&mcp).unwrap();
    config["mcpServers"]["demo"]["env"] = json!({"DEMO_SECRET":"${DEMO_SECRET}"});
    std::fs::write(mcp, config.to_string()).unwrap();
    let (_, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Credential example","kind":"local","location":source_root,"trusted":true}),
    )
    .await;
    let (_, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    let (_,installation)=request(state.clone(),&auth,Method::POST,"/api/v1/plugin-marketplace/v3/installations",json!({"preflight_id":preflight["id"],"approved_permissions":preflight["permissions"],"idempotency_key":"install"})).await;
    assert_eq!(installation["status"], "needs_configuration");
    assert_eq!(installation["required_credentials"], json!(["DEMO_SECRET"]));
    let id = installation["id"].as_str().unwrap();
    let (status,configured)=request(state.clone(),&auth,Method::POST,&format!("/api/v1/plugin-marketplace/v3/installations/{id}/configure"),json!({"credentials":{"DEMO_SECRET":"test-secret-never-serialize"},"idempotency_key":"configure"})).await;
    assert_eq!(status, StatusCode::OK, "{configured}");
    assert_eq!(configured["status"], "enabled", "{configured}");
    assert!(!configured
        .to_string()
        .contains("test-secret-never-serialize"));
    let scope = super::super::mcp_supervisor::McpScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    let server = state.mcp_supervisor.list_servers(&scope).unwrap().remove(0);
    let reference = server.vault_env_refs["DEMO_SECRET"].clone();
    assert!(vault.get(&reference).unwrap().is_some());
    let saved =
        std::fs::read_to_string(auth_root(&state, &auth).unwrap().join("state.json")).unwrap();
    assert!(!saved.contains("test-secret-never-serialize"));
    let (_, old_lease) = state.mcp_supervisor.acquire_catalog(&scope).unwrap();
    let manifest = source_root.join(".codex-plugin/plugin.json");
    let mut value = package::bounded_json(&manifest).unwrap();
    value["version"] = json!("2.0.0");
    std::fs::write(&manifest, value.to_string()).unwrap();
    let (_, next) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    assert_eq!(
        next["required_credentials"],
        json!([]),
        "existing credentials are reused internally"
    );
    let (status,updated)=request(state.clone(),&auth,Method::POST,&format!("/api/v1/plugin-marketplace/v3/installations/{id}/update"),json!({"preflight_id":next["id"],"approved_permissions":next["permissions"],"idempotency_key":"update-with-inherited-secret"})).await;
    assert_eq!(status, StatusCode::OK, "{updated}");
    assert_eq!(updated["version"], "2.0.0");
    assert_eq!(updated["status"], "enabled");
    let current = state.mcp_supervisor.list_servers(&scope).unwrap().remove(0);
    let current_reference = current.vault_env_refs["DEMO_SECRET"].clone();
    assert_ne!(reference, current_reference);
    assert!(
        vault.get(&reference).unwrap().is_some(),
        "old lease retains old vault binding"
    );
    assert!(vault.get(&current_reference).unwrap().is_some());
    drop(old_lease);
    assert!(vault.get(&reference).unwrap().is_none());
    let mut config = package::bounded_json(&source_root.join(".mcp.json")).unwrap();
    config["mcpServers"]["demo"]["env"]["NEW_SECRET"] = json!("${NEW_SECRET}");
    std::fs::write(source_root.join(".mcp.json"), config.to_string()).unwrap();
    let (_, pending) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    assert_eq!(pending["needs_configuration"], true);
    assert_eq!(pending["required_credentials"], json!(["NEW_SECRET"]));
    let (status, error) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/configure"),
        json!({"credentials":{"DEMO_SECRET":"different-secret"},"idempotency_key":"configure"}),
    )
    .await;
    assert_ne!(status, StatusCode::OK);
    assert!(error["detail"].as_str().unwrap().contains("idempotency"));
    request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/uninstall"),
        json!({"idempotency_key":"cleanup"}),
    )
    .await;
    assert!(vault.get(&reference).unwrap().is_none());
    assert!(vault.get(&current_reference).unwrap().is_none());
    std::fs::remove_dir_all(directory).unwrap();
}

#[tokio::test]
async fn update_failure_retains_working_version_and_snapshot_tampering_is_rejected() {
    let (state, auth, directory) = fixture();
    let source_root = directory.join("source");
    package::snapshot(&example().join("plugins/marketplace-demo"), &source_root).unwrap();
    let (_, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Mutable example","kind":"local","location":source_root,"trusted":true}),
    )
    .await;
    let (_, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    let (_,installation)=request(state.clone(),&auth,Method::POST,"/api/v1/plugin-marketplace/v3/installations",json!({"preflight_id":preflight["id"],"approved_permissions":preflight["permissions"],"idempotency_key":"first-install"})).await;
    assert_eq!(installation["status"], "enabled", "{installation}");
    let manifest_path = source_root.join(".codex-plugin/plugin.json");
    let mut manifest = package::bounded_json(&manifest_path).unwrap();
    manifest["version"] = json!("2.0.0");
    std::fs::write(manifest_path, manifest.to_string()).unwrap();
    std::fs::write(
        source_root.join(".mcp.json"),
        json!({"mcpServers":{"demo":{"command":"/usr/bin/false"}}}).to_string(),
    )
    .unwrap();
    let (_, next) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    let id = installation["id"].as_str().unwrap();
    let (status,_)=request(state.clone(),&auth,Method::POST,&format!("/api/v1/plugin-marketplace/v3/installations/{id}/update"),json!({"preflight_id":next["id"],"approved_permissions":next["permissions"],"idempotency_key":"failed-update"})).await;
    assert_ne!(status, StatusCode::OK);
    let persisted = load(&auth_root(&state, &auth).unwrap()).unwrap();
    assert_eq!(persisted.installations[0].version, "1.0.0");
    assert_eq!(persisted.installations[0].status, "enabled");
    resources::verify(&state, &auth, &persisted.installations[0])
        .await
        .unwrap();
    let pinned = &persisted.preflights[next["id"].as_str().unwrap()]
        .package
        .root;
    std::fs::write(pinned.join("README.md"), "changed after approval").unwrap();
    let (status,error)=request(state.clone(),&auth,Method::POST,&format!("/api/v1/plugin-marketplace/v3/installations/{id}/update"),json!({"preflight_id":next["id"],"approved_permissions":next["permissions"],"idempotency_key":"tampered-update"})).await;
    assert_ne!(status, StatusCode::OK);
    assert!(error["detail"]
        .as_str()
        .unwrap()
        .contains("snapshot changed"));
    request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/uninstall"),
        json!({"idempotency_key":"cleanup"}),
    )
    .await;
    std::fs::remove_dir_all(directory).unwrap();
}

#[tokio::test]
async fn refuses_missing_permissions_and_idempotency_reuse() {
    let (state, auth, directory) = fixture();
    let (_, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Example","kind":"local","location":example(),"trusted":true}),
    )
    .await;
    let (_, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    let (status,error)=request(state.clone(),&auth,Method::POST,"/api/v1/plugin-marketplace/v3/installations",json!({"preflight_id":preflight["id"],"approved_permissions":[],"idempotency_key":"missing-permission"})).await;
    assert_ne!(status, StatusCode::OK);
    assert!(error["detail"].as_str().unwrap().contains("permissions"));
    let (_,installation)=request(state.clone(),&auth,Method::POST,"/api/v1/plugin-marketplace/v3/installations",json!({"preflight_id":preflight["id"],"approved_permissions":preflight["permissions"],"idempotency_key":"valid"})).await;
    let id = installation["id"].as_str().unwrap();
    let (status, error) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/disable"),
        json!({"idempotency_key":"valid"}),
    )
    .await;
    assert_ne!(status, StatusCode::OK);
    assert!(error["detail"].as_str().unwrap().contains("idempotency"));
    request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/uninstall"),
        json!({"idempotency_key":"cleanup"}),
    )
    .await;
    std::fs::remove_dir_all(directory).unwrap();
}
