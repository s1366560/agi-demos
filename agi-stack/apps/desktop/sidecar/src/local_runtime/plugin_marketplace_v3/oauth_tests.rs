use super::tests::{example, fixture, request};
use super::*;
use axum::http::Method;
use std::process::Stdio;
struct Origin(Option<String>);
impl Drop for Origin {
    fn drop(&mut self) {
        if let Some(value) = &self.0 {
            std::env::set_var("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN", value)
        } else {
            std::env::remove_var("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN")
        }
    }
}
async fn authorize(client: &reqwest::Client, url: &str, origin: &str) -> String {
    let html = client.get(url).send().await.unwrap().text().await.unwrap();
    let ticket = html
        .split("name=\"ticket\" value=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap();
    let response = client
        .post(format!("{origin}/consent"))
        .form(&[
            ("ticket", ticket),
            ("username", "fixture-user"),
            ("password", "fixture-password"),
            ("decision", "allow"),
        ])
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), reqwest::StatusCode::FOUND);
    response.headers()["location"].to_str().unwrap().to_owned()
}
#[tokio::test]
async fn real_oauth_pkce_callback_refresh_rotation_scope_cancel_and_disconnect() {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    let origin = format!("http://127.0.0.1:{port}");
    let _origin = Origin(std::env::var("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN").ok());
    std::env::set_var("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN", &origin);
    let mut process = tokio::process::Command::new("python3")
        .arg(example().join("oauth-fixture/server.py"))
        .args(["--port", &port.to_string(), "--token-ttl", "2"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .unwrap();
    for _ in 0..100 {
        if client.get(format!("{origin}/health")).send().await.is_ok() {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
    }
    let (state, auth, directory) = fixture();
    let vault = crate::application_vault::ApplicationCredentialVault::open(&directory).unwrap();
    state
        .mcp_supervisor
        .install_credential_vault(vault.clone())
        .unwrap();
    let source_path = directory.join("source");
    package::snapshot(&example().join("oauth-fixture/plugin"), &source_path).unwrap();
    std::fs::write(source_path.join(".mcp.json"),json!({"mcpServers":{"fixture":{"type":"http","url":format!("{origin}/mcp"),"oauth":{"scopes":["mcp:tools"]}}}}).to_string()).unwrap();
    let (_, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"OAuth fixture","kind":"local","location":source_path,"trusted":true}),
    )
    .await;
    let plugin = package::parse(&source_path, "test").unwrap();
    assert!(plugin.descriptor.compatible);
    let (_, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":plugin.descriptor.id}),
    )
    .await;
    let (_,installed)=request(state.clone(),&auth,Method::POST,"/api/v1/plugin-marketplace/v3/installations",json!({"preflight_id":preflight["id"],"approved_permissions":preflight["permissions"],"idempotency_key":"install"})).await;
    assert_eq!(installed["status"], "needs_configuration");
    assert_eq!(installed["oauth_services"][0]["name"], "fixture");
    let id = installed["id"].as_str().unwrap();
    let endpoint = format!("/api/v1/plugin-marketplace/v3/installations/{id}/oauth/fixture");
    // Persisted records created before transport restrictions cannot bypass preflight checks.
    let db_root = auth_root(&state, &auth).unwrap();
    let mut persisted = load(&db_root).unwrap();
    persisted.installations[0]
        .package
        .servers
        .get_mut("fixture")
        .unwrap()["type"] = json!("sse");
    save(&db_root, &persisted).unwrap();
    let (blocked, body) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/start"),
        json!({"idempotency_key":"unsupported"}),
    )
    .await;
    assert_ne!(blocked, StatusCode::OK);
    assert!(body.to_string().contains("oauth_requires_streamable_http"));
    persisted.installations[0]
        .package
        .servers
        .get_mut("fixture")
        .unwrap()["type"] = json!("http");
    save(&db_root, &persisted).unwrap();

    let (code, _) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/start"),
        json!({"tenant_id":"another","idempotency_key":"cross"}),
    )
    .await;
    assert_ne!(code, StatusCode::OK);
    let (_, started) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/start"),
        json!({"idempotency_key":"start"}),
    )
    .await;
    assert_eq!(started["status"], "authorizing", "{started}");
    let (_, replay) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/start"),
        json!({"idempotency_key":"start"}),
    )
    .await;
    assert_eq!(replay, started);
    let (conflict, _) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/start"),
        json!({"idempotency_key":"start","client_id":"changed"}),
    )
    .await;
    assert_ne!(conflict, StatusCode::OK);

    let authorization = started["authorization_url"].as_str().unwrap();
    let parameters = url::Url::parse(authorization)
        .unwrap()
        .query_pairs()
        .into_owned()
        .collect::<BTreeMap<_, _>>();
    assert_eq!(parameters["code_challenge_method"], "S256");
    assert_eq!(parameters["resource"], format!("{origin}/mcp"));
    assert!(
        parameters["client_id"].starts_with("fixture-"),
        "DCR is used without preregistration"
    );
    let redirect = authorize(&client, authorization, &origin).await;
    let mut bad = url::Url::parse(&redirect).unwrap();
    bad.query_pairs_mut().append_pair("state", "wrong");
    assert_eq!(
        client.get(bad).send().await.unwrap().status(),
        reqwest::StatusCode::BAD_REQUEST
    );
    let response = client.get(&redirect).send().await.unwrap();
    assert!(response
        .text()
        .await
        .unwrap()
        .contains("Authorization complete"));
    let (_, status) = request(
        state.clone(),
        &auth,
        Method::GET,
        &format!("{endpoint}/status"),
        json!({}),
    )
    .await;
    assert_eq!(status["status"], "connected", "{status}");
    let scope = super::super::mcp_supervisor::McpScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    let server = state
        .mcp_supervisor
        .list_servers(&scope)
        .unwrap()
        .pop()
        .unwrap();
    let grant_key = vault
        .get(&format!("mcp-oauth-binding:{}", server.id))
        .unwrap()
        .unwrap();
    let mut expired: Value =
        serde_json::from_str(&vault.get(&grant_key).unwrap().unwrap()).unwrap();
    expired["expires_at"] = json!(chrono::Utc::now().timestamp() - 10);
    vault.put(&grant_key, &expired.to_string()).unwrap();
    let expired_status = state.mcp_supervisor.oauth_status(&server.id).unwrap();
    assert_eq!(expired_status["status"], "connected");
    assert_eq!(expired_status["expires_at"], expired["expires_at"]);
    assert_eq!(
        vault.get(&grant_key).unwrap().unwrap(),
        expired.to_string(),
        "status must not refresh or mutate vault"
    );
    let mut no_refresh = expired.clone();
    no_refresh["refresh_token"] = Value::Null;
    vault.put(&grant_key, &no_refresh.to_string()).unwrap();
    assert_eq!(
        state.mcp_supervisor.oauth_status(&server.id).unwrap()["status"],
        "expired"
    );
    vault.put(&grant_key, &expired.to_string()).unwrap();
    let reference = &server.vault_env_refs["Authorization"];
    let before = zeroize::Zeroizing::new(vault.get(reference).unwrap().unwrap());
    let output = state
        .mcp_supervisor
        .call_tool(
            &scope,
            &server.id,
            "echo",
            json!({"text":"oauth-connected"}),
            "oauth-echo",
        )
        .await
        .unwrap();
    assert!(output.result.to_string().contains("oauth-connected"));
    let after = zeroize::Zeroizing::new(vault.get(reference).unwrap().unwrap());
    assert!(
        *before != *after,
        "short-lived grant refreshed before tool dispatch"
    );
    let resources = state
        .mcp_supervisor
        .read_resource(&scope, &server.id, "ui://oauth-fixture/app.html")
        .await
        .unwrap();
    assert!(!resources.is_empty());
    assert!(
        client.get(&redirect).send().await.is_err(),
        "callback listener closes after one successful state consumption"
    );
    let (_, old_lease) = state.mcp_supervisor.acquire_catalog(&scope).unwrap();
    let manifest_path = source_path.join(".codex-plugin/plugin.json");
    let mut manifest = package::bounded_json(&manifest_path).unwrap();
    manifest["version"] = json!("2.0.0");
    std::fs::write(manifest_path, manifest.to_string()).unwrap();
    let (_, next) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":plugin.descriptor.id}),
    )
    .await;
    let (_,updated)=request(state.clone(),&auth,Method::POST,&format!("/api/v1/plugin-marketplace/v3/installations/{id}/update"),json!({"preflight_id":next["id"],"approved_permissions":next["permissions"],"idempotency_key":"oauth-update"})).await;
    assert_eq!(updated["status"], "enabled", "{updated}");
    let old_result = state
        .mcp_supervisor
        .call_tool_pinned(
            &old_lease,
            &scope,
            &server.id,
            "echo",
            json!({"text":"old-oauth-run"}),
            "old-oauth-run",
        )
        .await
        .unwrap();
    assert!(old_result.result.to_string().contains("old-oauth-run"));
    let old_reference = reference.clone();
    drop(old_lease);
    assert!(vault.get(&old_reference).unwrap().is_none());
    let server = state
        .mcp_supervisor
        .list_servers(&scope)
        .unwrap()
        .pop()
        .unwrap();
    let reference = &server.vault_env_refs["Authorization"];
    let result = state
        .mcp_supervisor
        .call_tool(
            &scope,
            &server.id,
            "echo",
            json!({"text":"updated-oauth-run"}),
            "updated-oauth-run",
        )
        .await
        .unwrap();
    assert!(result.result.to_string().contains("updated-oauth-run"));

    // A pending replacement must take precedence even over a still-refreshable old grant.
    let (_, pending_valid) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/start"),
        json!({"idempotency_key":"pending-valid"}),
    )
    .await;
    assert_eq!(pending_valid["status"], "authorizing");
    let (_, pending_status) = request(
        state.clone(),
        &auth,
        Method::GET,
        &format!("{endpoint}/status"),
        json!({}),
    )
    .await;
    assert_eq!(pending_status["status"], "authorizing");
    let mut expired_flow = load(&db_root).unwrap();
    let mut expired_service =
        serde_json::to_value(&expired_flow.installations[0].oauth_services[0]).unwrap();
    expired_service["expires_at"] = json!(chrono::Utc::now().timestamp() - 1);
    expired_flow.installations[0].oauth_services[0] =
        serde_json::from_value(expired_service).unwrap();
    save(&db_root, &expired_flow).unwrap();
    let (_, recovered_status) = request(
        state.clone(),
        &auth,
        Method::GET,
        &format!("{endpoint}/status"),
        json!({}),
    )
    .await;
    assert_eq!(recovered_status["status"], "connected");
    assert_eq!(
        serde_json::to_value(&load(&db_root).unwrap().installations[0].oauth_services[0]).unwrap()
            ["flow"],
        ""
    );

    let mut revoked: Value =
        serde_json::from_str(&vault.get(&grant_key).unwrap().unwrap()).unwrap();
    client
        .post(format!("{origin}/revoke"))
        .form(&[("token", revoked["refresh_token"].as_str().unwrap())])
        .send()
        .await
        .unwrap();
    revoked["expires_at"] = json!(chrono::Utc::now().timestamp() - 1);
    vault.put(&grant_key, &revoked.to_string()).unwrap();
    assert!(state
        .mcp_supervisor
        .oauth_refresh(&server.id)
        .await
        .is_err());
    assert_eq!(
        state.mcp_supervisor.oauth_status(&server.id).unwrap()["status"],
        "expired"
    );
    // Polling reauthorization must not overwrite pending state with the expired old grant.
    let (_, reauthorizing) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/start"),
        json!({"idempotency_key":"reauthorize-expired"}),
    )
    .await;
    assert_eq!(reauthorizing["status"], "authorizing");
    for _ in 0..2 {
        let (_, polled) = request(
            state.clone(),
            &auth,
            Method::GET,
            &format!("{endpoint}/status"),
            json!({}),
        )
        .await;
        assert_eq!(polled["status"], "authorizing");
        assert_eq!(polled["expires_at"], reauthorizing["expires_at"]);
    }
    let reauthorized_redirect = authorize(
        &client,
        reauthorizing["authorization_url"].as_str().unwrap(),
        &origin,
    )
    .await;
    assert!(client
        .get(&reauthorized_redirect)
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap()
        .contains("Authorization complete"));
    let (_, reauthorized_status) = request(
        state.clone(),
        &auth,
        Method::GET,
        &format!("{endpoint}/status"),
        json!({}),
    )
    .await;
    assert_eq!(reauthorized_status["status"], "connected");

    let (_, disconnected) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/disconnect"),
        json!({"idempotency_key":"disconnect"}),
    )
    .await;
    assert_eq!(disconnected["status"], "not_connected");
    assert!(vault.get(reference).unwrap().is_none());
    assert!(state
        .mcp_supervisor
        .call_tool(
            &scope,
            &server.id,
            "echo",
            json!({"text":"denied"}),
            "denied"
        )
        .await
        .is_err());
    let (_, pending) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/start"),
        json!({"idempotency_key":"cancel-start","client_id":"marketplace-fixture"}),
    )
    .await;
    let redirect = authorize(
        &client,
        pending["authorization_url"].as_str().unwrap(),
        &origin,
    )
    .await;
    request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/cancel"),
        json!({"idempotency_key":"cancel"}),
    )
    .await;
    assert!(
        client.get(&redirect).send().await.is_err(),
        "cancel closes the callback listener"
    );
    assert_eq!(
        state.mcp_supervisor.oauth_status(&server.id).unwrap()["status"],
        "not_connected"
    );
    let metadata = std::fs::read_to_string(
        root(
            &state,
            &auth.workspace.tenant_id,
            &auth.workspace.project_id,
        )
        .unwrap()
        .join("state.json"),
    )
    .unwrap();
    assert!(!metadata.contains("access_token") && !metadata.contains("refresh_token"));
    // Uninstall closes pending callback capabilities and removes only owned receipts.
    let (_, pending) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/start"),
        json!({"idempotency_key":"uninstall-pending","client_id":"marketplace-fixture"}),
    )
    .await;
    assert_eq!(pending["status"], "authorizing");
    let pending_url = url::Url::parse(pending["authorization_url"].as_str().unwrap()).unwrap();
    let callback = pending_url
        .query_pairs()
        .find(|(key, _)| key == "redirect_uri")
        .unwrap()
        .1
        .into_owned();
    let mut metadata = load(&db_root).unwrap();
    let old_services = metadata.installations[0].oauth_services.clone();
    let old_receipts = metadata.oauth_receipts.clone();
    let other_id = uuid::Uuid::new_v4().to_string();
    let unrelated_key = format!(
        "{}:{other_id}:fixture:start:key:{id}:tail",
        auth.user.user_id
    );
    metadata.oauth_receipts.insert(
        unrelated_key.clone(),
        ("other".into(), json!({"status":"connected"})),
    );
    save(&db_root, &metadata).unwrap();
    let (status, removed) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/uninstall"),
        json!({"idempotency_key":"uninstall-final"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{removed}");
    let mut metadata = load(&db_root).unwrap();
    assert!(metadata.installations[0].oauth_services.is_empty());
    assert_eq!(metadata.oauth_receipts.len(), 1);
    assert!(metadata.oauth_receipts.contains_key(&unrelated_key));
    tokio::time::sleep(std::time::Duration::from_millis(20)).await;
    assert!(client.get(callback).send().await.is_err());

    // Old persisted tombstones must recover without replaying old success receipts.
    metadata.installations[0].oauth_services = old_services;
    metadata.oauth_receipts.extend(old_receipts);
    save(&db_root, &metadata).unwrap();
    let (status, _) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("{endpoint}/cancel"),
        json!({"idempotency_key":"cancel"}),
    )
    .await;
    assert_ne!(status, StatusCode::OK);
    recover(&state).unwrap();
    let metadata = load(&db_root).unwrap();
    assert!(metadata.installations[0].oauth_services.is_empty());
    assert_eq!(metadata.oauth_receipts.len(), 1);
    assert!(metadata.oauth_receipts.contains_key(&unrelated_key));
    process.kill().await.unwrap();
    drop(state);
    let _ = std::fs::remove_dir_all(directory);
}

#[test]
fn oauth_transport_compatibility_is_structural() {
    let root = std::env::temp_dir().join(format!("oauth-transport-{}", uuid::Uuid::new_v4()));
    package::snapshot(&example().join("oauth-fixture/plugin"), &root).unwrap();
    for transport in ["sse", "websocket", "stdio", "http", "streamable-http"] {
        let config = json!({"mcpServers":{"fixture":{"type":transport,"url":"https://example.com/mcp","oauth":{}}}});
        std::fs::write(root.join(".mcp.json"), config.to_string()).unwrap();
        let package = package::parse(&root, "test").unwrap();
        assert_eq!(
            package.descriptor.compatible,
            matches!(transport, "http" | "streamable-http")
        );
        if !package.descriptor.compatible {
            assert!(package
                .descriptor
                .reasons
                .contains(&"oauth_requires_streamable_http:fixture".into()));
        }
    }
    assert!(!oauth::supported_transport(
        &json!({"command":"python3","url":"https://example.com","oauth":{}})
    ));
    std::fs::remove_dir_all(root).unwrap();
}
