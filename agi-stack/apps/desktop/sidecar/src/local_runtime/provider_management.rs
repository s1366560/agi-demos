use super::*;

pub(super) async fn create_llm_provider(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    Json(request): Json<LlmProviderMutation>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    let create_idempotency =
        provider_create_idempotency(&headers, &authenticated.workspace.tenant_id, &request)?;
    let provider_id = create_idempotency.as_ref().map_or_else(
        || format!("provider-{}", Uuid::new_v4()),
        |idempotency| idempotency.provider_id.clone(),
    );
    mutate_llm_provider_blocking(
        state,
        authenticated,
        provider_id,
        request,
        true,
        create_idempotency,
    )
    .await
}

pub(super) async fn update_llm_provider(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(provider_id): Path<String>,
    Json(request): Json<LlmProviderMutation>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    if request.expected_revision.is_none() {
        return Err((
            StatusCode::PRECONDITION_REQUIRED,
            Json(json!({ "detail": "expected_revision is required" })),
        ));
    }
    mutate_llm_provider_blocking(state, authenticated, provider_id, request, false, None).await
}

pub(super) async fn delete_llm_provider(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(provider_id): Path<String>,
    headers: HeaderMap,
    Json(request): Json<LlmProviderDeleteAction>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    let header_key = headers
        .get("idempotency-key")
        .map(|value| {
            value.to_str().map_err(|_| {
                local_bad_request("invalid provider delete idempotency key".to_string())
            })
        })
        .transpose()?;
    let idempotency_key = match (request.idempotency_key.as_deref(), header_key) {
        (Some(body_key), Some(header_key)) if body_key != header_key => {
            return Err(local_bad_request(
                "provider delete idempotency keys do not match".to_string(),
            ));
        }
        (Some(body_key), _) => body_key,
        (None, Some(header_key)) => header_key,
        (None, None) => {
            return Err((
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({
                    "code": "provider_delete_idempotency_key_required",
                    "detail": "provider delete requires an idempotency key",
                })),
            ));
        }
    };
    if !(16..=256).contains(&idempotency_key.len()) || idempotency_key.trim() != idempotency_key {
        return Err(local_bad_request(
            "invalid provider delete idempotency key".to_string(),
        ));
    }
    let idempotency_key = idempotency_key.to_string();
    tokio::task::spawn_blocking(move || {
        delete_llm_provider_blocking(state, authenticated, provider_id, request, idempotency_key)
    })
    .await
    .map_err(|_| local_store_error("provider credential storage task failed".to_string()))?
}

#[derive(Debug)]
struct LlmProviderCreateIdempotency {
    key: String,
    request_hash: String,
    provider_id: String,
}

fn delete_llm_provider_blocking(
    state: Arc<LocalRuntimeState>,
    authenticated: AuthenticatedContext,
    provider_id: String,
    request: LlmProviderDeleteAction,
    idempotency_key: String,
) -> LocalJsonResult {
    let tenant_id = authenticated.workspace.tenant_id.clone();
    let current = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            &tenant_id,
            &provider_id,
        )
        .map_err(local_store_error)?;
    let current_revision = current
        .as_ref()
        .and_then(|provider| provider.get("revision"))
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let credential_binding = current.as_ref().and_then(provider_credential_binding);
    if let Some(binding_digest) = credential_binding.as_deref() {
        state
            .provider_credentials
            .schedule_cleanup(&tenant_id, &provider_id, current_revision, binding_digest)
            .map_err(provider_credential_store_error)?;
    }
    let payload_hash = tool_authority::canonical_json_digest(&json!({
        "expected_revision": request.expected_revision,
        "idempotency_key": idempotency_key,
        "operation": "delete",
        "provider_id": provider_id,
        "scope_id": tenant_id,
        "scope_kind": "tenant",
    }))
    .map_err(|_| local_store_error("provider delete request digest failed".to_string()))?;
    let receipt = state
        .session_store
        .mutate_managed_resource(ManagedResourceMutationCommand {
            actor_id: authenticated.user.user_id.clone(),
            kind: ManagedResourceKind::Provider,
            scope_kind: "tenant".to_string(),
            scope_id: tenant_id.clone(),
            resource_id: provider_id.clone(),
            operation: ManagedResourceMutationOperation::Delete,
            expected_revision: request.expected_revision,
            idempotency_key,
            payload_hash,
            status: "deleted".to_string(),
            value: None,
            target_revision: None,
            vault_refs: Vec::new(),
            now_ms: Utc::now().timestamp_millis(),
        })
        .map_err(resource_registry_error)?;
    if current.is_some() {
        let key = ProviderRuntimeKey {
            tenant_id: tenant_id.clone(),
            provider_id: provider_id.clone(),
        };
        let _ = clear_provider_credential(
            &state.provider_credentials,
            &key,
            current_revision,
            credential_binding.as_deref(),
        );
        let mut runtime = state
            .provider_runtime
            .lock()
            .map_err(|error| local_store_error(error.to_string()))?;
        runtime.probes.remove(&key);
        runtime.bindings.remove(&key);
        runtime.credentials.remove(&key);
        runtime.configured_credentials.remove(&key);
        if runtime
            .selections
            .get(&tenant_id)
            .is_some_and(|selected| selected == &provider_id)
        {
            runtime.selections.remove(&tenant_id);
        }
    }
    Ok(Json(json!({
        "deleted": true,
        "id": provider_id,
        "replayed": receipt.duplicate,
    })))
}

