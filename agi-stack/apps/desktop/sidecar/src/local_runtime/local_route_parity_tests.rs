// Actual local HTTP request/response tests; no route inventory or evidence gate.
use std::path::PathBuf;
use std::sync::Arc;

use axum::{
    body::Body,
    http::{Method, Request, StatusCode},
};
use chrono::Utc;
use serde::Deserialize;
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::*;

#[derive(Debug, Deserialize)]
struct LocalRouteProbe {
    area: String,
    method: String,
    uri: String,
    authority: String,
    #[serde(default)]
    expected_status: Option<u16>,
    #[serde(default)]
    idempotency_key: Option<String>,
    #[serde(default)]
    expected_availability: Option<String>,
    #[serde(default)]
    expected_reason_code: Option<String>,
    body: Value,
}

fn test_root() -> PathBuf {
    std::env::temp_dir().join(format!("agistack-local-route-parity-{}", Uuid::new_v4()))
}

fn test_state(credential: &str) -> Arc<LocalRuntimeState> {
    let root = test_root();
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root.clone(),
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    std::fs::write(root.join("route-parity.txt"), "route parity")
        .expect("seed sandbox file route fixture");
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated test session");
    let conversation_id = "route-parity-artifact-conversation";
    state
        .session_store
        .insert_conversation(&LocalConversation {
            id: conversation_id.to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Route parity artifact".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Build,
            created_at: now_iso(),
            updated_at: now_iso(),
        })
        .expect("insert route parity artifact conversation");
    let artifact_path =
        root.join(".agistack/artifacts/route-parity/route-parity-version/route-parity.md");
    std::fs::create_dir_all(artifact_path.parent().expect("artifact parent"))
        .expect("create route parity artifact parent");
    std::fs::write(&artifact_path, "route parity").expect("write route parity artifact");
    state
        .session_store
        .record_artifact_version(
            conversation_id,
            None,
            &json!({
                "artifact_id": "route-parity",
                "artifact_version_id": "route-parity-version",
                "filename": "route-parity.md",
                "path": artifact_path,
                "relative_path":
                    ".agistack/artifacts/route-parity/route-parity-version/route-parity.md",
                "bytes": 12,
                "mime_type": "text/markdown",
                "sources": [],
                "checks": [],
            }),
            &now_iso(),
        )
        .expect("record route parity artifact");
    state
        .mcp_supervisor
        .seed_route_contract_fixture(&mcp_supervisor::McpScope {
            tenant_id: "local".to_string(),
            project_id: "local-project".to_string(),
        })
        .expect("seed route parity MCP fixture");
    state
}

fn authenticated_request(
    method: &str,
    uri: &str,
    credential: &str,
    idempotency_key: Option<&str>,
    body: &Value,
) -> Request<Body> {
    let mut builder = Request::builder()
        .method(Method::from_bytes(method.as_bytes()).expect("HTTP method"))
        .uri(uri)
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential)
        .header("content-type", "application/json");
    if let Some(expected_revision) = body.get("expected_revision").and_then(Value::as_u64) {
        builder = builder.header("x-expected-revision", expected_revision);
    }
    if let Some(idempotency_key) =
        idempotency_key.or_else(|| body.get("idempotency_key").and_then(Value::as_str))
    {
        builder = builder.header("idempotency-key", idempotency_key);
    }
    builder
        .body(Body::from(body.to_string()))
        .expect("authenticated route parity request")
}

async fn response_json(response: axum::response::Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    serde_json::from_slice(&body).expect("response JSON")
}

