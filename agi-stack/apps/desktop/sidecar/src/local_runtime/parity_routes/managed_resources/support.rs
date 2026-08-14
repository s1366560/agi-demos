use super::*;
use crate::local_runtime::subagent_scope;

pub(super) fn update_resource(
    state: &Arc<LocalRuntimeState>,
    authenticated: &AuthenticatedContext,
    query: &TenantQuery,
    kind: ManagedResourceKind,
    resource_id: &str,
    mut envelope: MutationEnvelope,
) -> LocalJsonResult {
    ensure_tenant_scope(authenticated, query.tenant_id.as_deref())?;
    ensure_project_scope(authenticated, query.project_id.as_deref())?;
    ensure_managed_resource_manager(authenticated)?;
    let (scope_kind, scope_id, current) = find_resource(state, authenticated, kind, resource_id)?;
    let mut incoming = envelope.value.take().ok_or_else(|| {
        resource_registry_error(ResourceRegistryError::InvalidMutation(
            "managed resource update value is required".to_string(),
        ))
    })?;
    if matches!(
        kind,
        ManagedResourceKind::Agent | ManagedResourceKind::SubAgent
    ) {
        let object = incoming
            .as_object_mut()
            .ok_or_else(invalid_resource_object)?;
        normalize_subagent_trigger(object);
    }
    let mut merged = merge_resource_values(current, incoming)?;
    if kind == ManagedResourceKind::SubAgent {
        let object = merged.as_object_mut().ok_or_else(invalid_resource_object)?;
        normalize_subagent_project_scope(object, &authenticated.workspace.project_id)?;
    }
    envelope.value = Some(merged);
    let status = envelope
        .value
        .as_ref()
        .map(resource_status)
        .unwrap_or("active")
        .to_string();
    let receipt = mutate_at_scope(
        state,
        authenticated,
        kind,
        scope_kind,
        scope_id,
        resource_id,
        ManagedResourceMutationOperation::Update,
        &status,
        envelope,
    )?;
    resource_mutation_response(receipt)
}

pub(super) fn delete_resource(
    state: &Arc<LocalRuntimeState>,
    authenticated: &AuthenticatedContext,
    query: &TenantQuery,
    kind: ManagedResourceKind,
    resource_id: &str,
    envelope: MutationEnvelope,
) -> LocalJsonResult {
    ensure_tenant_scope(authenticated, query.tenant_id.as_deref())?;
    ensure_project_scope(authenticated, query.project_id.as_deref())?;
    ensure_managed_resource_manager(authenticated)?;
    let (scope_kind, scope_id, _) = find_resource(state, authenticated, kind, resource_id)?;
    let receipt = mutate_at_scope(
        state,
        authenticated,
        kind,
        scope_kind,
        scope_id,
        resource_id,
        ManagedResourceMutationOperation::Delete,
        "deleted",
        envelope,
    )?;
    Ok(Json(json!({
        "deleted": true,
        "id": resource_id,
        "mutation_receipt": receipt_metadata(&receipt),
    })))
}

pub(super) fn get_project_resource(
    state: &Arc<LocalRuntimeState>,
    authenticated: &AuthenticatedContext,
    query: &TenantQuery,
    kind: ManagedResourceKind,
    resource_id: &str,
) -> LocalJsonResult {
    ensure_tenant_scope(authenticated, query.tenant_id.as_deref())?;
    ensure_project_scope(authenticated, query.project_id.as_deref())?;
    state
        .session_store
        .managed_resource(
            kind,
            "project",
            &authenticated.workspace.project_id,
            resource_id,
        )
        .map_err(super::super::local_store_error)?
        .map(Json)
        .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))
}

pub(super) fn get_tenant_resource(
    state: &Arc<LocalRuntimeState>,
    authenticated: &AuthenticatedContext,
    query: &TenantQuery,
    kind: ManagedResourceKind,
    resource_id: &str,
) -> LocalJsonResult {
    ensure_tenant_scope(authenticated, query.tenant_id.as_deref())?;
    state
        .session_store
        .managed_resource(
            kind,
            "tenant",
            &authenticated.workspace.tenant_id,
            resource_id,
        )
        .map_err(super::super::local_store_error)?
        .map(Json)
        .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))
}

