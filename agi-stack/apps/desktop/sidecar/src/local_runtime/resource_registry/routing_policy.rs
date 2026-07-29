use std::collections::HashSet;

use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};

use super::{
    schema::iso_from_millis, ResourceRegistryError, WorkspaceAgentCapabilityMode,
    WorkspaceAgentPolicyMutation, WORKSPACE_AGENT_POLICY_CAPABILITY_VERSION,
};

pub(super) fn query_routing_policy(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
) -> Result<Option<Value>, ResourceRegistryError> {
    let value_json = transaction
        .query_row(
            "SELECT value_json FROM desktop_llm_routing_policies WHERE tenant_id = ?1",
            params![tenant_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    value_json
        .map(|value| {
            serde_json::from_str(&value)
                .map_err(|error| ResourceRegistryError::Storage(error.to_string()))
        })
        .transpose()
}

pub(super) fn query_workspace_routing_policy(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<Option<Value>, ResourceRegistryError> {
    let value_json = transaction
        .query_row(
            "SELECT value_json FROM desktop_llm_workspace_routing_policies
             WHERE tenant_id = ?1 AND project_id = ?2 AND workspace_id = ?3",
            params![tenant_id, project_id, workspace_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    value_json
        .map(|value| {
            serde_json::from_str(&value)
                .map_err(|error| ResourceRegistryError::Storage(error.to_string()))
        })
        .transpose()
}

pub(in crate::local_runtime) fn apply_workspace_agent_policy_mutation(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    mutation: &WorkspaceAgentPolicyMutation,
    now_ms: i64,
) -> Result<Value, ResourceRegistryError> {
    if !matches!(
        mutation.reasoning_effort.as_str(),
        "low" | "medium" | "high"
    ) {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(
            "reasoning_effort must be low, medium, or high".to_string(),
        ));
    }
    if !matches!(
        mutation.permission_mode.as_str(),
        "ask" | "automatic" | "full_access"
    ) {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(
            "permission_mode must be ask, automatic, or full_access".to_string(),
        ));
    }
    validate_routing_target(transaction, tenant_id, &mutation.route)?;
    let baseline = query_routing_policy(transaction, tenant_id)?
        .or(legacy_routing_policy(transaction, tenant_id)?)
        .unwrap_or_else(|| empty_routing_policy(tenant_id, now_ms));
    let mut policy =
        query_workspace_routing_policy(transaction, tenant_id, project_id, workspace_id)?
            .unwrap_or(workspace_routing_policy_from_baseline(
                baseline,
                tenant_id,
                project_id,
                workspace_id,
                now_ms,
            )?);
    let current_revision = policy.get("revision").and_then(Value::as_u64).unwrap_or(0);
    if mutation.expected_revision != current_revision {
        return Err(ResourceRegistryError::RevisionConflict {
            expected: mutation.expected_revision,
            actual: current_revision,
        });
    }
    let object = policy.as_object_mut().ok_or_else(|| {
        ResourceRegistryError::Storage("workspace agent policy must be an object".to_string())
    })?;
    let roles = object
        .get_mut("roles")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            ResourceRegistryError::InvalidRoutingPolicy(
                "routing roles must be an object".to_string(),
            )
        })?;
    if roles.get("default").map_or(true, Value::is_null) {
        roles.insert("default".to_string(), mutation.route.clone());
    }
    let role = match mutation.capability_mode {
        WorkspaceAgentCapabilityMode::Work => "default",
        WorkspaceAgentCapabilityMode::Code => "coding",
    };
    roles.insert(role.to_string(), mutation.route.clone());
    let next_revision = current_revision.saturating_add(1);
    object.insert("revision".to_string(), json!(next_revision));
    object.insert(
        "reasoning_effort".to_string(),
        json!(mutation.reasoning_effort),
    );
    object.insert(
        "permission_mode".to_string(),
        json!(mutation.permission_mode),
    );
    object.insert(
        "capability_version".to_string(),
        json!(WORKSPACE_AGENT_POLICY_CAPABILITY_VERSION),
    );
    object.insert("updated_at".to_string(), json!(iso_from_millis(now_ms)));
    let roles = object.get("roles").cloned().unwrap_or(Value::Null);
    let fallbacks = object
        .get("fallbacks")
        .cloned()
        .unwrap_or_else(|| json!([]));
    validate_routing_policy_targets(transaction, tenant_id, &roles, &fallbacks)?;
    let value_json = serde_json::to_string(&policy)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    transaction
        .execute(
            "INSERT INTO desktop_llm_workspace_routing_policies(
               tenant_id, project_id, workspace_id, revision, updated_at_ms, value_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)
             ON CONFLICT(tenant_id, project_id, workspace_id) DO UPDATE SET
               revision = excluded.revision,
               updated_at_ms = excluded.updated_at_ms,
               value_json = excluded.value_json",
            params![
                tenant_id,
                project_id,
                workspace_id,
                next_revision,
                now_ms,
                value_json
            ],
        )
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    Ok(policy)
}

