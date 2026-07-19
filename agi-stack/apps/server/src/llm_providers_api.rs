//! P7 LLM provider metadata strangler slice.
//!
//! Rust owns authenticated provider-type discovery plus provider metadata CRUD,
//! read-only model catalog list/search/provider-model endpoints backed by the
//! same embedded Python `models_snapshot.json`, admin-only environment provider
//! detection, live connection probes, persisted provider-health reads/writes,
//! tenant assignment list, and provider usage statistics reads. Catalog refresh,
//! assignment mutations/provider resolution, system resilience runtime, and
//! usage writes remain Python-owned.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fmt;
use std::sync::Arc;
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{DateTime, Utc};
use serde::de::{MapAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{json, Value};
use tokio::sync::Mutex;
use url::Url;

use agistack_adapters_postgres::{
    decrypt_provider_api_key_for_mask, LlmProviderCreateRecord, LlmProviderMutationError,
    LlmProviderRecord, LlmProviderUpdateRecord, PgLlmProviderRepository, ProviderHealthRecord,
    TenantProviderMappingRecord, UsageStatisticRecord, UsageStatisticsQuery,
};

use crate::auth::Identity;
use crate::AppState;

const MODEL_SNAPSHOT_JSON: &str =
    include_str!("../../../../src/infrastructure/llm/models_snapshot.json");

const PROVIDER_TYPES: &[&str] = &[
    "openai",
    "openrouter",
    "dashscope",
    "gemini",
    "anthropic",
    "groq",
    "azure_openai",
    "cohere",
    "mistral",
    "bedrock",
    "vertex",
    "deepseek",
    "minimax",
    "zai",
    "kimi",
    "ollama",
    "lmstudio",
    "volcengine",
    "volcengine_coding",
    "volcengine_embedding",
    "volcengine_reranker",
    "minimax_coding",
    "minimax_embedding",
    "minimax_reranker",
    "zai_coding",
    "zai_embedding",
    "zai_reranker",
    "kimi_coding",
    "kimi_embedding",
    "kimi_reranker",
    "dashscope_coding",
    "dashscope_embedding",
    "dashscope_reranker",
];

const OPERATION_TYPES: &[&str] = &["llm", "embedding", "rerank"];
const API_KEY_AUTH_METHODS: &[&str] = &["api_key"];
const API_KEY_OR_ENVIRONMENT_AUTH_METHODS: &[&str] = &["api_key", "environment"];
const NO_AUTH_METHODS: &[&str] = &["none"];
const NO_AVAILABLE_AUTH_METHODS: &[&str] = &[];
const NO_UNAVAILABLE_AUTH_METHODS: &[&str] = &[];
const OAUTH_UNAVAILABLE_AUTH_METHODS: &[&str] = &["oauth"];
const UNSUPPORTED_STRUCTURED_AUTH_METHODS: &[&str] = &["api_key", "oauth"];
const SAFE_CUSTOM_PROVIDER_BASE_PATHS: &[&str] = &[
    "/",
    "/v1",
    "/api/v1",
    "/api",
    "/openai/v1",
    "/compatible-mode/v1",
    "/api/paas/v4",
    "/api/v3",
    "/v1beta",
];

pub(crate) type SharedLlmProviderHealth = Arc<dyn LlmProviderHealthService>;
pub(crate) type SharedLlmProviders = Arc<dyn LlmProviderCatalogService>;
pub(crate) type SharedLlmProviderAssignments = Arc<dyn LlmProviderAssignmentService>;
pub(crate) type SharedLlmProviderUsage = Arc<dyn LlmProviderUsageService>;

const LOCAL_NO_API_KEY_SENTINEL: &str = "__MEMSTACK_NO_API_KEY__";
const AUTH_METHOD_CONFIG_KEY: &str = "auth_method";
const ENVIRONMENT_VARIABLE_CONFIG_KEY: &str = "environment_variable";
const ENVIRONMENT_CREDENTIAL_MISSING: &str = "Environment credential is not configured";
const ENVIRONMENT_CREDENTIAL_INVALID: &str = "Environment credential configuration is invalid";
#[async_trait]
pub(crate) trait LlmProviderCatalogService: Send + Sync {
    async fn list_providers(
        &self,
        user_id: &str,
        include_inactive: bool,
    ) -> Result<Vec<ProviderConfigResponse>, LlmProvidersApiError>;

    async fn get_provider(
        &self,
        user_id: &str,
        provider_id: &str,
    ) -> Result<Option<ProviderConfigResponse>, LlmProvidersApiError>;

    async fn create_provider(
        &self,
        user_id: &str,
        request: ProviderCreateRequest,
    ) -> Result<ProviderConfigResponse, LlmProvidersApiError>;

    async fn update_provider(
        &self,
        user_id: &str,
        provider_id: &str,
        request: ProviderUpdateRequest,
    ) -> Result<Option<ProviderConfigResponse>, LlmProvidersApiError>;

    async fn delete_provider(
        &self,
        user_id: &str,
        provider_id: &str,
    ) -> Result<bool, LlmProvidersApiError>;

    async fn provider_probe_config(
        &self,
        user_id: &str,
        provider_id: &str,
    ) -> Result<Option<ProviderProbeConfig>, LlmProvidersApiError>;
}

pub(crate) struct PgLlmProviderCatalogService {
    repo: PgLlmProviderRepository,
}

impl PgLlmProviderCatalogService {
    pub(crate) fn new(repo: PgLlmProviderRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl LlmProviderCatalogService for PgLlmProviderCatalogService {
    async fn list_providers(
        &self,
        user_id: &str,
        include_inactive: bool,
    ) -> Result<Vec<ProviderConfigResponse>, LlmProvidersApiError> {
        let include_inactive = if self
            .repo
            .user_has_provider_admin_role(user_id)
            .await
            .map_err(LlmProvidersApiError::internal)?
        {
            include_inactive
        } else {
            false
        };
        let records = self
            .repo
            .list_providers(include_inactive)
            .await
            .map_err(LlmProvidersApiError::internal)?;
        self.records_to_responses(records).await
    }

    async fn get_provider(
        &self,
        user_id: &str,
        provider_id: &str,
    ) -> Result<Option<ProviderConfigResponse>, LlmProvidersApiError> {
        let Some(record) = self
            .repo
            .get_provider(provider_id)
            .await
            .map_err(LlmProvidersApiError::internal)?
        else {
            return Ok(None);
        };
        let is_admin = self
            .repo
            .user_has_provider_admin_role(user_id)
            .await
            .map_err(LlmProvidersApiError::internal)?;
        if !is_admin && !record.is_active {
            return Ok(None);
        }
        self.record_to_response(record).await.map(Some)
    }

    async fn create_provider(
        &self,
        _user_id: &str,
        request: ProviderCreateRequest,
    ) -> Result<ProviderConfigResponse, LlmProvidersApiError> {
        let record = provider_create_record_with_auth(request)?;
        let created = self
            .repo
            .create_provider(&record)
            .await
            .map_err(map_provider_mutation_error)?;
        self.record_to_response(created).await
    }

    async fn update_provider(
        &self,
        _user_id: &str,
        provider_id: &str,
        request: ProviderUpdateRequest,
    ) -> Result<Option<ProviderConfigResponse>, LlmProvidersApiError> {
        let existing = self
            .repo
            .get_provider(provider_id)
            .await
            .map_err(LlmProvidersApiError::internal)?;
        let Some(existing) = existing else {
            return Ok(None);
        };
        let update = provider_update_record_with_auth(&existing, request)?;
        let updated = self
            .repo
            .update_provider(provider_id, &update)
            .await
            .map_err(map_provider_mutation_error)?;
        let Some(updated) = updated else {
            return Err(LlmProvidersApiError::conflict(
                "Provider configuration changed; reload and try again",
            ));
        };
        self.record_to_response(updated).await.map(Some)
    }

    async fn delete_provider(
        &self,
        _user_id: &str,
        provider_id: &str,
    ) -> Result<bool, LlmProvidersApiError> {
        self.repo
            .soft_delete_provider(provider_id)
            .await
            .map_err(LlmProvidersApiError::internal)
    }

    async fn provider_probe_config(
        &self,
        _user_id: &str,
        provider_id: &str,
    ) -> Result<Option<ProviderProbeConfig>, LlmProvidersApiError> {
        let Some(record) = self
            .repo
            .get_provider(provider_id)
            .await
            .map_err(LlmProvidersApiError::internal)?
        else {
            return Ok(None);
        };
        Ok(Some(ProviderProbeConfig::from_persisted_record(record)))
    }
}

impl PgLlmProviderCatalogService {
    async fn records_to_responses(
        &self,
        records: Vec<LlmProviderRecord>,
    ) -> Result<Vec<ProviderConfigResponse>, LlmProvidersApiError> {
        // One batch query for every provider's latest health instead of one
        // round-trip per provider.
        let ids: Vec<String> = records.iter().map(|record| record.id.clone()).collect();
        let mut health_by_provider: HashMap<String, ProviderHealthRecord> = self
            .repo
            .latest_health_batch(&ids)
            .await
            .map_err(LlmProvidersApiError::internal)?
            .into_iter()
            .map(|health| (health.provider_id.clone(), health))
            .collect();
        let mut responses = Vec::with_capacity(records.len());
        for record in records {
            let health = health_by_provider.remove(&record.id);
            responses.push(provider_response_from_record(record, health));
        }
        Ok(responses)
    }

    async fn record_to_response(
        &self,
        record: LlmProviderRecord,
    ) -> Result<ProviderConfigResponse, LlmProvidersApiError> {
        let health = self
            .repo
            .latest_health(&record.id)
            .await
            .map_err(LlmProvidersApiError::internal)?;
        Ok(provider_response_from_record(record, health))
    }
}

#[derive(Default)]
pub(crate) struct DevLlmProviderCatalogService {
    records: Mutex<Vec<LlmProviderRecord>>,
}

#[async_trait]
impl LlmProviderCatalogService for DevLlmProviderCatalogService {
    async fn list_providers(
        &self,
        _user_id: &str,
        include_inactive: bool,
    ) -> Result<Vec<ProviderConfigResponse>, LlmProvidersApiError> {
        let records = self.records.lock().await;
        Ok(records
            .iter()
            .filter(|record| include_inactive || record.is_active)
            .cloned()
            .map(|record| provider_response_from_record(record, None))
            .collect())
    }

    async fn get_provider(
        &self,
        _user_id: &str,
        provider_id: &str,
    ) -> Result<Option<ProviderConfigResponse>, LlmProvidersApiError> {
        let records = self.records.lock().await;
        Ok(records
            .iter()
            .find(|record| record.id == provider_id)
            .cloned()
            .map(|record| provider_response_from_record(record, None)))
    }

    async fn create_provider(
        &self,
        _user_id: &str,
        request: ProviderCreateRequest,
    ) -> Result<ProviderConfigResponse, LlmProvidersApiError> {
        let record = provider_record_from_create_for_dev(request)?;
        let response = provider_response_from_record(record.clone(), None);
        self.records.lock().await.push(record);
        Ok(response)
    }

    async fn update_provider(
        &self,
        _user_id: &str,
        provider_id: &str,
        request: ProviderUpdateRequest,
    ) -> Result<Option<ProviderConfigResponse>, LlmProvidersApiError> {
        let mut records = self.records.lock().await;
        let Some(position) = records.iter().position(|record| record.id == provider_id) else {
            return Ok(None);
        };
        let update = provider_update_record_with_auth(&records[position], request)?;
        apply_update_to_dev_record(&mut records[position], update);
        let response = provider_response_from_record(records[position].clone(), None);
        Ok(Some(response))
    }

    async fn delete_provider(
        &self,
        _user_id: &str,
        provider_id: &str,
    ) -> Result<bool, LlmProvidersApiError> {
        let mut records = self.records.lock().await;
        let Some(record) = records.iter_mut().find(|record| record.id == provider_id) else {
            return Ok(false);
        };
        record.is_active = false;
        Ok(true)
    }

    async fn provider_probe_config(
        &self,
        _user_id: &str,
        provider_id: &str,
    ) -> Result<Option<ProviderProbeConfig>, LlmProvidersApiError> {
        let records = self.records.lock().await;
        Ok(records
            .iter()
            .find(|record| record.id == provider_id)
            .cloned()
            .map(ProviderProbeConfig::from_dev_record))
    }
}

#[async_trait]
pub(crate) trait LlmProviderHealthService: Send + Sync {
    async fn latest_health(
        &self,
        provider_id: &str,
    ) -> Result<Option<ProviderHealthResponse>, LlmProvidersApiError>;

    async fn record_health(
        &self,
        record: &ProviderHealthRecord,
    ) -> Result<(), LlmProvidersApiError>;
}

pub(crate) struct PgLlmProviderHealthService {
    repo: PgLlmProviderRepository,
}

impl PgLlmProviderHealthService {
    pub(crate) fn new(repo: PgLlmProviderRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl LlmProviderHealthService for PgLlmProviderHealthService {
    async fn latest_health(
        &self,
        provider_id: &str,
    ) -> Result<Option<ProviderHealthResponse>, LlmProvidersApiError> {
        self.repo
            .latest_health(provider_id)
            .await
            .map(|record| record.map(ProviderHealthResponse::from))
            .map_err(LlmProvidersApiError::internal)
    }

    async fn record_health(
        &self,
        record: &ProviderHealthRecord,
    ) -> Result<(), LlmProvidersApiError> {
        self.repo
            .record_health(record)
            .await
            .map(|_| ())
            .map_err(LlmProvidersApiError::internal)
    }
}

#[derive(Default)]
pub(crate) struct DevLlmProviderHealthService {
    records: Mutex<BTreeMap<String, ProviderHealthRecord>>,
}

#[async_trait]
impl LlmProviderHealthService for DevLlmProviderHealthService {
    async fn latest_health(
        &self,
        provider_id: &str,
    ) -> Result<Option<ProviderHealthResponse>, LlmProvidersApiError> {
        Ok(self
            .records
            .lock()
            .await
            .get(provider_id)
            .cloned()
            .map(ProviderHealthResponse::from))
    }

    async fn record_health(
        &self,
        record: &ProviderHealthRecord,
    ) -> Result<(), LlmProvidersApiError> {
        self.records
            .lock()
            .await
            .insert(record.provider_id.clone(), record.clone());
        Ok(())
    }
}

#[async_trait]
pub(crate) trait LlmProviderAssignmentService: Send + Sync {
    async fn list_tenant_assignments(
        &self,
        user_id: &str,
        tenant_id: &str,
        operation_type: Option<&str>,
    ) -> Result<Vec<TenantProviderMappingResponse>, LlmProvidersApiError>;
}

pub(crate) struct PgLlmProviderAssignmentService {
    repo: PgLlmProviderRepository,
}

impl PgLlmProviderAssignmentService {
    pub(crate) fn new(repo: PgLlmProviderRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl LlmProviderAssignmentService for PgLlmProviderAssignmentService {
    async fn list_tenant_assignments(
        &self,
        user_id: &str,
        tenant_id: &str,
        operation_type: Option<&str>,
    ) -> Result<Vec<TenantProviderMappingResponse>, LlmProvidersApiError> {
        let allowed = self
            .repo
            .user_can_read_tenant_assignments(user_id, tenant_id)
            .await
            .map_err(LlmProvidersApiError::internal)?;
        if !allowed {
            return Err(LlmProvidersApiError::forbidden(
                "Access denied to tenant assignments",
            ));
        }

        self.repo
            .list_tenant_assignments(tenant_id, operation_type)
            .await
            .map(|records| {
                records
                    .into_iter()
                    .map(TenantProviderMappingResponse::from)
                    .collect()
            })
            .map_err(LlmProvidersApiError::internal)
    }
}

#[derive(Default)]
pub(crate) struct DevLlmProviderAssignmentService {
    records: Vec<TenantProviderMappingResponse>,
}

#[async_trait]
impl LlmProviderAssignmentService for DevLlmProviderAssignmentService {
    async fn list_tenant_assignments(
        &self,
        _user_id: &str,
        tenant_id: &str,
        operation_type: Option<&str>,
    ) -> Result<Vec<TenantProviderMappingResponse>, LlmProvidersApiError> {
        let mut records = self
            .records
            .iter()
            .filter(|record| record.tenant_id == tenant_id)
            .filter(|record| operation_type.is_none_or(|op| record.operation_type == op))
            .cloned()
            .collect::<Vec<_>>();
        records.sort_by_key(|record| record.priority);
        Ok(records)
    }
}

#[async_trait]
pub(crate) trait LlmProviderUsageService: Send + Sync {
    async fn provider_usage(
        &self,
        user_id: &str,
        provider_id: &str,
        query: ProviderUsageQuery,
    ) -> Result<ProviderUsageResponse, LlmProvidersApiError>;
}

pub(crate) struct PgLlmProviderUsageService {
    repo: PgLlmProviderRepository,
}

impl PgLlmProviderUsageService {
    pub(crate) fn new(repo: PgLlmProviderRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl LlmProviderUsageService for PgLlmProviderUsageService {
    async fn provider_usage(
        &self,
        user_id: &str,
        provider_id: &str,
        query: ProviderUsageQuery,
    ) -> Result<ProviderUsageResponse, LlmProvidersApiError> {
        let tenant_id = if self
            .repo
            .user_has_provider_admin_role(user_id)
            .await
            .map_err(LlmProvidersApiError::internal)?
        {
            None
        } else {
            Some(
                self.repo
                    .default_tenant_for_user(user_id)
                    .await
                    .map_err(LlmProvidersApiError::internal)?
                    .ok_or_else(|| {
                        LlmProvidersApiError::forbidden("User does not belong to any tenant")
                    })?,
            )
        };
        let records = self
            .repo
            .usage_statistics(UsageStatisticsQuery {
                provider_id: Some(provider_id),
                tenant_id: tenant_id.as_deref(),
                operation_type: query.operation_type.as_deref(),
                start_date: query.start_date,
                end_date: query.end_date,
            })
            .await
            .map_err(LlmProvidersApiError::internal)?;
        Ok(ProviderUsageResponse {
            provider_id: provider_id.to_string(),
            tenant_id,
            statistics: records
                .into_iter()
                .map(UsageStatisticResponse::from)
                .collect(),
        })
    }
}

#[derive(Default)]
pub(crate) struct DevLlmProviderUsageService;

#[async_trait]
impl LlmProviderUsageService for DevLlmProviderUsageService {
    async fn provider_usage(
        &self,
        _user_id: &str,
        provider_id: &str,
        _query: ProviderUsageQuery,
    ) -> Result<ProviderUsageResponse, LlmProvidersApiError> {
        Ok(ProviderUsageResponse {
            provider_id: provider_id.to_string(),
            tenant_id: None,
            statistics: Vec::new(),
        })
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/llm-providers/",
            get(list_providers).post(create_provider),
        )
        .route(
            "/api/v1/llm-providers",
            get(list_providers).post(create_provider),
        )
        .route("/api/v1/llm-providers/types", get(list_provider_types))
        .route(
            "/api/v1/llm-providers/models/catalog",
            get(list_catalog_models),
        )
        .route(
            "/api/v1/llm-providers/models/catalog/search",
            get(search_catalog_models),
        )
        .route(
            "/api/v1/llm-providers/models/:provider_type",
            get(list_models_for_provider_type),
        )
        .route(
            "/api/v1/llm-providers/env-detection",
            get(detect_env_providers),
        )
        .route(
            "/api/v1/llm-providers/test-connection",
            axum::routing::post(test_provider_connection),
        )
        .route(
            "/api/v1/llm-providers/:provider_id",
            get(get_provider)
                .put(update_provider)
                .delete(delete_provider),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/health-check",
            axum::routing::post(check_provider_health),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/health",
            get(get_provider_health),
        )
        .route(
            "/api/v1/llm-providers/tenants/:tenant_id/assignments",
            get(list_tenant_assignments),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/usage",
            get(get_provider_usage),
        )
}

async fn list_provider_types() -> Json<Vec<ProviderTypeDescriptor>> {
    Json(
        PROVIDER_TYPES
            .iter()
            .copied()
            .map(|provider_type| ProviderTypeDescriptor {
                provider_type,
                operation_type: inferred_operation_type(provider_type),
                probe_supported: provider_probe_supported(provider_type),
                auth_methods: if matches!(provider_type, "ollama" | "lmstudio") {
                    NO_AUTH_METHODS
                } else if !provider_supports_persisted_auth(provider_type) {
                    NO_AVAILABLE_AUTH_METHODS
                } else if provider_supports_environment(provider_type) {
                    API_KEY_OR_ENVIRONMENT_AUTH_METHODS
                } else {
                    API_KEY_AUTH_METHODS
                },
                unavailable_auth_methods: if !provider_supports_persisted_auth(provider_type) {
                    UNSUPPORTED_STRUCTURED_AUTH_METHODS
                } else if matches!(provider_type, "openai" | "anthropic") {
                    OAUTH_UNAVAILABLE_AUTH_METHODS
                } else {
                    NO_UNAVAILABLE_AUTH_METHODS
                },
            })
            .collect(),
    )
}

async fn list_providers(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<ProviderListQuery>,
) -> Result<Json<Vec<ProviderConfigResponse>>, LlmProvidersApiError> {
    let response = app
        .llm_providers
        .list_providers(&identity.user_id, query.include_inactive.unwrap_or(false))
        .await?;
    Ok(Json(response))
}

async fn create_provider(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(request): Json<ProviderCreateRequest>,
) -> Result<(StatusCode, Json<ProviderConfigResponse>), LlmProvidersApiError> {
    ensure_admin_access(&app, &identity.user_id).await?;
    let response = app
        .llm_providers
        .create_provider(&identity.user_id, request)
        .await?;
    Ok((StatusCode::CREATED, Json(response)))
}

async fn get_provider(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(provider_id): Path<String>,
) -> Result<Json<ProviderConfigResponse>, LlmProvidersApiError> {
    let provider_id = validate_provider_id(&provider_id)?;
    let response = app
        .llm_providers
        .get_provider(&identity.user_id, &provider_id)
        .await?
        .ok_or_else(|| LlmProvidersApiError::not_found("Provider not found"))?;
    Ok(Json(response))
}

async fn update_provider(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(provider_id): Path<String>,
    Json(request): Json<ProviderUpdateRequest>,
) -> Result<Json<ProviderConfigResponse>, LlmProvidersApiError> {
    ensure_admin_access(&app, &identity.user_id).await?;
    let provider_id = validate_provider_id(&provider_id)?;
    let response = app
        .llm_providers
        .update_provider(&identity.user_id, &provider_id, request)
        .await?
        .ok_or_else(|| LlmProvidersApiError::not_found("Provider not found"))?;
    Ok(Json(response))
}

async fn delete_provider(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(provider_id): Path<String>,
) -> Result<StatusCode, LlmProvidersApiError> {
    ensure_admin_access(&app, &identity.user_id).await?;
    let provider_id = validate_provider_id(&provider_id)?;
    if app
        .llm_providers
        .delete_provider(&identity.user_id, &provider_id)
        .await?
    {
        Ok(StatusCode::NO_CONTENT)
    } else {
        Err(LlmProvidersApiError::not_found("Provider not found"))
    }
}

async fn list_catalog_models(Query(query): Query<CatalogListQuery>) -> Json<CatalogListResponse> {
    Json(model_catalog().list_models(&query))
}

async fn search_catalog_models(
    Query(query): Query<CatalogSearchQuery>,
) -> Result<Json<CatalogSearchResponse>, LlmProvidersApiError> {
    let query = query.validated()?;
    Ok(Json(model_catalog().search_models(query)))
}

async fn list_models_for_provider_type(
    Path(provider_type): Path<String>,
) -> Json<ProviderModelsResponse> {
    Json(model_catalog().provider_models(&provider_type))
}

async fn detect_env_providers(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
) -> Result<Json<EnvDetectionResponse>, LlmProvidersApiError> {
    ensure_admin_access(&app, &identity.user_id).await?;
    Ok(Json(detect_env_provider_configs()))
}

async fn test_provider_connection(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(request): Json<ProviderProbeRequest>,
) -> Result<Json<ProviderValidationResponse>, LlmProvidersApiError> {
    ensure_admin_access(&app, &identity.user_id).await?;
    Ok(Json(execute_provider_connection_test(request).await?))
}

async fn check_provider_health(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(provider_id): Path<String>,
) -> Result<Json<ProviderValidationResponse>, LlmProvidersApiError> {
    ensure_admin_access(&app, &identity.user_id).await?;
    Ok(Json(
        execute_persisted_provider_health_check(
            &app.llm_providers,
            &app.llm_provider_health,
            &identity.user_id,
            &provider_id,
        )
        .await?,
    ))
}

async fn execute_provider_connection_test(
    request: ProviderProbeRequest,
) -> Result<ProviderValidationResponse, LlmProvidersApiError> {
    execute_provider_connection_test_with(request, &|name| std::env::var(name).ok()).await
}

async fn execute_provider_connection_test_with<F>(
    request: ProviderProbeRequest,
    lookup: &F,
) -> Result<ProviderValidationResponse, LlmProvidersApiError>
where
    F: Fn(&str) -> Option<String>,
{
    let config = ProviderProbeConfig::from_probe_request_with(request, lookup)?;
    if !provider_probe_supported(&config.provider_type) {
        validate_persisted_provider_base_url(&config.provider_type, config.base_url.as_deref())
            .map_err(LlmProvidersApiError::unprocessable)?;
        if let Some(detail) = config.credential_error {
            return Ok(ProviderValidationResponse::from_credential_error(
                &config, detail,
            ));
        }
        return Ok(ProviderValidationResponse::from_configuration_validation(
            &config,
        ));
    }
    if let Some(detail) = config.credential_error {
        return Ok(ProviderValidationResponse::from_credential_error(
            &config, detail,
        ));
    }
    Ok(ProviderValidationResponse::from_probe_health(
        probe_provider_connection(&config).await,
        &config,
    ))
}

async fn execute_persisted_provider_health_check(
    providers: &SharedLlmProviders,
    health_service: &SharedLlmProviderHealth,
    user_id: &str,
    provider_id: &str,
) -> Result<ProviderValidationResponse, LlmProvidersApiError> {
    let provider_id = validate_provider_id(provider_id)?;
    let config = providers
        .provider_probe_config(user_id, &provider_id)
        .await?
        .ok_or_else(|| LlmProvidersApiError::not_found("Provider not found"))?;
    if !provider_probe_supported(&config.provider_type) {
        return Err(LlmProvidersApiError::bad_request(
            "Provider health check is not supported for this provider type",
        ));
    }
    if let Some(detail) = config.credential_error {
        return Ok(ProviderValidationResponse::from_credential_error(
            &config, detail,
        ));
    }
    let health = probe_provider_connection(&config).await;
    let current_config = providers
        .provider_probe_config(user_id, &provider_id)
        .await?
        .ok_or_else(|| LlmProvidersApiError::not_found("Provider not found"))?;
    if current_config.revision != config.revision {
        return Err(LlmProvidersApiError::conflict(
            "Provider configuration changed during health check; retry the check",
        ));
    }
    health_service.record_health(&health).await?;
    let persisted_config = providers
        .provider_probe_config(user_id, &provider_id)
        .await?
        .ok_or_else(|| LlmProvidersApiError::not_found("Provider not found"))?;
    if persisted_config.revision != config.revision {
        return Err(LlmProvidersApiError::conflict(
            "Provider configuration changed during health check; retry the check",
        ));
    }
    Ok(ProviderValidationResponse::from_probe_health(
        health, &config,
    ))
}

async fn get_provider_health(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(provider_id): Path<String>,
) -> Result<Json<ProviderHealthResponse>, LlmProvidersApiError> {
    Ok(Json(
        read_persisted_provider_health(
            &app.llm_providers,
            &app.llm_provider_health,
            &identity.user_id,
            &provider_id,
        )
        .await?,
    ))
}

async fn read_persisted_provider_health(
    providers: &SharedLlmProviders,
    health_service: &SharedLlmProviderHealth,
    user_id: &str,
    provider_id: &str,
) -> Result<ProviderHealthResponse, LlmProvidersApiError> {
    let provider_id = validate_provider_id(provider_id)?;
    let config = providers
        .provider_probe_config(user_id, &provider_id)
        .await?
        .ok_or_else(|| LlmProvidersApiError::not_found("Provider not found"))?;
    let health = health_service
        .latest_health(&provider_id)
        .await?
        .ok_or_else(|| {
            LlmProvidersApiError::not_found("No health data available for this provider")
        })?;
    if !provider_health_matches_config(&health, &config) {
        return Err(LlmProvidersApiError::not_found(
            "No health data available for the current provider configuration",
        ));
    }
    Ok(health)
}

fn provider_health_matches_config(
    health: &ProviderHealthResponse,
    config: &ProviderProbeConfig,
) -> bool {
    if !provider_probe_supported(&config.provider_type) && health.status != "configuration_valid" {
        return false;
    }
    let Some(revision) = config.revision else {
        return false;
    };
    DateTime::parse_from_rfc3339(&health.last_check)
        .map(|checked_at| checked_at.timestamp_micros() >= revision)
        .unwrap_or(false)
}

async fn list_tenant_assignments(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Query(query): Query<TenantAssignmentQuery>,
) -> Result<Json<Vec<TenantProviderMappingResponse>>, LlmProvidersApiError> {
    let operation_type = validate_operation_type(query.operation_type)?;
    let response = app
        .llm_provider_assignments
        .list_tenant_assignments(&identity.user_id, &tenant_id, operation_type.as_deref())
        .await?;
    Ok(Json(response))
}

async fn get_provider_usage(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(provider_id): Path<String>,
    Query(query): Query<ProviderUsageQuery>,
) -> Result<Json<ProviderUsageResponse>, LlmProvidersApiError> {
    let provider_id = validate_provider_id(&provider_id)?;
    let response = app
        .llm_provider_usage
        .provider_usage(&identity.user_id, &provider_id, query)
        .await?;
    Ok(Json(response))
}

#[derive(Debug, Default, Deserialize)]
struct ProviderListQuery {
    include_inactive: Option<bool>,
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProviderCreateRequest {
    name: String,
    provider_type: String,
    operation_type: Option<String>,
    auth_method: Option<String>,
    environment_variable: Option<String>,
    api_key: Option<String>,
    base_url: Option<String>,
    llm_model: Option<String>,
    llm_small_model: Option<String>,
    embedding_model: Option<String>,
    embedding_config: Option<Value>,
    reranker_model: Option<String>,
    config: Option<Value>,
    is_active: Option<bool>,
    is_default: Option<bool>,
    is_enabled: Option<bool>,
    allowed_models: Option<Vec<String>>,
    blocked_models: Option<Vec<String>>,
    pool_weight: Option<f64>,
    pool_enabled: Option<bool>,
    model_tier: Option<String>,
    secondary_models: Option<Vec<String>>,
}

#[derive(Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProviderProbeRequest {
    name: String,
    provider_type: String,
    operation_type: Option<String>,
    auth_method: Option<String>,
    environment_variable: Option<String>,
    api_key: Option<String>,
    base_url: Option<String>,
    llm_model: Option<String>,
    llm_small_model: Option<String>,
    embedding_model: Option<String>,
    embedding_config: Option<Value>,
    reranker_model: Option<String>,
    config: Option<Value>,
    is_active: Option<bool>,
    is_default: Option<bool>,
    is_enabled: Option<bool>,
    allowed_models: Option<Vec<String>>,
    blocked_models: Option<Vec<String>>,
    pool_weight: Option<f64>,
    pool_enabled: Option<bool>,
    model_tier: Option<String>,
    secondary_models: Option<Vec<String>>,
}

#[derive(Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProviderUpdateRequest {
    expected_revision: i64,
    name: Option<String>,
    provider_type: Option<String>,
    operation_type: Option<String>,
    auth_method: Option<String>,
    environment_variable: Option<String>,
    api_key: Option<String>,
    #[serde(default, deserialize_with = "deserialize_present_nullable_string")]
    base_url: Option<Option<String>>,
    llm_model: Option<String>,
    llm_small_model: Option<String>,
    embedding_model: Option<String>,
    embedding_config: Option<Value>,
    reranker_model: Option<String>,
    config: Option<Value>,
    is_active: Option<bool>,
    is_default: Option<bool>,
    is_enabled: Option<bool>,
    allowed_models: Option<Vec<String>>,
    blocked_models: Option<Vec<String>>,
    pool_weight: Option<f64>,
    pool_enabled: Option<bool>,
    model_tier: Option<String>,
    secondary_models: Option<Vec<String>>,
}

fn deserialize_present_nullable_string<'de, D>(
    deserializer: D,
) -> Result<Option<Option<String>>, D::Error>
where
    D: Deserializer<'de>,
{
    Option::<String>::deserialize(deserializer).map(Some)
}

impl ProviderUpdateRequest {
    fn normalized_base_url_update(&self) -> Option<Option<&str>> {
        self.base_url.as_ref().map(|value| {
            value
                .as_deref()
                .map(str::trim)
                .filter(|value| !value.is_empty())
        })
    }
}

#[derive(Debug, Default, Deserialize)]
struct CatalogListQuery {
    provider: Option<String>,
    include_deprecated: Option<bool>,
}

#[derive(Debug, Default, Deserialize)]
struct CatalogSearchQuery {
    q: Option<String>,
    provider: Option<String>,
    limit: Option<i64>,
}

#[derive(Debug, Default, Deserialize)]
struct TenantAssignmentQuery {
    operation_type: Option<String>,
}

#[derive(Debug, Default, Clone, Deserialize)]
pub(crate) struct ProviderUsageQuery {
    start_date: Option<DateTime<Utc>>,
    end_date: Option<DateTime<Utc>>,
    operation_type: Option<String>,
}

#[derive(Debug)]
struct ValidatedCatalogSearchQuery {
    q: String,
    provider: Option<String>,
    limit: usize,
}

impl CatalogSearchQuery {
    fn validated(self) -> Result<ValidatedCatalogSearchQuery, LlmProvidersApiError> {
        let q = self
            .q
            .ok_or_else(|| LlmProvidersApiError::unprocessable("q is required"))?;
        let limit = self.limit.unwrap_or(20);
        if !(1..=100).contains(&limit) {
            return Err(LlmProvidersApiError::unprocessable(
                "limit must be between 1 and 100",
            ));
        }

        Ok(ValidatedCatalogSearchQuery {
            q,
            provider: self.provider,
            limit: limit as usize,
        })
    }
}

#[derive(Debug, Serialize)]
struct CatalogListResponse {
    total: usize,
    models: Vec<ModelMetadataView>,
}

#[derive(Debug, Serialize)]
struct CatalogSearchResponse {
    query: String,
    total: usize,
    models: Vec<ModelMetadataView>,
}

#[derive(Debug, Serialize)]
struct ProviderModelsResponse {
    provider_type: String,
    models: CategorizedProviderModels,
    #[serde(skip_serializing_if = "Option::is_none")]
    source: Option<&'static str>,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
struct ProviderTypeDescriptor {
    provider_type: &'static str,
    operation_type: &'static str,
    probe_supported: bool,
    auth_methods: &'static [&'static str],
    unavailable_auth_methods: &'static [&'static str],
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct EnvDetectionResponse {
    detected_providers: BTreeMap<String, EnvProviderView>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct ProviderHealthResponse {
    provider_id: String,
    status: String,
    probed: bool,
    last_check: String,
    error_message: Option<String>,
    response_time_ms: Option<i32>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct ProviderValidationResponse {
    provider: Option<ProviderConfigResponse>,
    provider_id: String,
    status: String,
    probed: bool,
    environment_variable: Option<String>,
    detail: Option<String>,
    last_check: String,
    response_time_ms: Option<i32>,
    error_message: Option<String>,
    catalog: Option<Value>,
}

pub(crate) struct ProviderProbeConfig {
    provider_id: String,
    provider_type: String,
    auth_method: &'static str,
    environment_variable: Option<String>,
    base_url: Option<String>,
    llm_model: Option<String>,
    api_key: Option<String>,
    credential_error: Option<&'static str>,
    revision: Option<i64>,
}

impl ProviderProbeConfig {
    fn from_probe_request_with<F>(
        request: ProviderProbeRequest,
        lookup: &F,
    ) -> Result<Self, LlmProvidersApiError>
    where
        F: Fn(&str) -> Option<String>,
    {
        let _name = normalize_required_name(request.name)?;
        let provider_type = normalize_provider_type(request.provider_type)?;
        validate_persisted_provider_base_url(&provider_type, request.base_url.as_deref())
            .map_err(LlmProvidersApiError::unprocessable)?;
        let _operation_type = effective_operation_type(&provider_type, request.operation_type)?;
        let auth_method = validate_provider_auth_method(
            &provider_type,
            request.auth_method.as_deref(),
            provider_auth_method(&provider_type),
        )?;
        let submitted_api_key = request
            .api_key
            .as_deref()
            .is_some_and(|value| !value.trim().is_empty());
        let submitted_environment_variable = request
            .environment_variable
            .as_deref()
            .is_some_and(|value| !value.trim().is_empty());
        let (environment_variable, api_key, credential_error) = match auth_method {
            "api_key" => {
                if submitted_environment_variable {
                    return Err(LlmProvidersApiError::unprocessable(
                        "Environment variable requires environment authentication",
                    ));
                }
                let api_key = usable_probe_api_key(request.api_key);
                if api_key.is_none() {
                    return Err(LlmProvidersApiError::unprocessable("API key is required"));
                }
                (None, api_key, None)
            }
            "environment" => {
                if submitted_api_key {
                    return Err(LlmProvidersApiError::unprocessable(
                        "API key cannot be combined with environment authentication",
                    ));
                }
                let environment_variable =
                    validate_environment_variable(&provider_type, request.environment_variable)?;
                if !environment_credential_endpoint_is_official(
                    &provider_type,
                    request.base_url.as_deref(),
                ) {
                    return Err(LlmProvidersApiError::unprocessable(
                        "Environment credentials require the official provider endpoint",
                    ));
                }
                let api_key = environment_credential_with(&environment_variable, lookup);
                let credential_error = api_key.is_none().then_some(ENVIRONMENT_CREDENTIAL_MISSING);
                (Some(environment_variable), api_key, credential_error)
            }
            "none" => {
                if submitted_api_key || submitted_environment_variable {
                    return Err(LlmProvidersApiError::unprocessable(
                        "No-auth providers cannot accept credential fields",
                    ));
                }
                (None, None, None)
            }
            _ => {
                return Err(LlmProvidersApiError::unprocessable(
                    "Authentication method is not supported for this provider type",
                ));
            }
        };
        let llm_model = request.llm_model;
        let _compatibility_fields = (
            request.llm_small_model,
            request.embedding_model,
            request.embedding_config,
            request.reranker_model,
            request.config,
            request.is_active,
            request.is_default,
            request.is_enabled,
            request.allowed_models,
            request.blocked_models,
            request.pool_weight,
            request.pool_enabled,
            request.model_tier,
            request.secondary_models,
        );
        Ok(Self {
            provider_id: uuid::Uuid::new_v4().to_string(),
            provider_type,
            auth_method,
            environment_variable,
            base_url: request.base_url,
            llm_model,
            api_key,
            credential_error,
            revision: None,
        })
    }

    fn from_persisted_record(record: LlmProviderRecord) -> Self {
        let api_key = decrypt_provider_api_key_for_mask(&record.api_key_encrypted);
        Self::from_record_with(record, api_key, &|name| std::env::var(name).ok())
    }

    fn from_dev_record(record: LlmProviderRecord) -> Self {
        let api_key = Some(record.api_key_encrypted.clone());
        Self::from_record_with(record, api_key, &|name| std::env::var(name).ok())
    }

    fn from_record_with<F>(record: LlmProviderRecord, api_key: Option<String>, lookup: &F) -> Self
    where
        F: Fn(&str) -> Option<String>,
    {
        let auth_method = configured_provider_auth_method(&record.provider_type, &record.config);
        let environment_variable =
            configured_environment_variable(&record.provider_type, &record.config);
        let (api_key, credential_error) = match auth_method {
            "environment" => match environment_variable.as_deref() {
                Some(environment_variable)
                    if environment_credential_endpoint_is_official(
                        &record.provider_type,
                        record.base_url.as_deref(),
                    ) =>
                {
                    let api_key = environment_credential_with(environment_variable, lookup);
                    let credential_error =
                        api_key.is_none().then_some(ENVIRONMENT_CREDENTIAL_MISSING);
                    (api_key, credential_error)
                }
                Some(_) => (None, Some(ENVIRONMENT_CREDENTIAL_INVALID)),
                None => (None, Some(ENVIRONMENT_CREDENTIAL_INVALID)),
            },
            "api_key" => (usable_probe_api_key(api_key), None),
            _ => (None, None),
        };
        Self {
            provider_id: record.id,
            provider_type: record.provider_type,
            auth_method,
            environment_variable,
            base_url: record.base_url,
            llm_model: record.llm_model,
            api_key,
            credential_error,
            revision: Some(record.updated_at.timestamp_micros()),
        }
    }
}

async fn probe_provider_connection(config: &ProviderProbeConfig) -> ProviderHealthRecord {
    let started = Instant::now();
    let outcome = match provider_probe_client() {
        Ok(client) => match build_provider_probe_request(&client, config) {
            Ok(request) => match request.send().await {
                Ok(response) if response.status() == StatusCode::OK => ProbeOutcome::healthy(),
                Ok(response) => {
                    ProbeOutcome::unhealthy(format!("HTTP {}", response.status().as_u16()))
                }
                Err(error) if error.is_timeout() => ProbeOutcome::unhealthy("Connection timed out"),
                Err(error) if error.is_connect() => ProbeOutcome::unhealthy("Connection failed"),
                Err(_) => ProbeOutcome::unhealthy("Request failed"),
            },
            Err(message) => ProbeOutcome::unhealthy(message),
        },
        Err(message) => ProbeOutcome::unhealthy(message),
    };
    let response_time_ms = i32::try_from(started.elapsed().as_millis()).unwrap_or(i32::MAX);

    ProviderHealthRecord {
        provider_id: config.provider_id.clone(),
        status: outcome.status.to_string(),
        last_check: Utc::now(),
        error_message: outcome.error_message,
        response_time_ms: Some(response_time_ms),
    }
}

struct ProbeOutcome {
    status: &'static str,
    error_message: Option<String>,
}

impl ProbeOutcome {
    fn healthy() -> Self {
        Self {
            status: "healthy",
            error_message: None,
        }
    }

    fn unhealthy(message: impl Into<String>) -> Self {
        Self {
            status: "unhealthy",
            error_message: Some(message.into()),
        }
    }
}

fn provider_probe_client() -> Result<reqwest::Client, &'static str> {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(2))
        .timeout(Duration::from_secs(5))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "HTTP client initialization failed")
}

fn build_provider_probe_request(
    client: &reqwest::Client,
    config: &ProviderProbeConfig,
) -> Result<reqwest::RequestBuilder, &'static str> {
    let provider_type = catalog_provider_key(&config.provider_type);
    if !provider_probe_supported(&provider_type) {
        return Err("Provider health check is not supported for this provider type");
    }
    let raw_base_url = config
        .base_url
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .or_else(|| provider_probe_default_base_url(&provider_type))
        .ok_or("Provider base URL is required")?;
    let base_url = validated_probe_base_url(raw_base_url)?;
    validate_probe_transport(&base_url, &provider_type)?;
    validate_provider_base_url_path(&provider_type, &base_url)?;

    let request = match provider_type.as_str() {
        "gemini" => {
            let model = config
                .llm_model
                .as_deref()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .unwrap_or("gemini-pro");
            let url = append_probe_url_segments(base_url, &["v1beta", "models", model])?;
            client
                .get(url)
                .header("x-goog-api-key", required_probe_api_key(config)?)
        }
        "anthropic" => {
            let url = append_probe_url_segments(base_url, &["v1", "models"])?;
            client
                .get(url)
                .header("x-api-key", required_probe_api_key(config)?)
                .header("anthropic-version", "2023-06-01")
        }
        "ollama" => {
            let url = append_probe_url_segments(base_url, &["api", "tags"])?;
            client.get(url)
        }
        "lmstudio" => {
            let url = append_probe_url_segments(base_url, &["models"])?;
            client.get(url)
        }
        "azure_openai" => {
            let url = append_probe_url_segments(base_url, &["models"])?;
            client
                .get(url)
                .header("api-key", required_probe_api_key(config)?)
        }
        _ => {
            let url = append_probe_url_segments(base_url, &["models"])?;
            client.get(url).bearer_auth(required_probe_api_key(config)?)
        }
    };

    Ok(request)
}

fn provider_probe_default_base_url(provider_type: &str) -> Option<&'static str> {
    match provider_type {
        "openai" => Some("https://api.openai.com/v1"),
        "openrouter" => Some("https://openrouter.ai/api/v1"),
        "dashscope" => Some("https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "deepseek" => Some("https://api.deepseek.com/v1"),
        "minimax" => Some("https://api.minimax.io/v1"),
        "zai" => Some("https://open.bigmodel.cn/api/paas/v4"),
        "kimi" => Some("https://api.moonshot.cn/v1"),
        "groq" => Some("https://api.groq.com/openai/v1"),
        "mistral" => Some("https://api.mistral.ai/v1"),
        "volcengine" => Some("https://ark.cn-beijing.volces.com/api/v3"),
        "cohere" => Some("https://api.cohere.com/v1"),
        "anthropic" => Some("https://api.anthropic.com"),
        "gemini" => Some("https://generativelanguage.googleapis.com"),
        "ollama" => Some("http://localhost:11434"),
        "lmstudio" => Some("http://localhost:1234/v1"),
        _ => None,
    }
}

fn provider_probe_supported(provider_type: &str) -> bool {
    !matches!(
        catalog_provider_key(provider_type).as_str(),
        "azure_openai" | "bedrock" | "vertex"
    )
}

fn validated_probe_base_url(raw_url: &str) -> Result<Url, &'static str> {
    let url = Url::parse(raw_url).map_err(|_| "Invalid provider base URL")?;
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || url.host_str().is_none()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("Invalid provider base URL");
    }
    Ok(url)
}

fn validate_persisted_provider_base_url(
    provider_type: &str,
    raw_url: Option<&str>,
) -> Result<(), &'static str> {
    let Some(raw_url) = raw_url.map(str::trim).filter(|value| !value.is_empty()) else {
        return Ok(());
    };
    let provider_type = catalog_provider_key(provider_type);
    let url = validated_probe_base_url(raw_url)?;
    validate_probe_transport(&url, &provider_type)?;
    validate_provider_base_url_path(&provider_type, &url)
}

fn validate_provider_base_url_path(provider_type: &str, url: &Url) -> Result<(), &'static str> {
    if let Some(default_url) = provider_probe_default_base_url(provider_type) {
        let default_url = validated_probe_base_url(default_url)?;
        if provider_url_has_same_origin(url, &default_url) {
            return official_provider_base_path_is_allowed(
                provider_type,
                url.path(),
                default_url.path(),
            )
            .then_some(())
            .ok_or("Provider base URL must use the exact official API path");
        }
    }
    SAFE_CUSTOM_PROVIDER_BASE_PATHS
        .contains(&normalized_provider_base_path(url.path()))
        .then_some(())
        .ok_or("Provider base URL path is not allowed")
}

fn environment_credential_endpoint_is_official(provider_type: &str, raw_url: Option<&str>) -> bool {
    let provider_type = catalog_provider_key(provider_type);
    let Some(default_url) = provider_probe_default_base_url(&provider_type) else {
        return false;
    };
    let raw_url = raw_url
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(default_url);
    let (Ok(url), Ok(default_url)) = (
        validated_probe_base_url(raw_url),
        validated_probe_base_url(default_url),
    ) else {
        return false;
    };
    if validate_probe_transport(&url, &provider_type).is_err()
        || validate_provider_base_url_path(&provider_type, &url).is_err()
    {
        return false;
    }
    provider_url_has_same_origin(&url, &default_url)
        && official_provider_base_path_is_allowed(&provider_type, url.path(), default_url.path())
}

fn official_provider_base_path_is_allowed(
    provider_type: &str,
    path: &str,
    default_path: &str,
) -> bool {
    let path = normalized_provider_base_path(path);
    match provider_type {
        "anthropic" => matches!(path, "/" | "/v1"),
        "gemini" => matches!(path, "/" | "/v1beta"),
        "ollama" => matches!(path, "/" | "/api"),
        _ => path == normalized_provider_base_path(default_path),
    }
}

fn provider_url_has_same_origin(url: &Url, expected: &Url) -> bool {
    url.scheme() == expected.scheme()
        && url
            .host_str()
            .zip(expected.host_str())
            .is_some_and(|(host, expected_host)| host.eq_ignore_ascii_case(expected_host))
        && url.port_or_known_default() == expected.port_or_known_default()
}

fn normalized_provider_base_path(path: &str) -> &str {
    let normalized = path.trim_end_matches('/');
    if normalized.is_empty() {
        "/"
    } else {
        normalized
    }
}

fn validate_probe_transport(url: &Url, provider_type: &str) -> Result<(), &'static str> {
    if provider_requires_api_key(provider_type) {
        return (url.scheme() == "https")
            .then_some(())
            .ok_or("HTTPS is required for credentialed providers");
    }
    if url.scheme() == "http" && !is_local_probe_host(url) {
        return Err("HTTP is only allowed for local provider endpoints");
    }
    Ok(())
}

fn is_local_probe_host(url: &Url) -> bool {
    match url.host() {
        Some(url::Host::Domain(domain)) => domain.eq_ignore_ascii_case("localhost"),
        Some(url::Host::Ipv4(address)) => address.is_loopback(),
        Some(url::Host::Ipv6(address)) => address.is_loopback(),
        None => false,
    }
}

fn append_probe_url_segments(mut url: Url, segments: &[&str]) -> Result<Url, &'static str> {
    let overlap = {
        let existing = url
            .path_segments()
            .ok_or("Invalid provider base URL")?
            .filter(|segment| !segment.is_empty())
            .collect::<Vec<_>>();
        (0..=existing.len().min(segments.len()))
            .rev()
            .find(|&overlap| existing[existing.len() - overlap..] == segments[..overlap])
            .unwrap_or(0)
    };
    {
        let mut path = url
            .path_segments_mut()
            .map_err(|_| "Invalid provider base URL")?;
        path.pop_if_empty();
        for segment in &segments[overlap..] {
            path.push(segment);
        }
    }
    Ok(url)
}