#[tokio::test]
async fn desktop_client_and_axum_router_have_no_local_parity_route_difference() {
    let routes: Vec<LocalRouteProbe> =
        serde_json::from_str(include_str!("fixtures/local_route_requests.json"))
            .expect("local HTTP test requests");
    let credential = "local-route-parity-secret";
    let app = local_router(test_state(credential));
    let mut missing_router_routes = Vec::new();
    let mut automation_id = None;
    let mut trusted_session_id = None;

    for route in routes {
        let resolved_uri = automation_id.as_ref().map_or_else(
            || route.uri.clone(),
            |automation_id: &String| route.uri.replace("route-parity-automation", automation_id),
        );
        let mut resolved_body = route.body.clone();
        if route.uri == "/api/v1/auth/local-session/resume" {
            resolved_body["session_id"] = Value::String(
                trusted_session_id
                    .clone()
                    .expect("trusted local session probe must follow session creation"),
            );
        }

        let response = app
            .clone()
            .oneshot(authenticated_request(
                &route.method,
                &resolved_uri,
                credential,
                route.idempotency_key.as_deref(),
                &resolved_body,
            ))
            .await
            .expect("route parity response");
        if matches!(
            response.status(),
            StatusCode::NOT_FOUND | StatusCode::METHOD_NOT_ALLOWED
        ) {
            missing_router_routes.push(format!(
                "{} {} [{} returned {}]",
                route.method,
                resolved_uri,
                route.area,
                response.status()
            ));
            continue;
        }
        if let Some(expected_status) = route.expected_status {
            assert_eq!(
                response.status().as_u16(),
                expected_status,
                "{} {} returned an unexpected status",
                route.method,
                resolved_uri
            );
        }

        if route.area == "automations"
            && route.method == "POST"
            && route.uri == "/api/v1/projects/local-project/cron-jobs"
        {
            let payload = response_json(response).await;
            automation_id = Some(
                payload["id"]
                    .as_str()
                    .expect("automation creation probe must return an id")
                    .to_string(),
            );
            continue;
        }
        if route.area == "auth"
            && route.method == "POST"
            && route.uri == "/api/v1/auth/local-session"
        {
            let payload = response_json(response).await;
            trusted_session_id = Some(
                payload["session"]["session_id"]
                    .as_str()
                    .expect("trusted local session probe must return a session id")
                    .to_string(),
            );
            continue;
        }

        if route.authority == "agent_bindings_unavailable" {
            assert_eq!(
                response.status(),
                StatusCode::NOT_IMPLEMENTED,
                "{} {} must preserve the tenant binding availability contract",
                route.method,
                route.uri
            );
            let payload = response_json(response).await;
            assert_eq!(payload["contract_version"], "3.0.0");
            assert_eq!(payload["capability"], "tenant_agent_bindings");
            assert_eq!(payload["availability"], "unavailable");
            assert_eq!(
                payload["reason_code"],
                "local_agent_binding_routing_authority_unavailable"
            );
        } else if route.authority == "retired_v1" {
            assert_eq!(
                response.status(),
                StatusCode::GONE,
                "{} {} must reject the retired V1 plugin protocol",
                route.method,
                route.uri
            );
            let payload = response_json(response).await;
            assert_eq!(payload["detail"]["code"], "plugin_protocol_v1_retired");
            assert_eq!(
                payload["detail"]["migration_target"],
                "/api/v1/plugin-marketplace"
            );
        } else if route.authority == "structured_unavailable" {
            assert_eq!(
                response.status(),
                StatusCode::NOT_IMPLEMENTED,
                "{} {} must fail with a structured availability response",
                route.method,
                route.uri
            );
            let payload = response_json(response).await;
            assert_eq!(payload["contract_version"], "desktop-local-route-parity-v1");
            assert_eq!(payload["mode"], "local");
            let (expected_availability, expected_reason_code) =
                expected_unavailable_contract(&route);
            assert_eq!(payload["availability"], expected_availability);
            assert_eq!(payload["reason_code"], expected_reason_code);
        } else if route.authority == "sandbox_capabilities" {
            assert_eq!(
                response.status(),
                StatusCode::OK,
                "{} {} must expose the explicit local sandbox capability snapshot",
                route.method,
                route.uri
            );
            let payload = response_json(response).await;
            assert_eq!(payload["contract_version"], 2);
            assert_eq!(payload["terminal_interactive"]["availability"], "available");
            assert_eq!(payload["terminal_resume"]["availability"], "unavailable");
            assert_eq!(payload["files"]["availability"], "available");
            assert_eq!(payload["kasm_vnc"]["availability"], "not_applicable");
        } else if route.authority == "native_workspace" {
            assert_eq!(
                response.status(),
                StatusCode::OK,
                "{} {} must resolve against the native workspace authority",
                route.method,
                route.uri
            );
            if route.uri.contains("/download?") {
                assert_eq!(
                    response
                        .headers()
                        .get("x-memstack-file-authority")
                        .and_then(|value| value.to_str().ok()),
                    Some("native_workspace")
                );
                assert_eq!(
                    response
                        .headers()
                        .get("x-memstack-file-isolation")
                        .and_then(|value| value.to_str().ok()),
                    Some("not_applicable")
                );
            } else {
                let payload = response_json(response).await;
                assert_eq!(payload["contract_version"], 1);
                assert_eq!(payload["authority"], "native_workspace");
                assert_eq!(payload["isolation"], "not_applicable");
            }
        } else if route.authority == "artifact_content_v2" {
            assert_eq!(
                response.status(),
                StatusCode::OK,
                "{} {} must resolve against the Artifact Content V2 authority",
                route.method,
                route.uri
            );
            if route.uri.ends_with("/content/bytes") {
                assert_eq!(
                    response
                        .headers()
                        .get("x-content-type-options")
                        .and_then(|value| value.to_str().ok()),
                    Some("nosniff")
                );
            } else {
                let payload = response_json(response).await;
                assert_eq!(
                    payload["artifact_id"],
                    "route-parity-artifact-conversation:route-parity"
                );
                assert_eq!(
                    payload["revision"],
                    if route.method == "PUT" { 1 } else { 0 }
                );
            }
        } else {
            assert_ne!(
                response.status(),
                StatusCode::NOT_IMPLEMENTED,
                "{} {} declares local authority but returned unavailable",
                route.method,
                resolved_uri
            );
            if is_managed_resource_mutation(&route) && response.status().is_success() {
                let payload = response_json(response).await;
                assert_eq!(
                    payload["mutation_receipt"]["contract_version"], 2,
                    "{} {} must return a V2 mutation receipt",
                    route.method, route.uri
                );
                assert!(
                    payload["mutation_receipt"]["receipt_id"]
                        .as_str()
                        .is_some_and(|receipt_id| !receipt_id.is_empty()),
                    "{} {} must return a stable receipt id",
                    route.method,
                    route.uri
                );
            }
        }
    }

    assert!(
        missing_router_routes.is_empty(),
        "Desktop client routes missing from Axum router:\n{}",
        missing_router_routes.join("\n")
    );
}

