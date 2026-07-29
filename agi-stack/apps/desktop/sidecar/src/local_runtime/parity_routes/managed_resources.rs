use std::sync::Arc;

use axum::{
    extract::{Extension, Path, Query, Request, State},
    http::{Method, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, patch, post},
    Json, Router,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

use super::super::{
    ensure_managed_resource_manager, ensure_project_scope, ensure_tenant_scope,
    resource_registry::{
        ManagedResourceKind, ManagedResourceMutationCommand, ManagedResourceMutationOperation,
        ManagedResourceMutationReceipt, ManagedResourceVersion, ResourceRegistryError,
    },
    resource_registry_error, AuthenticatedContext, LocalJsonResult, LocalRuntimeState,
};

mod support;

use support::*;

const CONTRACT_VERSION: u8 = 2;
const MAX_RESOURCE_BYTES: usize = 2 * 1_048_576;
const MAX_RESOURCE_ID_BYTES: usize = 200;

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route(
            "/api/v1/skills/",
            get(super::super::list_managed_skills).post(create_skill),
        )
        .route("/api/v1/skills/:skill_id/status", patch(set_skill_status))
        .route("/api/v1/skills/import", post(import_skill))
        .route(
            "/api/v1/skills/:skill_id/content",
            get(get_skill_content).put(update_skill_content),
        )
        .route(
            "/api/v1/skills/:skill_id/versions",
            get(list_skill_versions),
        )
        .route(
            "/api/v1/skills/:skill_id/versions/:version_number",
            get(get_skill_version),
        )
        .route("/api/v1/skills/:skill_id/rollback", post(rollback_skill))
        .route("/api/v1/skills/:skill_id/export", get(export_skill))
        .route(
            "/api/v1/skills/:skill_id",
            get(get_skill).put(update_skill).delete(delete_skill),
        )
        .route(
            "/api/v1/agent/definitions/:definition_id",
            get(get_agent).put(update_agent).delete(delete_agent),
        )
        .route(
            "/api/v1/agent/definitions",
            get(super::super::list_managed_agents).post(create_agent),
        )
        .route(
            "/api/v1/agent/definitions/:definition_id/enabled",
            patch(set_agent_enabled),
        )
        .route(
            "/api/v1/agent/templates",
            get(list_prompt_templates).post(create_prompt_template),
        )
        .route(
            "/api/v1/agent/templates/:template_id",
            get(get_prompt_template)
                .put(update_prompt_template)
                .delete(delete_prompt_template),
        )
        .route(
            "/api/v1/subagents/",
            get(list_subagents).post(create_subagent),
        )
        .route(
            "/api/v1/subagents/:subagent_id/enable",
            patch(set_subagent_enabled),
        )
        .route(
            "/api/v1/subagents/:subagent_id",
            get(get_subagent)
                .put(update_subagent)
                .delete(delete_subagent),
        )
        .route_layer(middleware::from_fn(require_manager_for_mutation))
}