fn required_probe_api_key(config: &ProviderProbeConfig) -> Result<&str, &'static str> {
    config.api_key.as_deref().ok_or("API key is required")
}

fn usable_probe_api_key(api_key: Option<String>) -> Option<String> {
    api_key.and_then(|value| {
        let trimmed = value.trim();
        (!trimmed.is_empty() && trimmed != LOCAL_NO_API_KEY_SENTINEL).then(|| trimmed.to_string())
    })
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct ProviderConfigResponse {
    id: String,
    tenant_id: Option<String>,
    name: String,
    provider_type: String,
    operation_type: String,
    base_url: Option<String>,
    llm_model: Option<String>,
    llm_small_model: Option<String>,
    embedding_model: Option<String>,
    embedding_config: Option<Value>,
    reranker_model: Option<String>,
    config: Value,
    is_active: bool,
    is_default: bool,
    is_enabled: bool,
    allowed_models: Vec<String>,
    blocked_models: Vec<String>,
    pool_weight: f64,
    pool_enabled: bool,
    model_tier: Option<String>,
    secondary_models: Vec<String>,
    auth_method: String,
    credential_source: String,
    environment_variable: Option<String>,
    credential_configured: bool,
    api_key_masked: String,
    revision: i64,
    created_at: String,
    updated_at: String,
    health_status: Option<String>,
    health_last_check: Option<String>,
    response_time_ms: Option<i32>,
    error_message: Option<String>,
    resilience: Value,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct TenantProviderMappingResponse {
    id: String,
    tenant_id: String,
    provider_id: String,
    operation_type: String,
    priority: i32,
    created_at: String,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct ProviderUsageResponse {
    provider_id: String,
    tenant_id: Option<String>,
    statistics: Vec<UsageStatisticResponse>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct UsageStatisticResponse {
    provider_id: String,
    tenant_id: Option<String>,
    operation_type: String,
    total_requests: i64,
    total_prompt_tokens: i64,
    total_completion_tokens: i64,
    total_tokens: i64,
    total_cost_usd: Option<f64>,
    avg_response_time_ms: Option<f64>,
    first_request_at: Option<String>,
    last_request_at: Option<String>,
}

impl From<UsageStatisticRecord> for UsageStatisticResponse {
    fn from(record: UsageStatisticRecord) -> Self {
        Self {
            provider_id: record.provider_id,
            tenant_id: record.tenant_id,
            operation_type: record.operation_type,
            total_requests: record.total_requests,
            total_prompt_tokens: record.total_prompt_tokens,
            total_completion_tokens: record.total_completion_tokens,
            total_tokens: record.total_tokens,
            total_cost_usd: record.total_cost_usd,
            avg_response_time_ms: record.avg_response_time_ms,
            first_request_at: record
                .first_request_at
                .map(|value| value.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true)),
            last_request_at: record
                .last_request_at
                .map(|value| value.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true)),
        }
    }
}

impl From<TenantProviderMappingRecord> for TenantProviderMappingResponse {
    fn from(record: TenantProviderMappingRecord) -> Self {
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            provider_id: record.provider_id,
            operation_type: record.operation_type,
            priority: record.priority,
            created_at: record
                .created_at
                .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
        }
    }
}

impl From<ProviderHealthRecord> for ProviderHealthResponse {
    fn from(record: ProviderHealthRecord) -> Self {
        let probed = record.status != "configuration_valid";
        Self {
            provider_id: record.provider_id,
            status: record.status,
            probed,
            last_check: record
                .last_check
                .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
            error_message: record.error_message,
            response_time_ms: record.response_time_ms,
        }
    }
}

impl ProviderValidationResponse {
    fn from_health(record: ProviderHealthRecord) -> Self {
        Self {
            provider: None,
            provider_id: record.provider_id,
            status: record.status,
            probed: true,
            environment_variable: None,
            detail: None,
            last_check: record
                .last_check
                .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
            response_time_ms: record.response_time_ms,
            error_message: record.error_message,
            catalog: None,
        }
    }

    fn from_probe_health(record: ProviderHealthRecord, config: &ProviderProbeConfig) -> Self {
        let mut response = Self::from_health(record);
        response.environment_variable = (config.auth_method == "environment")
            .then(|| config.environment_variable.clone())
            .flatten();
        response
    }

    fn from_credential_error(config: &ProviderProbeConfig, detail: &'static str) -> Self {
        Self {
            provider: None,
            provider_id: config.provider_id.clone(),
            status: "unhealthy".to_string(),
            probed: false,
            environment_variable: (config.auth_method == "environment")
                .then(|| config.environment_variable.clone())
                .flatten(),
            detail: Some(detail.to_string()),
            last_check: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
            response_time_ms: Some(0),
            error_message: None,
            catalog: None,
        }
    }

    fn from_configuration_validation(config: &ProviderProbeConfig) -> Self {
        Self {
            provider: None,
            provider_id: config.provider_id.clone(),
            status: "configuration_valid".to_string(),
            probed: false,
            environment_variable: (config.auth_method == "environment")
                .then(|| config.environment_variable.clone())
                .flatten(),
            detail: Some(
                "Connection probing is not supported for this provider type; configuration validation passed"
                    .to_string(),
            ),
            last_check: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
            response_time_ms: None,
            error_message: None,
            catalog: None,
        }
    }
}

fn provider_response_from_record(
    record: LlmProviderRecord,
    health: Option<ProviderHealthRecord>,
) -> ProviderConfigResponse {
    let probe_supported = provider_probe_supported(&record.provider_type);
    let health = health.filter(|value| {
        value.last_check >= record.updated_at
            && (probe_supported || value.status == "configuration_valid")
    });
    let auth_method = configured_provider_auth_method(&record.provider_type, &record.config);
    let environment_variable =
        configured_environment_variable(&record.provider_type, &record.config);
    let encrypted_api_key = record.api_key_encrypted.trim();
    let credential_source = match auth_method {
        "api_key" => "encrypted_store",
        "environment" => "environment",
        "none" => "not_required",
        _ => "unknown",
    };
    let credential_configured = match auth_method {
        "api_key" => {
            !encrypted_api_key.is_empty() && encrypted_api_key != LOCAL_NO_API_KEY_SENTINEL
        }
        "environment"
            if environment_credential_endpoint_is_official(
                &record.provider_type,
                record.base_url.as_deref(),
            ) =>
        {
            environment_variable.as_deref().is_some_and(|name| {
                environment_credential_with(name, &|name| std::env::var(name).ok()).is_some()
            })
        }
        "none" => true,
        _ => false,
    };
    let api_key_masked = if auth_method == "api_key" {
        mask_api_key(&record.api_key_encrypted)
    } else {
        String::new()
    };
    let public_config = public_provider_config(&record.config);
    let embedding_config = extract_embedding_config(&public_config);
    let public_base_url = record
        .base_url
        .as_deref()
        .filter(|base_url| {
            validate_persisted_provider_base_url(&record.provider_type, Some(base_url)).is_ok()
        })
        .map(ToOwned::to_owned);
    let health_last_check = health.as_ref().map(|value| {
        value
            .last_check
            .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true)
    });
    ProviderConfigResponse {
        id: record.id,
        tenant_id: Some("default".to_string()),
        name: record.name,
        provider_type: record.provider_type,
        operation_type: record.operation_type,
        base_url: public_base_url,
        llm_model: record.llm_model,
        llm_small_model: record.llm_small_model,
        embedding_model: record.embedding_model,
        embedding_config,
        reranker_model: record.reranker_model,
        config: public_config,
        is_active: record.is_active,
        is_default: record.is_default,
        is_enabled: record.is_enabled,
        allowed_models: record.allowed_models,
        blocked_models: record.blocked_models,
        pool_weight: record.pool_weight,
        pool_enabled: record.pool_enabled,
        model_tier: record.model_tier,
        secondary_models: record.secondary_models,
        auth_method: auth_method.to_string(),
        credential_source: credential_source.to_string(),
        environment_variable,
        credential_configured,
        api_key_masked,
        revision: record.updated_at.timestamp_micros(),
        created_at: record
            .created_at
            .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
        updated_at: record
            .updated_at
            .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
        health_status: health.as_ref().map(|value| value.status.clone()),
        health_last_check,
        response_time_ms: health.as_ref().and_then(|value| value.response_time_ms),
        error_message: health.and_then(|value| value.error_message),
        resilience: default_resilience_status(),
    }
}

