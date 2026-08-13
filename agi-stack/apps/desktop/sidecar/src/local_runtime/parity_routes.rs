use axum::extract::OriginalUri;

use super::*;

mod activity_read_state;
#[cfg(test)]
mod activity_read_state_tests;
mod artifact_content;
#[cfg(test)]
mod artifact_content_tests;
mod conversation_title;
#[cfg(test)]
mod conversation_title_tests;
pub(super) mod managed_resources;
#[cfg(test)]
mod managed_resources_tests;
mod mcp_apps;
#[cfg(test)]
mod mcp_apps_tests;
mod project_overview;
#[cfg(test)]
mod project_overview_tests;
mod sandbox_files;
#[cfg(test)]
mod sandbox_files_tests;
mod search;
#[cfg(test)]
mod search_tests;
mod tenant_agent_bindings;
#[cfg(test)]
mod tenant_agent_bindings_tests;
mod tenant_analytics;
#[cfg(test)]
mod tenant_analytics_tests;
mod tenant_overview;
#[cfg(test)]
mod tenant_overview_tests;
mod tenant_projects;
#[cfg(test)]
mod tenant_projects_tests;

const LOCAL_ROUTE_CONTRACT_VERSION: &str = "desktop-local-route-parity-v1";

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .merge(artifact_content::router())
        .merge(activity_read_state::router())
        .merge(conversation_title::router())
        .merge(mcp_apps::router())
        .merge(project_overview::router())
        .merge(tenant_overview::router())
        .merge(tenant_analytics::router())
        .merge(tenant_agent_bindings::router())
        .merge(tenant_projects::router())
        .merge(search::router())
        .merge(managed_resources::router())
        .route(
            "/api/v1/agent/workflows/patterns",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/agent/workflows/patterns/:pattern_id",
            delete(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/genes/",
            get(managed_read_unavailable).post(managed_mutation_unavailable),
        )
        .route("/api/v1/genes/genomes", get(managed_read_unavailable))
        .route("/api/v1/genes/evolution", get(managed_read_unavailable))
        .route(
            "/api/v1/genes/instances/:instance_id/install",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/genes/:gene_id",
            put(managed_mutation_unavailable).delete(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/genes/:gene_id/publish",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/genes/:gene_id/unpublish",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/genes/:gene_id/ratings",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/genes/:gene_id/reviews",
            get(managed_read_unavailable).post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/genes/:gene_id/reviews/:review_id",
            delete(managed_mutation_unavailable),
        )
        .route("/api/v1/events", get(managed_read_unavailable))
        .route("/api/v1/events/types", get(managed_read_unavailable))
        .route(
            "/api/v1/skills/import/zip",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/skills/evolution/overview",
            get(managed_read_unavailable),
        )
        .route(
            "/api/v1/skills/evolution/config",
            get(managed_read_unavailable).put(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/skills/evolution/run",
            post(managed_mutation_unavailable),
        )
        .route(
            "/api/v1/skills/evolution/jobs/:job_id/:action",
            post(managed_mutation_unavailable),
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
            "/api/v1/acp/tenants/:tenant_id/external-agents",
            get(managed_read_unavailable),
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

fn managed_unavailability(path: &str) -> (&'static str, &'static str, &'static str) {
    if path.starts_with("/api/v1/agent/workflows/patterns") {
        return (
            "tenant_workflow_patterns",
            "unavailable",
            "local_workflow_patterns_authority_unavailable",
        );
    }
    if path.starts_with("/api/v1/genes/") {
        return (
            "tenant_gene_market",
            "unavailable",
            "local_gene_market_authority_unavailable",
        );
    }
    if path == "/api/v1/events" || path == "/api/v1/events/types" {
        return (
            "tenant_event_ledger",
            "unavailable",
            "local_event_ledger_authority_unavailable",
        );
    }
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
            "unavailable",
            "local_skill_evolution_authority_unavailable",
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
