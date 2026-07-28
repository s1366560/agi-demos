use axum::extract::OriginalUri;

use super::*;

mod artifact_content;
#[cfg(test)]
mod artifact_content_tests;
mod sandbox_files;
#[cfg(test)]
mod sandbox_files_tests;
mod search;
#[cfg(test)]
mod search_tests;

const LOCAL_ROUTE_CONTRACT_VERSION: &str = "desktop-local-route-parity-v1";

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .merge(artifact_content::router())
        .merge(search::router())
        .route("/api/v1/skills/import", post(managed_mutation_unavailable))
        .route(
            "/api/v1/skills/import/zip",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/skills/evolution/jobs/:job_id/:action",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/skills/:skill_id/content",
            get(managed_read_unavailable).put(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/skills/:skill_id/versions",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/skills/:skill_id/versions/:version_number",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/skills/:skill_id/rollback",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/skills/:skill_id/export",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/skills/:skill_id/evolution",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/skills/:skill_id/evolution/run",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/skills/:skill_id",
            put(managed_mutation_unavailable).delete(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/channels/tenants/:tenant_id/plugins/install",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/channels/tenants/:tenant_id/plugins/reload",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/channels/tenants/:tenant_id/plugins/channel-catalog",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/channels/tenants/:tenant_id/plugins/channel-catalog/:channel_type/schema",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/channels/tenants/:tenant_id/plugins/:plugin_id/uninstall",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/channels/tenants/:tenant_id/plugins/:plugin_id/config-schema",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/channels/tenants/:tenant_id/plugins/:plugin_id/config",
            get(managed_read_unavailable).put(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/channels/projects/:project_id/configs",
            get(managed_read_unavailable).post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/channels/configs/:config_id",
            put(managed_mutation_unavailable).delete(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/channels/configs/:config_id/test",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/agent/definitions/:definition_id",
            put(managed_mutation_unavailable).delete(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/agent/templates",
            get(managed_read_unavailable).post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/agent/templates/:template_id",
            delete(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/acp/tenants/:tenant_id/external-agents",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/subagents/",
            get(managed_read_unavailable).post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/subagents/templates/list",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/subagents/templates/:template_id/install",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/subagents/filesystem/:name/import",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/subagents/:subagent_id/enable",
            patch(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/subagents/:subagent_id",
            put(managed_mutation_unavailable).delete(managed_mutation_unavailable),
        )
        .route("/api/v1/mcp/apps", get(mcp_read_unavailable))
        .route(
            "/api/v1/mcp/apps/:app_id/tool-call",
            post(mcp_action_unavailable),
        )
        .route(
            "/api/v1/mcp/apps/proxy/tool-call",
            post(mcp_scoped_action_unavailable),
        )
        .route(
            "/api/v1/mcp/apps/resources/read",
            post(mcp_scoped_read_unavailable),
        )
        .route(
            "/api/v1/mcp/apps/resources/list",
            post(mcp_scoped_read_unavailable),
        )
        .merge(sandbox_files::router())
}

pub(super) async fn managed_mutation_unavailable(
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
) -> LocalJsonResult {
    ensure_uri_scope(&authenticated, &uri)?;
    ensure_managed_resource_manager(&authenticated)?;
    let (capability, availability, reason_code) = managed_unavailability(uri.path());
    unavailable(&uri, capability, availability, reason_code)
}

async fn managed_read_unavailable(
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
) -> LocalJsonResult {
    ensure_uri_scope(&authenticated, &uri)?;
    let (capability, availability, reason_code) = managed_unavailability(uri.path());
    unavailable(&uri, capability, availability, reason_code)
}

async fn mcp_read_unavailable(
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
) -> LocalJsonResult {
    ensure_uri_scope(&authenticated, &uri)?;
    unavailable(
        &uri,
        "mcp_apps",
        "unavailable",
        "local_mcp_supervisor_unavailable",
    )
}

async fn mcp_action_unavailable(
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
) -> LocalJsonResult {
    ensure_uri_scope(&authenticated, &uri)?;
    unavailable(
        &uri,
        "mcp_apps",
        "unavailable",
        "local_mcp_supervisor_unavailable",
    )
}

async fn mcp_scoped_action_unavailable(
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
    Json(body): Json<Value>,
) -> LocalJsonResult {
    ensure_uri_scope(&authenticated, &uri)?;
    ensure_body_scope(&authenticated, &body, false, true)?;
    unavailable(
        &uri,
        "mcp_apps",
        "unavailable",
        "local_mcp_supervisor_unavailable",
    )
}

async fn mcp_scoped_read_unavailable(
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
    Json(body): Json<Value>,
) -> LocalJsonResult {
    ensure_uri_scope(&authenticated, &uri)?;
    ensure_body_scope(&authenticated, &body, false, true)?;
    unavailable(
        &uri,
        "mcp_apps",
        "unavailable",
        "local_mcp_supervisor_unavailable",
    )
}

fn managed_unavailability(path: &str) -> (&'static str, &'static str, &'static str) {
    if path.starts_with("/api/v1/channels/") {
        return (
            "managed_plugins",
            "not_applicable",
            "local_channel_runtime_not_applicable",
        );
    }
    if path.starts_with("/api/v1/acp/") {
        return (
            "managed_agents",
            "not_applicable",
            "local_external_acp_not_applicable",
        );
    }
    if path.starts_with("/api/v1/subagents/") {
        return (
            "managed_subagents",
            "unavailable",
            "local_subagent_registry_unavailable",
        );
    }
    if path.contains("/evolution") {
        return (
            "managed_skills",
            "not_applicable",
            "local_skill_evolution_not_applicable",
        );
    }
    if path.contains("/versions") || path.ends_with("/rollback") || path.ends_with("/export") {
        return (
            "managed_skills",
            "unavailable",
            "local_skill_version_authority_unavailable",
        );
    }
    (
        if path.starts_with("/api/v1/skills/") {
            "managed_skills"
        } else {
            "managed_agents"
        },
        "unavailable",
        "managed_resource_contract_v2_required",
    )
}

fn ensure_uri_scope(
    authenticated: &AuthenticatedContext,
    uri: &OriginalUri,
) -> Result<(), (StatusCode, Json<Value>)> {
    let path = uri.path().trim_matches('/').split('/').collect::<Vec<_>>();
    match path.as_slice() {
        ["api", "v1", "channels", "tenants", tenant_id, ..]
        | ["api", "v1", "acp", "tenants", tenant_id, ..] => {
            ensure_tenant_scope(authenticated, Some(tenant_id))?;
        }
        ["api", "v1", "channels", "projects", project_id, ..] => {
            ensure_project_scope(authenticated, Some(project_id))?;
        }
        _ => {}
    }
    if let Some(query) = uri.query() {
        for (key, value) in url::form_urlencoded::parse(query.as_bytes()) {
            match key.as_ref() {
                "tenant_id" => ensure_tenant_scope(authenticated, Some(value.as_ref()))?,
                "project_id" => ensure_project_scope(authenticated, Some(value.as_ref()))?,
                _ => {}
            }
        }
    }
    Ok(())
}

fn ensure_body_scope(
    authenticated: &AuthenticatedContext,
    body: &Value,
    require_tenant: bool,
    require_project: bool,
) -> Result<(), (StatusCode, Json<Value>)> {
    let tenant_id = body.get("tenant_id").and_then(Value::as_str);
    let project_id = body.get("project_id").and_then(Value::as_str);
    if (require_tenant && tenant_id.is_none()) || (require_project && project_id.is_none()) {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({
                "code": "local_scope_required",
                "detail": "tenant_id and project_id must be explicit for this local route",
            })),
        ));
    }
    ensure_tenant_scope(authenticated, tenant_id)?;
    ensure_project_scope(authenticated, project_id)
}

fn unavailable(
    uri: &OriginalUri,
    capability: &str,
    availability: &str,
    reason_code: &str,
) -> LocalJsonResult {
    Err((
        StatusCode::NOT_IMPLEMENTED,
        Json(json!({
            "contract_version": LOCAL_ROUTE_CONTRACT_VERSION,
            "mode": "local",
            "capability": capability,
            "availability": availability,
            "reason_code": reason_code,
            "route": uri.path(),
        })),
    ))
}