fn public_provider_config(config: &Value) -> Value {
    let Some(config) = config.as_object() else {
        return json!({});
    };
    let mut public = serde_json::Map::new();
    copy_public_number_fields(
        config,
        &mut public,
        &[
            "temperature",
            "max_tokens",
            "top_p",
            "timeout",
            "timeout_seconds",
            "request_timeout_seconds",
            "connect_timeout_seconds",
            "frequency_penalty",
            "presence_penalty",
            "seed",
            "max_retries",
        ],
    );
    if let Some(region) = config
        .get("region")
        .and_then(Value::as_str)
        .filter(|region| {
            !region.is_empty()
                && region.len() <= 64
                && region
                    .chars()
                    .all(|character| character.is_ascii_alphanumeric() || character == '-')
        })
    {
        public.insert("region".to_string(), json!(region));
    }
    if let Some(retries) = project_public_number_object(
        config.get("retries"),
        &["max_attempts", "base_delay", "max_delay", "backoff_factor"],
    ) {
        public.insert("retries".to_string(), retries);
    }
    if let Some(transport) = project_public_number_object(
        config.get("transport"),
        &[
            "connect_timeout_seconds",
            "request_timeout_seconds",
            "idle_timeout_seconds",
        ],
    ) {
        public.insert("transport".to_string(), transport);
    }
    if let Some(embedding) = project_public_embedding_config(config.get("embedding")) {
        public.insert("embedding".to_string(), embedding);
    }
    Value::Object(public)
}

fn copy_public_number_fields(
    source: &serde_json::Map<String, Value>,
    target: &mut serde_json::Map<String, Value>,
    keys: &[&str],
) {
    for key in keys {
        if let Some(value) = source.get(*key).filter(|value| value.is_number()) {
            target.insert((*key).to_string(), value.clone());
        }
    }
}

fn project_public_number_object(value: Option<&Value>, keys: &[&str]) -> Option<Value> {
    let source = value?.as_object()?;
    let mut public = serde_json::Map::new();
    copy_public_number_fields(source, &mut public, keys);
    (!public.is_empty()).then_some(Value::Object(public))
}

fn project_public_embedding_config(value: Option<&Value>) -> Option<Value> {
    let source = value?.as_object()?;
    let mut public = serde_json::Map::new();
    copy_public_number_fields(source, &mut public, &["dimensions", "timeout"]);
    for key in ["model", "user"] {
        if let Some(value) = source.get(key).and_then(Value::as_str).filter(|value| {
            !value.is_empty() && value.len() <= 512 && !value.chars().any(char::is_control)
        }) {
            public.insert(key.to_string(), json!(value));
        }
    }
    if let Some(value @ ("float" | "base64")) =
        source.get("encoding_format").and_then(Value::as_str)
    {
        public.insert("encoding_format".to_string(), json!(value));
    }
    if let Some(provider_options) =
        project_public_embedding_provider_options(source.get("provider_options"))
    {
        public.insert("provider_options".to_string(), provider_options);
    }
    (!public.is_empty()).then_some(Value::Object(public))
}

fn project_public_embedding_provider_options(value: Option<&Value>) -> Option<Value> {
    let source = value?.as_object()?;
    let mut public = serde_json::Map::new();
    if let Some(batch_size) = source
        .get("batch_size")
        .and_then(Value::as_u64)
        .filter(|batch_size| (1..=2048).contains(batch_size))
    {
        public.insert("batch_size".to_string(), json!(batch_size));
    }
    if let Some(
        input_type @ ("search_document" | "search_query" | "classification" | "clustering"),
    ) = source.get("input_type").and_then(Value::as_str)
    {
        public.insert("input_type".to_string(), json!(input_type));
    }
    if let Some(truncate @ ("NONE" | "START" | "END")) =
        source.get("truncate").and_then(Value::as_str)
    {
        public.insert("truncate".to_string(), json!(truncate));
    }
    (!public.is_empty()).then_some(Value::Object(public))
}

fn validate_writable_provider_config(config: &Value) -> Result<Value, LlmProvidersApiError> {
    const NUMBER_FIELDS: &[&str] = &[
        "temperature",
        "max_tokens",
        "top_p",
        "timeout",
        "timeout_seconds",
        "request_timeout_seconds",
        "connect_timeout_seconds",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "max_retries",
    ];
    let source = config
        .as_object()
        .ok_or_else(unsupported_provider_config_error)?;
    let mut validated = serde_json::Map::new();
    for (key, value) in source {
        let safe_value = match key.as_str() {
            key if NUMBER_FIELDS.contains(&key) && writable_provider_number_is_safe(key, value) => {
                value.clone()
            }
            "region"
                if value.as_str().is_some_and(|region| {
                    !region.is_empty()
                        && region.len() <= 64
                        && region
                            .chars()
                            .all(|character| character.is_ascii_alphanumeric() || character == '-')
                }) =>
            {
                value.clone()
            }
            "retries" => validate_writable_number_object(
                value,
                &["max_attempts", "base_delay", "max_delay", "backoff_factor"],
            )?,
            "transport" => validate_writable_number_object(
                value,
                &[
                    "connect_timeout_seconds",
                    "request_timeout_seconds",
                    "idle_timeout_seconds",
                ],
            )?,
            "embedding" => validate_writable_embedding_config(value)?,
            _ => return Err(unsupported_provider_config_error()),
        };
        validated.insert(key.clone(), safe_value);
    }
    Ok(Value::Object(validated))
}

fn validate_writable_number_object(
    value: &Value,
    allowed_fields: &[&str],
) -> Result<Value, LlmProvidersApiError> {
    let source = value
        .as_object()
        .ok_or_else(unsupported_provider_config_error)?;
    if source.iter().any(|(key, value)| {
        !allowed_fields.contains(&key.as_str()) || !writable_provider_number_is_safe(key, value)
    }) {
        return Err(unsupported_provider_config_error());
    }
    Ok(Value::Object(source.clone()))
}

fn validate_writable_embedding_config(value: &Value) -> Result<Value, LlmProvidersApiError> {
    let source = value
        .as_object()
        .ok_or_else(unsupported_provider_config_error)?;
    let mut validated = serde_json::Map::new();
    for (key, value) in source {
        let is_safe = match key.as_str() {
            "dimensions" => value.as_u64().is_some_and(|value| value >= 1),
            "timeout" => numeric_in_range(value, f64::EPSILON, 86_400.0),
            "model" | "user" => value.as_str().is_some_and(|value| {
                !value.is_empty() && value.len() <= 512 && !value.chars().any(char::is_control)
            }),
            "encoding_format" => matches!(value.as_str(), Some("float" | "base64")),
            "provider_options" => {
                validated.insert(
                    key.clone(),
                    validate_writable_embedding_provider_options(value)?,
                );
                continue;
            }
            _ => false,
        };
        if !is_safe {
            return Err(unsupported_provider_config_error());
        }
        validated.insert(key.clone(), value.clone());
    }
    Ok(Value::Object(validated))
}

fn validate_writable_embedding_provider_options(
    value: &Value,
) -> Result<Value, LlmProvidersApiError> {
    let source = value
        .as_object()
        .ok_or_else(unsupported_provider_config_error)?;
    for (key, value) in source {
        let is_safe = match key.as_str() {
            "batch_size" => value
                .as_u64()
                .is_some_and(|batch_size| (1..=2048).contains(&batch_size)),
            "input_type" => matches!(
                value.as_str(),
                Some("search_document" | "search_query" | "classification" | "clustering")
            ),
            "truncate" => matches!(value.as_str(), Some("NONE" | "START" | "END")),
            _ => false,
        };
        if !is_safe {
            return Err(unsupported_provider_config_error());
        }
    }
    Ok(Value::Object(source.clone()))
}

fn writable_provider_number_is_safe(key: &str, value: &Value) -> bool {
    match key {
        "temperature" => numeric_in_range(value, 0.0, 2.0),
        "max_tokens" => value.as_u64().is_some_and(|value| value >= 1),
        "top_p" => numeric_in_range(value, 0.0, 1.0),
        "timeout" | "timeout_seconds" | "request_timeout_seconds" | "connect_timeout_seconds" => {
            numeric_in_range(value, f64::EPSILON, 3600.0)
        }
        "frequency_penalty" | "presence_penalty" => numeric_in_range(value, -2.0, 2.0),
        "seed" => value.as_i64().is_some() || value.as_u64().is_some(),
        "max_retries" | "max_attempts" => value.as_u64().is_some_and(|value| value <= 20),
        "base_delay" => numeric_in_range(value, 0.0, 300.0),
        "max_delay" => numeric_in_range(value, 0.0, 3600.0),
        "backoff_factor" => numeric_in_range(value, 0.0, 100.0),
        "idle_timeout_seconds" => numeric_in_range(value, f64::EPSILON, 86_400.0),
        _ => false,
    }
}

fn numeric_in_range(value: &Value, minimum: f64, maximum: f64) -> bool {
    value
        .as_f64()
        .is_some_and(|value| value >= minimum && value <= maximum)
}

const WRITABLE_PROVIDER_SCALAR_FIELDS: &[&str] = &[
    "temperature",
    "max_tokens",
    "top_p",
    "timeout",
    "timeout_seconds",
    "request_timeout_seconds",
    "connect_timeout_seconds",
    "frequency_penalty",
    "presence_penalty",
    "seed",
    "max_retries",
    "region",
];
const WRITABLE_RETRY_FIELDS: &[&str] =
    &["max_attempts", "base_delay", "max_delay", "backoff_factor"];
const WRITABLE_TRANSPORT_FIELDS: &[&str] = &[
    "connect_timeout_seconds",
    "request_timeout_seconds",
    "idle_timeout_seconds",
];
const WRITABLE_EMBEDDING_FIELDS: &[&str] =
    &["dimensions", "timeout", "model", "user", "encoding_format"];
const WRITABLE_EMBEDDING_PROVIDER_OPTION_FIELDS: &[&str] =
    &["batch_size", "input_type", "truncate"];

fn merge_writable_provider_config(
    existing: &Value,
    submitted: Option<Value>,
) -> Result<Value, LlmProvidersApiError> {
    let Some(submitted) = submitted else {
        return Ok(existing.clone());
    };
    let validated = validate_writable_provider_config(&submitted)?;
    let mut merged = existing.as_object().cloned().unwrap_or_default();
    for key in WRITABLE_PROVIDER_SCALAR_FIELDS {
        merged.remove(*key);
    }
    strip_writable_nested_fields(&mut merged, "retries", WRITABLE_RETRY_FIELDS);
    strip_writable_nested_fields(&mut merged, "transport", WRITABLE_TRANSPORT_FIELDS);
    strip_writable_embedding_fields(&mut merged);
    for (key, value) in validated
        .as_object()
        .expect("validated provider config is an object")
    {
        if matches!(key.as_str(), "retries" | "transport" | "embedding") {
            let mut nested = merged
                .get(key)
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            for (nested_key, nested_value) in value
                .as_object()
                .expect("validated nested provider config is an object")
            {
                if key == "embedding" && nested_key == "provider_options" {
                    let mut provider_options = nested
                        .get(nested_key)
                        .and_then(Value::as_object)
                        .cloned()
                        .unwrap_or_default();
                    for (option_key, option_value) in nested_value
                        .as_object()
                        .expect("validated embedding provider options are an object")
                    {
                        provider_options.insert(option_key.clone(), option_value.clone());
                    }
                    nested.insert(nested_key.clone(), Value::Object(provider_options));
                } else {
                    nested.insert(nested_key.clone(), nested_value.clone());
                }
            }
            merged.insert(key.clone(), Value::Object(nested));
        } else {
            merged.insert(key.clone(), value.clone());
        }
    }
    Ok(Value::Object(merged))
}

fn strip_writable_nested_fields(
    config: &mut serde_json::Map<String, Value>,
    key: &str,
    safe_fields: &[&str],
) {
    let remove_container = match config.get_mut(key) {
        Some(Value::Object(nested)) => {
            for safe_field in safe_fields {
                nested.remove(*safe_field);
            }
            nested.is_empty()
        }
        Some(_) => true,
        None => false,
    };
    if remove_container {
        config.remove(key);
    }
}

fn strip_writable_embedding_fields(config: &mut serde_json::Map<String, Value>) {
    let remove_embedding = match config.get_mut("embedding") {
        Some(Value::Object(embedding)) => {
            for safe_field in WRITABLE_EMBEDDING_FIELDS {
                embedding.remove(*safe_field);
            }
            let remove_provider_options = match embedding.get_mut("provider_options") {
                Some(Value::Object(provider_options)) => {
                    for safe_field in WRITABLE_EMBEDDING_PROVIDER_OPTION_FIELDS {
                        provider_options.remove(*safe_field);
                    }
                    provider_options.is_empty()
                }
                Some(_) => true,
                None => false,
            };
            if remove_provider_options {
                embedding.remove("provider_options");
            }
            embedding.is_empty()
        }
        Some(_) => true,
        None => false,
    };
    if remove_embedding {
        config.remove("embedding");
    }
}

fn unsupported_provider_config_error() -> LlmProvidersApiError {
    LlmProvidersApiError::unprocessable("Provider config contains unsupported fields")
}

fn provider_record_from_create_for_dev(
    request: ProviderCreateRequest,
) -> Result<LlmProviderRecord, LlmProvidersApiError> {
    let record = provider_create_record_with_auth(request)?;
    let now = Utc::now();
    Ok(LlmProviderRecord {
        id: uuid::Uuid::new_v4().to_string(),
        name: record.name,
        provider_type: record.provider_type,
        operation_type: record.operation_type,
        api_key_encrypted: record.api_key_plaintext,
        base_url: record.base_url,
        llm_model: record.llm_model,
        llm_small_model: record.llm_small_model,
        embedding_model: record.embedding_model,
        reranker_model: record.reranker_model,
        config: record.config,
        is_active: record.is_active,
        is_default: record.is_default,
        is_enabled: record.is_enabled,
        allowed_models: record.allowed_models,
        blocked_models: record.blocked_models,
        pool_weight: record.pool_weight,
        pool_enabled: record.pool_enabled,
        model_tier: record.model_tier,
        secondary_models: record.secondary_models,
        created_at: now,
        updated_at: now,
    })
}

