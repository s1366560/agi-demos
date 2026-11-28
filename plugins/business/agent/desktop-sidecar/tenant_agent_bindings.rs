use serde::{Deserialize, Serialize};

use super::super::*;

const CAPABILITY: &str = "tenant_agent_bindings";
const SERVICE_VERSION: &str = env!("CARGO_PKG_VERSION");
const CONTRACT_VERSION: &str = "3.0.0";
const REASON_CODE: &str = "local_agent_binding_routing_authority_unavailable";

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route(
            "/api/v1/agent/bindings",
            get(list_bindings).post(mutation_unavailable),
        )
        .route("/api/v1/agent/bindings/test", post(mutation_unavailable))
        .route(
            "/api/v1/agent/bindings/:binding_id",
            delete(mutation_unavailable),
        )
        .route(
            "/api/v1/agent/bindings/:binding_id/enabled",
            patch(mutation_unavailable),
        )
}

async fn list_bindings(
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<TenantAgentBindingsQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, Some(&query.tenant_id))?;
    let response = TenantAgentBindingsResponse {
        capability: CAPABILITY,
        availability: "unavailable",
        reason_code: REASON_CODE,
        service_version: SERVICE_VERSION,
        contract_version: CONTRACT_VERSION,
        allowed_actions: [],
        scope: TenantAgentBindingsScope {
            tenant_id: query.tenant_id,
            project_id: None,
            workspace_id: None,
            instance_id: None,
        },
        authority_revision: authenticated.workspace.revision,
        bindings: [],
        definitions: [],
    };
    serde_json::to_value(response)
        .map(Json)
        .map_err(|error| response_error(error.to_string()))
}

async fn mutation_unavailable(
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<TenantAgentBindingsQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, Some(&query.tenant_id))?;
    Err((
        StatusCode::NOT_IMPLEMENTED,
        Json(json!({
            "capability": CAPABILITY,
            "availability": "unavailable",
            "reason_code": REASON_CODE,
            "service_version": SERVICE_VERSION,
            "contract_version": CONTRACT_VERSION,
            "allowed_actions": [],
            "scope": {
                "tenant_id": query.tenant_id,
                "project_id": null,
                "workspace_id": null,
                "instance_id": null,
            },
            "authority_revision": authenticated.workspace.revision,
        })),
    ))
}

fn response_error(error: String) -> (StatusCode, Json<Value>) {
    tracing::error!(
        error = %error,
        "local tenant agent bindings response serialization failed"
    );
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({
            "reason_code": "local_agent_bindings_response_error",
            "detail": "local tenant agent bindings are temporarily unavailable",
        })),
    )
}

#[derive(Deserialize)]
struct TenantAgentBindingsQuery {
    tenant_id: String,
}

#[derive(Serialize)]
struct TenantAgentBindingsResponse {
    capability: &'static str,
    availability: &'static str,
    reason_code: &'static str,
    service_version: &'static str,
    contract_version: &'static str,
    allowed_actions: [&'static str; 0],
    scope: TenantAgentBindingsScope,
    authority_revision: u64,
    bindings: [Value; 0],
    definitions: [Value; 0],
}

#[derive(Serialize)]
struct TenantAgentBindingsScope {
    tenant_id: String,
    project_id: Option<String>,
    workspace_id: Option<String>,
    instance_id: Option<String>,
}
