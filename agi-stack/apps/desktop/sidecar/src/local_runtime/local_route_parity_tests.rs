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

const ROUTE_CONTRACT: &str = include_str!("../../../contracts/local-route-parity.v1.json");
const DESKTOP_CLIENT_SOURCE: &str = concat!(
    include_str!("../../../src/api/client.ts"),
    include_str!("../../../src/api/managedResourcesClient.ts"),
);
const SEARCH_CONTRACT_SOURCE: &str = include_str!("../../../src/api/searchContract.ts");
const CAPABILITY_CLIENT_SOURCE: &str =
    include_str!("../../../src/features/runtime/workbenchCapabilityClient.ts");
const ARTIFACT_CLIENT_SOURCE: &str =
    include_str!("../../../src/features/chat/desktopArtifactClient.ts");
const SANDBOX_CLIENT_SOURCE: &str =
    include_str!("../../../src/features/sandbox/sandboxRuntimeClient.ts");
const SANDBOX_SURFACE_CLIENT_SOURCE: &str =
    include_str!("../../../src/features/sandbox/sandboxRuntimeSurfaceClient.ts");
const LOCAL_PROJECT_OVERVIEW_CLIENT_SOURCE: &str =
    include_str!("../../../src/features/project/projectOverviewLocalClient.ts");

#[derive(Debug, Deserialize)]
struct LocalRouteContract {
    contract_version: String,
    routes: Vec<LocalRouteProbe>,
}

#[derive(Debug, Deserialize)]
struct LocalRouteProbe {
    area: String,
    method: String,
    uri: String,
    source: String,
    source_marker: String,
    authority: String,
    #[serde(default)]
    expected_status: Option<u16>,
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

fn authenticated_request(method: &str, uri: &str, credential: &str, body: &Value) -> Request<Body> {
    let mut builder = Request::builder()
        .method(Method::from_bytes(method.as_bytes()).expect("HTTP method"))
        .uri(uri)
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential)
        .header("content-type", "application/json");
    if let (Some(expected_revision), Some(idempotency_key)) = (
        body.get("expected_revision").and_then(Value::as_u64),
        body.get("idempotency_key").and_then(Value::as_str),
    ) {
        builder = builder
            .header("x-expected-revision", expected_revision)
            .header("idempotency-key", idempotency_key);
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

fn route_contract() -> LocalRouteContract {
    serde_json::from_str(ROUTE_CONTRACT).expect("local route parity contract")
}

#[tokio::test]
async fn desktop_client_and_axum_router_have_no_local_parity_route_difference() {
    let contract = route_contract();
    assert_eq!(contract.contract_version, "desktop-local-route-parity-v1");
    let credential = "local-route-parity-secret";
    let app = local_router(test_state(credential));
    let mut missing_client_markers = Vec::new();
    let mut missing_router_routes = Vec::new();

    for route in contract.routes {
        let source = match route.source.as_str() {
            "artifact" => ARTIFACT_CLIENT_SOURCE,
            "capability" => CAPABILITY_CLIENT_SOURCE,
            "client" => DESKTOP_CLIENT_SOURCE,
            "project_overview_local" => LOCAL_PROJECT_OVERVIEW_CLIENT_SOURCE,
            "search" => SEARCH_CONTRACT_SOURCE,
            "sandbox" => SANDBOX_CLIENT_SOURCE,
            "sandbox_surface" => SANDBOX_SURFACE_CLIENT_SOURCE,
            other => panic!("unsupported route source {other}"),
        };
        if !source.contains(&route.source_marker) {
            missing_client_markers.push(format!(
                "{} {} [{} marker {}]",
                route.method, route.uri, route.area, route.source_marker
            ));
        }

        let response = app
            .clone()
            .oneshot(authenticated_request(
                &route.method,
                &route.uri,
                credential,
                &route.body,
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
                route.uri,
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
                route.uri
            );
        }

        if route.authority == "structured_unavailable" {
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
                route.uri
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
        missing_client_markers.is_empty(),
        "route contract drifted from Desktop client sources:\n{}",
        missing_client_markers.join("\n")
    );
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
            &json!({}),
        ))
        .await
        .expect("member mutation response");
    assert_eq!(member_mutation.status(), StatusCode::FORBIDDEN);
    let payload = response_json(member_mutation).await;
    assert_eq!(payload["code"], "resource_manager_required");
}

fn expected_unavailable_contract(route: &LocalRouteProbe) -> (&'static str, &'static str) {
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
            ("not_applicable", "local_skill_evolution_not_applicable")
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