fn apply_update_to_dev_record(record: &mut LlmProviderRecord, update: LlmProviderUpdateRecord) {
    let replace_model_fields = update.provider_type.is_some()
        || update.operation_type.is_some()
        || update.config.is_some();
    if let Some(value) = update.name {
        record.name = value;
    }
    if let Some(value) = update.provider_type {
        record.provider_type = value;
    }
    if let Some(value) = update.operation_type {
        record.operation_type = value;
    }
    if let Some(value) = update.api_key_plaintext {
        record.api_key_encrypted = value;
    }
    if let Some(value) = update.base_url {
        record.base_url = value;
    }
    if replace_model_fields || update.llm_model.is_some() {
        record.llm_model = update.llm_model;
    }
    if replace_model_fields || update.llm_small_model.is_some() {
        record.llm_small_model = update.llm_small_model;
    }
    if replace_model_fields || update.embedding_model.is_some() {
        record.embedding_model = update.embedding_model;
    }
    if replace_model_fields || update.reranker_model.is_some() {
        record.reranker_model = update.reranker_model;
    }
    if let Some(value) = update.config {
        record.config = value;
    }
    if let Some(value) = update.is_active {
        record.is_active = value;
    }
    if let Some(value) = update.is_default {
        record.is_default = value;
    }
    if let Some(value) = update.is_enabled {
        record.is_enabled = value;
    }
    if let Some(value) = update.allowed_models {
        record.allowed_models = value;
    }
    if let Some(value) = update.blocked_models {
        record.blocked_models = value;
    }
    if let Some(value) = update.pool_weight {
        record.pool_weight = value;
    }
    if let Some(value) = update.pool_enabled {
        record.pool_enabled = value;
    }
    if replace_model_fields || update.model_tier.is_some() {
        record.model_tier = update.model_tier;
    }
    if let Some(value) = update.secondary_models {
        record.secondary_models = value;
    }
    let next_revision = Utc::now()
        .timestamp_micros()
        .max(record.updated_at.timestamp_micros().saturating_add(1));
    record.updated_at = DateTime::from_timestamp_micros(next_revision).unwrap_or_else(Utc::now);
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct EnvProviderConfig {
    provider_type: String,
    operation_type: String,
    api_key: Option<String>,
    base_url: Option<String>,
    llm_model: Option<String>,
    llm_small_model: Option<String>,
    embedding_model: Option<String>,
    reranker_model: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct EnvProviderView {
    provider_type: String,
    operation_type: String,
    credential_source: &'static str,
    credential_configured: bool,
    environment_variable: Option<String>,
    base_url: Option<String>,
    llm_model: Option<String>,
    llm_small_model: Option<String>,
    embedding_model: Option<String>,
    reranker_model: Option<String>,
}

impl EnvProviderView {
    fn from_detected(config: EnvProviderConfig, environment_variable: &str) -> Self {
        let provider_type = catalog_provider_key(&config.provider_type);
        let endpoint_is_official_safe =
            environment_credential_endpoint_is_official(&provider_type, config.base_url.as_deref());
        let credential_configured = provider_requires_api_key(&provider_type)
            && endpoint_is_official_safe
            && config
                .api_key
                .as_deref()
                .is_some_and(|api_key| !api_key.is_empty());
        let base_url = endpoint_is_official_safe
            .then_some(config.base_url)
            .flatten();
        Self {
            provider_type: config.provider_type,
            operation_type: config.operation_type,
            credential_source: "environment",
            credential_configured,
            environment_variable: credential_configured.then(|| environment_variable.to_string()),
            base_url,
            llm_model: config.llm_model,
            llm_small_model: config.llm_small_model,
            embedding_model: config.embedding_model,
            reranker_model: config.reranker_model,
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, PartialEq, Eq)]
struct CategorizedProviderModels {
    chat: Vec<String>,
    embedding: Vec<String>,
    rerank: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    vision: Option<Vec<String>>,
}

#[derive(Debug)]
struct ModelCatalog {
    models: Vec<ModelMetadataView>,
}

impl ModelCatalog {
    fn load_embedded() -> Self {
        serde_json::from_str::<Snapshot>(MODEL_SNAPSHOT_JSON)
            .map(|snapshot| Self {
                models: snapshot.models.0,
            })
            .unwrap_or_else(|_| Self { models: Vec::new() })
    }

    fn list_models(&self, query: &CatalogListQuery) -> CatalogListResponse {
        let include_deprecated = query.include_deprecated.unwrap_or(false);
        let models = self
            .models
            .iter()
            .filter(|model| provider_matches(model, query.provider.as_deref()))
            .filter(|model| include_deprecated || !model.is_deprecated)
            .cloned()
            .collect::<Vec<_>>();
        CatalogListResponse {
            total: models.len(),
            models,
        }
    }

    fn search_models(&self, query: ValidatedCatalogSearchQuery) -> CatalogSearchResponse {
        let needle = query.q.to_lowercase();
        let models = self
            .models
            .iter()
            .filter(|model| provider_matches(model, query.provider.as_deref()))
            .filter(|model| model.matches_query(&needle))
            .take(query.limit)
            .cloned()
            .collect::<Vec<_>>();
        CatalogSearchResponse {
            query: query.q,
            total: models.len(),
            models,
        }
    }

    fn provider_models(&self, provider_type: &str) -> ProviderModelsResponse {
        let provider_key = catalog_provider_key(provider_type);
        let mut categorized = CategorizedProviderModels::default();
        for model in self
            .models
            .iter()
            .filter(|model| provider_matches(model, Some(provider_key.as_str())))
            .filter(|model| !model.is_deprecated)
        {
            let capabilities = model
                .capabilities
                .iter()
                .map(|capability| capability.to_lowercase())
                .collect::<BTreeSet<_>>();
            if capabilities.contains("embedding") {
                categorized.embedding.push(model.name.clone());
            } else if capabilities.contains("rerank") || capabilities.contains("reranking") {
                categorized.rerank.push(model.name.clone());
            } else if capabilities.contains("chat") || capabilities.contains("completion") {
                categorized.chat.push(model.name.clone());
            }
        }

        categorized.chat.sort();
        categorized.embedding.sort();
        categorized.rerank.sort();
        if !categorized.chat.is_empty()
            || !categorized.embedding.is_empty()
            || !categorized.rerank.is_empty()
        {
            return ProviderModelsResponse {
                provider_type: provider_type.to_string(),
                models: categorized,
                source: Some("models.dev"),
            };
        }

        ProviderModelsResponse {
            provider_type: provider_type.to_string(),
            models: static_provider_models(provider_type),
            source: static_provider_models_source(provider_type),
        }
    }
}

fn model_catalog() -> &'static ModelCatalog {
    static CATALOG: OnceLock<ModelCatalog> = OnceLock::new();
    CATALOG.get_or_init(ModelCatalog::load_embedded)
}

fn provider_matches(model: &ModelMetadataView, provider: Option<&str>) -> bool {
    provider.is_none_or(|provider| model.provider.as_deref() == Some(provider))
}

fn catalog_provider_key(provider_type: &str) -> String {
    let mut normalized = provider_type.trim().to_lowercase();
    for suffix in ["_coding", "_embedding", "_reranker"] {
        if normalized.ends_with(suffix) {
            normalized.truncate(normalized.len() - suffix.len());
            break;
        }
    }
    normalized
}

fn static_provider_models_source(provider_type: &str) -> Option<&'static str> {
    match provider_type {
        "openai" | "openrouter" | "dashscope" | "zai" | "kimi" | "ollama" | "lmstudio"
        | "gemini" | "anthropic" | "groq" | "deepseek" | "minimax" | "cohere" | "mistral"
        | "azure_openai" | "bedrock" | "vertex" | "volcengine" => Some("static-fallback"),
        _ => None,
    }
}

fn static_provider_models(provider_type: &str) -> CategorizedProviderModels {
    let mut models = match provider_type {
        "openai" => CategorizedProviderModels {
            chat: vecs(&["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]),
            embedding: vecs(&["text-embedding-3-small", "text-embedding-3-large"]),
            rerank: Vec::new(),
            vision: None,
        },
        "openrouter" => CategorizedProviderModels {
            chat: vecs(&[
                "openai/gpt-4o",
                "openai/gpt-4o-mini",
                "anthropic/claude-3.5-sonnet",
            ]),
            embedding: vecs(&["openai/text-embedding-3-small"]),
            rerank: Vec::new(),
            vision: None,
        },
        "dashscope" => CategorizedProviderModels {
            chat: vecs(&["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long"]),
            embedding: vecs(&["text-embedding-v3", "text-embedding-v2"]),
            rerank: vecs(&["qwen3-rerank"]),
            vision: None,
        },
        "zai" => CategorizedProviderModels {
            chat: vecs(&["glm-4-plus", "glm-4-flash", "glm-4-air"]),
            embedding: vecs(&["embedding-3", "embedding-2"]),
            rerank: Vec::new(),
            vision: None,
        },
        "kimi" => CategorizedProviderModels {
            chat: vecs(&["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]),
            embedding: vecs(&["kimi-embedding-1"]),
            rerank: vecs(&["kimi-rerank-1"]),
            vision: None,
        },
        "ollama" => CategorizedProviderModels {
            chat: vecs(&["llama3.1:8b", "qwen2.5:7b", "mistral-nemo"]),
            embedding: vecs(&["nomic-embed-text"]),
            rerank: Vec::new(),
            vision: None,
        },
        "lmstudio" => CategorizedProviderModels {
            chat: vecs(&["local-model"]),
            embedding: vecs(&["text-embedding-nomic-embed-text-v1.5"]),
            rerank: Vec::new(),
            vision: None,
        },
        "gemini" => CategorizedProviderModels {
            chat: vecs(&[
                "gemini-1.5-pro",
                "gemini-1.5-flash",
                "gemini-1.5-pro-002",
                "gemini-1.5-flash-002",
            ]),
            embedding: vecs(&["text-embedding-004"]),
            rerank: Vec::new(),
            vision: None,
        },
        "anthropic" => CategorizedProviderModels {
            chat: vecs(&[
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ]),
            embedding: Vec::new(),
            rerank: Vec::new(),
            vision: None,
        },
        "groq" => CategorizedProviderModels {
            chat: vecs(&[
                "llama-3.3-70b-versatile",
                "llama-3.1-70b-versatile",
                "mixtral-8x7b-32768",
                "llama-3.1-8b-instant",
            ]),
            embedding: Vec::new(),
            rerank: Vec::new(),
            vision: None,
        },
        "deepseek" => CategorizedProviderModels {
            chat: vecs(&["deepseek-chat", "deepseek-coder"]),
            embedding: Vec::new(),
            rerank: Vec::new(),
            vision: None,
        },
        "minimax" => CategorizedProviderModels {
            chat: vecs(&["abab6.5-chat", "abab6.5s-chat", "MiniMax-Text-01"]),
            embedding: vecs(&["embo-01"]),
            rerank: Vec::new(),
            vision: None,
        },
        "cohere" => CategorizedProviderModels {
            chat: vecs(&["command-r-plus", "command-r"]),
            embedding: vecs(&["embed-english-v3.0", "embed-multilingual-v3.0"]),
            rerank: vecs(&["rerank-english-v3.0", "rerank-multilingual-v3.0"]),
            vision: None,
        },
        "mistral" => CategorizedProviderModels {
            chat: vecs(&[
                "mistral-large-latest",
                "mistral-medium-latest",
                "mistral-small-latest",
            ]),
            embedding: vecs(&["mistral-embed"]),
            rerank: Vec::new(),
            vision: None,
        },
        "azure_openai" => CategorizedProviderModels {
            chat: vecs(&["gpt-4o", "gpt-4", "gpt-4o-mini", "gpt-35-turbo"]),
            embedding: vecs(&["text-embedding-3-small", "text-embedding-ada-002"]),
            rerank: Vec::new(),
            vision: None,
        },
        "bedrock" => CategorizedProviderModels {
            chat: vecs(&[
                "anthropic.claude-3-sonnet-20240229-v1:0",
                "anthropic.claude-3-haiku-20240307-v1:0",
                "meta.llama3-70b-instruct-v1:0",
            ]),
            embedding: vecs(&["amazon.titan-embed-text-v1", "amazon.titan-embed-text-v2:0"]),
            rerank: Vec::new(),
            vision: None,
        },
        "vertex" => CategorizedProviderModels {
            chat: vecs(&["gemini-1.5-pro", "gemini-1.5-flash"]),
            embedding: vecs(&["textembedding-gecko"]),
            rerank: Vec::new(),
            vision: None,
        },
        "volcengine" => CategorizedProviderModels {
            chat: vecs(&[
                "doubao-seed-2.0-pro",
                "doubao-seed-2.0-lite",
                "doubao-seed-2.0-mini",
                "doubao-seed-2.0-code",
                "doubao-1.5-pro-32k",
                "doubao-1.5-pro-128k",
                "doubao-1.5-pro-256k",
                "doubao-1.5-lite-32k",
                "doubao-1.5-lite-128k",
                "doubao-pro-32k",
                "doubao-pro-128k",
                "doubao-pro-256k",
                "doubao-lite-32k",
                "doubao-lite-128k",
            ]),
            embedding: vecs(&[
                "doubao-embedding",
                "doubao-embedding-large",
                "doubao-embedding-large-text-240915",
                "doubao-embedding-large-text-250515",
                "doubao-embedding-text-240715",
            ]),
            rerank: vecs(&["doubao-reranker-large"]),
            vision: Some(vecs(&[
                "doubao-1.5-vision-pro-32k",
                "doubao-1.5-vision-pro-128k",
                "doubao-vision-pro-32k",
                "doubao-vision-pro-128k",
                "doubao-vision-lite-32k",
            ])),
        },
        _ => CategorizedProviderModels::default(),
    };
    models.chat.shrink_to_fit();
    models.embedding.shrink_to_fit();
    models.rerank.shrink_to_fit();
    if let Some(vision) = models.vision.as_mut() {
        vision.shrink_to_fit();
    }
    models
}

fn vecs(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_string()).collect()
}

const ENV_PROVIDER_AUTO_DETECT: &[(&str, &str)] = &[
    ("GOOGLE_API_KEY", "gemini"),
    ("GOOGLE_GENERATIVE_AI_API_KEY", "gemini"),
    ("GEMINI_API_KEY", "gemini"),
    ("DASHSCOPE_API_KEY", "dashscope"),
    ("OPENAI_API_KEY", "openai"),
    ("OPENROUTER_API_KEY", "openrouter"),
    ("DEEPSEEK_API_KEY", "deepseek"),
    ("MINIMAX_API_KEY", "minimax"),
    ("ZAI_API_KEY", "zai"),
    ("ZHIPU_API_KEY", "zai"),
    ("MOONSHOT_API_KEY", "kimi"),
    ("KIMI_API_KEY", "kimi"),
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("OLLAMA_BASE_URL", "ollama"),
    ("LMSTUDIO_BASE_URL", "lmstudio"),
    ("VOLCENGINE_API_KEY", "volcengine"),
    ("ARK_API_KEY", "volcengine"),
];

fn detect_env_provider_configs() -> EnvDetectionResponse {
    detect_env_provider_configs_with(|name| std::env::var(name).ok())
}

fn validate_provider_id(provider_id: &str) -> Result<String, LlmProvidersApiError> {
    uuid::Uuid::parse_str(provider_id)
        .map(|uuid| uuid.to_string())
        .map_err(|_| LlmProvidersApiError::unprocessable("Invalid provider ID"))
}

fn provider_create_record(
    request: ProviderCreateRequest,
) -> Result<LlmProviderCreateRecord, LlmProvidersApiError> {
    let name = normalize_required_name(request.name)?;
    let provider_type = normalize_provider_type(request.provider_type)?;
    validate_persisted_provider_base_url(&provider_type, request.base_url.as_deref())
        .map_err(LlmProvidersApiError::unprocessable)?;
    let operation_type = effective_operation_type(&provider_type, request.operation_type)?;
    let api_key_plaintext = storable_api_key(&provider_type, request.api_key)?;
    validate_required_model(
        &operation_type,
        request.llm_model.as_deref(),
        request.embedding_model.as_deref(),
        request.embedding_config.as_ref(),
        request.reranker_model.as_deref(),
    )?;
    let mut config = request.config.unwrap_or_else(|| json!({}));
    let embedding_payload = build_embedding_payload(
        request.embedding_model.as_deref(),
        request.embedding_config.as_ref(),
    );
    apply_embedding_payload(&operation_type, &mut config, embedding_payload.as_ref());
    let (
        llm_model,
        llm_small_model,
        embedding_model,
        reranker_model,
        pool_enabled,
        model_tier,
        secondary_models,
    ) = separated_model_fields(ModelSeparationInput {
        operation_type: &operation_type,
        llm_model: request.llm_model,
        llm_small_model: request.llm_small_model,
        embedding_model: embedding_payload
            .as_ref()
            .and_then(|payload| payload.get("model"))
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .or(request.embedding_model),
        reranker_model: request.reranker_model,
        pool_enabled: request.pool_enabled.unwrap_or(true),
        model_tier: request.model_tier,
        secondary_models: request.secondary_models.unwrap_or_default(),
    });
    validate_model_tier(model_tier.as_deref())?;
    validate_pool_weight(request.pool_weight)?;
    Ok(LlmProviderCreateRecord {
        name,
        provider_type,
        operation_type,
        api_key_plaintext,
        base_url: request.base_url,
        llm_model,
        llm_small_model,
        embedding_model,
        reranker_model,
        config,
        is_active: request.is_active.unwrap_or(true),
        is_default: request.is_default.unwrap_or(false),
        is_enabled: request.is_enabled.unwrap_or(true),
        allowed_models: request.allowed_models.unwrap_or_default(),
        blocked_models: request.blocked_models.unwrap_or_default(),
        pool_weight: request.pool_weight.unwrap_or(1.0),
        pool_enabled,
        model_tier,
        secondary_models,
    })
}

fn provider_create_record_with_auth(
    mut request: ProviderCreateRequest,
) -> Result<LlmProviderCreateRecord, LlmProvidersApiError> {
    let provider_type = normalize_provider_type(request.provider_type.clone())?;
    let auth_method = validate_provider_auth_method(
        &provider_type,
        request.auth_method.as_deref(),
        provider_auth_method(&provider_type),
    )?;
    let submitted_api_key = request
        .api_key
        .as_deref()
        .is_some_and(|value| !value.trim().is_empty());
    let submitted_environment_variable = request
        .environment_variable
        .as_deref()
        .is_some_and(|value| !value.trim().is_empty());
    let environment_variable = match auth_method {
        "api_key" => {
            if submitted_environment_variable {
                return Err(LlmProvidersApiError::unprocessable(
                    "Environment variable requires environment authentication",
                ));
            }
            None
        }
        "environment" => {
            if submitted_api_key {
                return Err(LlmProvidersApiError::unprocessable(
                    "API key cannot be combined with environment authentication",
                ));
            }
            let environment_variable =
                validate_environment_variable(&provider_type, request.environment_variable.take())?;
            if !environment_credential_endpoint_is_official(
                &provider_type,
                request.base_url.as_deref(),
            ) {
                return Err(LlmProvidersApiError::unprocessable(
                    "Environment credentials require the official provider endpoint",
                ));
            }
            request.api_key = Some(LOCAL_NO_API_KEY_SENTINEL.to_string());
            Some(environment_variable)
        }
        "none" => {
            if submitted_api_key || submitted_environment_variable {
                return Err(LlmProvidersApiError::unprocessable(
                    "No-auth providers cannot accept credential fields",
                ));
            }
            request.api_key = None;
            None
        }
        _ => {
            return Err(LlmProvidersApiError::unprocessable(
                "Authentication method is not supported for this provider type",
            ));
        }
    };
    let mut config = request
        .config
        .take()
        .map(|config| validate_writable_provider_config(&config))
        .transpose()?
        .unwrap_or_else(|| json!({}));
    request.embedding_config = request
        .embedding_config
        .take()
        .map(|config| validate_writable_embedding_config(&config))
        .transpose()?;
    apply_provider_auth_metadata(&mut config, auth_method, environment_variable.as_deref());
    request.config = Some(config);
    provider_create_record(request)
}

fn provider_update_record_with_auth(
    existing: &LlmProviderRecord,
    mut request: ProviderUpdateRequest,
) -> Result<LlmProviderUpdateRecord, LlmProvidersApiError> {
    let provider_type = match request.provider_type.as_ref() {
        Some(value) => normalize_provider_type(value.clone())?,
        None => existing.provider_type.clone(),
    };
    let existing_auth_method =
        configured_provider_auth_method(&existing.provider_type, &existing.config);
    let provider_type_changed = provider_type != existing.provider_type;
    let fallback_auth_method = if provider_type_changed {
        provider_auth_method(&provider_type)
    } else {
        existing_auth_method
    };
    let auth_method = validate_provider_auth_method(
        &provider_type,
        request.auth_method.as_deref(),
        fallback_auth_method,
    )?;
    let submitted_api_key = request
        .api_key
        .as_deref()
        .is_some_and(|value| !value.trim().is_empty());
    let submitted_environment_variable = request
        .environment_variable
        .as_deref()
        .is_some_and(|value| !value.trim().is_empty());
    let environment_variable = match auth_method {
        "api_key" => {
            if submitted_environment_variable {
                return Err(LlmProvidersApiError::unprocessable(
                    "Environment variable requires environment authentication",
                ));
            }
            if existing_auth_method != "api_key" && !submitted_api_key {
                return Err(LlmProvidersApiError::bad_request(
                    "API key is required when changing authentication method",
                ));
            }
            None
        }
        "environment" => {
            if submitted_api_key {
                return Err(LlmProvidersApiError::unprocessable(
                    "API key cannot be combined with environment authentication",
                ));
            }
            let environment_variable = request.environment_variable.take().or_else(|| {
                (!provider_type_changed && existing_auth_method == "environment")
                    .then(|| configured_environment_variable(&provider_type, &existing.config))
                    .flatten()
            });
            let environment_variable =
                validate_environment_variable(&provider_type, environment_variable)?;
            let effective_base_url = match request.normalized_base_url_update() {
                Some(value) => value,
                None => existing.base_url.as_deref(),
            };
            if !environment_credential_endpoint_is_official(&provider_type, effective_base_url) {
                return Err(LlmProvidersApiError::unprocessable(
                    "Environment credentials require the official provider endpoint",
                ));
            }
            request.api_key = Some(LOCAL_NO_API_KEY_SENTINEL.to_string());
            Some(environment_variable)
        }
        "none" => {
            if submitted_api_key || submitted_environment_variable {
                return Err(LlmProvidersApiError::unprocessable(
                    "No-auth providers cannot accept credential fields",
                ));
            }
            request.api_key = Some(LOCAL_NO_API_KEY_SENTINEL.to_string());
            None
        }
        _ => {
            return Err(LlmProvidersApiError::unprocessable(
                "Authentication method is not supported for this provider type",
            ));
        }
    };
    let mut config = merge_writable_provider_config(&existing.config, request.config.take())?;
    request.embedding_config = request
        .embedding_config
        .take()
        .map(|config| validate_writable_embedding_config(&config))
        .transpose()?;
    apply_provider_auth_metadata(&mut config, auth_method, environment_variable.as_deref());
    request.config = Some(config);
    provider_update_record(existing, request)
}

fn provider_update_record(
    existing: &LlmProviderRecord,
    request: ProviderUpdateRequest,
) -> Result<LlmProviderUpdateRecord, LlmProvidersApiError> {
    if existing.updated_at.timestamp_micros() != request.expected_revision {
        return Err(LlmProvidersApiError::conflict(
            "Provider configuration changed; reload and try again",
        ));
    }
    let expected_updated_at = DateTime::from_timestamp_micros(request.expected_revision)
        .ok_or_else(|| LlmProvidersApiError::bad_request("Invalid provider revision"))?;
    let provider_type = match request.provider_type.as_ref() {
        Some(value) => normalize_provider_type(value.clone())?,
        None => existing.provider_type.clone(),
    };
    let base_url_update = request
        .normalized_base_url_update()
        .map(|value| value.map(ToOwned::to_owned));
    if let Some(Some(base_url)) = &base_url_update {
        validate_persisted_provider_base_url(&provider_type, Some(base_url))
            .map_err(LlmProvidersApiError::unprocessable)?;
    }
    let provider_type_changed = provider_type != existing.provider_type;
    let base_url_changed = base_url_update
        .as_ref()
        .is_some_and(|base_url| existing.base_url.as_ref() != base_url.as_ref());
    let api_key_submitted = request
        .api_key
        .as_deref()
        .is_some_and(|api_key| !api_key.trim().is_empty());
    if provider_requires_api_key(&provider_type)
        && (provider_type_changed || base_url_changed)
        && !api_key_submitted
    {
        return Err(LlmProvidersApiError::bad_request(
            "API key must be resubmitted when changing provider type or base URL",
        ));
    }
    let operation_type = effective_operation_type(&provider_type, request.operation_type.clone())?;
    let mut config = request.config.unwrap_or_else(|| existing.config.clone());
    let replace_embedding_public_config = request.embedding_config.is_some();
    let embedding_payload = match request.embedding_config.as_ref() {
        Some(_) => build_embedding_payload(
            request.embedding_model.as_deref(),
            request.embedding_config.as_ref(),
        ),
        None if request.embedding_model.is_some() => {
            let mut existing_embedding = config
                .get("embedding")
                .and_then(Value::as_object)
                .map(|object| Value::Object(object.clone()))
                .unwrap_or_else(|| json!({}));
            if let Some(model) = request.embedding_model.as_deref() {
                existing_embedding["model"] = json!(model);
            }
            Some(existing_embedding)
        }
        None => extract_embedding_config(&config),
    };
    apply_embedding_update(
        &operation_type,
        &mut config,
        embedding_payload.as_ref(),
        replace_embedding_public_config,
    );
    let (
        llm_model,
        llm_small_model,
        embedding_model,
        reranker_model,
        pool_enabled,
        model_tier,
        secondary_models,
    ) = separated_model_fields(ModelSeparationInput {
        operation_type: &operation_type,
        llm_model: request.llm_model.or_else(|| existing.llm_model.clone()),
        llm_small_model: request
            .llm_small_model
            .or_else(|| existing.llm_small_model.clone()),
        embedding_model: embedding_payload
            .as_ref()
            .and_then(|payload| payload.get("model"))
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .or(request.embedding_model)
            .or_else(|| existing.embedding_model.clone()),
        reranker_model: request
            .reranker_model
            .or_else(|| existing.reranker_model.clone()),
        pool_enabled: request.pool_enabled.unwrap_or(existing.pool_enabled),
        model_tier: request.model_tier.or_else(|| existing.model_tier.clone()),
        secondary_models: request
            .secondary_models
            .clone()
            .unwrap_or_else(|| existing.secondary_models.clone()),
    });
    validate_model_tier(model_tier.as_deref())?;
    validate_pool_weight(request.pool_weight)?;
    let api_key_plaintext = if provider_type_changed && !provider_requires_api_key(&provider_type) {
        Some(LOCAL_NO_API_KEY_SENTINEL.to_string())
    } else {
        request
            .api_key
            .map(|api_key| storable_api_key(&provider_type, Some(api_key)))
            .transpose()?
    };
    Ok(LlmProviderUpdateRecord {
        expected_updated_at,
        name: request.name.map(normalize_required_name).transpose()?,
        provider_type: Some(provider_type),
        operation_type: Some(operation_type),
        api_key_plaintext,
        base_url: base_url_update,
        llm_model,
        llm_small_model,
        embedding_model,
        reranker_model,
        config: Some(config),
        is_active: request.is_active,
        is_default: request.is_default,
        is_enabled: request.is_enabled,
        allowed_models: request.allowed_models,
        blocked_models: request.blocked_models,
        pool_weight: request.pool_weight,
        pool_enabled: Some(pool_enabled),
        model_tier,
        secondary_models: Some(secondary_models),
    })
}

type SeparatedModelFields = (
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
    bool,
    Option<String>,
    Vec<String>,
);

struct ModelSeparationInput<'a> {
    operation_type: &'a str,
    llm_model: Option<String>,
    llm_small_model: Option<String>,
    embedding_model: Option<String>,
    reranker_model: Option<String>,
    pool_enabled: bool,
    model_tier: Option<String>,
    secondary_models: Vec<String>,
}

fn separated_model_fields(input: ModelSeparationInput<'_>) -> SeparatedModelFields {
    match input.operation_type {
        "llm" => (
            input.llm_model,
            input.llm_small_model,
            None,
            None,
            input.pool_enabled,
            input.model_tier,
            input.secondary_models,
        ),
        "embedding" => (
            None,
            None,
            input.embedding_model,
            None,
            false,
            None,
            Vec::new(),
        ),
        "rerank" => (
            None,
            None,
            None,
            input.reranker_model,
            false,
            None,
            Vec::new(),
        ),
        _ => (None, None, None, None, false, None, Vec::new()),
    }
}

fn normalize_required_name(value: String) -> Result<String, LlmProvidersApiError> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        Err(LlmProvidersApiError::bad_request(
            "Invalid provider request",
        ))
    } else {
        Ok(trimmed.to_string())
    }
}

fn normalize_provider_type(value: String) -> Result<String, LlmProvidersApiError> {
    let normalized = value.trim().to_lowercase();
    if PROVIDER_TYPES.contains(&normalized.as_str()) {
        Ok(normalized)
    } else {
        Err(LlmProvidersApiError::bad_request(
            "Invalid provider request",
        ))
    }
}

fn effective_operation_type(
    provider_type: &str,
    requested: Option<String>,
) -> Result<String, LlmProvidersApiError> {
    let inferred = inferred_operation_type(provider_type);
    if inferred != "llm" {
        return Ok(inferred.to_string());
    }
    match validate_operation_type(requested)? {
        Some(value) => Ok(value),
        None => Ok("llm".to_string()),
    }
}

fn inferred_operation_type(provider_type: &str) -> &'static str {
    if provider_type.ends_with("_embedding") {
        "embedding"
    } else if provider_type.ends_with("_reranker") {
        "rerank"
    } else {
        "llm"
    }
}

fn storable_api_key(
    provider_type: &str,
    api_key: Option<String>,
) -> Result<String, LlmProvidersApiError> {
    let normalized = api_key.unwrap_or_default().trim().to_string();
    if !normalized.is_empty() {
        return Ok(normalized);
    }
    if matches!(provider_type, "ollama" | "lmstudio") {
        return Ok(LOCAL_NO_API_KEY_SENTINEL.to_string());
    }
    Err(LlmProvidersApiError::bad_request(
        "Invalid provider request",
    ))
}

fn validate_required_model(
    operation_type: &str,
    llm_model: Option<&str>,
    embedding_model: Option<&str>,
    embedding_config: Option<&Value>,
    reranker_model: Option<&str>,
) -> Result<(), LlmProvidersApiError> {
    let valid = match operation_type {
        "llm" => llm_model.is_some_and(|value| !value.trim().is_empty()),
        "embedding" => {
            embedding_model.is_some_and(|value| !value.trim().is_empty())
                || embedding_config
                    .and_then(|value| value.get("model"))
                    .and_then(Value::as_str)
                    .is_some_and(|value| !value.trim().is_empty())
        }
        "rerank" => reranker_model.is_some_and(|value| !value.trim().is_empty()),
        _ => false,
    };
    if valid {
        Ok(())
    } else {
        Err(LlmProvidersApiError::bad_request(
            "Invalid provider request",
        ))
    }
}

