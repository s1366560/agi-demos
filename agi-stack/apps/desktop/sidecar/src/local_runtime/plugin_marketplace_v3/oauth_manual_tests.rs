use super::*;
use crate::application_vault::ApplicationCredentialVault;
use crate::local_runtime::plugin_marketplace_v3::tests::{example, fixture};
use axum::{
    body::{to_bytes, Body},
    http::{Method, Request},
};
use std::process::Stdio;
use tower::ServiceExt;

struct Origin(Option<String>);
impl Drop for Origin {
    fn drop(&mut self) {
        match &self.0 {
            Some(value) => std::env::set_var("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN", value),
            None => std::env::remove_var("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN"),
        }
    }
}

async fn request(
    state: &Arc<LocalRuntimeState>,
    auth: &AuthenticatedContext,
    method: Method,
    path: &str,
    body: Value,
) -> (StatusCode, Value) {
    let app = router()
        .layer(Extension(auth.clone()))
        .with_state(state.clone());
    let response = app
        .oneshot(
            Request::builder()
                .method(method)
                .uri(path)
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let body = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
    (status, serde_json::from_slice(&body).unwrap())
}

#[tokio::test]
async fn manual_mcp_oauth_uses_real_pkce_vault_and_scoped_revocation() {
    let _origin_lock = crate::local_runtime::plugin_marketplace_v3::oauth_http::TEST_ORIGIN_LOCK
        .lock()
        .await;
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    let origin = format!("http://127.0.0.1:{port}");
    let _origin = Origin(std::env::var("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN").ok());
    std::env::set_var("PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN", &origin);
    let mut process = tokio::process::Command::new("python3")
        .arg(example().join("oauth-fixture/server.py"))
        .args(["--port", &port.to_string(), "--token-ttl", "30"])
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
    let (state, auth, root) = fixture();
    let vault = ApplicationCredentialVault::open(&root).unwrap();
    state
        .mcp_supervisor
        .install_credential_vault(vault.clone())
        .unwrap();
    let scope = scope(&auth);
    let server = state
        .mcp_supervisor
        .create_server(
            &scope,
            McpServerDefinitionInput {
                name: "manual-oauth-fixture".into(),
                description: None,
                transport: McpTransport::Http,
                command: vec![format!("{origin}/mcp")],
                cwd: None,
                vault_env_refs: BTreeMap::new(),
                enabled: true,
            },
            "create-manual",
        )
        .unwrap();
    let base = format!("/api/v1/mcp/{}/oauth", server.id);
    let input = json!({"project_id":scope.project_id,"expected_revision":server.revision,"idempotency_key":"start-one","scopes":["mcp:tools"]});
    let (status, started) = request(
        &state,
        &auth,
        Method::POST,
        &format!("{base}/start"),
        input.clone(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{started}");
    assert_eq!(started["status"], "authorizing");
    let (_, duplicate) =
        request(&state, &auth, Method::POST, &format!("{base}/start"), input).await;
    assert_eq!(duplicate, started);
    let authorization_url = started["authorization_url"].as_str().unwrap();
    let parsed = url::Url::parse(authorization_url).unwrap();
    let query: BTreeMap<_, _> = parsed.query_pairs().collect();
    assert_eq!(query["code_challenge_method"], "S256");
    assert_eq!(query["resource"], format!("{origin}/mcp"));
    assert!(!query.contains_key("code_verifier"));
    let html = client
        .get(authorization_url)
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    let ticket = html
        .split("name=\"ticket\" value=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap();
    let consent = client
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
    let callback = consent.headers()["location"].to_str().unwrap();
    assert!(client
        .get(callback)
        .send()
        .await
        .unwrap()
        .status()
        .is_success());
    let (_, connected) = request(
        &state,
        &auth,
        Method::GET,
        &format!("{base}?project_id={}", scope.project_id),
        json!({}),
    )
    .await;
    assert_eq!(connected["status"], "connected", "{connected}");
    assert!(connected.get("authorization_url").is_none());
    assert!(vault
        .get(&format!("mcp-oauth-binding:{}", server.id))
        .unwrap()
        .is_some());
    let result = state
        .mcp_supervisor
        .call_tool(
            &scope,
            &server.id,
            "echo",
            json!({"text":"manual-mcp-owned-fixture"}),
            "owned-call",
        )
        .await
        .unwrap();
    assert!(result
        .result
        .to_string()
        .contains("manual-mcp-owned-fixture"));
    let revision = state
        .mcp_supervisor
        .server(&scope, &server.id)
        .unwrap()
        .unwrap()
        .revision;
    let (status, denied) = request(&state,&auth,Method::POST,&format!("{base}/disconnect"),json!({"project_id":"other-project","expected_revision":revision,"idempotency_key":"wrong-scope"})).await;
    assert!(!status.is_success(), "{denied}");
    assert_eq!(
        state.mcp_supervisor.oauth_status(&server.id).unwrap()["status"],
        "connected"
    );
    let (status, disconnected) = request(&state,&auth,Method::POST,&format!("{base}/disconnect"),json!({"project_id":scope.project_id,"expected_revision":revision,"idempotency_key":"disconnect"})).await;
    assert_eq!(status, StatusCode::OK, "{disconnected}");
    assert_eq!(disconnected["status"], "not_connected");
    assert!(
        !state
            .mcp_supervisor
            .server(&scope, &server.id)
            .unwrap()
            .unwrap()
            .enabled
    );
    assert!(vault
        .get(&format!("mcp-oauth-binding:{}", server.id))
        .unwrap()
        .is_none());
    assert!(state
        .mcp_supervisor
        .call_tool(&scope, &server.id, "echo", json!({}), "after-disconnect")
        .await
        .is_err());
    let revision = state
        .mcp_supervisor
        .server(&scope, &server.id)
        .unwrap()
        .unwrap()
        .revision;
    let (_, pending) = request(&state,&auth,Method::POST,&format!("{base}/start"),json!({"project_id":scope.project_id,"expected_revision":revision,"idempotency_key":"start-two","scopes":["mcp:tools"]})).await;
    assert_eq!(pending["status"], "authorizing");
    let (_, cancelled) = request(&state,&auth,Method::POST,&format!("{base}/cancel"),json!({"project_id":scope.project_id,"expected_revision":revision,"idempotency_key":"cancel"})).await;
    assert_eq!(cancelled["status"], "not_connected");
    let flow = state
        .mcp_supervisor
        .manual_oauth_flow(&scope, &server.id, &auth.user.user_id)
        .unwrap()
        .unwrap();
    assert!(flow.flow.is_empty());
    let (_, replay) = request(&state,&auth,Method::POST,&format!("{base}/start"),json!({"project_id":scope.project_id,"expected_revision":revision,"idempotency_key":"start-two","scopes":["mcp:tools"]})).await;
    assert_eq!(
        replay["status"], "not_connected",
        "old start cannot resurrect cancelled authorization"
    );
    state
        .mcp_supervisor
        .delete_server(&scope, &server.id, revision, "cleanup")
        .unwrap();
    process.kill().await.unwrap();
    process.wait().await.unwrap();
    std::fs::remove_dir_all(root).unwrap();
}