pub(in crate::local_runtime) fn ensure_workspace_agent_policy_in_transaction(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    now_ms: i64,
) -> Result<Value, ResourceRegistryError> {
    if let Some(policy) =
        query_workspace_routing_policy(transaction, tenant_id, project_id, workspace_id)?
    {
        return with_workspace_agent_policy_defaults(policy);
    }
    let baseline = query_routing_policy(transaction, tenant_id)?
        .or(legacy_routing_policy(transaction, tenant_id)?)
        .unwrap_or_else(|| empty_routing_policy(tenant_id, now_ms));
    let policy = workspace_routing_policy_from_baseline(
        baseline,
        tenant_id,
        project_id,
        workspace_id,
        now_ms,
    )?;
    let value_json = serde_json::to_string(&policy)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    transaction
        .execute(
            "INSERT INTO desktop_llm_workspace_routing_policies(
               tenant_id, project_id, workspace_id, revision, updated_at_ms, value_json
             ) VALUES (?1, ?2, ?3, 0, ?4, ?5)",
            params![tenant_id, project_id, workspace_id, now_ms, value_json],
        )
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    Ok(policy)
}

pub(super) fn with_workspace_agent_policy_defaults(
    mut policy: Value,
) -> Result<Value, ResourceRegistryError> {
    let object = policy.as_object_mut().ok_or_else(|| {
        ResourceRegistryError::Storage("workspace agent policy must be an object".to_string())
    })?;
    object
        .entry("reasoning_effort".to_string())
        .or_insert_with(|| json!("medium"));
    object
        .entry("permission_mode".to_string())
        .or_insert_with(|| json!("ask"));
    object.insert(
        "capability_version".to_string(),
        json!(WORKSPACE_AGENT_POLICY_CAPABILITY_VERSION),
    );
    Ok(policy)
}

fn workspace_routing_policy_from_baseline(
    mut policy: Value,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    now_ms: i64,
) -> Result<Value, ResourceRegistryError> {
    let object = policy.as_object_mut().ok_or_else(|| {
        ResourceRegistryError::Storage("routing policy must be an object".to_string())
    })?;
    object.insert("tenant_id".to_string(), json!(tenant_id));
    object.insert("project_id".to_string(), json!(project_id));
    object.insert("workspace_id".to_string(), json!(workspace_id));
    object.insert("revision".to_string(), json!(0));
    object.insert("updated_at".to_string(), json!(iso_from_millis(now_ms)));
    object.insert("reasoning_effort".to_string(), json!("medium"));
    object.insert("permission_mode".to_string(), json!("ask"));
    object.insert(
        "capability_version".to_string(),
        json!(WORKSPACE_AGENT_POLICY_CAPABILITY_VERSION),
    );
    Ok(policy)
}

fn query_workspace_routing_policies_for_tenant(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
) -> Result<Vec<Value>, ResourceRegistryError> {
    let mut statement = transaction
        .prepare(
            "SELECT value_json FROM desktop_llm_workspace_routing_policies
             WHERE tenant_id = ?1 ORDER BY project_id ASC, workspace_id ASC",
        )
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    let policies = statement
        .query_map(params![tenant_id], |row| row.get::<_, String>(0))
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?
        .map(|row| {
            let value_json =
                row.map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
            serde_json::from_str(&value_json)
                .map_err(|error| ResourceRegistryError::Storage(error.to_string()))
        })
        .collect();
    policies
}