pub(super) fn find_resource<'a>(
    state: &Arc<LocalRuntimeState>,
    authenticated: &'a AuthenticatedContext,
    kind: ManagedResourceKind,
    resource_id: &str,
) -> Result<(&'static str, &'a str, Value), (StatusCode, Json<Value>)> {
    let candidates = match kind {
        ManagedResourceKind::Skill => vec![
            ("tenant", authenticated.workspace.tenant_id.as_str()),
            ("project", authenticated.workspace.project_id.as_str()),
        ],
        ManagedResourceKind::Agent => {
            vec![("project", authenticated.workspace.project_id.as_str())]
        }
        _ => vec![("tenant", authenticated.workspace.tenant_id.as_str())],
    };
    let mut found = None;
    for (scope_kind, scope_id) in candidates {
        if let Some(resource) = state
            .session_store
            .managed_resource(kind, scope_kind, scope_id, resource_id)
            .map_err(super::super::local_store_error)?
        {
            if kind == ManagedResourceKind::SubAgent
                && !subagent_scope::is_visible_in_project(
                    &resource,
                    &authenticated.workspace.project_id,
                )
            {
                continue;
            }
            if found.is_some() {
                return Err(resource_registry_error(
                    ResourceRegistryError::InvalidMutation(
                        "managed resource id is ambiguous across active scopes".to_string(),
                    ),
                ));
            }
            found = Some((scope_kind, scope_id, resource));
        }
    }
    found.ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))
}

#[allow(clippy::too_many_arguments)]
pub(super) fn mutate(
    state: &Arc<LocalRuntimeState>,
    authenticated: &AuthenticatedContext,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    resource_id: &str,
    operation: ManagedResourceMutationOperation,
    mut envelope: MutationEnvelope,
) -> Result<ManagedResourceMutationReceipt, (StatusCode, Json<Value>)> {
    ensure_managed_resource_manager(authenticated)?;
    if envelope.contract_version != CONTRACT_VERSION {
        return Err(resource_registry_error(
            ResourceRegistryError::InvalidMutation(
                "managed resource contract_version must be 2".to_string(),
            ),
        ));
    }
    if envelope
        .resource_id
        .as_deref()
        .is_some_and(|envelope_id| envelope_id != resource_id)
    {
        return Err(resource_registry_error(
            ResourceRegistryError::InvalidMutation(
                "managed resource body resource_id does not match the route".to_string(),
            ),
        ));
    }
    if let Some(value) = envelope.value.as_mut() {
        normalize_resource_value(kind, authenticated, scope_kind, resource_id, value)?;
    }
    let status = match operation {
        ManagedResourceMutationOperation::Delete => "deleted",
        _ => envelope
            .value
            .as_ref()
            .map(resource_status)
            .unwrap_or("active"),
    }
    .to_string();
    mutate_at_scope(
        state,
        authenticated,
        kind,
        scope_kind,
        scope_id,
        resource_id,
        operation,
        &status,
        envelope,
    )
}

#[allow(clippy::too_many_arguments)]
pub(super) fn mutate_at_scope(
    state: &Arc<LocalRuntimeState>,
    authenticated: &AuthenticatedContext,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    resource_id: &str,
    operation: ManagedResourceMutationOperation,
    status: &str,
    envelope: MutationEnvelope,
) -> Result<ManagedResourceMutationReceipt, (StatusCode, Json<Value>)> {
    if envelope.contract_version != CONTRACT_VERSION {
        return Err(resource_registry_error(
            ResourceRegistryError::InvalidMutation(
                "managed resource contract_version must be 2".to_string(),
            ),
        ));
    }
    validate_resource_id(resource_id)?;
    let payload = serde_json::to_vec(&(
        kind,
        scope_kind,
        scope_id,
        resource_id,
        operation,
        &envelope,
    ))
    .map_err(|error| super::super::local_store_error(error.to_string()))?;
    if payload.len() > MAX_RESOURCE_BYTES {
        return Err(resource_registry_error(
            ResourceRegistryError::InvalidMutation(
                "managed resource mutation exceeds the maximum payload size".to_string(),
            ),
        ));
    }
    let payload_hash = format!("sha256:{:x}", Sha256::digest(&payload));
    state
        .session_store
        .mutate_managed_resource(ManagedResourceMutationCommand {
            actor_id: authenticated.user.user_id.clone(),
            kind,
            scope_kind: scope_kind.to_string(),
            scope_id: scope_id.to_string(),
            resource_id: resource_id.to_string(),
            operation,
            expected_revision: envelope.expected_revision,
            idempotency_key: envelope.idempotency_key,
            payload_hash,
            status: status.to_string(),
            value: envelope.value,
            target_revision: envelope.target_revision,
            vault_refs: envelope.vault_refs,
            now_ms: Utc::now().timestamp_millis(),
        })
        .map_err(resource_registry_error)
}