fn is_managed_resource_mutation(route: &LocalRouteProbe) -> bool {
    matches!(route.area.as_str(), "skills" | "agents" | "subagents")
        && matches!(route.method.as_str(), "POST" | "PUT" | "PATCH" | "DELETE")
}

#[tokio::test]
async fn unavailable_routes_fail_closed_on_scope_and_role() {
    let credential = "local-route-scope-secret";
    let state = test_state(credential);
    let app = local_router(Arc::clone(&state));

    let wrong_tenant = app
        .clone()
        .oneshot(authenticated_request(
            "GET",
            "/api/v1/subagents/?tenant_id=orbital",
            credential,
            None,
            &json!({}),
        ))
        .await
        .expect("wrong tenant response");
    assert_eq!(wrong_tenant.status(), StatusCode::FORBIDDEN);

    let wrong_project = app
        .clone()
        .oneshot(authenticated_request(
            "POST",
            "/api/v1/search-enhanced/advanced",
            credential,
            None,
            &json!({
                "tenant_id": "local",
                "project_id": "desktop-client",
                "query": "out of scope",
            }),
        ))
        .await
        .expect("wrong project response");
    assert_eq!(wrong_project.status(), StatusCode::FORBIDDEN);

    let authenticated = state
        .session_store
        .validate_session_credential(credential, Utc::now().timestamp_millis())
        .expect("validate session")
        .expect("authenticated context");
    state
        .session_store
        .switch_workspace_context(
            &authenticated,
            &ContextSwitchRequest {
                tenant_id: "orbital".to_string(),
                project_id: "agent-evals".to_string(),
                expected_revision: 0,
                idempotency_key: "switch-member-route-parity".to_string(),
            },
            Utc::now().timestamp_millis(),
        )
        .expect("switch to member project");
    let member_mutation = app
        .oneshot(authenticated_request(
            "POST",
            "/api/v1/subagents/?tenant_id=orbital",
            credential,
            None,
            &json!({}),
        ))
        .await
        .expect("member mutation response");
    assert_eq!(member_mutation.status(), StatusCode::FORBIDDEN);
    let payload = response_json(member_mutation).await;
    assert_eq!(payload["code"], "resource_manager_required");
}