pub(super) fn sync_routing_policy_default(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    provider_id: &str,
    model_id: &str,
    expected_revision: u64,
    now_ms: i64,
) -> Result<(), ResourceRegistryError> {
    let target = json!({
        "provider_id": provider_id,
        "model_id": model_id,
    });
    let mut policy = query_routing_policy(transaction, tenant_id)?.unwrap_or_else(|| {
        json!({
            "tenant_id": tenant_id,
            "revision": 0,
            "roles": {
                "default": null,
                "fast": null,
                "coding": null,
                "vision": null,
            },
            "fallbacks": [],
            "updated_at": iso_from_millis(now_ms),
        })
    });
    let current_revision = policy.get("revision").and_then(Value::as_u64).unwrap_or(0);
    if expected_revision != current_revision {
        return Err(ResourceRegistryError::RevisionConflict {
            expected: expected_revision,
            actual: current_revision,
        });
    }
    if policy.get("roles").and_then(|roles| roles.get("default")) == Some(&target) {
        return Ok(());
    }
    let next_revision = current_revision.saturating_add(1);
    let policy_object = policy.as_object_mut().ok_or_else(|| {
        ResourceRegistryError::Storage("routing policy must be an object".to_string())
    })?;
    let roles = policy_object
        .get_mut("roles")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            ResourceRegistryError::Storage("routing policy roles must be an object".to_string())
        })?;
    roles.insert("default".to_string(), target);
    policy_object.insert("revision".to_string(), json!(next_revision));
    policy_object.insert("updated_at".to_string(), json!(iso_from_millis(now_ms)));
    let value_json = serde_json::to_string(&policy)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    transaction
        .execute(
            "INSERT INTO desktop_llm_routing_policies(
               tenant_id, revision, updated_at_ms, value_json
             ) VALUES (?1, ?2, ?3, ?4)
             ON CONFLICT(tenant_id) DO UPDATE SET
               revision = excluded.revision,
               updated_at_ms = excluded.updated_at_ms,
               value_json = excluded.value_json",
            params![tenant_id, next_revision, now_ms, value_json],
        )
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    Ok(())
}

fn legacy_routing_policy(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
) -> Result<Option<Value>, ResourceRegistryError> {
    let selected = transaction
        .query_row(
            "SELECT selection.provider_id, selection.selected_at_ms, resource.value_json
             FROM desktop_llm_provider_selections AS selection
             JOIN desktop_managed_resources AS resource
               ON resource.kind = 'provider'
              AND resource.scope_kind = 'tenant'
              AND resource.scope_id = selection.tenant_id
              AND resource.id = selection.provider_id
             WHERE selection.tenant_id = ?1",
            params![tenant_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, i64>(1)?,
                    row.get::<_, String>(2)?,
                ))
            },
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    let Some((provider_id, selected_at_ms, provider_json)) = selected else {
        return Ok(None);
    };
    let provider: Value = serde_json::from_str(&provider_json)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    let Some(model_id) = provider
        .get("llm_model")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|model| !model.is_empty())
    else {
        return Ok(None);
    };
    Ok(Some(json!({
        "tenant_id": tenant_id,
        "revision": 0,
        "roles": {
            "default": {
                "provider_id": provider_id,
                "model_id": model_id,
            },
            "fast": null,
            "coding": null,
            "vision": null,
        },
        "fallbacks": [],
        "updated_at": iso_from_millis(selected_at_ms),
    })))
}

fn empty_routing_policy(tenant_id: &str, now_ms: i64) -> Value {
    json!({
        "tenant_id": tenant_id,
        "revision": 0,
        "roles": {
            "default": null,
            "fast": null,
            "coding": null,
            "vision": null,
        },
        "fallbacks": [],
        "updated_at": iso_from_millis(now_ms),
    })
}

pub(super) fn validate_routing_policy_targets(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    roles: &Value,
    fallbacks: &Value,
) -> Result<(), ResourceRegistryError> {
    let roles = roles.as_object().ok_or_else(|| {
        ResourceRegistryError::InvalidRoutingPolicy("routing roles must be an object".to_string())
    })?;
    let default = roles
        .get("default")
        .filter(|target| !target.is_null())
        .ok_or_else(|| {
            ResourceRegistryError::InvalidRoutingPolicy(
                "default routing target is required".to_string(),
            )
        })?;
    validate_routing_target(transaction, tenant_id, default)?;
    for role in ["fast", "coding", "vision"] {
        if let Some(target) = roles.get(role).filter(|target| !target.is_null()) {
            validate_routing_target(transaction, tenant_id, target)?;
        }
    }
    let fallbacks = fallbacks.as_array().ok_or_else(|| {
        ResourceRegistryError::InvalidRoutingPolicy(
            "routing fallbacks must be an array".to_string(),
        )
    })?;
    if fallbacks.len() > 8 {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(
            "routing fallbacks cannot contain more than 8 targets".to_string(),
        ));
    }
    let mut seen = HashSet::with_capacity(fallbacks.len());
    for target in fallbacks {
        let identity = routing_target_identity(target)?;
        if !seen.insert(identity) {
            return Err(ResourceRegistryError::InvalidRoutingPolicy(
                "routing fallbacks cannot contain duplicate targets".to_string(),
            ));
        }
        validate_routing_target(transaction, tenant_id, target)?;
    }
    Ok(())
}

