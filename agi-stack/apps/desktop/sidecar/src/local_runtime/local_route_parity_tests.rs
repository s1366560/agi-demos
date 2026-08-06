use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use axum::{
    body::Body,
    http::{header::ALLOW, Method, Request, StatusCode},
};
use chrono::Utc;
use serde::Deserialize;
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::*;

const ROUTE_CONTRACT: &str = include_str!("../../../contracts/local-route-parity.v1.json");
const PARITY_MANIFEST: &str =
    include_str!("../../../contracts/desktop-web-parity/parity-manifest.v3.json");
const NATIVE_EQUIVALENT_REQUEST_MARKER: &str = "requestNativeEquivalentJson";

#[derive(Debug, Deserialize)]
struct LocalRouteContract {
    contract_version: String,
    routes: Vec<LocalRouteProbe>,
    #[serde(default)]
    manifest_pending_routes: Vec<RouteFixtureNotApplicable>,
    #[serde(default)]
    catalog_fixture_not_applicable: Vec<RouteFixtureNotApplicable>,
    #[serde(default)]
    router_fixture_not_applicable: Vec<RouteFixtureNotApplicable>,
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
    #[serde(default)]
    idempotency_key: Option<String>,
    #[serde(default)]
    expected_availability: Option<String>,
    #[serde(default)]
    expected_reason_code: Option<String>,
    body: Value,
}

#[derive(Debug)]
struct DesktopRouteSource {
    relative_path: String,
    content: String,
}

#[derive(Debug, Deserialize)]
struct RouteFixtureNotApplicable {
    method: String,
    path: String,
    reason_code: String,
}

#[derive(Debug, Deserialize)]
struct ParityManifest {
    schema_version: String,
    capabilities: Vec<ParityCapability>,
}

#[derive(Debug, Deserialize)]
struct ParityCapability {
    api_contracts: Vec<ParityApiContract>,
    #[serde(default)]
    journeys: Vec<ParityJourney>,
}

#[derive(Debug, Deserialize)]
struct ParityJourney {
    api_contracts: Vec<ParityApiContract>,
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd)]
struct ParityApiContract {
    surface: String,
    method: String,
    path: String,
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

fn route_contract() -> LocalRouteContract {
    serde_json::from_str(ROUTE_CONTRACT).expect("local route parity contract")
}

fn parity_manifest() -> ParityManifest {
    serde_json::from_str(PARITY_MANIFEST).expect("Desktop/Web parity manifest")
}

fn desktop_route_sources() -> Vec<DesktopRouteSource> {
    let desktop_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sidecar crate must be nested below the Desktop root")
        .to_path_buf();
    let source_root = desktop_root.join("src");
    let mut sources = Vec::new();
    collect_desktop_route_sources(&source_root, &source_root, &mut sources);
    sources.sort_by(|left, right| left.relative_path.cmp(&right.relative_path));
    sources
}

fn collect_desktop_route_sources(
    source_root: &Path,
    directory: &Path,
    sources: &mut Vec<DesktopRouteSource>,
) {
    let mut entries: Vec<_> = fs::read_dir(directory)
        .expect("read Desktop source directory")
        .map(|entry| entry.expect("read Desktop source entry"))
        .collect();
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let path = entry.path();
        if path.is_dir() {
            collect_desktop_route_sources(source_root, &path, sources);
            continue;
        }
        let Some(file_name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        if !is_desktop_route_source_file(file_name) {
            continue;
        }
        let content = fs::read_to_string(&path).expect("read Desktop route source");
        if !content.contains("/api/v1/") {
            continue;
        }
        let relative_path = path
            .strip_prefix(source_root)
            .expect("Desktop route source must be below src")
            .to_string_lossy()
            .replace('\\', "/");
        sources.push(DesktopRouteSource {
            relative_path,
            content,
        });
    }
}

fn is_desktop_route_source_file(file_name: &str) -> bool {
    file_name.ends_with("Client.ts")
        || file_name.ends_with("client.ts")
        || file_name.ends_with("Contract.ts")
}

fn source_path_suffix(source: &str) -> Option<&'static str> {
    match source {
        "client" => None,
        "artifact" => Some("features/chat/desktopArtifactClient.ts"),
        "capability" => Some("features/runtime/workbenchCapabilityClient.ts"),
        "project_overview_local" => Some("features/project/projectOverviewLocalClient.ts"),
        "search" => Some("api/searchContract.ts"),
        "sandbox" => Some("features/sandbox/sandboxRuntimeClient.ts"),
        "sandbox_surface" => Some("features/sandbox/sandboxRuntimeSurfaceClient.ts"),
        "tenant_overview" => Some("features/tenant/tenantOverviewHttpClient.ts"),
        "tenant_projects" => Some("features/tenant/tenantProjectsHttpClient.ts"),
        other => panic!("unsupported route source {other}"),
    }
}