async fn require_manager_for_mutation(request: Request, next: Next) -> Response {
    if matches!(*request.method(), Method::GET | Method::HEAD) {
        return next.run(request).await;
    }
    let Some(authenticated) = request.extensions().get::<AuthenticatedContext>() else {
        return (
            StatusCode::UNAUTHORIZED,
            Json(json!({ "detail": "authenticated desktop session required" })),
        )
            .into_response();
    };
    if let Err(error) = ensure_managed_resource_manager(authenticated) {
        return error.into_response();
    }
    next.run(request).await
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(in crate::local_runtime) struct MutationEnvelope {
    contract_version: u8,
    expected_revision: u64,
    idempotency_key: String,
    #[serde(default)]
    resource_id: Option<String>,
    #[serde(default)]
    value: Option<Value>,
    #[serde(default)]
    target_revision: Option<u64>,
    #[serde(default)]
    vault_refs: Vec<String>,
}

#[derive(Deserialize)]
pub(in crate::local_runtime) struct TenantQuery {
    tenant_id: Option<String>,
    project_id: Option<String>,
}

#[derive(Deserialize)]
struct SubAgentEnabledQuery {
    tenant_id: Option<String>,
    enabled: bool,
}

#[derive(Deserialize)]
pub(in crate::local_runtime) struct SkillStatusQuery {
    tenant_id: Option<String>,
    status: String,
}

pub(in crate::local_runtime) async fn create_skill(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    ensure_project_scope(&authenticated, query.project_id.as_deref())?;
    let scope_kind = skill_scope_kind(envelope.value.as_ref())?;
    let scope_id = scope_id(&authenticated, scope_kind);
    let resource_id = require_resource_id(&envelope)?;
    let receipt = mutate(
        &state,
        &authenticated,
        ManagedResourceKind::Skill,
        scope_kind,
        scope_id,
        &resource_id,
        ManagedResourceMutationOperation::Create,
        envelope,
    )?;
    resource_mutation_response(receipt)
}

pub(in crate::local_runtime) async fn create_agent(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    ensure_project_scope(&authenticated, query.project_id.as_deref())?;
    let resource_id = require_resource_id(&envelope)?;
    let receipt = mutate(
        &state,
        &authenticated,
        ManagedResourceKind::Agent,
        "project",
        &authenticated.workspace.project_id,
        &resource_id,
        ManagedResourceMutationOperation::Create,
        envelope,
    )?;
    resource_mutation_response(receipt)
}

pub(in crate::local_runtime) async fn set_skill_status(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(skill_id): Path<String>,
    Query(query): Query<SkillStatusQuery>,
    Json(mut envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    if !matches!(query.status.as_str(), "active" | "disabled" | "deprecated") {
        return Err(resource_registry_error(
            ResourceRegistryError::InvalidMutation("unsupported managed skill status".to_string()),
        ));
    }
    envelope.value = Some(json!({ "status": query.status }));
    update_resource(
        &state,
        &authenticated,
        &TenantQuery {
            tenant_id: query.tenant_id,
            project_id: None,
        },
        ManagedResourceKind::Skill,
        &skill_id,
        envelope,
    )
}

pub(in crate::local_runtime) async fn set_agent_enabled(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(agent_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(mut envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    let enabled = envelope
        .value
        .as_ref()
        .and_then(|value| value.get("enabled"))
        .and_then(Value::as_bool)
        .ok_or_else(|| {
            resource_registry_error(ResourceRegistryError::InvalidMutation(
                "managed Agent enabled mutation requires a boolean enabled value".to_string(),
            ))
        })?;
    envelope.value = Some(json!({
        "enabled": enabled,
        "status": if enabled { "active" } else { "disabled" },
    }));
    update_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::Agent,
        &agent_id,
        envelope,
    )
}

async fn get_skill(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(skill_id): Path<String>,
    Query(query): Query<TenantQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    ensure_project_scope(&authenticated, query.project_id.as_deref())?;
    let (_, _, skill) = find_resource(
        &state,
        &authenticated,
        ManagedResourceKind::Skill,
        &skill_id,
    )?;
    Ok(Json(skill))
}

async fn update_skill(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(skill_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    update_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::Skill,
        &skill_id,
        envelope,
    )
}

async fn delete_skill(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(skill_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    delete_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::Skill,
        &skill_id,
        envelope,
    )
}

async fn get_skill_content(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(skill_id): Path<String>,
    Query(query): Query<TenantQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let (_, _, skill) = find_resource(
        &state,
        &authenticated,
        ManagedResourceKind::Skill,
        &skill_id,
    )?;
    Ok(Json(json!({
        "skill_id": skill_id,
        "name": skill.get("name").cloned().unwrap_or(Value::Null),
        "full_content": skill.get("full_content").cloned().unwrap_or(Value::Null),
        "scope": skill.get("scope").cloned().unwrap_or_else(|| json!("tenant")),
        "is_system_skill": skill
            .get("is_system_skill")
            .cloned()
            .unwrap_or(Value::Bool(false)),
    })))
}

async fn update_skill_content(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(skill_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    update_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::Skill,
        &skill_id,
        envelope,
    )
}

async fn list_skill_versions(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(skill_id): Path<String>,
    Query(query): Query<TenantQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let (scope_kind, scope_id, _) = find_resource(
        &state,
        &authenticated,
        ManagedResourceKind::Skill,
        &skill_id,
    )?;
    let versions = state
        .session_store
        .list_managed_resource_versions(ManagedResourceKind::Skill, scope_kind, scope_id, &skill_id)
        .map_err(super::super::local_store_error)?;
    let items = versions
        .iter()
        .map(|version| version_summary(&skill_id, version))
        .collect::<Vec<_>>();
    Ok(Json(json!({ "versions": items, "total": items.len() })))
}

async fn get_skill_version(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((skill_id, version_number)): Path<(String, u64)>,
    Query(query): Query<TenantQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let (scope_kind, scope_id, _) = find_resource(
        &state,
        &authenticated,
        ManagedResourceKind::Skill,
        &skill_id,
    )?;
    let versions = state
        .session_store
        .list_managed_resource_versions(ManagedResourceKind::Skill, scope_kind, scope_id, &skill_id)
        .map_err(super::super::local_store_error)?;
    let version = versions
        .iter()
        .find(|version| version.revision == version_number)
        .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))?;
    let mut response = version_summary(&skill_id, version);
    response["skill_md_content"] = version
        .value
        .get("full_content")
        .cloned()
        .unwrap_or(Value::Null);
    response["resource_files"] = version
        .value
        .get("resource_files")
        .cloned()
        .unwrap_or_else(|| json!({}));
    response["tombstone"] = json!(version.tombstone);
    Ok(Json(response))
}

async fn rollback_skill(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(skill_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    ensure_managed_resource_manager(&authenticated)?;
    let (scope_kind, scope_id, current) = find_resource(
        &state,
        &authenticated,
        ManagedResourceKind::Skill,
        &skill_id,
    )?;
    let status = resource_status(&current).to_string();
    let receipt = mutate_at_scope(
        &state,
        &authenticated,
        ManagedResourceKind::Skill,
        scope_kind,
        scope_id,
        &skill_id,
        ManagedResourceMutationOperation::Rollback,
        &status,
        envelope,
    )?;
    resource_mutation_response(receipt)
}

async fn export_skill(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(skill_id): Path<String>,
    Query(query): Query<TenantQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let (_, _, skill) = find_resource(
        &state,
        &authenticated,
        ManagedResourceKind::Skill,
        &skill_id,
    )?;
    let content = skill
        .get("full_content")
        .and_then(Value::as_str)
        .map(str::to_string)
        .unwrap_or_else(|| generated_skill_content(&skill));
    Ok(Json(json!({
        "format": "agentskills.io/skill-package",
        "skill": skill,
        "skill_md_content": content,
        "resource_files": skill
            .get("resource_files")
            .cloned()
            .unwrap_or_else(|| json!({})),
        "version_number": skill.get("revision").cloned().unwrap_or_else(|| json!(0)),
        "version_label": skill.get("version_label").cloned().unwrap_or(Value::Null),
    })))
}

async fn import_skill(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let resource_id = require_resource_id(&envelope)?;
    let scope_kind = skill_scope_kind(envelope.value.as_ref())?;
    let scope_id = scope_id(&authenticated, scope_kind);
    let operation = if skill_import_overwrite(envelope.value.as_ref())? {
        ManagedResourceMutationOperation::Import
    } else {
        ManagedResourceMutationOperation::Create
    };
    let receipt = mutate(
        &state,
        &authenticated,
        ManagedResourceKind::Skill,
        scope_kind,
        scope_id,
        &resource_id,
        operation,
        envelope,
    )?;
    let duplicate = receipt.duplicate;
    let receipt_id = receipt.receipt_id.clone();
    let skill = receipt.resource.clone().ok_or_else(|| {
        resource_registry_error(ResourceRegistryError::InvalidMutation(
            "skill import did not produce a resource".to_string(),
        ))
    })?;
    Ok(Json(json!({
        "action": if operation == ManagedResourceMutationOperation::Create {
            "imported"
        } else {
            "updated"
        },
        "version_number": skill.get("revision").cloned().unwrap_or_else(|| json!(0)),
        "version_label": skill.get("version_label").cloned().unwrap_or(Value::Null),
        "skill": skill,
        "mutation_receipt": {
            "contract_version": CONTRACT_VERSION,
            "receipt_id": receipt_id,
            "duplicate": duplicate,
        },
    })))
}

async fn get_agent(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(agent_id): Path<String>,
    Query(query): Query<TenantQuery>,
) -> LocalJsonResult {
    get_project_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::Agent,
        &agent_id,
    )
}

async fn update_agent(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(agent_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    update_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::Agent,
        &agent_id,
        envelope,
    )
}

async fn delete_agent(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(agent_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    delete_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::Agent,
        &agent_id,
        envelope,
    )
}

async fn list_subagents(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<TenantQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let items = state
        .session_store
        .list_managed_resources(
            ManagedResourceKind::SubAgent,
            "tenant",
            &authenticated.workspace.tenant_id,
        )
        .map_err(super::super::local_store_error)?;
    Ok(Json(json!({ "items": items, "total": items.len() })))
}

async fn create_subagent(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let resource_id = require_resource_id(&envelope)?;
    let receipt = mutate(
        &state,
        &authenticated,
        ManagedResourceKind::SubAgent,
        "tenant",
        &authenticated.workspace.tenant_id,
        &resource_id,
        ManagedResourceMutationOperation::Create,
        envelope,
    )?;
    resource_mutation_response(receipt)
}

async fn get_subagent(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(subagent_id): Path<String>,
    Query(query): Query<TenantQuery>,
) -> LocalJsonResult {
    get_tenant_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::SubAgent,
        &subagent_id,
    )
}