pub(super) fn validate_routing_target(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    target: &Value,
) -> Result<(), ResourceRegistryError> {
    let (provider_id, model_id) = routing_target_identity(target)?;
    let provider = transaction
        .query_row(
            "SELECT status, value_json FROM desktop_managed_resources
             WHERE kind = 'provider' AND scope_kind = 'tenant'
               AND scope_id = ?1 AND id = ?2",
            params![tenant_id, provider_id],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?
        .ok_or(ResourceRegistryError::NotFound)?;
    let provider_value: Value = serde_json::from_str(&provider.1)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    if !provider_is_configured(&provider.0, &provider_value) {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(format!(
            "provider {provider_id} must be active and configured"
        )));
    }
    if !provider_supports_model(&provider_value, &model_id) {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(format!(
            "model {model_id} is not configured for provider {provider_id}"
        )));
    }
    Ok(())
}

pub(super) fn ensure_provider_policy_compatible(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    provider_id: &str,
    status: &str,
    provider: &Value,
) -> Result<(), ResourceRegistryError> {
    let mut policies = query_workspace_routing_policies_for_tenant(transaction, tenant_id)?;
    if let Some(policy) = query_routing_policy(transaction, tenant_id)? {
        policies.push(policy);
    } else if let Some(policy) = legacy_routing_policy(transaction, tenant_id)? {
        policies.push(policy);
    }
    if policies.is_empty() {
        return Ok(());
    }
    let mut referenced_models = Vec::new();
    for policy in policies {
        if let Some(roles) = policy.get("roles").and_then(Value::as_object) {
            for role in ["default", "fast", "coding", "vision"] {
                if let Some(target) = roles.get(role).filter(|target| !target.is_null()) {
                    let (target_provider_id, model_id) = routing_target_identity(target)?;
                    if target_provider_id == provider_id {
                        referenced_models.push((role.to_string(), model_id));
                    }
                }
            }
        }
        if let Some(fallbacks) = policy.get("fallbacks").and_then(Value::as_array) {
            for target in fallbacks {
                let (target_provider_id, model_id) = routing_target_identity(target)?;
                if target_provider_id == provider_id {
                    referenced_models.push(("fallback".to_string(), model_id));
                }
            }
        }
    }
    if referenced_models.is_empty() {
        return Ok(());
    }
    if !provider_is_configured(status, provider) {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(format!(
            "provider update would invalidate routing policy target {provider_id}"
        )));
    }
    if let Some((role, model_id)) = referenced_models
        .into_iter()
        .find(|(_, model_id)| !provider_supports_model(provider, model_id))
    {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(format!(
            "provider update would invalidate {role} routing model {model_id}"
        )));
    }
    Ok(())
}

fn routing_target_identity(target: &Value) -> Result<(String, String), ResourceRegistryError> {
    let provider_id = target
        .get("provider_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            ResourceRegistryError::InvalidRoutingPolicy(
                "routing target provider_id cannot be empty".to_string(),
            )
        })?;
    let model_id = target
        .get("model_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            ResourceRegistryError::InvalidRoutingPolicy(
                "routing target model_id cannot be empty".to_string(),
            )
        })?;
    Ok((provider_id.to_string(), model_id.to_string()))
}

fn provider_supports_model(provider: &Value, model_id: &str) -> bool {
    provider
        .get("llm_model")
        .and_then(Value::as_str)
        .is_some_and(|model| model.trim() == model_id)
        || provider
            .get("allowed_models")
            .and_then(Value::as_array)
            .is_some_and(|models| {
                models
                    .iter()
                    .any(|model| model.as_str().is_some_and(|model| model.trim() == model_id))
            })
}

fn provider_is_configured(status: &str, provider: &Value) -> bool {
    let credential_configured = provider
        .get("auth_method")
        .and_then(Value::as_str)
        .is_some_and(|auth_method| auth_method == "none")
        || provider
            .get("credential_configured")
            .and_then(Value::as_bool)
            == Some(true);
    status == "active"
        && credential_configured
        && provider.get("is_active").and_then(Value::as_bool) == Some(true)
        && provider
            .get("provider_type")
            .and_then(Value::as_str)
            .is_some_and(|value| !value.trim().is_empty())
        && provider
            .get("base_url")
            .and_then(Value::as_str)
            .is_some_and(|value| !value.trim().is_empty())
        && provider
            .get("llm_model")
            .and_then(Value::as_str)
            .is_some_and(|value| !value.trim().is_empty())
}