fn validate_model_tier(model_tier: Option<&str>) -> Result<(), LlmProvidersApiError> {
    match model_tier {
        Some("small" | "medium" | "large") | None => Ok(()),
        Some(_) => Err(LlmProvidersApiError::bad_request(
            "Invalid provider request",
        )),
    }
}

fn validate_pool_weight(pool_weight: Option<f64>) -> Result<(), LlmProvidersApiError> {
    match pool_weight {
        Some(value) if value < 0.0 => Err(LlmProvidersApiError::bad_request(
            "Invalid provider request",
        )),
        _ => Ok(()),
    }
}

fn build_embedding_payload(
    embedding_model: Option<&str>,
    embedding_config: Option<&Value>,
) -> Option<Value> {
    let mut payload = embedding_config.cloned().unwrap_or_else(|| json!({}));
    if let Some(model) = embedding_model {
        payload["model"] = json!(model);
    }
    payload
        .as_object()
        .is_some_and(|object| !object.is_empty())
        .then_some(payload)
}

fn apply_embedding_payload(operation_type: &str, config: &mut Value, payload: Option<&Value>) {
    if !config.is_object() {
        *config = json!({});
    }
    if operation_type == "embedding" {
        if let Some(payload) = payload.and_then(Value::as_object) {
            let config = config
                .as_object_mut()
                .expect("provider config was normalized to an object");
            let embedding = config
                .entry("embedding".to_string())
                .or_insert_with(|| json!({}));
            if !embedding.is_object() {
                *embedding = json!({});
            }
            let embedding = embedding
                .as_object_mut()
                .expect("embedding config was normalized to an object");
            for (key, value) in payload {
                if key == "provider_options" {
                    let Some(submitted_options) = value.as_object() else {
                        continue;
                    };
                    let mut provider_options = embedding
                        .get(key)
                        .and_then(Value::as_object)
                        .cloned()
                        .unwrap_or_default();
                    for (option_key, option_value) in submitted_options {
                        provider_options.insert(option_key.clone(), option_value.clone());
                    }
                    embedding.insert(key.clone(), Value::Object(provider_options));
                } else {
                    embedding.insert(key.clone(), value.clone());
                }
            }
        }
    } else if let Some(object) = config.as_object_mut() {
        object.remove("embedding");
    }
}

fn apply_embedding_update(
    operation_type: &str,
    config: &mut Value,
    payload: Option<&Value>,
    replace_public_fields: bool,
) {
    if operation_type == "embedding" && replace_public_fields {
        if !config.is_object() {
            *config = json!({});
        }
        strip_writable_embedding_fields(
            config
                .as_object_mut()
                .expect("provider config was normalized to an object"),
        );
    }
    apply_embedding_payload(operation_type, config, payload);
}

fn extract_embedding_config(config: &Value) -> Option<Value> {
    config
        .get("embedding")
        .filter(|value| value.is_object())
        .cloned()
}

fn mask_api_key(encrypted: &str) -> String {
    let plaintext = decrypt_provider_api_key_for_mask(encrypted).unwrap_or_else(|| {
        if encrypted == LOCAL_NO_API_KEY_SENTINEL {
            LOCAL_NO_API_KEY_SENTINEL.to_string()
        } else {
            encrypted.to_string()
        }
    });
    if plaintext == LOCAL_NO_API_KEY_SENTINEL {
        return "(local-no-key)".to_string();
    }
    if plaintext.len() <= 8 {
        "sk-***".to_string()
    } else {
        format!(
            "sk-{}...{}",
            &plaintext[..4],
            &plaintext[plaintext.len() - 4..]
        )
    }
}

fn default_resilience_status() -> Value {
    json!({
        "circuit_breaker_state": "closed",
        "failure_count": 0,
        "success_count": 0,
        "rate_limit": {
            "current_concurrent": 0,
            "max_concurrent": 50,
            "total_requests": 0,
            "requests_per_minute": 0,
            "max_rpm": null
        },
        "can_execute": true
    })
}

fn validate_operation_type(
    operation_type: Option<String>,
) -> Result<Option<String>, LlmProvidersApiError> {
    match operation_type {
        Some(operation_type) if OPERATION_TYPES.contains(&operation_type.as_str()) => {
            Ok(Some(operation_type))
        }
        Some(_) => Err(LlmProvidersApiError::unprocessable(
            "Invalid operation_type",
        )),
        None => Ok(None),
    }
}

fn detect_env_provider_configs_with<F>(lookup: F) -> EnvDetectionResponse
where
    F: Fn(&str) -> Option<String>,
{
    let mut detected_providers = BTreeMap::new();
    let mut seen_providers = BTreeSet::new();

    for (env_var, provider_name) in ENV_PROVIDER_AUTO_DETECT {
        if seen_providers.contains(provider_name) || !env_present(&lookup, env_var) {
            continue;
        }
        let Some(config) = provider_env_config(provider_name, &lookup) else {
            continue;
        };
        if provider_requires_api_key(provider_name)
            && config.api_key.as_deref().is_none_or(str::is_empty)
        {
            continue;
        }
        detected_providers.insert(
            (*provider_name).to_string(),
            EnvProviderView::from_detected(config, env_var),
        );
        seen_providers.insert(*provider_name);
    }

    EnvDetectionResponse { detected_providers }
}

fn provider_env_config<F>(provider_name: &str, lookup: &F) -> Option<EnvProviderConfig>
where
    F: Fn(&str) -> Option<String>,
{
    let config = match provider_name {
        "gemini" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: first_nonempty(
                lookup,
                &[
                    "GOOGLE_API_KEY",
                    "GOOGLE_GENERATIVE_AI_API_KEY",
                    "GEMINI_API_KEY",
                ],
            ),
            base_url: None,
            llm_model: env_default(lookup, "GEMINI_MODEL", "gemini-2.0-flash"),
            llm_small_model: None,
            embedding_model: env_default(lookup, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"),
            reranker_model: env_raw(lookup, "GEMINI_RERANK_MODEL"),
        },
        "zai" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: first_nonempty(lookup, &["ZAI_API_KEY", "ZHIPU_API_KEY"]),
            base_url: first_nonempty_or_env_default(
                lookup,
                &["ZAI_BASE_URL"],
                "ZHIPU_BASE_URL",
                "https://open.bigmodel.cn/api/paas/v4",
            ),
            llm_model: first_nonempty_or_env_default(
                lookup,
                &["ZAI_MODEL"],
                "ZHIPU_MODEL",
                "glm-5.1",
            ),
            llm_small_model: first_nonempty_or_env_default(
                lookup,
                &["ZAI_SMALL_MODEL"],
                "ZHIPU_SMALL_MODEL",
                "glm-4.7-flash",
            ),
            embedding_model: first_nonempty_or_env_default(
                lookup,
                &["ZAI_EMBEDDING_MODEL"],
                "ZHIPU_EMBEDDING_MODEL",
                "embedding-3",
            ),
            reranker_model: first_nonempty(lookup, &["ZAI_RERANK_MODEL", "ZHIPU_RERANK_MODEL"]),
        },
        "dashscope" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: env_nonempty(lookup, "DASHSCOPE_API_KEY"),
            base_url: env_default(
                lookup,
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            llm_model: env_default(lookup, "DASHSCOPE_MODEL", "qwen-plus"),
            llm_small_model: env_default(lookup, "DASHSCOPE_SMALL_MODEL", "qwen-turbo"),
            embedding_model: env_default(lookup, "DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v3"),
            reranker_model: env_raw(lookup, "DASHSCOPE_RERANK_MODEL"),
        },
        "openai" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: env_nonempty(lookup, "OPENAI_API_KEY"),
            base_url: env_raw(lookup, "OPENAI_BASE_URL"),
            llm_model: env_default(lookup, "OPENAI_MODEL", "gpt-4o"),
            llm_small_model: env_default(lookup, "OPENAI_SMALL_MODEL", "gpt-4o-mini"),
            embedding_model: env_default(
                lookup,
                "OPENAI_EMBEDDING_MODEL",
                "text-embedding-3-small",
            ),
            reranker_model: env_raw(lookup, "OPENAI_RERANK_MODEL"),
        },
        "openrouter" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: env_nonempty(lookup, "OPENROUTER_API_KEY"),
            base_url: env_default(
                lookup,
                "OPENROUTER_BASE_URL",
                "https://openrouter.ai/api/v1",
            ),
            llm_model: env_default(lookup, "OPENROUTER_MODEL", "openai/gpt-4o"),
            llm_small_model: env_default(lookup, "OPENROUTER_SMALL_MODEL", "openai/gpt-4o-mini"),
            embedding_model: env_default(
                lookup,
                "OPENROUTER_EMBEDDING_MODEL",
                "openai/text-embedding-3-small",
            ),
            reranker_model: env_raw(lookup, "OPENROUTER_RERANK_MODEL"),
        },
        "deepseek" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: env_nonempty(lookup, "DEEPSEEK_API_KEY"),
            base_url: env_default(lookup, "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            llm_model: env_default(lookup, "DEEPSEEK_MODEL", "deepseek-chat"),
            llm_small_model: env_default(lookup, "DEEPSEEK_SMALL_MODEL", "deepseek-v4-flash"),
            embedding_model: None,
            reranker_model: env_raw(lookup, "DEEPSEEK_RERANK_MODEL"),
        },
        "minimax" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: env_nonempty(lookup, "MINIMAX_API_KEY"),
            base_url: env_default(lookup, "MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
            llm_model: env_default(lookup, "MINIMAX_MODEL", "MiniMax-M2.5"),
            llm_small_model: env_default(lookup, "MINIMAX_SMALL_MODEL", "MiniMax-M2.5-highspeed"),
            embedding_model: env_default(lookup, "MINIMAX_EMBEDDING_MODEL", "embo-01"),
            reranker_model: env_raw(lookup, "MINIMAX_RERANK_MODEL"),
        },
        "kimi" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: first_nonempty(lookup, &["MOONSHOT_API_KEY", "KIMI_API_KEY"]),
            base_url: env_default(lookup, "KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
            llm_model: first_nonempty_or_env_default(
                lookup,
                &["KIMI_MODEL"],
                "MOONSHOT_MODEL",
                "kimi-k2.5",
            ),
            llm_small_model: first_nonempty_or_env_default(
                lookup,
                &["KIMI_SMALL_MODEL"],
                "MOONSHOT_SMALL_MODEL",
                "kimi-k2.5",
            ),
            embedding_model: env_default(lookup, "KIMI_EMBEDDING_MODEL", "kimi-embedding-1"),
            reranker_model: env_raw(lookup, "KIMI_RERANK_MODEL"),
        },
        "anthropic" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: env_nonempty(lookup, "ANTHROPIC_API_KEY"),
            base_url: env_raw(lookup, "ANTHROPIC_BASE_URL"),
            llm_model: env_default(lookup, "ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620"),
            llm_small_model: env_default(
                lookup,
                "ANTHROPIC_SMALL_MODEL",
                "claude-3-haiku-20240307",
            ),
            embedding_model: env_default(lookup, "ANTHROPIC_EMBEDDING_MODEL", ""),
            reranker_model: env_raw(lookup, "ANTHROPIC_RERANK_MODEL"),
        },
        "ollama" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: env_raw(lookup, "OLLAMA_API_KEY"),
            base_url: env_default(lookup, "OLLAMA_BASE_URL", "http://localhost:11434"),
            llm_model: env_default(lookup, "OLLAMA_MODEL", "llama3.1:8b"),
            llm_small_model: env_default(lookup, "OLLAMA_SMALL_MODEL", "llama3.1:8b"),
            embedding_model: env_default(lookup, "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
            reranker_model: env_raw(lookup, "OLLAMA_RERANK_MODEL"),
        },
        "lmstudio" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: env_raw(lookup, "LMSTUDIO_API_KEY"),
            base_url: env_default(lookup, "LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
            llm_model: env_default(lookup, "LMSTUDIO_MODEL", "local-model"),
            llm_small_model: env_default(lookup, "LMSTUDIO_SMALL_MODEL", "local-model"),
            embedding_model: env_default(
                lookup,
                "LMSTUDIO_EMBEDDING_MODEL",
                "text-embedding-nomic-embed-text-v1.5",
            ),
            reranker_model: env_raw(lookup, "LMSTUDIO_RERANK_MODEL"),
        },
        "volcengine" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: first_nonempty(lookup, &["VOLCENGINE_API_KEY", "ARK_API_KEY"]),
            base_url: env_default(
                lookup,
                "VOLCENGINE_BASE_URL",
                "https://ark.cn-beijing.volces.com/api/v3",
            ),
            llm_model: env_default(lookup, "VOLCENGINE_MODEL", "doubao-1.5-pro-32k"),
            llm_small_model: env_default(lookup, "VOLCENGINE_SMALL_MODEL", "doubao-1.5-lite-32k"),
            embedding_model: env_default(lookup, "VOLCENGINE_EMBEDDING_MODEL", "doubao-embedding"),
            reranker_model: env_raw(lookup, "VOLCENGINE_RERANK_MODEL"),
        },
        _ => return None,
    };
    Some(config)
}

fn provider_requires_api_key(provider_name: &str) -> bool {
    !matches!(provider_name, "ollama" | "lmstudio")
}

fn provider_environment_variables(provider_name: &str) -> &'static [&'static str] {
    match catalog_provider_key(provider_name).as_str() {
        "openai" => &["OPENAI_API_KEY"],
        "openrouter" => &["OPENROUTER_API_KEY"],
        "dashscope" => &["DASHSCOPE_API_KEY"],
        "gemini" => &[
            "GOOGLE_API_KEY",
            "GOOGLE_GENERATIVE_AI_API_KEY",
            "GEMINI_API_KEY",
        ],
        "anthropic" => &["ANTHROPIC_API_KEY"],
        "groq" => &["GROQ_API_KEY"],
        "mistral" => &["MISTRAL_API_KEY"],
        "deepseek" => &["DEEPSEEK_API_KEY"],
        "minimax" => &["MINIMAX_API_KEY"],
        "zai" => &["ZAI_API_KEY", "ZHIPU_API_KEY"],
        "kimi" => &["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "volcengine" => &["VOLCENGINE_API_KEY", "ARK_API_KEY"],
        _ => &[],
    }
}

fn provider_supports_environment(provider_name: &str) -> bool {
    !provider_environment_variables(provider_name).is_empty()
}

fn provider_supports_persisted_auth(provider_name: &str) -> bool {
    !matches!(
        catalog_provider_key(provider_name).as_str(),
        "bedrock" | "vertex"
    )
}

fn provider_auth_method(provider_name: &str) -> &'static str {
    if provider_requires_api_key(&catalog_provider_key(provider_name)) {
        "api_key"
    } else {
        "none"
    }
}

fn validate_provider_auth_method(
    provider_name: &str,
    requested: Option<&str>,
    fallback: &'static str,
) -> Result<&'static str, LlmProvidersApiError> {
    if !provider_supports_persisted_auth(provider_name) {
        return Err(LlmProvidersApiError::unprocessable(
            "Authentication is unavailable until structured credential storage is configured",
        ));
    }
    let method = requested
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(fallback);
    match method {
        "api_key" if provider_requires_api_key(&catalog_provider_key(provider_name)) => {
            Ok("api_key")
        }
        "environment" if provider_supports_environment(provider_name) => Ok("environment"),
        "none" if !provider_requires_api_key(&catalog_provider_key(provider_name)) => Ok("none"),
        _ => Err(LlmProvidersApiError::unprocessable(
            "Authentication method is not supported for this provider type",
        )),
    }
}

fn validate_environment_variable(
    provider_name: &str,
    environment_variable: Option<String>,
) -> Result<String, LlmProvidersApiError> {
    let environment_variable = environment_variable
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            LlmProvidersApiError::unprocessable(
                "Environment variable is required for environment authentication",
            )
        })?;
    if provider_environment_variables(provider_name).contains(&environment_variable.as_str()) {
        Ok(environment_variable)
    } else {
        Err(LlmProvidersApiError::unprocessable(
            "Environment variable is not supported for this provider type",
        ))
    }
}

fn configured_provider_auth_method(provider_name: &str, config: &Value) -> &'static str {
    validate_provider_auth_method(
        provider_name,
        config.get(AUTH_METHOD_CONFIG_KEY).and_then(Value::as_str),
        provider_auth_method(provider_name),
    )
    .unwrap_or_else(|_| provider_auth_method(provider_name))
}

fn configured_environment_variable(provider_name: &str, config: &Value) -> Option<String> {
    if configured_provider_auth_method(provider_name, config) != "environment" {
        return None;
    }
    validate_environment_variable(
        provider_name,
        config
            .get(ENVIRONMENT_VARIABLE_CONFIG_KEY)
            .and_then(Value::as_str)
            .map(str::to_string),
    )
    .ok()
}

fn apply_provider_auth_metadata(
    config: &mut Value,
    auth_method: &str,
    environment_variable: Option<&str>,
) {
    if !config.is_object() {
        *config = json!({});
    }
    let Some(object) = config.as_object_mut() else {
        return;
    };
    object.remove(AUTH_METHOD_CONFIG_KEY);
    object.remove(ENVIRONMENT_VARIABLE_CONFIG_KEY);
    if auth_method == "environment" {
        object.insert(
            AUTH_METHOD_CONFIG_KEY.to_string(),
            Value::String("environment".to_string()),
        );
        if let Some(environment_variable) = environment_variable {
            object.insert(
                ENVIRONMENT_VARIABLE_CONFIG_KEY.to_string(),
                Value::String(environment_variable.to_string()),
            );
        }
    }
}

fn environment_credential_with<F>(environment_variable: &str, lookup: &F) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    lookup(environment_variable).and_then(|value| {
        let trimmed = value.trim();
        (!trimmed.is_empty()).then(|| trimmed.to_string())
    })
}

fn env_present<F>(lookup: &F, name: &str) -> bool
where
    F: Fn(&str) -> Option<String>,
{
    lookup(name).is_some_and(|value| !value.is_empty())
}

fn env_raw<F>(lookup: &F, name: &str) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    lookup(name)
}

fn env_nonempty<F>(lookup: &F, name: &str) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    lookup(name).filter(|value| !value.is_empty())
}

fn env_default<F>(lookup: &F, name: &str, default: &str) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    Some(lookup(name).unwrap_or_else(|| default.to_string()))
}

fn first_nonempty<F>(lookup: &F, names: &[&str]) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    names.iter().find_map(|name| env_nonempty(lookup, name))
}

fn first_nonempty_or_env_default<F>(
    lookup: &F,
    nonempty_names: &[&str],
    default_name: &str,
    default: &str,
) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    first_nonempty(lookup, nonempty_names).or_else(|| env_default(lookup, default_name, default))
}

#[derive(Debug, Deserialize)]
struct Snapshot {
    #[allow(dead_code)]
    #[serde(default, rename = "_meta")]
    meta: Value,
    #[serde(default)]
    models: OrderedModels,
}

#[derive(Debug, Default)]
struct OrderedModels(Vec<ModelMetadataView>);

impl<'de> Deserialize<'de> for OrderedModels {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_map(OrderedModelsVisitor)
    }
}

struct OrderedModelsVisitor;

impl<'de> Visitor<'de> for OrderedModelsVisitor {
    type Value = OrderedModels;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a models object")
    }

    fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut models = Vec::with_capacity(map.size_hint().unwrap_or_default());
        while let Some((key, value)) = map.next_entry::<String, ModelMetadataView>()? {
            let mut model = value;
            if model.name.is_empty() {
                model.name = key;
            }
            model.coerce_python_bounds();
            models.push(model);
        }
        Ok(OrderedModels(models))
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct ModelMetadataView {
    #[serde(default)]
    name: String,
    #[serde(default = "default_context_length")]
    context_length: u64,
    #[serde(default = "default_max_output_tokens")]
    max_output_tokens: u64,
    #[serde(default)]
    input_cost_per_1m: Option<f64>,
    #[serde(default)]
    output_cost_per_1m: Option<f64>,
    #[serde(default)]
    capabilities: Vec<String>,
    #[serde(default = "default_true")]
    supports_streaming: bool,
    #[serde(default)]
    supports_json_mode: bool,
    #[serde(default)]
    provider: Option<String>,
    #[serde(default)]
    modalities: Vec<String>,
    #[serde(default)]
    variants: Vec<String>,
    #[serde(default)]
    default_variant: Option<String>,
    #[serde(default)]
    family: Option<String>,
    #[serde(default)]
    release_date: Option<String>,
    #[serde(default)]
    is_deprecated: bool,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    max_input_tokens: Option<u64>,
    #[serde(default)]
    reasoning: bool,
    #[serde(default = "default_true")]
    supports_temperature: bool,
    #[serde(default)]
    supports_tool_call: bool,
    #[serde(default)]
    supports_structured_output: bool,
    #[serde(default)]
    supports_attachment: bool,
    #[serde(default)]
    cache_read_cost_per_1m: Option<f64>,
    #[serde(default)]
    cache_write_cost_per_1m: Option<f64>,
    #[serde(default)]
    reasoning_cost_per_1m: Option<f64>,
    #[serde(default)]
    knowledge_cutoff: Option<String>,
    #[serde(default)]
    open_weights: bool,
    #[serde(default)]
    default_temperature: Option<f64>,
    #[serde(default)]
    default_top_p: Option<f64>,
    #[serde(default)]
    default_frequency_penalty: Option<f64>,
    #[serde(default)]
    default_presence_penalty: Option<f64>,
    #[serde(default)]
    default_seed: Option<i64>,
    #[serde(default)]
    default_stop: Option<Vec<String>>,
    #[serde(default)]
    supports_response_format: bool,
    #[serde(default)]
    supports_seed: bool,
    #[serde(default = "default_true")]
    supports_stop: bool,
    #[serde(default = "default_true")]
    supports_frequency_penalty: bool,
    #[serde(default = "default_true")]
    supports_presence_penalty: bool,
    #[serde(default = "default_true")]
    supports_top_p: bool,
    #[serde(default)]
    temperature_range: Option<Vec<f64>>,
    #[serde(default)]
    top_p_range: Option<Vec<f64>>,
    #[serde(default)]
    supported_params: Option<Vec<String>>,
}

impl ModelMetadataView {
    fn coerce_python_bounds(&mut self) {
        if self.max_output_tokens < 1 {
            self.max_output_tokens = default_max_output_tokens();
        }
        if self.context_length < 1024 {
            self.context_length = default_context_length();
        }
    }

    fn matches_query(&self, query: &str) -> bool {
        self.name.to_lowercase().contains(query)
            || self
                .family
                .as_deref()
                .is_some_and(|family| family.to_lowercase().contains(query))
            || self
                .provider
                .as_deref()
                .is_some_and(|provider| provider.to_lowercase().contains(query))
            || self
                .description
                .as_deref()
                .is_some_and(|description| description.to_lowercase().contains(query))
    }
}

fn default_context_length() -> u64 {
    128_000
}

fn default_max_output_tokens() -> u64 {
    4_096
}

fn default_true() -> bool {
    true
}

async fn ensure_admin_access(app: &AppState, user_id: &str) -> Result<(), LlmProvidersApiError> {
    let allowed = app
        .admin_access
        .user_has_admin_access(user_id)
        .await
        .map_err(LlmProvidersApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(LlmProvidersApiError::forbidden("Admin access required"))
    }
}

fn map_provider_mutation_error(error: LlmProviderMutationError) -> LlmProvidersApiError {
    match error {
        LlmProviderMutationError::NameConflict => {
            LlmProvidersApiError::conflict("Provider name already exists")
        }
        LlmProviderMutationError::Storage(error) => LlmProvidersApiError::internal(error),
    }
}

#[derive(Debug)]
pub(crate) struct LlmProvidersApiError {
    status: StatusCode,
    detail: String,
}

impl LlmProvidersApiError {
    fn not_found(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            detail: detail.into(),
        }
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::FORBIDDEN,
            detail: detail.into(),
        }
    }

    fn conflict(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::CONFLICT,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            detail: detail.into(),
        }
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::UNPROCESSABLE_ENTITY,
            detail: detail.into(),
        }
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            detail: detail.to_string(),
        }
    }
}