pub(super) fn normalize_resource_value(
    kind: ManagedResourceKind,
    authenticated: &AuthenticatedContext,
    scope_kind: &str,
    resource_id: &str,
    value: &mut Value,
) -> Result<(), (StatusCode, Json<Value>)> {
    let object = value.as_object_mut().ok_or_else(invalid_resource_object)?;
    object.insert("id".to_string(), json!(resource_id));
    object.insert(
        "tenant_id".to_string(),
        json!(authenticated.workspace.tenant_id),
    );
    if scope_kind == "project" {
        object.insert(
            "project_id".to_string(),
            json!(authenticated.workspace.project_id),
        );
    }
    object
        .entry("status".to_string())
        .or_insert_with(|| json!("active"));
    match kind {
        ManagedResourceKind::Skill => {
            let is_package_import = object.contains_key("skill_md_content");
            normalize_skill_package(object)?;
            if is_package_import && object.get("name").and_then(Value::as_str) != Some(resource_id)
            {
                return Err(invalid_skill_package(
                    "managed skill package name must match resource_id",
                ));
            }
            object.remove("overwrite");
            object.insert("source".to_string(), json!("database"));
            object.insert("is_system_skill".to_string(), json!(false));
            object
                .entry("tools".to_string())
                .or_insert_with(|| json!([]));
            object
                .entry("scope".to_string())
                .or_insert_with(|| json!(scope_kind));
        }
        ManagedResourceKind::Agent => {
            object.insert("source".to_string(), json!("database"));
            object
                .entry("enabled".to_string())
                .or_insert_with(|| json!(true));
            normalize_subagent_trigger(object);
        }
        ManagedResourceKind::SubAgent => {
            normalize_subagent_project_scope(object, &authenticated.workspace.project_id)?;
            object.insert("source".to_string(), json!("database"));
            object
                .entry("enabled".to_string())
                .or_insert_with(|| json!(true));
            normalize_subagent_trigger(object);
        }
        ManagedResourceKind::PromptTemplate => {
            object.insert("is_system".to_string(), json!(false));
            object.insert("project_id".to_string(), Value::Null);
            object.insert("created_by".to_string(), json!(authenticated.user.user_id));
            object
                .entry("variables".to_string())
                .or_insert_with(|| json!([]));
            object
                .entry("usage_count".to_string())
                .or_insert_with(|| json!(0));
        }
        ManagedResourceKind::Provider | ManagedResourceKind::Plugin => {}
    }
    Ok(())
}

fn normalize_subagent_project_scope(
    object: &mut Map<String, Value>,
    active_project_id: &str,
) -> Result<(), (StatusCode, Json<Value>)> {
    subagent_scope::normalize_project_scope(object, active_project_id).map_err(|_| {
        resource_registry_error(ResourceRegistryError::InvalidMutation(
            "managed SubAgent project_id must be null or match the active project".to_string(),
        ))
    })
}