fn source_contains_marker(sources: &[DesktopRouteSource], source: &str, marker: &str) -> bool {
    let suffix = source_path_suffix(source);
    sources.iter().any(|candidate| {
        suffix.is_none_or(|expected| candidate.relative_path.ends_with(expected))
            && candidate.content.contains(marker)
    })
}

fn is_standard_http_method(method: &str) -> bool {
    matches!(method, "GET" | "POST" | "PUT" | "PATCH" | "DELETE")
}

#[test]
fn route_path_matching_enforces_manifest_query_contracts() {
    let pattern = "/api/v1/agent/conversations/{conversation_id}/session?tenant_id={tenant_id}&project_id={project_id}&workspace_id={workspace_id}";
    assert!(route_path_matches(
        pattern,
        "/api/v1/agent/conversations/route-parity/session?tenant_id=local&project_id=local-project&workspace_id=local-workspace&refresh=true"
    ));
    assert!(!route_path_matches(
        pattern,
        "/api/v1/agent/conversations/route-parity/session?tenant_id=local&project_id=local-project"
    ));
    assert!(!route_path_matches(
        "/api/v1/agent/runs/{run_id}/changes?expected_revision=7",
        "/api/v1/agent/runs/route-parity/changes?expected_revision=8"
    ));
}

fn route_path_matches(pattern: &str, concrete_uri: &str) -> bool {
    let (pattern_path, pattern_query) = pattern
        .split_once('?')
        .map_or((pattern, None), |(path, query)| (path, Some(query)));
    let (concrete_path, concrete_query) = concrete_uri
        .split_once('?')
        .map_or((concrete_uri, None), |(path, query)| (path, Some(query)));
    let pattern_segments: Vec<_> = pattern_path.split('/').collect();
    let concrete_segments: Vec<_> = concrete_path.split('/').collect();
    let path_matches = pattern_segments.len() == concrete_segments.len()
        && pattern_segments.iter().zip(concrete_segments).all(
            |(pattern_segment, concrete_segment)| {
                let placeholder = pattern_segment.starts_with('{')
                    && pattern_segment.ends_with('}')
                    && pattern_segment.len() > 2;
                if placeholder {
                    !concrete_segment.is_empty()
                } else {
                    *pattern_segment == concrete_segment
                }
            },
        );
    path_matches && query_contract_matches(pattern_query, concrete_query)
}

fn query_contract_matches(pattern: Option<&str>, concrete: Option<&str>) -> bool {
    let Some(pattern) = pattern else {
        return true;
    };
    let Some(concrete) = concrete else {
        return false;
    };
    let concrete_parameters: Vec<_> = concrete
        .split('&')
        .filter_map(|parameter| parameter.split_once('='))
        .collect();
    pattern.split('&').all(|parameter| {
        let Some((expected_key, expected_value)) = parameter.split_once('=') else {
            return false;
        };
        concrete_parameters.iter().any(|(key, value)| {
            if *key != expected_key {
                return false;
            }
            let placeholder = expected_value.starts_with('{')
                && expected_value.ends_with('}')
                && expected_value.len() > 2;
            (placeholder && !value.is_empty()) || (!placeholder && *value == expected_value)
        })
    })
}

fn route_exception_matches(
    route: &ParityApiContract,
    exception: &RouteFixtureNotApplicable,
) -> bool {
    route.method == exception.method && route.path == exception.path
}

fn catalog_exception_matches(
    route: &LocalRouteProbe,
    exception: &RouteFixtureNotApplicable,
) -> bool {
    route.method == exception.method && route.uri == exception.path
}

fn registered_axum_paths(router: &Router) -> std::collections::BTreeSet<String> {
    format!("{router:?}")
        .split('"')
        .filter(|part| part.starts_with("/api/v1/"))
        .map(str::to_string)
        .collect()
}

fn manifest_pattern_for_axum_path(path: &str) -> String {
    path.split('/')
        .map(|segment| {
            segment
                .strip_prefix(':')
                .or_else(|| segment.strip_prefix('*'))
                .map_or_else(|| segment.to_string(), |name| format!("{{{name}}}"))
        })
        .collect::<Vec<_>>()
        .join("/")
}

fn executable_uri_for_axum_path(path: &str) -> String {
    path.split('/')
        .map(|segment| {
            let Some(parameter) = segment
                .strip_prefix(':')
                .or_else(|| segment.strip_prefix('*'))
            else {
                return segment.to_string();
            };
            match parameter {
                "tenant_id" => "local",
                "project_id" => "local-project",
                "workspace_id" => "local-workspace",
                "conversation_id" => "route-parity-artifact-conversation",
                _ => "route-parity",
            }
            .to_string()
        })
        .collect::<Vec<_>>()
        .join("/")
}