impl IntoResponse for LlmProvidersApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex as StdMutex;

    use axum::http::header::AUTHORIZATION;
    use axum::http::HeaderMap;
    use chrono::{TimeZone, Utc};
    use serde_json::Value;
    use tokio::net::TcpListener;

    use super::*;

    struct MockProviderServer {
        base_url: String,
        requests: Arc<StdMutex<Vec<HeaderMap>>>,
        task: tokio::task::JoinHandle<()>,
    }

    struct MockApiServer {
        base_url: String,
        task: tokio::task::JoinHandle<()>,
    }

    impl Drop for MockApiServer {
        fn drop(&mut self) {
            self.task.abort();
        }
    }

    impl Drop for MockProviderServer {
        fn drop(&mut self) {
            self.task.abort();
        }
    }

    async fn spawn_mock_provider(path: &'static str, status: StatusCode) -> MockProviderServer {
        let requests = Arc::new(StdMutex::new(Vec::new()));
        let captured_requests = Arc::clone(&requests);
        let app = Router::new().route(
            path,
            get(move |headers: HeaderMap| {
                let captured_requests = Arc::clone(&captured_requests);
                async move {
                    captured_requests
                        .lock()
                        .expect("request capture lock remains available")
                        .push(headers);
                    status
                }
            }),
        );
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("mock provider binds");
        let address = listener.local_addr().expect("mock provider has address");
        let task = tokio::spawn(async move {
            axum::serve(listener, app)
                .await
                .expect("mock provider serves requests");
        });
        MockProviderServer {
            base_url: format!("http://{address}"),
            requests,
            task,
        }
    }

    async fn unguarded_test_connection_route(
        Json(request): Json<ProviderProbeRequest>,
    ) -> Result<Json<ProviderValidationResponse>, LlmProvidersApiError> {
        execute_provider_connection_test(request).await.map(Json)
    }

    async fn spawn_test_connection_api() -> MockApiServer {
        let app = Router::new().route(
            "/api/v1/llm-providers/test-connection",
            axum::routing::post(unguarded_test_connection_route),
        );
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("test provider API binds");
        let address = listener
            .local_addr()
            .expect("test provider API has address");
        let task = tokio::spawn(async move {
            axum::serve(listener, app)
                .await
                .expect("test provider API serves requests");
        });
        MockApiServer {
            base_url: format!("http://{address}"),
            task,
        }
    }

    #[derive(Clone)]
    struct TestHealthCheckState {
        providers: SharedLlmProviders,
        health: SharedLlmProviderHealth,
    }

    async fn unguarded_persisted_health_check_route(
        State(state): State<TestHealthCheckState>,
        Path(provider_id): Path<String>,
    ) -> Result<Json<ProviderValidationResponse>, LlmProvidersApiError> {
        execute_persisted_provider_health_check(
            &state.providers,
            &state.health,
            "dev-user",
            &provider_id,
        )
        .await
        .map(Json)
    }

    async fn spawn_persisted_health_check_api(
        providers: SharedLlmProviders,
        health: SharedLlmProviderHealth,
    ) -> MockApiServer {
        let app = Router::new()
            .route(
                "/api/v1/llm-providers/:provider_id/health-check",
                axum::routing::post(unguarded_persisted_health_check_route),
            )
            .with_state(TestHealthCheckState { providers, health });
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("test persisted health API binds");
        let address = listener
            .local_addr()
            .expect("test persisted health API has address");
        let task = tokio::spawn(async move {
            axum::serve(listener, app)
                .await
                .expect("test persisted health API serves requests");
        });
        MockApiServer {
            base_url: format!("http://{address}"),
            task,
        }
    }

    async fn unguarded_persisted_health_read_route(
        State(state): State<TestHealthCheckState>,
        Path(provider_id): Path<String>,
    ) -> Result<Json<ProviderHealthResponse>, LlmProvidersApiError> {
        read_persisted_provider_health(&state.providers, &state.health, "dev-user", &provider_id)
            .await
            .map(Json)
    }

    async fn spawn_persisted_health_read_api(
        providers: SharedLlmProviders,
        health: SharedLlmProviderHealth,
    ) -> MockApiServer {
        let app = Router::new()
            .route(
                "/api/v1/llm-providers/:provider_id/health",
                get(unguarded_persisted_health_read_route),
            )
            .with_state(TestHealthCheckState { providers, health });
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("test persisted health read API binds");
        let address = listener
            .local_addr()
            .expect("test persisted health read API has address");
        let task = tokio::spawn(async move {
            axum::serve(listener, app)
                .await
                .expect("test persisted health read API serves requests");
        });
        MockApiServer {
            base_url: format!("http://{address}"),
            task,
        }
    }

    async fn post_test_connection(api: &MockApiServer, payload: Value) -> (StatusCode, Value) {
        let response = reqwest::Client::new()
            .post(format!(
                "{}/api/v1/llm-providers/test-connection",
                api.base_url
            ))
            .json(&payload)
            .send()
            .await
            .expect("test connection request succeeds");
        let status = response.status();
        let body = response
            .json::<Value>()
            .await
            .expect("test connection response is JSON");
        (status, body)
    }

    async fn post_persisted_health_check(
        api: &MockApiServer,
        provider_id: &str,
    ) -> (StatusCode, Value) {
        let response = reqwest::Client::new()
            .post(format!(
                "{}/api/v1/llm-providers/{provider_id}/health-check",
                api.base_url
            ))
            .send()
            .await
            .expect("persisted health check request succeeds");
        let status = response.status();
        let body = response
            .json::<Value>()
            .await
            .expect("persisted health check response is JSON");
        (status, body)
    }

    async fn get_persisted_health(api: &MockApiServer, provider_id: &str) -> (StatusCode, Value) {
        let response = reqwest::Client::new()
            .get(format!(
                "{}/api/v1/llm-providers/{provider_id}/health",
                api.base_url
            ))
            .send()
            .await
            .expect("persisted health read request succeeds");
        let status = response.status();
        let body = response
            .json::<Value>()
            .await
            .expect("persisted health read response is JSON");
        (status, body)
    }

    fn provider_create_request(
        provider_type: &str,
        base_url: String,
        api_key: Option<&str>,
        model: &str,
    ) -> ProviderCreateRequest {
        ProviderCreateRequest {
            name: format!("{provider_type}-test"),
            provider_type: provider_type.to_string(),
            operation_type: None,
            auth_method: None,
            environment_variable: None,
            api_key: api_key.map(str::to_string),
            base_url: Some(base_url),
            llm_model: Some(model.to_string()),
            llm_small_model: None,
            embedding_model: None,
            embedding_config: None,
            reranker_model: None,
            config: None,
            is_active: None,
            is_default: None,
            is_enabled: None,
            allowed_models: None,
            blocked_models: None,
            pool_weight: None,
            pool_enabled: None,
            model_tier: None,
            secondary_models: None,
        }
    }

    #[tokio::test]
    async fn provider_types_response_matches_python_descriptor_contract() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/llm_provider_types.json"))
                .expect("llm provider types golden must be valid JSON");

        let value =
            serde_json::to_value(list_provider_types().await.0).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn provider_name_conflict_maps_to_http_409_without_storage_details() {
        let error = map_provider_mutation_error(LlmProviderMutationError::NameConflict);
        assert_eq!(error.status, StatusCode::CONFLICT);
        assert_eq!(error.detail, "Provider name already exists");
    }

    #[tokio::test]
    async fn pg_provider_service_maps_name_conflicts_and_preserves_hidden_config() {
        const PROVIDER_NAME: &str = "llm_provider_server_security_contract";
        let Ok(database_url) = std::env::var("DATABASE_URL") else {
            eprintln!(
                "[skip] pg_provider_service_maps_name_conflicts_and_preserves_hidden_config: \
                 DATABASE_URL unset"
            );
            return;
        };
        if std::env::var("LLM_ENCRYPTION_KEY").is_err() {
            eprintln!(
                "[skip] pg_provider_service_maps_name_conflicts_and_preserves_hidden_config: \
                 LLM_ENCRYPTION_KEY unset"
            );
            return;
        }
        let pool = agistack_adapters_postgres::connect(&database_url)
            .await
            .expect("test database connection succeeds");
        sqlx::query("DELETE FROM llm_providers WHERE name = $1")
            .bind(PROVIDER_NAME)
            .execute(&pool)
            .await
            .expect("clean provider server security fixture");
        let service = PgLlmProviderCatalogService::new(PgLlmProviderRepository::new(pool.clone()));
        let request = || {
            serde_json::from_value::<ProviderCreateRequest>(json!({
                "name": PROVIDER_NAME,
                "provider_type": "openai",
                "api_key": "sk-server-security-test",
                "base_url": "https://api.openai.com/v1",
                "llm_model": "gpt-4o",
                "config": {"temperature": 0.2}
            }))
            .expect("provider server security request deserializes")
        };
        let created = service
            .create_provider("test-user", request())
            .await
            .expect("provider server security fixture creates");

        let conflict = service
            .create_provider("test-user", request())
            .await
            .expect_err("duplicate provider name returns an API conflict");
        assert_eq!(conflict.status, StatusCode::CONFLICT);
        assert_eq!(conflict.detail, "Provider name already exists");

        let mut historical_config = service
            .repo
            .get_provider(&created.id)
            .await
            .expect("provider fixture reads")
            .expect("provider fixture exists")
            .config;
        historical_config["legacy_private"] = json!({"speech_access_token": "historical-secret"});
        historical_config["max_tokens"] = json!(2048);
        historical_config["transport"] = json!({
            "connect_timeout_seconds": 5,
            "private_header": "historical-secret"
        });
        sqlx::query(
            "UPDATE llm_providers SET config = $2, \
             updated_at = GREATEST(now(), updated_at + interval '1 microsecond') \
             WHERE id = $1::uuid",
        )
        .bind(&created.id)
        .bind(&historical_config)
        .execute(&pool)
        .await
        .expect("seed historical hidden provider config");
        let persisted = service
            .repo
            .get_provider(&created.id)
            .await
            .expect("provider fixture rereads")
            .expect("provider fixture remains available");
        service
            .update_provider(
                "test-user",
                &created.id,
                serde_json::from_value(json!({
                    "expected_revision": persisted.updated_at.timestamp_micros(),
                    "config": {
                        "temperature": 0.7,
                        "transport": {"connect_timeout_seconds": 15}
                    }
                }))
                .expect("safe provider config update deserializes"),
            )
            .await
            .expect("safe provider config update succeeds")
            .expect("updated provider remains available");
        let updated = service
            .repo
            .get_provider(&created.id)
            .await
            .expect("updated provider fixture reads")
            .expect("updated provider fixture exists");
        assert_eq!(updated.config["temperature"], 0.7);
        assert_eq!(updated.config.get("max_tokens"), None);
        assert_eq!(
            updated.config["legacy_private"]["speech_access_token"],
            "historical-secret"
        );
        assert_eq!(
            updated.config["transport"]["private_header"],
            "historical-secret"
        );
        assert_eq!(updated.config["transport"]["connect_timeout_seconds"], 15);

        sqlx::query("DELETE FROM llm_providers WHERE name = $1")
            .bind(PROVIDER_NAME)
            .execute(&pool)
            .await
            .expect("clean provider server security fixture after test");
    }

    #[test]
    fn environment_probe_resolves_only_allowlisted_variable_without_exposing_value() {
        let secret = "sk-runtime-only-secret";
        let request = serde_json::from_value::<ProviderProbeRequest>(json!({
            "name": "Environment OpenAI",
            "provider_type": "openai",
            "auth_method": "environment",
            "environment_variable": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1"
        }))
        .expect("environment probe request deserializes");

        let config = ProviderProbeConfig::from_probe_request_with(request, &|name| {
            (name == "OPENAI_API_KEY").then(|| secret.to_string())
        })
        .expect("allowlisted environment reference resolves");

        assert_eq!(config.auth_method, "environment");
        assert_eq!(
            config.environment_variable.as_deref(),
            Some("OPENAI_API_KEY")
        );
        assert_eq!(config.api_key.as_deref(), Some(secret));
        assert!(config.credential_error.is_none());

        let arbitrary_reference = serde_json::from_value::<ProviderProbeRequest>(json!({
            "name": "Rejected environment reference",
            "provider_type": "openai",
            "auth_method": "environment",
            "environment_variable": "DATABASE_URL"
        }))
        .expect("structurally valid probe request deserializes");
        let error = ProviderProbeConfig::from_probe_request_with(arbitrary_reference, &|name| {
            (name == "DATABASE_URL").then(|| "must-not-be-readable".to_string())
        })
        .err()
        .expect("non-provider variables must be rejected");
        assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(
            error.detail,
            "Environment variable is not supported for this provider type"
        );

        let custom_origin = serde_json::from_value::<ProviderProbeRequest>(json!({
            "name": "Rejected environment origin",
            "provider_type": "openai",
            "auth_method": "environment",
            "environment_variable": "OPENAI_API_KEY",
            "base_url": "https://collector.example.test/v1"
        }))
        .expect("custom-origin probe request deserializes");
        let error = ProviderProbeConfig::from_probe_request_with(custom_origin, &|_| {
            panic!("environment must not be read before the endpoint origin is accepted")
        })
        .err()
        .expect("standard environment secret cannot target a custom origin");
        assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(
            error.detail,
            "Environment credentials require the official provider endpoint"
        );
    }

    #[tokio::test]
    async fn environment_probe_reports_missing_credential_without_network_or_secret() {
        let request = serde_json::from_value::<ProviderProbeRequest>(json!({
            "name": "Missing environment OpenAI",
            "provider_type": "openai",
            "auth_method": "environment",
            "environment_variable": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1"
        }))
        .expect("environment probe request deserializes");

        let response = execute_provider_connection_test_with(request, &|_| None)
            .await
            .expect("missing environment credential is a validation response");
        let value = serde_json::to_value(response).expect("validation response serializes");

        assert_eq!(value["status"], "unhealthy");
        assert_eq!(value["probed"], false);
        assert_eq!(value["environment_variable"], "OPENAI_API_KEY");
        assert_eq!(value["detail"], "Environment credential is not configured");
        assert!(!value.to_string().contains("runtime-only-secret"));
    }

    #[test]
    fn provider_type_names_are_unique() {
        let unique = PROVIDER_TYPES.iter().copied().collect::<BTreeSet<_>>();
        assert_eq!(unique.len(), PROVIDER_TYPES.len());
    }

    #[test]
    fn router_builds_with_catalog_provider_model_and_probe_routes() {
        let _ = router();
    }

    #[tokio::test]
    async fn provider_connection_probe_returns_healthy_for_local_ollama() {
        let server = spawn_mock_provider("/api/tags", StatusCode::OK).await;
        let api = spawn_test_connection_api().await;

        let (status, body) = post_test_connection(
            &api,
            json!({
                "name": "Ollama test",
                "provider_type": "ollama",
                "auth_method": "none",
                "base_url": server.base_url.clone(),
                "is_active": true
            }),
        )
        .await;

        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["status"], "healthy");
        assert_eq!(body["probed"], true);
        assert_eq!(body["provider"], Value::Null);
        assert_eq!(body["detail"], Value::Null);
        assert_eq!(body["catalog"], Value::Null);
        assert_eq!(body["error_message"], Value::Null);
        let requests = server
            .requests
            .lock()
            .expect("request capture lock remains available");
        assert_eq!(requests.len(), 1);
        assert!(requests[0].get(AUTHORIZATION).is_none());
    }

    #[tokio::test]
    async fn provider_connection_probe_returns_unhealthy_without_response_body_or_secret() {
        let server = spawn_mock_provider("/v1/models", StatusCode::UNAUTHORIZED).await;
        let api = spawn_test_connection_api().await;
        let secret = "sk-rejected-secret-98765";

        let (status, body) = post_test_connection(
            &api,
            json!({
                "name": "OpenAI rejected",
                "provider_type": "openai",
                "auth_method": "api_key",
                "api_key": secret,
                "base_url": format!("{}/v1", server.base_url),
                "is_active": true
            }),
        )
        .await;

        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(
            body["detail"],
            "HTTPS is required for credentialed providers"
        );
        let response_json = serde_json::to_string(&body).expect("health response serializes");
        assert!(!response_json.contains(secret));
        assert!(!response_json.contains("response body"));
        assert!(server
            .requests
            .lock()
            .expect("request capture lock remains available")
            .is_empty());
    }

    #[tokio::test]
    async fn provider_connection_probe_allows_ollama_without_credentials() {
        let server = spawn_mock_provider("/api/tags", StatusCode::OK).await;
        let api = spawn_test_connection_api().await;

        let (status, body) = post_test_connection(
            &api,
            json!({
                "name": "Ollama local",
                "provider_type": "ollama",
                "auth_method": "none",
                "base_url": server.base_url.clone(),
                "is_active": true
            }),
        )
        .await;

        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["status"], "healthy");
        assert_eq!(body["probed"], true);
        let requests = server
            .requests
            .lock()
            .expect("request capture lock remains available");
        assert_eq!(requests.len(), 1);
        assert!(requests[0].get(AUTHORIZATION).is_none());
    }

    #[tokio::test]
    async fn persisted_health_check_route_probes_and_records_success_and_failure() {
        let ollama_server = spawn_mock_provider("/api/tags", StatusCode::OK).await;
        let lmstudio_server = spawn_mock_provider("/models", StatusCode::SERVICE_UNAVAILABLE).await;
        let catalog = Arc::new(DevLlmProviderCatalogService::default());
        let health_service = Arc::new(DevLlmProviderHealthService::default());
        let ollama = catalog
            .create_provider(
                "dev-user",
                provider_create_request(
                    "ollama",
                    ollama_server.base_url.clone(),
                    None,
                    "llama3.1:8b",
                ),
            )
            .await
            .expect("ollama provider create succeeds");
        let lmstudio = catalog
            .create_provider(
                "dev-user",
                provider_create_request(
                    "lmstudio",
                    lmstudio_server.base_url.clone(),
                    None,
                    "local-model",
                ),
            )
            .await
            .expect("lmstudio provider create succeeds");
        let providers: SharedLlmProviders = catalog;
        let persisted_health: SharedLlmProviderHealth = health_service.clone();
        let api = spawn_persisted_health_check_api(providers, persisted_health).await;

        let (ollama_status, ollama_body) = post_persisted_health_check(&api, &ollama.id).await;
        let (lmstudio_status, lmstudio_body) =
            post_persisted_health_check(&api, &lmstudio.id).await;

        assert_eq!(ollama_status, StatusCode::OK);
        assert_eq!(ollama_body["status"], "healthy");
        assert_eq!(ollama_body["probed"], true);
        assert_eq!(ollama_body["provider"], Value::Null);
        assert_eq!(lmstudio_status, StatusCode::OK);
        assert_eq!(lmstudio_body["status"], "unhealthy");
        assert_eq!(lmstudio_body["probed"], true);
        assert_eq!(lmstudio_body["detail"], Value::Null);
        assert_eq!(lmstudio_body["error_message"], "HTTP 503");
        let stored_ollama = health_service
            .latest_health(&ollama.id)
            .await
            .expect("stored ollama health read succeeds")
            .expect("stored ollama health exists");
        let stored_lmstudio = health_service
            .latest_health(&lmstudio.id)
            .await
            .expect("stored lmstudio health read succeeds")
            .expect("stored lmstudio health exists");
        assert_eq!(stored_ollama.status, "healthy");
        assert_eq!(stored_lmstudio.status, "unhealthy");
        assert_eq!(stored_lmstudio.error_message.as_deref(), Some("HTTP 503"));
    }

    #[tokio::test]
    async fn persisted_health_get_returns_configuration_validation_without_network_probe() {
        let catalog = Arc::new(DevLlmProviderCatalogService::default());
        let health_service = Arc::new(DevLlmProviderHealthService::default());
        let provider = catalog
            .create_provider(
                "dev-user",
                provider_create_request(
                    "azure_openai",
                    "https://example.openai.azure.com".to_string(),
                    Some("azure-test-secret"),
                    "gpt-4o",
                ),
            )
            .await
            .expect("unsupported-probe provider create succeeds");
        health_service
            .record_health(&ProviderHealthRecord {
                provider_id: provider.id.clone(),
                status: "configuration_valid".to_string(),
                last_check: Utc::now(),
                error_message: None,
                response_time_ms: None,
            })
            .await
            .expect("configuration validation health persists");
        let providers: SharedLlmProviders = catalog;
        let persisted_health: SharedLlmProviderHealth = health_service.clone();
        let api = spawn_persisted_health_read_api(providers, persisted_health).await;

        let (status, body) = get_persisted_health(&api, &provider.id).await;

        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["status"], "configuration_valid");
        assert_eq!(body["probed"], false);
        assert_eq!(body["response_time_ms"], Value::Null);
        assert_eq!(body["error_message"], Value::Null);

        health_service
            .record_health(&ProviderHealthRecord {
                provider_id: provider.id.clone(),
                status: "healthy".to_string(),
                last_check: Utc::now(),
                error_message: None,
                response_time_ms: Some(12),
            })
            .await
            .expect("legacy probe health persists for negative read coverage");

        let (status, body) = get_persisted_health(&api, &provider.id).await;

        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(
            body["detail"],
            "No health data available for the current provider configuration"
        );
    }

    #[test]
    fn provider_probe_builds_secure_provider_requests_and_omits_local_credentials() {
        let client = provider_probe_client().expect("probe client builds");
        let anthropic = ProviderProbeConfig {
            provider_id: uuid::Uuid::new_v4().to_string(),
            provider_type: "anthropic".to_string(),
            auth_method: "api_key",
            environment_variable: None,
            base_url: Some("https://proxy.example".to_string()),
            llm_model: Some("claude-sonnet-4".to_string()),
            api_key: Some("anthropic-test-secret".to_string()),
            credential_error: None,
            revision: None,
        };
        let gemini = ProviderProbeConfig {
            provider_id: uuid::Uuid::new_v4().to_string(),
            provider_type: "gemini".to_string(),
            auth_method: "api_key",
            environment_variable: None,
            base_url: Some("https://generative.example".to_string()),
            llm_model: Some("gemini/test".to_string()),
            api_key: Some("gemini-test-secret".to_string()),
            credential_error: None,
            revision: None,
        };
        let lmstudio = ProviderProbeConfig {
            provider_id: uuid::Uuid::new_v4().to_string(),
            provider_type: "lmstudio".to_string(),
            auth_method: "none",
            environment_variable: None,
            base_url: Some("http://127.0.0.1:1234/v1".to_string()),
            llm_model: Some("local-model".to_string()),
            api_key: Some("must-not-be-sent".to_string()),
            credential_error: None,
            revision: None,
        };

        let anthropic_request = build_provider_probe_request(&client, &anthropic)
            .expect("anthropic request builds")
            .build()
            .expect("anthropic headers are valid");
        let gemini_request = build_provider_probe_request(&client, &gemini)
            .expect("gemini request builds")
            .build()
            .expect("gemini headers are valid");
        let lmstudio_request = build_provider_probe_request(&client, &lmstudio)
            .expect("lmstudio request builds")
            .build()
            .expect("lmstudio request is valid");

        assert_eq!(anthropic_request.url().path(), "/v1/models");
        assert_eq!(
            anthropic_request
                .headers()
                .get("x-api-key")
                .expect("anthropic key header exists"),
            "anthropic-test-secret"
        );
        assert!(!anthropic_request.url().as_str().contains("test-secret"));
        assert_eq!(gemini_request.url().path(), "/v1beta/models/gemini%2Ftest");
        assert_eq!(
            gemini_request
                .headers()
                .get("x-goog-api-key")
                .expect("gemini key header exists"),
            "gemini-test-secret"
        );
        assert!(!gemini_request.url().as_str().contains("test-secret"));
        assert_eq!(lmstudio_request.url().path(), "/v1/models");
        assert!(lmstudio_request.headers().get(AUTHORIZATION).is_none());
    }

    #[test]
    fn anthropic_probe_path_is_idempotent_with_or_without_v1_base_path() {
        let client = provider_probe_client().expect("probe client builds");

        for (base_url, expected_path) in [
            ("https://api.anthropic.com", "/v1/models"),
            ("https://api.anthropic.com/", "/v1/models"),
            ("https://api.anthropic.com/v1", "/v1/models"),
            ("https://api.anthropic.com/v1/", "/v1/models"),
        ] {
            let config = ProviderProbeConfig {
                provider_id: "draft-anthropic".to_string(),
                provider_type: "anthropic".to_string(),
                auth_method: "api_key",
                environment_variable: None,
                base_url: Some(base_url.to_string()),
                llm_model: Some("claude-sonnet-4".to_string()),
                api_key: Some("anthropic-test-secret".to_string()),
                credential_error: None,
                revision: None,
            };

            let request = build_provider_probe_request(&client, &config)
                .expect("anthropic request builds")
                .build()
                .expect("anthropic request is valid");

            assert_eq!(request.url().path(), expected_path, "base URL: {base_url}");
        }
    }

    #[test]
    fn provider_probe_rejects_credentialed_or_query_bearing_base_urls() {
        assert!(validated_probe_base_url("https://user:pass@example.com/v1").is_err());
        assert!(validated_probe_base_url("https://example.com/v1?api_key=secret").is_err());
        assert!(validated_probe_base_url("file:///tmp/provider").is_err());
        let insecure_remote = validated_probe_base_url("http://api.example.test/v1")
            .expect("HTTP URL parses structurally");
        assert!(validate_probe_transport(&insecure_remote, "openai").is_err());
        let remote_ollama = validated_probe_base_url("http://ollama.example.test:11434")
            .expect("remote Ollama URL parses structurally");
        assert!(validate_probe_transport(&remote_ollama, "ollama").is_err());
        let local_ollama = validated_probe_base_url("http://127.0.0.1:11434")
            .expect("local Ollama URL parses structurally");
        assert!(validate_probe_transport(&local_ollama, "ollama").is_ok());

        let unsupported = ProviderProbeConfig {
            provider_id: "draft-provider".to_string(),
            provider_type: "azure_openai".to_string(),
            auth_method: "api_key",
            environment_variable: None,
            base_url: Some("https://example.openai.azure.com".to_string()),
            llm_model: Some("gpt-4o".to_string()),
            api_key: Some("test-secret".to_string()),
            credential_error: None,
            revision: None,
        };
        let client = provider_probe_client().expect("probe client builds");
        assert_eq!(
            build_provider_probe_request(&client, &unsupported)
                .expect_err("unsupported provider probe must fail"),
            "Provider health check is not supported for this provider type"
        );
    }

    #[tokio::test]
    async fn provider_connection_test_validates_configuration_without_unsupported_network_probe() {
        let response = execute_provider_connection_test(ProviderProbeRequest {
            name: "azure_openai test".to_string(),
            provider_type: "azure_openai".to_string(),
            auth_method: Some("api_key".to_string()),
            environment_variable: None,
            api_key: Some("test-secret".to_string()),
            base_url: Some("https://example.openai.azure.com".to_string()),
            operation_type: None,
            is_active: Some(true),
            ..Default::default()
        })
        .await
        .expect("configuration-only provider validation succeeds without network I/O");

        assert_eq!(response.status, "configuration_valid");
        assert!(!response.probed);
        assert!(response.provider.is_none());
        assert_eq!(response.response_time_ms, None);
        assert_eq!(response.error_message, None);
        assert_eq!(response.catalog, None);
        assert_eq!(
            response.detail.as_deref(),
            Some(
                "Connection probing is not supported for this provider type; configuration validation passed"
            )
        );

        for provider_type in ["bedrock", "vertex"] {
            let error = execute_provider_connection_test(ProviderProbeRequest {
                name: format!("{provider_type} test"),
                provider_type: provider_type.to_string(),
                auth_method: Some("api_key".to_string()),
                environment_variable: None,
                api_key: Some("test-secret".to_string()),
                base_url: None,
                operation_type: None,
                is_active: Some(true),
                ..Default::default()
            })
            .await
            .expect_err("providers without structured credential storage must fail closed");
            assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
        }

        let error = execute_provider_connection_test(ProviderProbeRequest {
            name: "Unsafe Azure OpenAI".to_string(),
            provider_type: "azure_openai".to_string(),
            auth_method: Some("api_key".to_string()),
            environment_variable: None,
            api_key: Some("test-secret".to_string()),
            base_url: Some("http://example.openai.azure.com".to_string()),
            operation_type: None,
            is_active: Some(true),
            ..Default::default()
        })
        .await
        .expect_err("configuration-only validation still enforces transport security");

        assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(error.detail, "HTTPS is required for credentialed providers");
    }

    #[tokio::test]
    async fn provider_connection_test_rejects_unsafe_supported_provider_path_before_network() {
        for base_url in [
            "https://api.openai.com/v1/tenant-token",
            "https://gateway.example.test/tenant/private-token",
        ] {
            let error = execute_provider_connection_test(ProviderProbeRequest {
                name: "unsafe OpenAI probe".to_string(),
                provider_type: "openai".to_string(),
                auth_method: Some("api_key".to_string()),
                api_key: Some("test-secret".to_string()),
                base_url: Some(base_url.to_string()),
                llm_model: Some("gpt-4o".to_string()),
                ..Default::default()
            })
            .await
            .expect_err("unsafe draft probe path must fail before network I/O");

            assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
            assert!(error.detail.contains("path"));
        }
    }

    #[test]
    fn env_detection_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/llm_env_detection_response.json"
        ))
        .expect("llm env detection golden must be valid JSON");

        let response = detect_env_provider_configs_with(|name| match name {
            "OPENAI_API_KEY" => Some("sk-openai".to_string()),
            "OPENAI_BASE_URL" => Some("https://api.openai.com/v1".to_string()),
            "OLLAMA_BASE_URL" => Some("http://ollama.test".to_string()),
            _ => None,
        });

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
        assert_eq!(
            value["detected_providers"]["openai"]["environment_variable"],
            "OPENAI_API_KEY"
        );
        assert_eq!(
            value["detected_providers"]["ollama"]["environment_variable"],
            Value::Null
        );
        let serialized = serde_json::to_string(&value).expect("response JSON serializes");
        assert!(!serialized.contains("sk-openai"));
        assert!(!serialized.contains("\"api_key\""));
    }

    #[test]
    fn env_detection_uses_canonical_deepseek_and_minimax_base_urls() {
        let response = detect_env_provider_configs_with(|name| match name {
            "DEEPSEEK_API_KEY" => Some("deepseek-test-key".to_string()),
            "MINIMAX_API_KEY" => Some("minimax-test-key".to_string()),
            _ => None,
        });

        let deepseek = response
            .detected_providers
            .get("deepseek")
            .expect("DeepSeek should be detected");
        assert_eq!(
            deepseek.base_url.as_deref(),
            Some("https://api.deepseek.com/v1")
        );
        assert!(deepseek.credential_configured);

        let minimax = response
            .detected_providers
            .get("minimax")
            .expect("MiniMax should be detected");
        assert_eq!(
            minimax.base_url.as_deref(),
            Some("https://api.minimax.io/v1")
        );
        assert!(minimax.credential_configured);

        let serialized = serde_json::to_string(&response).expect("response JSON serializes");
        assert!(!serialized.contains("deepseek-test-key"));
        assert!(!serialized.contains("minimax-test-key"));
    }

    #[test]
    fn env_detection_skips_duplicate_aliases_and_required_empty_keys() {
        let response = detect_env_provider_configs_with(|name| match name {
            "ZAI_API_KEY" => Some(String::new()),
            "ZHIPU_API_KEY" => Some("zhipu-key".to_string()),
            "OPENAI_API_KEY" => Some(String::new()),
            "OPENROUTER_API_KEY" => Some("openrouter-key".to_string()),
            _ => None,
        });

        assert!(!response.detected_providers.contains_key("openai"));
        let zai = response
            .detected_providers
            .get("zai")
            .expect("zai should be detected via its non-empty alias");
        assert_eq!(zai.credential_source, "environment");
        assert!(zai.credential_configured);

        let openrouter = response
            .detected_providers
            .get("openrouter")
            .expect("openrouter should be detected");
        assert_eq!(openrouter.credential_source, "environment");
        assert!(openrouter.credential_configured);

        let serialized = serde_json::to_string(&response).expect("response JSON serializes");
        assert!(!serialized.contains("zhipu-key"));
        assert!(!serialized.contains("openrouter-key"));
        assert!(!serialized.contains("\"api_key\""));
    }

    #[test]
    fn env_detection_hides_unsafe_custom_base_url_paths() {
        let response = detect_env_provider_configs_with(|name| match name {
            "OPENAI_API_KEY" => Some("sk-openai".to_string()),
            "OPENAI_BASE_URL" => {
                Some("https://gateway.example.test/tenant/secret-route".to_string())
            }
            _ => None,
        });

        let openai = response
            .detected_providers
            .get("openai")
            .expect("OpenAI remains detectable from its API key");
        assert_eq!(openai.base_url, None);
        assert!(!openai.credential_configured);
        assert_eq!(openai.environment_variable, None);
        let serialized = serde_json::to_string(&response).expect("response JSON serializes");
        assert!(!serialized.contains("secret-route"));
    }

    #[test]
    fn env_detection_only_exposes_official_safe_environment_bindings() {
        for unsafe_base_url in [
            "https://gateway.example.test/v1",
            "http://api.openai.com/v1",
        ] {
            let response = detect_env_provider_configs_with(|name| match name {
                "OPENAI_API_KEY" => Some("sk-openai".to_string()),
                "OPENAI_BASE_URL" => Some(unsafe_base_url.to_string()),
                _ => None,
            });
            let openai = response
                .detected_providers
                .get("openai")
                .expect("OpenAI remains detectable for remediation");
            assert_eq!(openai.base_url, None);
            assert!(!openai.credential_configured);
            assert_eq!(openai.environment_variable, None);
        }

        let response = detect_env_provider_configs_with(|name| match name {
            "OLLAMA_BASE_URL" => Some("http://192.168.1.50:11434".to_string()),
            _ => None,
        });
        let ollama = response
            .detected_providers
            .get("ollama")
            .expect("Ollama remains detectable for remediation");
        assert_eq!(ollama.base_url, None);
        assert_eq!(ollama.environment_variable, None);

        let response = detect_env_provider_configs_with(|name| match name {
            "OLLAMA_BASE_URL" => Some("http://localhost:11434".to_string()),
            _ => None,
        });
        let ollama = response
            .detected_providers
            .get("ollama")
            .expect("official local Ollama should be detected");
        assert_eq!(ollama.base_url.as_deref(), Some("http://localhost:11434"));
        assert!(!ollama.credential_configured);
        assert_eq!(ollama.environment_variable, None);
    }

    #[test]
    fn env_detection_accepts_both_official_anthropic_base_paths() {
        for base_url in ["https://api.anthropic.com", "https://api.anthropic.com/v1"] {
            let response = detect_env_provider_configs_with(|name| match name {
                "ANTHROPIC_API_KEY" => Some("sk-ant-test".to_string()),
                "ANTHROPIC_BASE_URL" => Some(base_url.to_string()),
                _ => None,
            });
            let anthropic = response
                .detected_providers
                .get("anthropic")
                .expect("Anthropic should be detected");
            assert_eq!(anthropic.base_url.as_deref(), Some(base_url));
            assert!(anthropic.credential_configured);
            assert_eq!(
                anthropic.environment_variable.as_deref(),
                Some("ANTHROPIC_API_KEY")
            );
        }
    }

    #[test]
    fn model_catalog_embedded_snapshot_loads_in_python_order() {
        let catalog = ModelCatalog::load_embedded();
        assert_eq!(catalog.models.len(), 859);
        assert_eq!(catalog.models[0].name, "claude-3-5-haiku-20241022");
    }

    #[tokio::test]
    async fn model_catalog_list_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/llm_model_catalog_list_response.json"
        ))
        .expect("llm model catalog list golden must be valid JSON");

        let value = serde_json::to_value(
            list_catalog_models(Query(CatalogListQuery {
                provider: Some("cohere".to_string()),
                include_deprecated: Some(false),
            }))
            .await
            .0,
        )
        .expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[tokio::test]
    async fn model_catalog_search_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/llm_model_catalog_search_response.json"
        ))
        .expect("llm model catalog search golden must be valid JSON");

        let value = serde_json::to_value(
            search_catalog_models(Query(CatalogSearchQuery {
                q: Some("claude-3-5-haiku-20241022".to_string()),
                provider: Some("anthropic".to_string()),
                limit: Some(1),
            }))
            .await
            .expect("query is valid")
            .0,
        )
        .expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[tokio::test]
    async fn provider_models_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/llm_provider_models_response.json"
        ))
        .expect("llm provider models golden must be valid JSON");

        let value = serde_json::to_value(
            list_models_for_provider_type(Path("anthropic".to_string()))
                .await
                .0,
        )
        .expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[tokio::test]
    async fn provider_models_unknown_provider_keeps_python_empty_contract() {
        let value = serde_json::to_value(
            list_models_for_provider_type(Path("unknown-provider".to_string()))
                .await
                .0,
        )
        .expect("response serializes");

        assert_eq!(
            value,
            json!({
                "provider_type": "unknown-provider",
                "models": {
                    "chat": [],
                    "embedding": [],
                    "rerank": []
                }
            })
        );
    }

    #[test]
    fn provider_health_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/llm_provider_health_response.json"
        ))
        .expect("llm provider health golden must be valid JSON");

        let response = ProviderHealthResponse::from(ProviderHealthRecord {
            provider_id: "11111111-2222-4333-8444-555555555555".to_string(),
            status: "healthy".to_string(),
            last_check: Utc
                .with_ymd_and_hms(2026, 1, 2, 3, 4, 5)
                .single()
                .expect("fixture timestamp is valid"),
            error_message: None,
            response_time_ms: Some(88),
        });
        let value = serde_json::to_value(response.clone()).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);

        let current_config = ProviderProbeConfig {
            provider_id: response.provider_id.clone(),
            provider_type: "openai".to_string(),
            auth_method: "api_key",
            environment_variable: None,
            base_url: None,
            llm_model: Some("gpt-4o".to_string()),
            api_key: Some("test-secret".to_string()),
            credential_error: None,
            revision: Some(
                Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 4)
                    .single()
                    .expect("fixture timestamp is valid")
                    .timestamp_micros(),
            ),
        };
        assert!(provider_health_matches_config(&response, &current_config));
        let stale_config = ProviderProbeConfig {
            revision: Some(
                Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 6)
                    .single()
                    .expect("fixture timestamp is valid")
                    .timestamp_micros(),
            ),
            ..current_config
        };
        assert!(!provider_health_matches_config(&response, &stale_config));
    }

    #[test]
    fn provider_validation_response_matches_desktop_and_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/llm_provider_validation_response.json"
        ))
        .expect("llm provider validation golden must be valid JSON");

        let response = ProviderValidationResponse::from_health(ProviderHealthRecord {
            provider_id: "11111111-2222-4333-8444-555555555555".to_string(),
            status: "healthy".to_string(),
            last_check: Utc
                .with_ymd_and_hms(2026, 1, 2, 3, 4, 5)
                .single()
                .expect("fixture timestamp is valid"),
            error_message: None,
            response_time_ms: Some(88),
        });
        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn provider_config_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/llm_provider_config_response.json"
        ))
        .expect("llm provider config golden must be valid JSON");

        let record = LlmProviderRecord {
            id: "11111111-2222-4333-8444-555555555555".to_string(),
            name: "test-openai".to_string(),
            provider_type: "openai".to_string(),
            operation_type: "llm".to_string(),
            api_key_encrypted: "sk-test-key-12345".to_string(),
            base_url: None,
            llm_model: Some("gpt-4o".to_string()),
            llm_small_model: Some("gpt-4o-mini".to_string()),
            embedding_model: None,
            reranker_model: None,
            config: json!({}),
            is_active: true,
            is_default: false,
            is_enabled: true,
            allowed_models: vec!["gpt-4o".to_string()],
            blocked_models: Vec::new(),
            pool_weight: 1.0,
            pool_enabled: true,
            model_tier: Some("large".to_string()),
            secondary_models: vec!["gpt-4o-mini".to_string()],
            created_at: Utc
                .with_ymd_and_hms(2026, 1, 2, 3, 4, 5)
                .single()
                .expect("fixture timestamp is valid"),
            updated_at: Utc
                .with_ymd_and_hms(2026, 1, 2, 3, 5, 5)
                .single()
                .expect("fixture timestamp is valid"),
        };
        let health = ProviderHealthRecord {
            provider_id: "11111111-2222-4333-8444-555555555555".to_string(),
            status: "healthy".to_string(),
            last_check: Utc
                .with_ymd_and_hms(2026, 1, 2, 3, 6, 5)
                .single()
                .expect("fixture timestamp is valid"),
            error_message: None,
            response_time_ms: Some(88),
        };
        let current = provider_response_from_record(record.clone(), Some(health.clone()));
        let value = serde_json::to_value(current).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);

        let stale = provider_response_from_record(
            LlmProviderRecord {
                updated_at: Utc
                    .with_ymd_and_hms(2026, 1, 2, 3, 7, 5)
                    .single()
                    .expect("fixture timestamp is valid"),
                ..record.clone()
            },
            Some(health.clone()),
        );
        assert_eq!(stale.health_status, None);
        assert_eq!(stale.health_last_check, None);

        let unsupported = provider_response_from_record(
            LlmProviderRecord {
                provider_type: "azure_openai".to_string(),
                ..record.clone()
            },
            Some(health.clone()),
        );
        assert_eq!(unsupported.health_status, None);

        let configuration_valid = provider_response_from_record(
            LlmProviderRecord {
                provider_type: "azure_openai".to_string(),
                ..record.clone()
            },
            Some(ProviderHealthRecord {
                status: "configuration_valid".to_string(),
                response_time_ms: None,
                ..health
            }),
        );
        assert_eq!(
            configuration_valid.health_status.as_deref(),
            Some("configuration_valid")
        );
        assert!(configuration_valid.health_last_check.is_some());
        assert_eq!(configuration_valid.response_time_ms, None);

        let sentinel = provider_response_from_record(
            LlmProviderRecord {
                api_key_encrypted: LOCAL_NO_API_KEY_SENTINEL.to_string(),
                ..record
            },
            None,
        );
        assert!(!sentinel.credential_configured);
    }

    #[tokio::test]
    async fn provider_config_public_projection_redacts_list_get_and_direct_responses() {
        const SECRET_CANARY: &str = "provider-config-secret-canary";

        fn contains_key(value: &Value, expected: &str) -> bool {
            match value {
                Value::Object(object) => {
                    object.contains_key(expected)
                        || object.values().any(|value| contains_key(value, expected))
                }
                Value::Array(values) => values.iter().any(|value| contains_key(value, expected)),
                _ => false,
            }
        }

        let persisted_config = json!({
            "request_timeout_seconds": 45,
            "region": "us-east-1",
            "retries": {"max_attempts": 3},
            "aws_secret_access_key": SECRET_CANARY,
            "apiKey": SECRET_CANARY,
            "clientSecret": SECRET_CANARY,
            "x-api-key": SECRET_CANARY,
            "apiSecret": SECRET_CANARY,
            "token": SECRET_CANARY,
            "custom_value": SECRET_CANARY,
            "credentials": {
                "secret_access_key": SECRET_CANARY,
                "session_token": SECRET_CANARY,
                "safe_role": "inference"
            },
            "nested": [
                {
                    "aws_session_token": SECRET_CANARY,
                    "access_token": SECRET_CANARY,
                    "safe_model": "gpt-4o"
                },
                {"oauth_token": SECRET_CANARY, "safe_weight": 2}
            ],
            "embedding": {
                "dimensions": 1536,
                "headers": {"Authorization": SECRET_CANARY},
                "access_token": SECRET_CANARY
            },
            "headers": {
                "Authorization": SECRET_CANARY,
                "X-Request-ID": "safe-but-container-must-not-be-public"
            },
            "transport": {
                "custom_headers": {"X-Api-Key": SECRET_CANARY},
                "fallbackHeaders": {"X-Api-Key": SECRET_CANARY},
                "authorization": SECRET_CANARY,
                "proxyAuthorization": SECRET_CANARY,
                "proxy_authorization": SECRET_CANARY,
                "connect_timeout_seconds": 10
            }
        });
        let record = LlmProviderRecord {
            id: "11111111-2222-4333-8444-555555555555".to_string(),
            name: "redacted-openai".to_string(),
            provider_type: "openai".to_string(),
            operation_type: "llm".to_string(),
            api_key_encrypted: "sk-redaction-fixture-key".to_string(),
            base_url: Some("https://api.example.test/v1".to_string()),
            llm_model: Some("gpt-4o".to_string()),
            llm_small_model: None,
            embedding_model: None,
            reranker_model: None,
            config: persisted_config.clone(),
            is_active: true,
            is_default: false,
            is_enabled: true,
            allowed_models: vec!["gpt-4o".to_string()],
            blocked_models: Vec::new(),
            pool_weight: 1.0,
            pool_enabled: true,
            model_tier: None,
            secondary_models: Vec::new(),
            created_at: Utc
                .with_ymd_and_hms(2026, 1, 2, 3, 4, 5)
                .single()
                .expect("fixture timestamp is valid"),
            updated_at: Utc
                .with_ymd_and_hms(2026, 1, 2, 3, 5, 5)
                .single()
                .expect("fixture timestamp is valid"),
        };
        let service = DevLlmProviderCatalogService::default();
        service.records.lock().await.push(record.clone());

        let unsafe_legacy_url = serde_json::to_value(provider_response_from_record(
            LlmProviderRecord {
                base_url: Some(
                    "https://legacy-user:legacy-url-secret@example.test/v1?api_key=secret"
                        .to_string(),
                ),
                ..record.clone()
            },
            None,
        ))
        .expect("legacy provider response serializes");
        assert_eq!(unsafe_legacy_url["base_url"], Value::Null);
        assert!(!unsafe_legacy_url.to_string().contains("legacy-url-secret"));

        let unsafe_legacy_path = serde_json::to_value(provider_response_from_record(
            LlmProviderRecord {
                base_url: Some(
                    "https://gateway.example.test/tenant/private-route-token".to_string(),
                ),
                ..record.clone()
            },
            None,
        ))
        .expect("legacy provider response with unsafe path serializes");
        assert_eq!(unsafe_legacy_path["base_url"], Value::Null);
        assert!(!unsafe_legacy_path
            .to_string()
            .contains("private-route-token"));

        let direct = serde_json::to_value(provider_response_from_record(record, None))
            .expect("direct provider response serializes");
        let listed = serde_json::to_value(
            service
                .list_providers("dev-user", true)
                .await
                .expect("provider list succeeds"),
        )
        .expect("provider list response serializes");
        let fetched = serde_json::to_value(
            service
                .get_provider("dev-user", "11111111-2222-4333-8444-555555555555")
                .await
                .expect("provider get succeeds")
                .expect("provider exists"),
        )
        .expect("provider get response serializes");
        let listed_provider = listed
            .as_array()
            .and_then(|providers| providers.first())
            .expect("provider list has fixture");

        for response in [&direct, listed_provider, &fetched] {
            let public_config = &response["config"];
            let serialized = serde_json::to_string(response).expect("provider response serializes");
            assert!(!serialized.contains(SECRET_CANARY));
            for sensitive_key in [
                "aws_secret_access_key",
                "secret_access_key",
                "aws_session_token",
                "session_token",
                "access_token",
                "oauth_token",
                "apiKey",
                "clientSecret",
                "x-api-key",
                "apiSecret",
                "token",
                "custom_value",
                "headers",
                "custom_headers",
                "fallbackHeaders",
                "authorization",
                "proxyAuthorization",
                "proxy_authorization",
            ] {
                assert!(!contains_key(response, sensitive_key));
            }
            assert_eq!(public_config["request_timeout_seconds"], 45);
            assert_eq!(public_config["region"], "us-east-1");
            assert_eq!(public_config["retries"]["max_attempts"], 3);
            assert_eq!(public_config.get("credentials"), None);
            assert_eq!(public_config.get("nested"), None);
            assert_eq!(public_config["embedding"]["dimensions"], 1536);
            assert_eq!(response["embedding_config"]["dimensions"], 1536);
            assert_eq!(public_config["transport"]["connect_timeout_seconds"], 10);
        }

        let stored = service.records.lock().await;
        assert_eq!(stored[0].config, persisted_config);
        assert!(stored[0].config.to_string().contains(SECRET_CANARY));
        assert!(!stored[0].config.to_string().contains("***"));
    }

    #[test]
    fn provider_config_write_schema_rejects_secrets_and_merges_safe_updates() {
        const SECRET_CANARY: &str = "write-schema-secret-canary";
        let created_at = Utc
            .with_ymd_and_hms(2026, 2, 3, 4, 5, 6)
            .single()
            .expect("fixture timestamp is valid");
        let existing = LlmProviderRecord {
            id: "11111111-2222-4333-8444-555555555555".to_string(),
            name: "legacy-openai".to_string(),
            provider_type: "openai".to_string(),
            operation_type: "llm".to_string(),
            api_key_encrypted: "encrypted-fixture".to_string(),
            base_url: Some("https://api.openai.com/v1".to_string()),
            llm_model: Some("gpt-4o".to_string()),
            llm_small_model: None,
            embedding_model: None,
            reranker_model: None,
            config: json!({
                "auth_method": "api_key",
                "temperature": 0.2,
                "max_tokens": 2048,
                "region": "us-east-1",
                "legacy_private": {"speech_access_token": SECRET_CANARY},
                "retries": {
                    "max_attempts": 3,
                    "private_retry_policy": SECRET_CANARY
                },
                "transport": {
                    "connect_timeout_seconds": 5,
                    "request_timeout_seconds": 30,
                    "private_header": SECRET_CANARY
                }
            }),
            is_active: true,
            is_default: false,
            is_enabled: true,
            allowed_models: Vec::new(),
            blocked_models: Vec::new(),
            pool_weight: 1.0,
            pool_enabled: true,
            model_tier: None,
            secondary_models: Vec::new(),
            created_at,
            updated_at: created_at,
        };
        let update = provider_update_record_with_auth(
            &existing,
            serde_json::from_value(json!({
                "expected_revision": existing.updated_at.timestamp_micros(),
                "config": {
                    "temperature": 0.7,
                    "transport": {"connect_timeout_seconds": 15}
                }
            }))
            .expect("safe config update deserializes"),
        )
        .expect("safe config update is accepted");
        let merged = update.config.expect("update carries merged config");
        assert_eq!(merged["temperature"], 0.7);
        assert_eq!(merged.get("max_tokens"), None);
        assert_eq!(merged.get("region"), None);
        assert_eq!(merged["transport"]["connect_timeout_seconds"], 15);
        assert_eq!(merged["transport"].get("request_timeout_seconds"), None);
        assert_eq!(merged["transport"]["private_header"], SECRET_CANARY);
        assert_eq!(merged["retries"].get("max_attempts"), None);
        assert_eq!(merged["retries"]["private_retry_policy"], SECRET_CANARY);
        assert_eq!(
            merged["legacy_private"]["speech_access_token"],
            SECRET_CANARY
        );

        assert_eq!(
            merge_writable_provider_config(&existing.config, None)
                .expect("omitted config is preserved"),
            existing.config
        );
        let layered_existing = json!({
            "temperature": 0.2,
            "private_top_level": SECRET_CANARY,
            "embedding": {
                "model": "legacy-model",
                "dimensions": 1536,
                "private_embedding_key": SECRET_CANARY,
                "provider_options": {
                    "batch_size": 16,
                    "api_key": SECRET_CANARY
                }
            }
        });
        let layered = merge_writable_provider_config(
            &layered_existing,
            Some(json!({
                "temperature": 0.8,
                "embedding": {
                    "provider_options": {"batch_size": 64}
                }
            })),
        )
        .expect("layered public config replacement succeeds");
        assert_eq!(layered["temperature"], 0.8);
        assert_eq!(layered["private_top_level"], SECRET_CANARY);
        assert_eq!(layered["embedding"].get("model"), None);
        assert_eq!(layered["embedding"].get("dimensions"), None);
        assert_eq!(layered["embedding"]["private_embedding_key"], SECRET_CANARY);
        assert_eq!(layered["embedding"]["provider_options"]["batch_size"], 64);
        assert_eq!(
            layered["embedding"]["provider_options"]["api_key"],
            SECRET_CANARY
        );

        for forbidden_config in [
            json!({"speech_access_token": SECRET_CANARY}),
            json!({"provider_options": {"api_key": SECRET_CANARY}}),
            json!({"embedding": {"provider_options": {"token": SECRET_CANARY}}}),
            json!({"aws_secret_access_key": SECRET_CANARY}),
        ] {
            let request = serde_json::from_value::<ProviderCreateRequest>(json!({
                "name": "unsafe-openai",
                "provider_type": "openai",
                "api_key": "sk-test-secret",
                "llm_model": "gpt-4o",
                "config": forbidden_config
            }))
            .expect("credential-bearing config request deserializes");
            let error = provider_create_record_with_auth(request)
                .expect_err("credential-bearing JSON config must be rejected");
            assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
            assert!(!error.detail.contains(SECRET_CANARY));
        }

        let embedding_request = serde_json::from_value::<ProviderCreateRequest>(json!({
            "name": "unsafe-embedding",
            "provider_type": "dashscope_embedding",
            "api_key": "sk-test-secret",
            "embedding_model": "text-embedding-v3",
            "embedding_config": {
                "provider_options": {"api_key": SECRET_CANARY}
            }
        }))
        .expect("credential-bearing embedding request deserializes");
        let error = provider_create_record_with_auth(embedding_request)
            .expect_err("embedding provider_options must not be persisted in JSONB");
        assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
        assert!(!error.detail.contains(SECRET_CANARY));

        let safe_embedding_request = serde_json::from_value::<ProviderCreateRequest>(json!({
            "name": "safe-embedding",
            "provider_type": "dashscope_embedding",
            "api_key": "sk-test-secret",
            "embedding_model": "text-embedding-v3",
            "embedding_config": {
                "dimensions": 1024,
                "provider_options": {
                    "batch_size": 32,
                    "input_type": "search_document",
                    "truncate": "END"
                }
            }
        }))
        .expect("safe embedding options request deserializes");
        let safe_embedding = provider_create_record_with_auth(safe_embedding_request)
            .expect("positive-schema embedding options are accepted");
        assert_eq!(
            safe_embedding.config["embedding"]["provider_options"],
            json!({
                "batch_size": 32,
                "input_type": "search_document",
                "truncate": "END"
            })
        );

        let embedding_existing = LlmProviderRecord {
            provider_type: "dashscope_embedding".to_string(),
            operation_type: "embedding".to_string(),
            base_url: Some("https://dashscope.aliyuncs.com/compatible-mode/v1".to_string()),
            llm_model: None,
            embedding_model: Some("text-embedding-v3".to_string()),
            config: json!({
                "auth_method": "api_key",
                "embedding": {
                    "model": "stale-config-model",
                    "dimensions": 1536,
                    "timeout": 60,
                    "user": "stale-user",
                    "encoding_format": "float",
                    "private_embedding_key": SECRET_CANARY,
                    "provider_options": {
                        "batch_size": 16,
                        "input_type": "search_document",
                        "truncate": "END",
                        "api_key": SECRET_CANARY
                    }
                }
            }),
            ..existing.clone()
        };
        let embedding_update = provider_update_record_with_auth(
            &embedding_existing,
            serde_json::from_value(json!({
                "expected_revision": embedding_existing.updated_at.timestamp_micros(),
                "embedding_config": {
                    "dimensions": 768,
                    "provider_options": {"batch_size": 32}
                }
            }))
            .expect("standalone embedding config update deserializes"),
        )
        .expect("standalone embedding config update succeeds");
        let embedding = &embedding_update
            .config
            .expect("embedding update carries config")["embedding"];
        assert_eq!(embedding["dimensions"], 768);
        assert_eq!(embedding["provider_options"]["batch_size"], 32);
        for stale_public_field in ["model", "timeout", "user", "encoding_format"] {
            assert_eq!(embedding.get(stale_public_field), None);
        }
        for stale_public_option in ["input_type", "truncate"] {
            assert_eq!(embedding["provider_options"].get(stale_public_option), None);
        }
        assert_eq!(embedding["private_embedding_key"], SECRET_CANARY);
        assert_eq!(embedding["provider_options"]["api_key"], SECRET_CANARY);
    }

    #[tokio::test]
    async fn provider_types_fail_closed_when_structured_auth_storage_is_unavailable() {
        let descriptors = list_provider_types().await.0;
        for provider_type in ["bedrock", "vertex"] {
            let descriptor = descriptors
                .iter()
                .find(|descriptor| descriptor.provider_type == provider_type)
                .expect("provider descriptor exists");
            assert!(descriptor.auth_methods.is_empty());
            assert!(descriptor.unavailable_auth_methods.contains(&"api_key"));

            let request = serde_json::from_value::<ProviderCreateRequest>(json!({
                "name": format!("{provider_type}-unsafe-auth"),
                "provider_type": provider_type,
                "auth_method": "api_key",
                "api_key": "single-field-credential",
                "llm_model": "test-model"
            }))
            .expect("unsupported auth request deserializes");
            let error = provider_create_record_with_auth(request)
                .expect_err("unsupported structured auth must fail closed");
            assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
        }
    }

    #[test]
    fn provider_base_url_policy_requires_exact_official_or_safe_custom_paths() {
        assert!(
            validate_persisted_provider_base_url("openai", Some("https://api.openai.com/v1"))
                .is_ok()
        );
        assert!(validate_persisted_provider_base_url(
            "openai",
            Some("https://gateway.example.test")
        )
        .is_ok());
        assert!(validate_persisted_provider_base_url(
            "openai",
            Some("https://gateway.example.test/v1")
        )
        .is_ok());
        assert!(validate_persisted_provider_base_url(
            "openai",
            Some("https://api.openai.com/v1/tenant-token")
        )
        .is_err());
        assert!(validate_persisted_provider_base_url(
            "openai",
            Some("https://gateway.example.test/tenant/private-token")
        )
        .is_err());
        assert!(!environment_credential_endpoint_is_official(
            "openai",
            Some("https://api.openai.com/v1/tenant-token")
        ));
        for anthropic_base_url in [
            "https://api.anthropic.com",
            "https://api.anthropic.com/",
            "https://api.anthropic.com/v1",
            "https://api.anthropic.com/v1/",
        ] {
            assert!(
                validate_persisted_provider_base_url("anthropic", Some(anthropic_base_url)).is_ok()
            );
            assert!(environment_credential_endpoint_is_official(
                "anthropic",
                Some(anthropic_base_url)
            ));
        }

        for (provider_type, base_url) in [
            ("gemini", "https://generativelanguage.googleapis.com"),
            ("gemini", "https://generativelanguage.googleapis.com/v1beta"),
            ("ollama", "http://localhost:11434"),
            ("ollama", "http://localhost:11434/api"),
            ("deepseek", "https://api.deepseek.com/v1"),
            ("minimax", "https://api.minimax.io/v1"),
        ] {
            assert!(
                validate_persisted_provider_base_url(provider_type, Some(base_url)).is_ok(),
                "official base URL must be accepted: {provider_type} {base_url}"
            );
            assert!(
                environment_credential_endpoint_is_official(provider_type, Some(base_url)),
                "official origin/path must remain eligible for environment references: {provider_type} {base_url}"
            );
        }

        for (provider_type, base_url) in [
            ("gemini", "https://generativelanguage.googleapis.com/v1"),
            ("ollama", "http://localhost:11434/v1"),
            ("deepseek", "https://api.deepseek.com"),
            ("minimax", "https://api.minimax.io/anthropic/v1"),
        ] {
            assert!(
                validate_persisted_provider_base_url(provider_type, Some(base_url)).is_err(),
                "non-canonical official path must fail closed: {provider_type} {base_url}"
            );
            assert!(!environment_credential_endpoint_is_official(
                provider_type,
                Some(base_url)
            ));
        }
    }

    #[test]
    fn provider_requests_accept_known_compatibility_fields_and_reject_unknown_fields() {
        let create = serde_json::from_value::<ProviderCreateRequest>(json!({
            "name": "known-openai",
            "provider_type": "openai",
            "operation_type": "llm",
            "api_key": "sk-test-secret",
            "base_url": "https://api.openai.com/v1",
            "llm_model": "gpt-4o",
            "llm_small_model": "gpt-4o-mini",
            "embedding_model": null,
            "embedding_config": null,
            "reranker_model": null,
            "config": {"temperature": 0.2},
            "is_active": true,
            "is_default": false,
            "is_enabled": true,
            "allowed_models": ["gpt-4o"],
            "blocked_models": [],
            "pool_weight": 1.0,
            "pool_enabled": true,
            "model_tier": "large",
            "secondary_models": ["gpt-4o-mini"]
        }));
        assert!(create.is_ok());

        let update = serde_json::from_value::<ProviderUpdateRequest>(json!({
            "expected_revision": 1,
            "name": "known-openai",
            "provider_type": "openai",
            "operation_type": "llm",
            "base_url": null,
            "llm_model": "gpt-4o",
            "llm_small_model": "gpt-4o-mini",
            "embedding_model": null,
            "embedding_config": null,
            "reranker_model": null,
            "config": {"temperature": 0.2},
            "is_active": true,
            "is_default": false,
            "is_enabled": true,
            "allowed_models": ["gpt-4o"],
            "blocked_models": [],
            "pool_weight": 1.0,
            "pool_enabled": true,
            "model_tier": null,
            "secondary_models": ["gpt-4o-mini"]
        }));
        assert!(update.is_ok());

        let probe = serde_json::from_value::<ProviderProbeRequest>(json!({
            "name": "known-openai-probe",
            "provider_type": "openai",
            "operation_type": "llm",
            "api_key": "sk-test-secret",
            "base_url": "https://api.openai.com/v1",
            "llm_model": "gpt-4o",
            "llm_small_model": "gpt-4o-mini",
            "embedding_model": null,
            "embedding_config": null,
            "reranker_model": null,
            "config": {"temperature": 0.2},
            "is_active": true,
            "is_default": false,
            "is_enabled": true,
            "allowed_models": ["gpt-4o"],
            "blocked_models": [],
            "pool_weight": 1.0,
            "pool_enabled": true,
            "model_tier": "large",
            "secondary_models": ["gpt-4o-mini"]
        }));
        assert!(probe.is_ok());

        let create = serde_json::from_value::<ProviderCreateRequest>(json!({
            "name": "strict-openai",
            "provider_type": "openai",
            "api_key": "sk-test-secret",
            "llm_model": "gpt-4o",
            "oauth_token": "must-not-be-ignored"
        }));
        assert!(create.is_err());

        let update = serde_json::from_value::<ProviderUpdateRequest>(json!({
            "expected_revision": 0,
            "credential_value": "must-not-be-ignored"
        }));
        assert!(update.is_err());

        let probe = serde_json::from_value::<ProviderProbeRequest>(json!({
            "name": "strict-openai-probe",
            "provider_type": "openai",
            "api_key": "sk-test-secret",
            "unknown_probe_field": "must-not-be-ignored"
        }));
        assert!(probe.is_err());
    }

    #[test]
    fn provider_persistence_rejects_credential_urls_and_environment_custom_origins() {
        for unsafe_url in [
            "https://user:secret@example.test/v1",
            "https://example.test/v1?api_key=secret",
            "https://example.test/v1#token=secret",
        ] {
            let request = serde_json::from_value::<ProviderCreateRequest>(json!({
                "name": "unsafe-openai",
                "provider_type": "openai",
                "api_key": "sk-test-secret",
                "base_url": unsafe_url,
                "llm_model": "gpt-4o"
            }))
            .expect("unsafe URL request shape deserializes");
            assert!(provider_create_record_with_auth(request).is_err());
        }

        let environment_request = serde_json::from_value::<ProviderCreateRequest>(json!({
            "name": "environment-openai",
            "provider_type": "openai",
            "auth_method": "environment",
            "environment_variable": "OPENAI_API_KEY",
            "base_url": "https://collector.example.test/v1",
            "llm_model": "gpt-4o"
        }))
        .expect("environment request shape deserializes");
        assert!(provider_create_record_with_auth(environment_request).is_err());

        let official_origin_wrong_path = serde_json::from_value::<ProviderCreateRequest>(json!({
            "name": "environment-openai-wrong-path",
            "provider_type": "openai",
            "auth_method": "environment",
            "environment_variable": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1/tenant-secret",
            "llm_model": "gpt-4o"
        }))
        .expect("official-origin wrong-path request deserializes");
        assert!(provider_create_record_with_auth(official_origin_wrong_path).is_err());
    }

    #[tokio::test]
    async fn dev_provider_update_preserves_credentials_and_advances_response_contract() {
        let service = DevLlmProviderCatalogService::default();
        let created = service
            .create_provider(
                "dev-user",
                provider_create_request(
                    "openai",
                    "https://api.example.test/v1".to_string(),
                    Some("sk-dev-secret-12345"),
                    "gpt-4o",
                ),
            )
            .await
            .expect("dev provider create succeeds");

        let updated = service
            .update_provider(
                "dev-user",
                &created.id,
                ProviderUpdateRequest {
                    expected_revision: created.revision,
                    name: Some("updated-openai".to_string()),
                    llm_model: Some("gpt-4o-mini".to_string()),
                    ..Default::default()
                },
            )
            .await
            .expect("dev provider update succeeds")
            .expect("updated provider exists");

        assert_eq!(updated.name, "updated-openai");
        assert_eq!(updated.llm_model.as_deref(), Some("gpt-4o-mini"));
        assert_eq!(updated.auth_method, "api_key");
        assert!(updated.credential_configured);
        let updated_json = serde_json::to_value(&updated).expect("provider response serializes");
        assert_eq!(updated_json["credential_source"], "encrypted_store");
        assert!(!updated.api_key_masked.contains("sk-dev-secret-12345"));
        assert!(updated.revision > created.revision);
        let probe = service
            .provider_probe_config("dev-user", &created.id)
            .await
            .expect("dev probe lookup succeeds")
            .expect("dev probe config exists");
        assert_eq!(probe.api_key.as_deref(), Some("sk-dev-secret-12345"));

        let stale = service
            .update_provider(
                "dev-user",
                &created.id,
                ProviderUpdateRequest {
                    expected_revision: created.revision,
                    name: Some("stale-name".to_string()),
                    ..Default::default()
                },
            )
            .await
            .expect_err("stale revision is rejected");
        assert_eq!(stale.status, StatusCode::CONFLICT);

        let unsafe_endpoint_change = service
            .update_provider(
                "dev-user",
                &created.id,
                ProviderUpdateRequest {
                    expected_revision: updated.revision,
                    base_url: Some(Some("https://other.example.test/v1".to_string())),
                    ..Default::default()
                },
            )
            .await
            .expect_err("endpoint change without a new key is rejected");
        assert_eq!(unsafe_endpoint_change.status, StatusCode::BAD_REQUEST);

        let unsafe_provider_change = service
            .update_provider(
                "dev-user",
                &created.id,
                ProviderUpdateRequest {
                    expected_revision: updated.revision,
                    provider_type: Some("anthropic".to_string()),
                    ..Default::default()
                },
            )
            .await
            .expect_err("provider change without a new key is rejected");
        assert_eq!(unsafe_provider_change.status, StatusCode::BAD_REQUEST);

        let safely_rekeyed = service
            .update_provider(
                "dev-user",
                &created.id,
                ProviderUpdateRequest {
                    expected_revision: updated.revision,
                    api_key: Some("sk-replacement-secret-67890".to_string()),
                    base_url: Some(Some("https://other.example.test/v1".to_string())),
                    ..Default::default()
                },
            )
            .await
            .expect("endpoint change with replacement key succeeds")
            .expect("rekeyed provider exists");
        let probe = service
            .provider_probe_config("dev-user", &created.id)
            .await
            .expect("rekeyed probe lookup succeeds")
            .expect("rekeyed probe config exists");
        assert_eq!(
            probe.api_key.as_deref(),
            Some("sk-replacement-secret-67890")
        );
        assert!(safely_rekeyed.revision > updated.revision);

        let local = service
            .create_provider(
                "dev-user",
                provider_create_request(
                    "ollama",
                    "http://127.0.0.1:11434".to_string(),
                    None,
                    "llama3.1:8b",
                ),
            )
            .await
            .expect("local provider create succeeds");
        let unsafe_auth_change = service
            .update_provider(
                "dev-user",
                &local.id,
                ProviderUpdateRequest {
                    expected_revision: local.revision,
                    provider_type: Some("openai".to_string()),
                    base_url: Some(Some("https://api.openai.com/v1".to_string())),
                    ..Default::default()
                },
            )
            .await
            .expect_err("local to credentialed change requires a new API key");
        assert_eq!(unsafe_auth_change.status, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn dev_provider_update_distinguishes_missing_null_and_empty_base_url() {
        let service = DevLlmProviderCatalogService::default();
        let created = service
            .create_provider(
                "dev-user",
                provider_create_request(
                    "ollama",
                    "http://127.0.0.1:11434".to_string(),
                    None,
                    "llama3.1:8b",
                ),
            )
            .await
            .expect("local provider create succeeds");
        let preserved = service
            .update_provider(
                "dev-user",
                &created.id,
                serde_json::from_value(json!({
                    "expected_revision": created.revision,
                    "name": "renamed-ollama"
                }))
                .expect("missing base URL update deserializes"),
            )
            .await
            .expect("missing base URL update succeeds")
            .expect("provider remains available");
        assert_eq!(
            preserved.base_url.as_deref(),
            Some("http://127.0.0.1:11434")
        );

        let cleared_with_null = service
            .update_provider(
                "dev-user",
                &created.id,
                serde_json::from_value(json!({
                    "expected_revision": preserved.revision,
                    "base_url": null
                }))
                .expect("null base URL update deserializes"),
            )
            .await
            .expect("null base URL update succeeds")
            .expect("provider remains available");
        assert_eq!(cleared_with_null.base_url, None);
        {
            let stored = service.records.lock().await;
            assert_eq!(stored[0].base_url, None);
        }

        let reset = service
            .update_provider(
                "dev-user",
                &created.id,
                serde_json::from_value(json!({
                    "expected_revision": cleared_with_null.revision,
                    "base_url": "http://127.0.0.1:11435"
                }))
                .expect("replacement base URL update deserializes"),
            )
            .await
            .expect("replacement base URL update succeeds")
            .expect("provider remains available");
        assert_eq!(reset.base_url.as_deref(), Some("http://127.0.0.1:11435"));

        let cleared_with_empty = service
            .update_provider(
                "dev-user",
                &created.id,
                serde_json::from_value(json!({
                    "expected_revision": reset.revision,
                    "base_url": "   "
                }))
                .expect("empty base URL update deserializes"),
            )
            .await
            .expect("empty base URL update succeeds")
            .expect("provider remains available");
        assert_eq!(cleared_with_empty.base_url, None);
        let stored = service.records.lock().await;
        assert_eq!(stored[0].base_url, None);
    }

    #[tokio::test]
    async fn dev_no_auth_provider_reports_credentials_not_required() {
        let service = DevLlmProviderCatalogService::default();
        let created = service
            .create_provider(
                "dev-user",
                provider_create_request(
                    "ollama",
                    "http://127.0.0.1:11434".to_string(),
                    None,
                    "llama3.1:8b",
                ),
            )
            .await
            .expect("local provider create succeeds");
        let created_json =
            serde_json::to_value(&created).expect("local provider response serializes");

        assert_eq!(created_json["credential_source"], "not_required");
        assert_eq!(created_json["credential_configured"], true);
    }

    #[tokio::test]
    async fn dev_provider_environment_reference_round_trips_without_persisting_secret() {
        let service = DevLlmProviderCatalogService::default();
        let request = serde_json::from_value::<ProviderCreateRequest>(json!({
            "name": "environment-openai",
            "provider_type": "openai",
            "auth_method": "environment",
            "environment_variable": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "llm_model": "gpt-4o"
        }))
        .expect("environment provider create request deserializes");

        let created = service
            .create_provider("dev-user", request)
            .await
            .expect("environment provider create succeeds");

        assert_eq!(created.auth_method, "environment");
        let created_json =
            serde_json::to_value(&created).expect("environment provider response serializes");
        assert_eq!(created_json["credential_source"], "environment");
        assert_eq!(
            created.environment_variable.as_deref(),
            Some("OPENAI_API_KEY")
        );
        assert!(created.api_key_masked.is_empty());
        assert_eq!(created.config, json!({}));

        let stored = service.records.lock().await;
        assert_eq!(stored[0].api_key_encrypted, LOCAL_NO_API_KEY_SENTINEL);
        assert_eq!(stored[0].config["auth_method"], "environment");
        assert_eq!(stored[0].config["environment_variable"], "OPENAI_API_KEY");
        assert!(!stored[0].config.to_string().contains("sk-"));
        drop(stored);

        let switched = service
            .update_provider(
                "dev-user",
                &created.id,
                serde_json::from_value::<ProviderUpdateRequest>(json!({
                    "expected_revision": created.revision,
                    "auth_method": "api_key",
                    "api_key": "sk-new-explicit-secret"
                }))
                .expect("API-key update request deserializes"),
            )
            .await
            .expect("switching to explicit API key succeeds")
            .expect("updated provider exists");

        assert_eq!(switched.auth_method, "api_key");
        assert!(switched.environment_variable.is_none());
        assert!(!serde_json::to_string(&switched)
            .expect("provider response serializes")
            .contains("sk-new-explicit-secret"));
    }

    #[tokio::test]
    async fn dev_health_service_persists_latest_probe_result() {
        let service = DevLlmProviderHealthService::default();
        let record = ProviderHealthRecord {
            provider_id: "11111111-2222-4333-8444-555555555555".to_string(),
            status: "unhealthy".to_string(),
            last_check: Utc
                .with_ymd_and_hms(2026, 1, 2, 3, 4, 5)
                .single()
                .expect("fixture timestamp is valid"),
            error_message: Some("HTTP 503".to_string()),
            response_time_ms: Some(91),
        };

        service
            .record_health(&record)
            .await
            .expect("dev health write succeeds");
        let latest = service
            .latest_health(&record.provider_id)
            .await
            .expect("dev health read succeeds")
            .expect("dev health record exists");

        assert_eq!(latest.status, "unhealthy");
        assert_eq!(latest.error_message.as_deref(), Some("HTTP 503"));
        assert_eq!(latest.response_time_ms, Some(91));
    }

    #[test]
    fn provider_create_validation_matches_python_model_rules() {
        let missing_key = provider_create_record(ProviderCreateRequest {
            name: "test-openai".to_string(),
            provider_type: "openai".to_string(),
            operation_type: None,
            auth_method: None,
            environment_variable: None,
            api_key: None,
            base_url: None,
            llm_model: Some("gpt-4o".to_string()),
            llm_small_model: None,
            embedding_model: None,
            embedding_config: None,
            reranker_model: None,
            config: None,
            is_active: None,
            is_default: None,
            is_enabled: None,
            allowed_models: None,
            blocked_models: None,
            pool_weight: None,
            pool_enabled: None,
            model_tier: None,
            secondary_models: None,
        })
        .unwrap_err();
        assert_eq!(missing_key.status, StatusCode::BAD_REQUEST);

        let local = provider_create_record(ProviderCreateRequest {
            name: "local-ollama".to_string(),
            provider_type: "ollama".to_string(),
            operation_type: None,
            auth_method: None,
            environment_variable: None,
            api_key: None,
            base_url: Some("http://localhost:11434".to_string()),
            llm_model: Some("llama3.1:8b".to_string()),
            llm_small_model: None,
            embedding_model: None,
            embedding_config: None,
            reranker_model: None,
            config: None,
            is_active: None,
            is_default: None,
            is_enabled: None,
            allowed_models: None,
            blocked_models: None,
            pool_weight: None,
            pool_enabled: None,
            model_tier: None,
            secondary_models: None,
        })
        .expect("local providers may omit api keys");
        assert_eq!(local.api_key_plaintext, LOCAL_NO_API_KEY_SENTINEL);
    }

    #[test]
    fn provider_health_validates_provider_id_like_python() {
        let valid = validate_provider_id("11111111-2222-4333-8444-555555555555")
            .expect("valid UUID parses");
        assert_eq!(valid, "11111111-2222-4333-8444-555555555555");

        let invalid = validate_provider_id("not-a-uuid").unwrap_err();
        assert_eq!(invalid.status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(invalid.detail, "Invalid provider ID");
    }

    #[test]
    fn tenant_assignment_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/llm_provider_tenant_assignments_response.json"
        ))
        .expect("llm provider tenant assignments golden must be valid JSON");

        let value = serde_json::to_value(vec![TenantProviderMappingResponse::from(
            TenantProviderMappingRecord {
                id: "31111111-2222-4333-8444-555555555555".to_string(),
                tenant_id: "tenant-llm".to_string(),
                provider_id: "11111111-2222-4333-8444-555555555555".to_string(),
                operation_type: "llm".to_string(),
                priority: 3,
                created_at: Utc
                    .with_ymd_and_hms(2026, 1, 2, 3, 4, 5)
                    .single()
                    .expect("fixture timestamp is valid"),
            },
        )])
        .expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn tenant_assignment_operation_type_validation_matches_python_enum() {
        assert_eq!(
            validate_operation_type(Some("llm".to_string()))
                .expect("llm operation type is valid")
                .as_deref(),
            Some("llm")
        );
        assert_eq!(
            validate_operation_type(Some("embedding".to_string()))
                .expect("embedding operation type is valid")
                .as_deref(),
            Some("embedding")
        );
        assert_eq!(
            validate_operation_type(Some("rerank".to_string()))
                .expect("rerank operation type is valid")
                .as_deref(),
            Some("rerank")
        );
        assert!(validate_operation_type(None)
            .expect("missing operation type is valid")
            .is_none());

        let invalid = validate_operation_type(Some("chat".to_string())).unwrap_err();
        assert_eq!(invalid.status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(invalid.detail, "Invalid operation_type");
    }

    #[test]
    fn provider_usage_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/llm_provider_usage_response.json"
        ))
        .expect("llm provider usage golden must be valid JSON");

        let response = ProviderUsageResponse {
            provider_id: "11111111-2222-4333-8444-555555555555".to_string(),
            tenant_id: Some("tenant-llm".to_string()),
            statistics: vec![UsageStatisticResponse::from(UsageStatisticRecord {
                provider_id: "11111111-2222-4333-8444-555555555555".to_string(),
                tenant_id: Some("tenant-llm".to_string()),
                operation_type: "llm".to_string(),
                total_requests: 2,
                total_prompt_tokens: 13,
                total_completion_tokens: 27,
                total_tokens: 40,
                total_cost_usd: Some(0.03),
                avg_response_time_ms: None,
                first_request_at: Some(
                    Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0)
                        .single()
                        .expect("fixture timestamp is valid"),
                ),
                last_request_at: Some(
                    Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0)
                        .single()
                        .expect("fixture timestamp is valid"),
                ),
            })],
        };
        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn search_query_validation_matches_bounds() {
        let missing = CatalogSearchQuery::default().validated().unwrap_err();
        assert_eq!(missing.status, StatusCode::UNPROCESSABLE_ENTITY);

        let zero = CatalogSearchQuery {
            q: Some("claude".to_string()),
            provider: None,
            limit: Some(0),
        }
        .validated()
        .unwrap_err();
        assert_eq!(zero.status, StatusCode::UNPROCESSABLE_ENTITY);

        let too_large = CatalogSearchQuery {
            q: Some("claude".to_string()),
            provider: None,
            limit: Some(101),
        }
        .validated()
        .unwrap_err();
        assert_eq!(too_large.status, StatusCode::UNPROCESSABLE_ENTITY);
    }
}