pub(super) fn normalize_skill_package(
    object: &mut Map<String, Value>,
) -> Result<(), (StatusCode, Json<Value>)> {
    let Some(skill_md_content) = object
        .get("skill_md_content")
        .and_then(Value::as_str)
        .map(str::to_string)
    else {
        return validate_resource_files(object);
    };
    if skill_md_content.len() > 1_048_576 {
        return Err(resource_registry_error(
            ResourceRegistryError::InvalidMutation(
                "managed skill package content exceeds 1 MiB".to_string(),
            ),
        ));
    }
    let mut lines = skill_md_content.lines();
    if lines.next() != Some("---") {
        return Err(invalid_skill_package(
            "managed skill package must begin with YAML frontmatter",
        ));
    }
    let mut frontmatter_lines = Vec::new();
    let mut closed = false;
    for line in lines.by_ref() {
        if line == "---" {
            closed = true;
            break;
        }
        frontmatter_lines.push(line);
    }
    if !closed {
        return Err(invalid_skill_package(
            "managed skill package frontmatter is not terminated",
        ));
    }
    let frontmatter: Value = serde_yaml_ng::from_str(&frontmatter_lines.join("\n"))
        .map_err(|_| invalid_skill_package("managed skill package frontmatter is invalid"))?;
    let name = required_package_string(&frontmatter, "name")?;
    let description = required_package_string(&frontmatter, "description")?;
    let tools = match frontmatter.get("allowed-tools") {
        Some(Value::String(value)) => value
            .split_whitespace()
            .map(str::to_string)
            .collect::<Vec<_>>(),
        Some(Value::Array(values)) => values
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()
            .ok_or_else(|| {
                invalid_skill_package(
                    "managed skill package allowed-tools must contain only strings",
                )
            })?
            .into_iter()
            .map(str::to_string)
            .collect(),
        Some(_) => {
            return Err(invalid_skill_package(
                "managed skill package allowed-tools must be a string or string array",
            ));
        }
        None => vec!["*".to_string()],
    };
    object.insert("name".to_string(), json!(name));
    object.insert("description".to_string(), json!(description));
    object.insert("tools".to_string(), json!(tools));
    object.insert("full_content".to_string(), json!(skill_md_content));
    validate_resource_files(object)
}

pub(super) fn required_package_string(
    frontmatter: &Value,
    key: &str,
) -> Result<String, (StatusCode, Json<Value>)> {
    frontmatter
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| {
            invalid_skill_package(&format!(
                "managed skill package {key} must be a non-empty string"
            ))
        })
}

pub(super) fn validate_resource_files(
    object: &Map<String, Value>,
) -> Result<(), (StatusCode, Json<Value>)> {
    let Some(files) = object.get("resource_files") else {
        return Ok(());
    };
    let files = files.as_object().ok_or_else(|| {
        invalid_skill_package("managed skill package resource_files must be an object")
    })?;
    let mut total_bytes = 0_usize;
    for (path, content) in files {
        let invalid_path = path.is_empty()
            || path.starts_with('/')
            || path.contains('\\')
            || path
                .split('/')
                .any(|component| component.is_empty() || matches!(component, "." | ".."));
        if invalid_path {
            return Err(invalid_skill_package(
                "managed skill package resource path is invalid",
            ));
        }
        let content = content.as_str().ok_or_else(|| {
            invalid_skill_package("managed skill package resources must contain text")
        })?;
        total_bytes = total_bytes.saturating_add(content.len());
        if total_bytes > 1_048_576 {
            return Err(invalid_skill_package(
                "managed skill package resources exceed 1 MiB",
            ));
        }
    }
    Ok(())
}

pub(super) fn invalid_skill_package(detail: &str) -> (StatusCode, Json<Value>) {
    resource_registry_error(ResourceRegistryError::InvalidMutation(detail.to_string()))
}

pub(super) fn normalize_subagent_trigger(object: &mut Map<String, Value>) {
    if object.contains_key("trigger") {
        return;
    }
    let description = object
        .remove("trigger_description")
        .unwrap_or_else(|| json!(""));
    let keywords = object
        .remove("trigger_keywords")
        .unwrap_or_else(|| json!([]));
    let examples = object
        .remove("trigger_examples")
        .unwrap_or_else(|| json!([]));
    object.insert(
        "trigger".to_string(),
        json!({
            "description": description,
            "keywords": keywords,
            "examples": examples,
        }),
    );
}

pub(super) fn merge_resource_values(
    current: Value,
    incoming: Value,
) -> Result<Value, (StatusCode, Json<Value>)> {
    let mut current = current
        .as_object()
        .cloned()
        .ok_or_else(invalid_resource_object)?;
    let incoming = incoming.as_object().ok_or_else(invalid_resource_object)?;
    current.extend(incoming.clone());
    Ok(Value::Object(current))
}