fn provider_create_idempotency(
    headers: &HeaderMap,
    tenant_id: &str,
    request: &LlmProviderMutation,
) -> Result<Option<LlmProviderCreateIdempotency>, (StatusCode, Json<Value>)> {
    let Some(value) = headers.get("idempotency-key") else {
        return Ok(None);
    };
    let key = value
        .to_str()
        .map_err(|_| local_bad_request("invalid provider create idempotency key".to_string()))?;
    if !(16..=256).contains(&key.len()) || key.trim() != key {
        return Err(local_bad_request(
            "invalid provider create idempotency key".to_string(),
        ));
    }
    let request_value = serde_json::to_value(request)
        .map_err(|_| local_store_error("provider create request digest failed".to_string()))?;
    let request_hash = tool_authority::canonical_json_digest(&request_value)
        .map_err(|_| local_store_error("provider create request digest failed".to_string()))?;
    let mut provider_id_hash = Sha256::new();
    provider_id_hash.update(b"memstack-provider-create-id:v1\0");
    for value in [tenant_id, key] {
        provider_id_hash.update((value.len() as u64).to_be_bytes());
        provider_id_hash.update(value.as_bytes());
    }
    let provider_id_hash = format!("{:x}", provider_id_hash.finalize());
    Ok(Some(LlmProviderCreateIdempotency {
        key: key.to_string(),
        request_hash,
        provider_id: format!("provider-{}", &provider_id_hash[..32]),
    }))
}

async fn mutate_llm_provider_blocking(
    state: Arc<LocalRuntimeState>,
    authenticated: AuthenticatedContext,
    provider_id: String,
    request: LlmProviderMutation,
    creating: bool,
    create_idempotency: Option<LlmProviderCreateIdempotency>,
) -> LocalJsonResult {
    tokio::task::spawn_blocking(move || {
        mutate_llm_provider(
            state,
            authenticated,
            provider_id,
            request,
            creating,
            create_idempotency,
        )
    })
    .await
    .map_err(|_| local_store_error("provider credential storage task failed".to_string()))?
}