#[tokio::test]
async fn registered_axum_routes_are_closed_over_the_executable_catalog() {
    let contract = route_contract();
    let credential = "local-route-registration-secret";
    let app = local_router(test_state(credential));
    let registered_paths = registered_axum_paths(&app);
    assert!(
        !registered_paths.is_empty(),
        "Axum Router debug contract must expose registered paths"
    );

    let mut missing_catalog_contracts = Vec::new();
    let mut registered_contracts = std::collections::BTreeSet::new();
    for registered_path in registered_paths {
        let response = app
            .clone()
            .oneshot(authenticated_request(
                "OPTIONS",
                &executable_uri_for_axum_path(&registered_path),
                credential,
                None,
                &json!({}),
            ))
            .await
            .expect("registered route OPTIONS response");
        let Some(allow) = response
            .headers()
            .get(ALLOW)
            .and_then(|value| value.to_str().ok())
        else {
            missing_catalog_contracts.push(format!(
                "{} [registered route did not expose an Allow header]",
                registered_path
            ));
            continue;
        };
        let manifest_pattern = manifest_pattern_for_axum_path(&registered_path);
        for method in allow
            .split(',')
            .map(str::trim)
            .filter(|method| is_standard_http_method(method))
        {
            registered_contracts.insert((method.to_string(), manifest_pattern.clone()));
            let covered = contract.routes.iter().any(|probe| {
                probe.method == method && route_path_matches(&manifest_pattern, &probe.uri)
            }) || contract
                .manifest_pending_routes
                .iter()
                .any(|pending| {
                    pending.method == method
                        && route_path_matches(&manifest_pattern, &pending.path)
                })
                || contract
                    .router_fixture_not_applicable
                    .iter()
                    .any(|exception| {
                        exception.method == method && exception.path == manifest_pattern
                    });
            if !covered {
                missing_catalog_contracts.push(format!("{method} {manifest_pattern}"));
            }
        }
    }
    let stale_router_exceptions: Vec<_> = contract
        .router_fixture_not_applicable
        .iter()
        .filter(|exception| {
            !registered_contracts.contains(&(exception.method.clone(), exception.path.clone()))
                || contract.routes.iter().any(|probe| {
                    probe.method == exception.method
                        && route_path_matches(&exception.path, &probe.uri)
                })
        })
        .map(|exception| format!("{} {}", exception.method, exception.path))
        .collect();

    assert!(
        missing_catalog_contracts.is_empty(),
        "registered Axum routes missing executable catalog probes or explicit fixture N/A entries:\n{}",
        missing_catalog_contracts.join("\n")
    );
    assert!(
        stale_router_exceptions.is_empty(),
        "router fixture N/A entries are stale or shadow executable probes:\n{}",
        stale_router_exceptions.join("\n")
    );
}

#[test]
fn native_equivalent_desktop_client_inventory_is_covered_by_executable_local_routes() {
    let contract = route_contract();
    let sources = desktop_route_sources();
    let missing_sources: Vec<_> = sources
        .iter()
        .filter(|source| source.content.contains(NATIVE_EQUIVALENT_REQUEST_MARKER))
        .filter(|source| {
            !contract.routes.iter().any(|route| {
                route.source == "client" && source.content.contains(&route.source_marker)
            })
        })
        .map(|source| source.relative_path.clone())
        .collect();

    assert!(
        missing_sources.is_empty(),
        "native-equivalent Desktop clients missing executable local route probes:\n{}",
        missing_sources.join("\n")
    );
}