pub(super) fn resource_mutation_response(
    receipt: ManagedResourceMutationReceipt,
) -> LocalJsonResult {
    let mut resource = receipt
        .resource
        .clone()
        .ok_or_else(|| resource_registry_error(ResourceRegistryError::NotFound))?;
    let object = resource
        .as_object_mut()
        .ok_or_else(invalid_resource_object)?;
    object.insert("mutation_receipt".to_string(), receipt_metadata(&receipt));
    Ok(Json(resource))
}

pub(super) fn receipt_metadata(receipt: &ManagedResourceMutationReceipt) -> Value {
    json!({
        "contract_version": CONTRACT_VERSION,
        "receipt_id": receipt.receipt_id,
        "operation": receipt.operation,
        "resource_id": receipt.resource_id,
        "duplicate": receipt.duplicate,
    })
}

pub(super) fn version_summary(resource_id: &str, version: &ManagedResourceVersion) -> Value {
    json!({
        "id": format!("{resource_id}:{}", version.revision),
        "skill_id": resource_id,
        "version_number": version.revision,
        "version_label": version.value.get("version_label").cloned().unwrap_or(Value::Null),
        "change_summary": Value::Null,
        "created_by": "local-runtime",
        "created_at": iso_from_millis(version.created_at_ms),
        "status": version.status,
        "tombstone": version.tombstone,
    })
}

pub(super) fn require_resource_id(
    envelope: &MutationEnvelope,
) -> Result<String, (StatusCode, Json<Value>)> {
    let resource_id = envelope
        .resource_id
        .as_deref()
        .map(str::trim)
        .filter(|resource_id| !resource_id.is_empty())
        .ok_or_else(|| {
            resource_registry_error(ResourceRegistryError::InvalidMutation(
                "managed resource create requires resource_id".to_string(),
            ))
        })?;
    validate_resource_id(resource_id)?;
    Ok(resource_id.to_string())
}

pub(super) fn validate_resource_id(resource_id: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if resource_id.is_empty()
        || resource_id.len() > MAX_RESOURCE_ID_BYTES
        || resource_id.contains('/')
        || resource_id.contains('\\')
        || resource_id == "."
        || resource_id == ".."
    {
        return Err(resource_registry_error(
            ResourceRegistryError::InvalidMutation("managed resource id is invalid".to_string()),
        ));
    }
    Ok(())
}

pub(super) fn skill_scope_kind(
    value: Option<&Value>,
) -> Result<&'static str, (StatusCode, Json<Value>)> {
    match value
        .and_then(|value| value.get("scope"))
        .and_then(Value::as_str)
        .unwrap_or("tenant")
    {
        "tenant" => Ok("tenant"),
        "project" => Ok("project"),
        _ => Err(resource_registry_error(
            ResourceRegistryError::InvalidMutation(
                "local managed skill scope must be tenant or project".to_string(),
            ),
        )),
    }
}

pub(super) fn skill_import_overwrite(
    value: Option<&Value>,
) -> Result<bool, (StatusCode, Json<Value>)> {
    match value.and_then(|value| value.get("overwrite")) {
        Some(Value::Bool(overwrite)) => Ok(*overwrite),
        Some(_) => Err(invalid_skill_package(
            "managed skill package overwrite must be a boolean",
        )),
        None => Ok(false),
    }
}

pub(super) fn scope_id<'a>(authenticated: &'a AuthenticatedContext, scope_kind: &str) -> &'a str {
    if scope_kind == "project" {
        &authenticated.workspace.project_id
    } else {
        &authenticated.workspace.tenant_id
    }
}

pub(super) fn resource_status(value: &Value) -> &str {
    value
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("active")
}

pub(super) fn generated_skill_content(skill: &Value) -> String {
    let name = skill
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or("Local skill");
    let description = skill
        .get("description")
        .and_then(Value::as_str)
        .unwrap_or("");
    format!("# {name}\n\n{description}\n")
}

pub(super) fn iso_from_millis(timestamp_ms: i64) -> String {
    DateTime::<Utc>::from_timestamp_millis(timestamp_ms)
        .unwrap_or_else(Utc::now)
        .to_rfc3339()
}

pub(super) fn invalid_resource_object() -> (StatusCode, Json<Value>) {
    resource_registry_error(ResourceRegistryError::InvalidMutation(
        "managed resource value must be an object".to_string(),
    ))
}
