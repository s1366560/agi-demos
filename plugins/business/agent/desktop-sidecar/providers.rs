// Compatibility endpoints for the full desktop profile.

async fn list_llm_provider_types() -> Json<Vec<LlmProviderTypeDescriptor>> {
    Json(LOCAL_LLM_PROVIDER_TYPES.to_vec())
}

async fn list_llm_provider_models(
    Path(provider_type): Path<String>,
) -> Result<Json<LocalLlmProviderModelsResponse>, (StatusCode, Json<Value>)> {
    let provider_type = provider_type.trim().to_lowercase();
    let (models, source) = match provider_type.as_str() {
        "openai" | "anthropic" => (
            static_local_roster(provider_type.as_str()),
            Some("static-fallback"),
        ),
        "openai_compatible" => (LocalLlmProviderModels::default(), None),
        _ => {
            return Err((
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({ "detail": "unsupported local provider type" })),
            ));
        }
    };
    Ok(Json(LocalLlmProviderModelsResponse {
        provider_type,
        models,
        source,
    }))
}

async fn list_llm_providers(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
) -> LocalJsonResult {
    let tenant_id = &authenticated.workspace.tenant_id;
    let runtime = state
        .provider_runtime
        .lock()
        .map_err(|error| local_store_error(error.to_string()))?;
    let providers = state
        .session_store
        .list_managed_resources(ManagedResourceKind::Provider, "tenant", tenant_id)
        .map_err(local_store_error)?;
    let selected_provider_id = runtime.selections.get(tenant_id);
    let providers = providers
        .into_iter()
        .map(|provider| {
            let provider_id = provider
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string();
            let key = ProviderRuntimeKey {
                tenant_id: tenant_id.clone(),
                provider_id: provider_id.clone(),
            };
            provider_with_runtime_state(
                provider,
                selected_provider_id.map(String::as_str) == Some(provider_id.as_str()),
                runtime.bindings.get(&key),
                runtime.configured_credentials.contains(&key),
                runtime.probes.get(&key),
            )
        })
        .collect();
    Ok(Json(Value::Array(providers)))
}

async fn validate_llm_provider_draft(
    Extension(authenticated): Extension<AuthenticatedContext>,
    State(state): State<Arc<LocalRuntimeState>>,
    Json(request): Json<LlmProviderDraftProbe>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    if request.name.trim().is_empty() {
        return Err(provider_probe_request_error("provider name is required"));
    }
    let provider_type = request.provider_type.trim().to_lowercase();
    if !runtime_provider_supported(&provider_type) {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({ "detail": "unsupported local provider type" })),
        ));
    }

    let base_url = normalized_runtime_provider_base_url(&provider_type, &request.base_url)?;
    let auth_method = request.auth_method.trim().to_lowercase();
    if !matches!(auth_method.as_str(), "api_key" | "environment" | "none") {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({ "detail": "unsupported local provider auth method" })),
        ));
    }
    validate_provider_auth_fields(
        &auth_method,
        request.api_key.is_some(),
        request.environment_variable.is_some(),
    )?;
    let credential = if auth_method == "environment" {
        let environment_variable = request
            .environment_variable
            .as_deref()
            .map(|value| normalized_provider_environment_variable(&provider_type, &base_url, value))
            .transpose()?
            .ok_or_else(|| provider_probe_request_error("environment variable name is required"))?;
        std::env::var(environment_variable)
            .ok()
            .and_then(|value| normalized_runtime_credential(&value))
    } else {
        request
            .api_key
            .as_deref()
            .and_then(normalized_runtime_credential)
    };
    if matches!(auth_method.as_str(), "api_key" | "environment") && credential.is_none() {
        return Ok(Json(json!({
            "provider": null,
            "status": "needs_credentials",
            "probed": false,
            "detail": if auth_method == "environment" {
                "The referenced environment variable is unavailable in this runtime."
            } else {
                "Enter a provider credential before testing this connection."
            },
            "last_check": null,
            "response_time_ms": null,
            "error_code": "credential_unavailable",
            "error_message": if auth_method == "environment" {
                "The referenced environment variable is unavailable in this runtime."
            } else {
                "Enter a provider credential before testing this connection."
            },
            "catalog": null,
        })));
    }
    let last_check = now_iso();
    let outcome = state
        .provider_probe
        .probe(ProviderProbeRequest {
            provider_type: provider_type.clone(),
            base_url,
            auth_method: provider_probe_auth_method(&auth_method).to_string(),
            credential,
        })
        .await;
    Ok(Json(json!({
        "provider": null,
        "status": outcome.status,
        "probed": true,
        "detail": outcome.detail,
        "last_check": last_check,
        "response_time_ms": outcome.response_time_ms,
        "error_code": outcome.error_code,
        "error_message": outcome.error_code.map(|_| outcome.detail),
        "catalog": provider_probe_catalog(
            &provider_type,
            None,
            &outcome,
            &last_check,
            None,
        ),
    })))
}