fn expected_unavailable_contract(route: &LocalRouteProbe) -> (&str, &str) {
    match (
        route.expected_availability.as_deref(),
        route.expected_reason_code.as_deref(),
    ) {
        (Some(availability), Some(reason_code)) => return (availability, reason_code),
        (None, None) => {}
        _ => panic!(
            "{} {} must declare expected_availability and expected_reason_code together",
            route.method, route.uri
        ),
    }
    match route.area.as_str() {
        "search" if route.uri.contains("/graph-traversal") => (
            "unavailable",
            "local_structured_graph_projection_unavailable",
        ),
        "search" => (
            "unavailable",
            "local_structured_community_projection_unavailable",
        ),
        "mcp_apps" => ("unavailable", "local_mcp_supervisor_unavailable"),
        "subagents" => ("unavailable", "local_subagent_registry_unavailable"),
        "plugins" => ("not_applicable", "local_channel_runtime_not_applicable"),
        "agents" if route.uri.starts_with("/api/v1/acp/") => {
            ("not_applicable", "local_external_acp_not_applicable")
        }
        "agents" => ("unavailable", "managed_resource_contract_v2_required"),
        "skills" if route.uri.contains("/evolution") => {
            ("unavailable", "local_skill_evolution_authority_unavailable")
        }
        "skills"
            if route.uri.contains("/versions")
                || route.uri.contains("/rollback")
                || route.uri.contains("/export") =>
        {
            ("unavailable", "local_skill_version_authority_unavailable")
        }
        "skills" => ("unavailable", "managed_resource_contract_v2_required"),
        other => panic!("unsupported unavailable route area {other}"),
    }
}

#[tokio::test]
async fn evolution_authority_probe_routes_return_structured_local_unavailability() {
    let credential = "local-evolution-authority-secret";
    let app = local_router(test_state(credential));
    for (method, uri) in [
        ("GET", "/api/v1/skills/evolution/overview?tenant_id=local"),
        ("GET", "/api/v1/skills/evolution/config?tenant_id=local"),
        ("PUT", "/api/v1/skills/evolution/config?tenant_id=local"),
        ("POST", "/api/v1/skills/evolution/run?tenant_id=local"),
    ] {
        let response = app
            .clone()
            .oneshot(authenticated_request(
                method,
                uri,
                credential,
                None,
                &json!({}),
            ))
            .await
            .expect("evolution authority response");
        assert_eq!(
            response.status(),
            StatusCode::NOT_IMPLEMENTED,
            "{method} {uri}"
        );
        let payload = response_json(response).await;
        assert_eq!(payload["contract_version"], "desktop-local-route-parity-v1");
        assert_eq!(payload["availability"], "unavailable");
        assert_eq!(
            payload["reason_code"],
            "local_skill_evolution_authority_unavailable"
        );
    }
}