async fn update_subagent(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(subagent_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    update_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::SubAgent,
        &subagent_id,
        envelope,
    )
}

async fn delete_subagent(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(subagent_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    delete_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::SubAgent,
        &subagent_id,
        envelope,
    )
}

async fn set_subagent_enabled(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(subagent_id): Path<String>,
    Query(query): Query<SubAgentEnabledQuery>,
    Json(mut envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let current = state
        .session_store
        .managed_resource(
            ManagedResourceKind::SubAgent,
            "tenant",
            &authenticated.workspace.tenant_id,
            &subagent_id,
        )
        .map_err(super::super::local_store_error)?
        .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))?;
    let mut value = current;
    let object = value.as_object_mut().ok_or_else(invalid_resource_object)?;
    object.insert("enabled".to_string(), json!(query.enabled));
    object.insert(
        "status".to_string(),
        json!(if query.enabled { "active" } else { "disabled" }),
    );
    envelope.value = Some(value);
    let receipt = mutate(
        &state,
        &authenticated,
        ManagedResourceKind::SubAgent,
        "tenant",
        &authenticated.workspace.tenant_id,
        &subagent_id,
        ManagedResourceMutationOperation::Update,
        envelope,
    )?;
    resource_mutation_response(receipt)
}

async fn list_prompt_templates(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<TenantQuery>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let items = state
        .session_store
        .list_managed_resources(
            ManagedResourceKind::PromptTemplate,
            "tenant",
            &authenticated.workspace.tenant_id,
        )
        .map_err(super::super::local_store_error)?;
    Ok(Json(Value::Array(items)))
}

async fn create_prompt_template(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    ensure_tenant_scope(&authenticated, query.tenant_id.as_deref())?;
    let resource_id = require_resource_id(&envelope)?;
    let receipt = mutate(
        &state,
        &authenticated,
        ManagedResourceKind::PromptTemplate,
        "tenant",
        &authenticated.workspace.tenant_id,
        &resource_id,
        ManagedResourceMutationOperation::Create,
        envelope,
    )?;
    resource_mutation_response(receipt)
}

async fn get_prompt_template(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(template_id): Path<String>,
    Query(query): Query<TenantQuery>,
) -> LocalJsonResult {
    get_tenant_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::PromptTemplate,
        &template_id,
    )
}

async fn update_prompt_template(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(template_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    update_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::PromptTemplate,
        &template_id,
        envelope,
    )
}

async fn delete_prompt_template(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(template_id): Path<String>,
    Query(query): Query<TenantQuery>,
    Json(envelope): Json<MutationEnvelope>,
) -> LocalJsonResult {
    delete_resource(
        &state,
        &authenticated,
        &query,
        ManagedResourceKind::PromptTemplate,
        &template_id,
        envelope,
    )
}