#[test]
fn executable_local_route_catalog_is_closed_over_desktop_local_manifest_contracts() {
    let contract = route_contract();
    let manifest = parity_manifest();
    assert_eq!(manifest.schema_version, "3.0.0");
    let manifest_routes: std::collections::BTreeSet<_> = manifest
        .capabilities
        .into_iter()
        .flat_map(|capability| {
            capability.api_contracts.into_iter().chain(
                capability
                    .journeys
                    .into_iter()
                    .flat_map(|journey| journey.api_contracts),
            )
        })
        .filter(|route| route.surface == "desktop_local")
        .filter(|route| is_standard_http_method(&route.method))
        .collect();

    let mut invalid_exceptions = Vec::new();
    let mut duplicate_exceptions = std::collections::BTreeSet::new();
    for pending in &contract.manifest_pending_routes {
        if !is_standard_http_method(&pending.method)
            || pending.path.is_empty()
            || !pending
                .reason_code
                .starts_with("executable_fixture_pending_")
        {
            invalid_exceptions.push(format!(
                "{} {} [{}]",
                pending.method, pending.path, pending.reason_code
            ));
        }
        let key = format!("{} {}", pending.method, pending.path);
        if !duplicate_exceptions.insert(key.clone()) {
            invalid_exceptions.push(format!("duplicate exception {key}"));
        }
    }
    for exception in contract
        .catalog_fixture_not_applicable
        .iter()
        .chain(&contract.router_fixture_not_applicable)
    {
        if !is_standard_http_method(&exception.method)
            || exception.path.is_empty()
            || !exception.reason_code.starts_with("executable_fixture_")
        {
            invalid_exceptions.push(format!(
                "{} {} [{}]",
                exception.method, exception.path, exception.reason_code
            ));
        }
        let key = format!("{} {}", exception.method, exception.path);
        if !duplicate_exceptions.insert(key.clone()) {
            invalid_exceptions.push(format!("duplicate exception {key}"));
        }
    }

    let missing_catalog_probes: Vec<_> = manifest_routes
        .iter()
        .filter(|manifest_route| {
            !contract.routes.iter().any(|probe| {
                probe.method == manifest_route.method
                    && route_path_matches(&manifest_route.path, &probe.uri)
            }) && !contract
                .manifest_pending_routes
                .iter()
                .any(|exception| route_exception_matches(manifest_route, exception))
        })
        .map(|route| format!("{} {}", route.method, route.path))
        .collect();
    let stale_manifest_pending_routes: Vec<_> = contract
        .manifest_pending_routes
        .iter()
        .filter(|exception| {
            !manifest_routes
                .iter()
                .any(|route| route_exception_matches(route, exception))
                || contract.routes.iter().any(|probe| {
                    probe.method == exception.method
                        && route_path_matches(&exception.path, &probe.uri)
                })
        })
        .map(|exception| format!("{} {}", exception.method, exception.path))
        .collect();
    let catalog_probes_without_manifest_contract: Vec<_> = contract
        .routes
        .iter()
        .filter(|probe| {
            !manifest_routes.iter().any(|manifest_route| {
                probe.method == manifest_route.method
                    && route_path_matches(&manifest_route.path, &probe.uri)
            }) && !contract
                .catalog_fixture_not_applicable
                .iter()
                .any(|exception| catalog_exception_matches(probe, exception))
        })
        .map(|probe| format!("{} {}", probe.method, probe.uri))
        .collect();
    let stale_catalog_exceptions: Vec<_> = contract
        .catalog_fixture_not_applicable
        .iter()
        .filter(|exception| {
            !contract
                .routes
                .iter()
                .any(|probe| catalog_exception_matches(probe, exception))
                || manifest_routes.iter().any(|manifest_route| {
                    exception.method == manifest_route.method
                        && route_path_matches(&manifest_route.path, &exception.path)
                })
        })
        .map(|exception| format!("{} {}", exception.method, exception.path))
        .collect();

    assert!(
        invalid_exceptions.is_empty(),
        "pending routes and fixture N/A entries must be unique HTTP contracts with a matching executable_fixture_* reason:\n{}",
        invalid_exceptions.join("\n")
    );
    assert!(
        missing_catalog_probes.is_empty(),
        "desktop_local manifest contracts missing executable probes or explicit pending entries:\n{}",
        missing_catalog_probes.join("\n")
    );
    assert!(
        stale_manifest_pending_routes.is_empty(),
        "manifest pending routes are stale or shadow executable probes:\n{}",
        stale_manifest_pending_routes.join("\n")
    );
    assert!(
        catalog_probes_without_manifest_contract.is_empty(),
        "executable probes missing manifest contracts or explicit fixture N/A entries:\n{}",
        catalog_probes_without_manifest_contract.join("\n")
    );
    assert!(
        stale_catalog_exceptions.is_empty(),
        "catalog fixture N/A entries are stale or shadow manifest contracts:\n{}",
        stale_catalog_exceptions.join("\n")
    );
}

#[tokio::test]
async fn desktop_client_and_axum_router_have_no_local_parity_route_difference() {
    let contract = route_contract();
    let sources = desktop_route_sources();
    assert_eq!(contract.contract_version, "desktop-local-route-parity-v1");
    let credential = "local-route-parity-secret";
    let app = local_router(test_state(credential));
    let mut missing_client_markers = Vec::new();
    let mut missing_router_routes = Vec::new();
    let mut automation_id = None;
    let mut trusted_session_id = None;

    for route in contract.routes {
        if !source_contains_marker(&sources, &route.source, &route.source_marker) {
            missing_client_markers.push(format!(
                "{} {} [{} marker {}]",
                route.method, route.uri, route.area, route.source_marker
            ));
        }

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