fn mutate_llm_provider(
    state: Arc<LocalRuntimeState>,
    authenticated: AuthenticatedContext,
    provider_id: String,
    request: LlmProviderMutation,
    creating: bool,
    create_idempotency: Option<LlmProviderCreateIdempotency>,
) -> LocalJsonResult {
    let tenant_id = &authenticated.workspace.tenant_id;
    let LlmProviderMutation {
        name,
        provider_type,
        base_url,
        auth_method,
        api_key,
        environment_variable,
        llm_model,
        allowed_models,
        is_active,
        expected_revision,
    } = request;
    // Provider mutations are serialized before reading the current DB revision. This keeps the
    // versioned credential pre-write aligned with the SQLite compare-and-swap in this process;
    // the session store's exclusive SQLite ownership provides the cross-process boundary.
    let mut runtime = state
        .provider_runtime
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?;
    let provider_id = if let Some(idempotency) = create_idempotency.as_ref() {
        let receipt = state
            .session_store
            .claim_llm_provider_create(
                tenant_id,
                &idempotency.key,
                &idempotency.request_hash,
                &idempotency.provider_id,
                &now_iso(),
            )
            .map_err(provider_create_receipt_error)?;
        if let Some(response) = receipt.response {
            return Ok(Json(response));
        }
        receipt.provider_id
    } else {
        provider_id
    };
    let current = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            tenant_id,
            &provider_id,
        )
        .map_err(local_store_error)?;
    if !creating && current.is_none() {
        return Err(resource_registry_error(ResourceRegistryError::NotFound));
    }
    if creating {
        if let Some(provider) = current.as_ref() {
            if let Some(idempotency) = create_idempotency.as_ref() {
                let key = ProviderRuntimeKey {
                    tenant_id: tenant_id.clone(),
                    provider_id: provider_id.clone(),
                };
                let selected = runtime
                    .selections
                    .get(tenant_id)
                    .is_some_and(|selected| selected == &provider_id);
                let binding = runtime.bindings.get(&key);
                let credential_configured = runtime.configured_credentials.contains(&key);
                let response = provider_with_runtime_state(
                    provider.clone(),
                    selected,
                    binding,
                    credential_configured,
                    runtime.probes.get(&key),
                );
                state
                    .session_store
                    .complete_llm_provider_create(
                        tenant_id,
                        &idempotency.key,
                        &idempotency.request_hash,
                        &provider_id,
                        &response,
                    )
                    .map_err(local_store_error)?;
                return Ok(Json(response));
            }
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": "provider id already exists" })),
            ));
        }
    }
    let current_revision = current
        .as_ref()
        .and_then(|provider| provider.get("revision"))
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let previous_credential_binding = current.as_ref().and_then(provider_credential_binding);
    let mut provider = current.unwrap_or_else(|| {
        json!({
            "id": provider_id,
            "name": "New provider",
            "provider_type": "openai_compatible",
            "tenant_id": tenant_id,
            "is_active": false,
            "base_url": null,
            "auth_method": "api_key",
            "environment_variable": null,
            "credential_source": "application_vault",
            "credential_configured": false,
            "llm_model": null,
            "allowed_models": [],
            "secondary_models": [],
            "health_status": "not_configured",
            "revision": 0,
        })
    });
    let object = provider
        .as_object_mut()
        .ok_or_else(|| local_store_error("managed provider must be an object".to_string()))?;
    if let Some(name) = normalized_optional(name, "provider name")? {
        object.insert("name".to_string(), json!(name));
    }
    if let Some(provider_type) = normalized_optional(provider_type, "provider type")? {
        object.insert("provider_type".to_string(), json!(provider_type));
    }
    if let Some(base_url) = base_url {
        let base_url = base_url.trim().trim_end_matches('/').to_string();
        object.insert(
            "base_url".to_string(),
            if base_url.is_empty() {
                Value::Null
            } else {
                json!(base_url)
            },
        );
    }
    if let Some(auth_method) = normalized_optional(auth_method, "auth method")? {
        object.insert("auth_method".to_string(), json!(auth_method));
    }
    if let Some(model) = llm_model {
        let model = model.trim().to_string();
        object.insert(
            "llm_model".to_string(),
            if model.is_empty() {
                Value::Null
            } else {
                json!(model)
            },
        );
    }
    if let Some(models) = allowed_models {
        object.insert(
            "allowed_models".to_string(),
            json!(normalized_model_ids(models)),
        );
    }
    if let Some(is_active) = is_active {
        object.insert("is_active".to_string(), json!(is_active));
    }
    let provider_type = object
        .get("provider_type")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    if !runtime_provider_supported(&provider_type) {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({ "detail": "unsupported local provider type" })),
        ));
    }
    let auth_method = object
        .get("auth_method")
        .and_then(Value::as_str)
        .unwrap_or("api_key")
        .to_string();
    if !matches!(auth_method.as_str(), "api_key" | "environment" | "none") {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({ "detail": "unsupported local provider auth method" })),
        ));
    }
    if let Some(base_url) = object.get("base_url").and_then(Value::as_str) {
        let base_url = normalized_runtime_provider_base_url(&provider_type, base_url)?;
        object.insert("base_url".to_string(), json!(base_url));
    }
    let base_url = object
        .get("base_url")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    validate_provider_auth_fields(
        &auth_method,
        api_key.is_some(),
        environment_variable.is_some(),
    )?;
    if auth_method == "environment" {
        let base_url = base_url
            .as_deref()
            .ok_or_else(|| provider_probe_request_error("provider base URL is required"))?;
        let environment_variable = match environment_variable {
            Some(value) => {
                normalized_provider_environment_variable(&provider_type, base_url, &value)?
            }
            None => object
                .get("environment_variable")
                .and_then(Value::as_str)
                .map(|value| {
                    normalized_provider_environment_variable(&provider_type, base_url, value)
                })
                .transpose()?
                .ok_or_else(|| {
                    provider_probe_request_error("environment variable name is required")
                })?,
        };
        object.insert(
            "environment_variable".to_string(),
            json!(environment_variable),
        );
    } else {
        object.remove("environment_variable");
    }
    object.insert(
        "credential_source".to_string(),
        json!(match auth_method.as_str() {
            "none" => "none",
            "environment" => "environment",
            _ => "application_vault",
        }),
    );
    object.insert("credential_configured".to_string(), json!(false));
    object.insert("health_status".to_string(), json!("not_checked"));

    let is_active = object.get("is_active").and_then(Value::as_bool) == Some(true);
    let expected_revision = if creating { Some(0) } else { expected_revision };
    if expected_revision != Some(current_revision) {
        return Err(resource_registry_error(
            ResourceRegistryError::RevisionConflict {
                expected: expected_revision.unwrap_or(0),
                actual: current_revision,
            },
        ));
    }
    let next_revision = if creating {
        0
    } else {
        current_revision.saturating_add(1)
    };
    let next_credential_binding = provider_credential_binding(&provider);
    let key = ProviderRuntimeKey {
        tenant_id: tenant_id.clone(),
        provider_id: provider_id.clone(),
    };
    let previous_binding = runtime.bindings.get(&key).cloned();
    let previous_credential = if let Some(credential) = runtime.credentials.get(&key).cloned() {
        Some(credential)
    } else if runtime.configured_credentials.contains(&key) {
        let binding_digest = previous_credential_binding.as_deref().ok_or_else(|| {
            provider_credential_store_error(ProviderCredentialStoreError::InvalidRecord)
        })?;
        let credential = state
            .provider_credentials
            .load(
                &key.tenant_id,
                &key.provider_id,
                current_revision,
                binding_digest,
            )
            .map_err(provider_credential_store_error)?;
        if credential.is_none() {
            runtime.configured_credentials.remove(&key);
        }
        credential
    } else {
        None
    };
    let was_selected = runtime
        .selections
        .get(tenant_id)
        .is_some_and(|selected| selected == &provider_id);
    let submitted_credential = api_key.as_deref().and_then(normalized_runtime_credential);
    let next_binding = runtime_binding_from_provider(&provider).map(|mut next| {
        if was_selected {
            if let Some(previous) = previous_binding
                .as_ref()
                .filter(|previous| provider_supports_route_model(&provider, &previous.model))
            {
                next.model.clone_from(&previous.model);
            }
        }
        next
    });
    let next_credential = if auth_method == "environment" {
        resolved_environment_credential(&provider)
    } else if next_credential_binding.is_none() {
        None
    } else if submitted_credential.is_some() {
        submitted_credential
    } else if previous_credential_binding == next_credential_binding {
        previous_credential.clone()
    } else {
        None
    };
    if was_selected
        && next_binding.is_some()
        && auth_method == "api_key"
        && next_credential.is_none()
    {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({
                "detail": "replacement credentials are required when changing a selected provider connection"
            })),
        ));
    }
    if let Some(object) = provider.as_object_mut() {
        object.insert(
            "credential_configured".to_string(),
            json!(auth_method == "none" || next_credential.is_some()),
        );
    }
    let scheduled_previous_credential =
        if let Some(binding_digest) = previous_credential_binding.as_deref() {
            state
                .provider_credentials
                .schedule_cleanup(
                    &key.tenant_id,
                    &key.provider_id,
                    current_revision,
                    binding_digest,
                )
                .map_err(provider_credential_store_error)?;
            true
        } else {
            false
        };
    let wrote_next_credential = if let (Some(binding_digest), Some(credential)) = (
        next_credential_binding.as_deref(),
        next_credential.as_deref(),
    ) {
        state
            .provider_credentials
            .save(
                &key.tenant_id,
                &key.provider_id,
                next_revision,
                binding_digest,
                credential,
            )
            .map_err(provider_credential_store_error)?;
        true
    } else {
        false
    };
    let stored = match state.session_store.put_managed_resource(
        ManagedResourceKind::Provider,
        "tenant",
        tenant_id,
        &provider_id,
        if is_active { "active" } else { "disabled" },
        expected_revision,
        provider,
        Utc::now().timestamp_millis(),
    ) {
        Ok(stored) => stored,
        Err(error) => {
            if reconcile_provider_credential_cleanup(&state).is_err() {
                eprintln!(
                    "failed to reconcile provider credential cleanup after rejected mutation; cleanup remains scheduled"
                );
            }
            return Err(resource_registry_error(error));
        }
    };
    if wrote_next_credential {
        if let Some(binding_digest) = next_credential_binding.as_deref() {
            if let Err(error) = state.provider_credentials.mark_authoritative(
                &key.tenant_id,
                &key.provider_id,
                next_revision,
                binding_digest,
            ) {
                eprintln!(
                    "failed to reconcile committed provider credential cleanup journal: {error}"
                );
            }
        }
    }
    if scheduled_previous_credential {
        let _ = clear_provider_credential(
            &state.provider_credentials,
            &key,
            current_revision,
            previous_credential_binding.as_deref(),
        );
    }
    runtime.probes.remove(&key);
    if was_selected && next_binding.is_none() {
        runtime.selections.remove(tenant_id);
    }
    if let Some(binding) = next_binding.clone() {
        runtime.bindings.insert(key.clone(), binding);
    } else {
        runtime.bindings.remove(&key);
    }
    if let Some(credential) = next_credential {
        runtime.configured_credentials.insert(key.clone());
        if next_binding.is_some() {
            runtime.credentials.insert(key.clone(), credential);
        } else {
            runtime.credentials.remove(&key);
        }
    } else {
        runtime.credentials.remove(&key);
        runtime.configured_credentials.remove(&key);
    }
    let selected = runtime
        .selections
        .get(tenant_id)
        .is_some_and(|selected| selected == &provider_id);
    let credential_configured = runtime.configured_credentials.contains(&key);
    let response = provider_with_runtime_state(
        stored,
        selected,
        next_binding.as_ref(),
        credential_configured,
        None,
    );
    if let Some(idempotency) = create_idempotency.as_ref() {
        state
            .session_store
            .complete_llm_provider_create(
                tenant_id,
                &idempotency.key,
                &idempotency.request_hash,
                &provider_id,
                &response,
            )
            .map_err(local_store_error)?;
    }
    Ok(Json(response))
}

