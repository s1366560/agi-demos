//! Bodyless project HTTP contributions execute in the installed Wasm generation.
//! A signed route permission grants one verb and one relative path in one project.
use super::{
    local_plugin_tool_host_v2::OperationReleaseGuardV2, workspace_core_bridge,
    AuthenticatedContext, LocalRuntimeState,
};
use agistack_plugin_host::protocol_v2::{
    wasm_runtime::{
        WasmOperationAuthorityV2, WasmOperationV2, WasmToolAttributionV2, WasmToolSetV2,
        WASM_TOOL_SET_SERVICE_V2,
    },
    ScopeKindV2, ScopeV2,
};
use axum::{
    body::Body,
    extract::{Extension, State},
    http::{Request, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::sync::{Arc, OnceLock};

struct Authority {
    state: Arc<LocalRuntimeState>,
    auth: AuthenticatedContext,
    scope: ScopeV2,
    permission: String,
    approved: OnceLock<(WasmToolAttributionV2, u64)>,
}

#[async_trait::async_trait]
impl WasmOperationAuthorityV2 for Authority {
    async fn authorize(&self, operation: &WasmOperationV2, tool: &WasmToolAttributionV2) -> bool {
        if operation.scope() != &self.scope
            || !self
                .state
                .session_store
                .session_context_is_current(&self.auth, chrono::Utc::now().timestamp_millis())
                .unwrap_or(false)
        {
            return false;
        }
        let Ok(keys) = self.state.local_plugin_signing_keys.as_ref() else {
            return false;
        };
        let Ok(db) = self.state.session_store.connection() else {
            return false;
        };
        let Some(epoch) = crate::local_plugin_installations_v2::route_epoch(
            &db,
            &self.scope,
            &tool.bundle.bundle_id,
        ) else {
            return false;
        };
        if let Some((pinned, approved_epoch)) = self.approved.get() {
            return pinned == tool && *approved_epoch == epoch;
        }
        let allowed = crate::local_plugin_installations_v2::authorizes_permission(
            &db,
            keys,
            &self.scope,
            tool,
            &self.permission,
        );
        if !allowed {
            return false;
        }
        let (pinned, pinned_epoch) = self.approved.get_or_init(|| (tool.clone(), epoch));
        pinned == tool && *pinned_epoch == epoch
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct GuestResponse {
    status: u16,
    body: Value,
}

fn failure(status: StatusCode, code: &str) -> Response {
    (status, Json(json!({"code":code}))).into_response()
}

pub(super) fn route_permission(method: &str, path: &str) -> Option<String> {
    if !matches!(method, "GET" | "POST")
        || path.len() > 160
        || !path.split('/').all(|segment| {
            !segment.is_empty()
                && segment
                    .bytes()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
        })
    {
        return None;
    }
    Some(format!(
        "desktop.http.{}.{}",
        method.to_ascii_lowercase(),
        path.replace('/', ".")
    ))
}

pub(super) async fn cloud(
    State(state): State<Arc<LocalRuntimeState>>,
    request: Request<Body>,
    next: axum::middleware::Next,
) -> Response {
    // Mounted only around the authenticated host fallback. Registered kernel endpoints
    // retain their own authentication and handlers.
    if request
        .extensions()
        .get::<axum::extract::MatchedPath>()
        .is_some()
        || state
            .platform_plugin_authority_v2
            .acquire_generation()
            .is_ok_and(|lease| lease.descriptor().publication_version.is_none())
    {
        return next.run(request).await;
    }
    let Some((project, path)) = request
        .uri()
        .path()
        .strip_prefix("/api/v1/projects/")
        .and_then(|p| p.split_once('/'))
    else {
        return next.run(request).await;
    };
    let method = if request.method() == "HEAD" {
        "GET"
    } else {
        request.method().as_str()
    };
    let Some(permission) = route_permission(method, path) else {
        return next.run(request).await;
    };
    let Some(bearer) = super::bearer_credential(request.headers()) else {
        return next.run(request).await;
    };
    let Some(broker) = state.platform_plugin_authority_v2.trusted_sessions() else {
        return next.run(request).await;
    };
    let owner = match super::device_mcp::CloudOwner::resolve_project_http(
        &broker,
        state.session_store.installation_id(),
        project,
        bearer,
    )
    .await
    {
        Ok(Some(owner)) => owner,
        Ok(None) => return next.run(request).await,
        Err(_) => return failure(StatusCode::FORBIDDEN, "project_route_scope_denied"),
    };
    let input = json!({"method":method,"path":path,"tenant_id":owner.tenant,"project_id":project});
    match super::device_plugins::project_http(&state, &broker, owner, &permission, input).await {
        Ok(Some((output, grant))) => {
            let head = request.method() == "HEAD";
            if let Some(raw) = output.get("workspace_read") {
                let Ok(plan) = serde_json::from_value::<super::workspace_read::Plan>(raw.clone())
                else {
                    return failure(StatusCode::BAD_GATEWAY, "project_route_response_invalid");
                };
                return grant
                    .read(&state, plan, request.uri().clone(), head)
                    .await
                    .unwrap_or_else(|_| {
                        failure(StatusCode::FORBIDDEN, "project_route_grant_denied")
                    });
            }
            guest_response(output, head)
        }
        Ok(None) => next.run(request).await,
        Err(code) if code == "project_route_conflict" => failure(StatusCode::CONFLICT, &code),
        Err(_) => failure(StatusCode::FORBIDDEN, "project_route_grant_denied"),
    }
}

pub(super) async fn dispatch(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    request: Request<Body>,
) -> Response {
    let project = &auth.workspace.project_id;
    let prefix = format!("/api/v1/projects/{project}/");
    let Some(path) = request.uri().path().strip_prefix(&prefix) else {
        return workspace_core_bridge::proxy_workspace_fallback(State(state), request).await;
    };
    let method = if request.method() == "HEAD" {
        "GET"
    } else {
        request.method().as_str()
    };
    let Some(permission) = route_permission(method, path) else {
        return workspace_core_bridge::proxy_workspace_fallback(State(state), request).await;
    };
    let scope = ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: Some(auth.workspace.tenant_id.clone()),
        project_id: Some(project.clone()),
        session_id: None,
    };
    let Some(admission) = request
        .extensions()
        .get::<Arc<super::ActivePlatformPluginGenerationLeaseV2>>()
    else {
        return workspace_core_bridge::proxy_workspace_fallback(State(state), request).await;
    };
    if admission.descriptor().publication_version.is_some() {
        return workspace_core_bridge::proxy_workspace_fallback(State(state), request).await;
    }
    let Ok(lease) = admission.operation_lease() else {
        return failure(
            StatusCode::SERVICE_UNAVAILABLE,
            "project_generation_unavailable",
        );
    };
    let Ok(generation) = lease.generation() else {
        return failure(
            StatusCode::SERVICE_UNAVAILABLE,
            "project_generation_unavailable",
        );
    };
    let generation = Arc::clone(generation);
    let input = json!({"method":method,"path":path,"tenant_id":auth.workspace.tenant_id,"project_id":project});
    let authority = Arc::new(Authority {
        state: Arc::clone(&state),
        auth,
        scope: scope.clone(),
        permission: permission.clone(),
        approved: OnceLock::new(),
    });
    let operation = OperationReleaseGuardV2::new(WasmOperationV2::new(
        lease,
        scope.clone(),
        uuid::Uuid::new_v4().to_string(),
        Some(authority.clone()),
    ));
    let mut matches = generation.snapshot.entries.iter().filter(|entry| {
        entry.enabled
            && entry.scope == scope
            && entry.permissions.contains(&permission)
            && entry.isolate.get(WASM_TOOL_SET_SERVICE_V2) == Some(&entry.entry_id)
    });
    let Some(entry) = matches.next() else {
        return workspace_core_bridge::proxy_workspace_fallback(State(state), request).await;
    };
    if matches.next().is_some() {
        return failure(StatusCode::CONFLICT, "project_route_conflict");
    }
    let Ok(set) = generation.resolve::<WasmToolSetV2>(
        WASM_TOOL_SET_SERVICE_V2,
        &scope,
        Some(&entry.entry_id),
    ) else {
        return failure(StatusCode::SERVICE_UNAVAILABLE, "project_route_unavailable");
    };
    let tools = set.prepare(&operation).await;
    let [tool] = tools.as_slice() else {
        return failure(StatusCode::FORBIDDEN, "project_route_grant_denied");
    };
    let result = tool.invoke(input).await;
    if !authority.authorize(&operation, tool.attribution()).await {
        return failure(StatusCode::FORBIDDEN, "project_route_grant_denied");
    }
    let Ok(output) = result else {
        return failure(StatusCode::BAD_GATEWAY, "project_route_execution_failed");
    };
    let head = request.method() == "HEAD";
    if let Some(raw) = output.get("workspace_read") {
        let Ok(plan) = serde_json::from_value::<super::workspace_read::Plan>(raw.clone()) else {
            return failure(StatusCode::BAD_GATEWAY, "project_route_response_invalid");
        };
        if !entry.permissions.iter().any(|p| p == plan.permission()) {
            return failure(StatusCode::FORBIDDEN, "project_route_grant_denied");
        }
        let root = || -> Option<std::path::PathBuf> {
            let configured = state.workspace_root.lock().ok()?.clone();
            let approved=state.session_store.connection().ok()?.query_row(
                "SELECT root FROM desktop_local_plugin_workspace_roots WHERE tenant_id=?1 AND project_id=?2 AND bundle_id=?3",
                rusqlite::params![scope.tenant_id,scope.project_id,tool.attribution().bundle.bundle_id],|r|r.get::<_,String>(0)).ok()?;
            let current = configured.canonicalize().ok()?;
            (std::path::Path::new(&approved) == current).then_some(current)
        };
        let Some(bound) = root() else {
            return failure(StatusCode::FORBIDDEN, "project_route_grant_denied");
        };
        let reply = plan
            .respond(bound.clone(), request.uri().clone(), head)
            .await;
        if root() != Some(bound) || !authority.authorize(&operation, tool.attribution()).await {
            return failure(StatusCode::FORBIDDEN, "project_route_grant_denied");
        }
        return reply;
    }
    guest_response(output, head)
}

fn guest_response(output: Value, head: bool) -> Response {
    let Ok(reply) = serde_json::from_value::<GuestResponse>(output) else {
        return failure(StatusCode::BAD_GATEWAY, "project_route_response_invalid");
    };
    let Ok(status) = StatusCode::from_u16(reply.status) else {
        return failure(StatusCode::BAD_GATEWAY, "project_route_response_invalid");
    };
    if !(200..600).contains(&reply.status) {
        return failure(StatusCode::BAD_GATEWAY, "project_route_response_invalid");
    }
    let mut response = (status, Json(reply.body)).into_response();
    if head {
        *response.body_mut() = Body::empty();
    }
    response
}