fn provider_create_receipt_error(
    error: LlmProviderCreateReceiptError,
) -> (StatusCode, Json<Value>) {
    match error {
        LlmProviderCreateReceiptError::PayloadConflict => (
            StatusCode::CONFLICT,
            Json(json!({
                "code": "provider_create_idempotency_conflict",
                "detail": "provider create idempotency key is already bound to a different request",
            })),
        ),
        LlmProviderCreateReceiptError::Storage(error) => local_store_error(error),
    }
}

fn clear_provider_credential(
    broker: &ProviderCredentialBroker,
    key: &ProviderRuntimeKey,
    provider_revision: u64,
    binding_digest: Option<&str>,
) -> Result<(), (StatusCode, Json<Value>)> {
    let result = match binding_digest {
        Some(binding_digest) => broker.clear(
            &key.tenant_id,
            &key.provider_id,
            provider_revision,
            binding_digest,
        ),
        None => Ok(()),
    };
    result.map_err(provider_credential_store_error)
}

fn reconcile_provider_credential_cleanup(
    state: &LocalRuntimeState,
) -> Result<(), ProviderCredentialStoreError> {
    let providers = state
        .session_store
        .list_runtime_provider_connections()
        .map_err(|_| ProviderCredentialStoreError::Unavailable)?;
    let mut authoritative = Vec::new();
    for (tenant_id, provider) in providers {
        let Some(provider_id) = provider.get("id").and_then(Value::as_str) else {
            continue;
        };
        let Some(binding_digest) = provider_credential_binding(&provider) else {
            continue;
        };
        let provider_revision = provider
            .get("revision")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        authoritative.push((
            tenant_id,
            provider_id.to_string(),
            provider_revision,
            binding_digest,
        ));
    }
    state
        .provider_credentials
        .recover_pending(authoritative.iter().map(
            |(tenant_id, provider_id, provider_revision, binding_digest)| {
                (
                    tenant_id.as_str(),
                    provider_id.as_str(),
                    *provider_revision,
                    binding_digest.as_str(),
                )
            },
        ))
}
