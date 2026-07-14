//! P7 LLM provider metadata strangler slice.
//!
//! Rust owns authenticated provider-type discovery plus provider metadata CRUD,
//! read-only model catalog
//! list/search/provider-model endpoints backed by the same embedded Python
//! `models_snapshot.json`, admin-only environment provider detection, and latest
//! persisted provider-health reads plus tenant assignment list and provider usage
//! statistics reads. Catalog refresh, active health checks, assignment
//! mutations/provider resolution, system resilience runtime, and usage writes
//! remain Python-owned.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::sync::Arc;
use std::sync::OnceLock;

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

use agistack_adapters_postgres::{
    decrypt_provider_api_key_for_mask, LlmProviderCreateRecord, LlmProviderRecord,
    LlmProviderUpdateRecord, PgLlmProviderRepository, ProviderHealthRecord,
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
const NO_AUTH_METHODS: &[&str] = &["none"];

pub(crate) type SharedLlmProviderHealth = Arc<dyn LlmProviderHealthService>;
pub(crate) type SharedLlmProviders = Arc<dyn LlmProviderCatalogService>;
pub(crate) type SharedLlmProviderAssignments = Arc<dyn LlmProviderAssignmentService>;
pub(crate) type SharedLlmProviderUsage = Arc<dyn LlmProviderUsageService>;

const LOCAL_NO_API_KEY_SENTINEL: &str = "__MEMSTACK_NO_API_KEY__";

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
        let record = provider_create_record(request)?;
        let created = self
            .repo
            .create_provider(&record)
            .await
            .map_err(LlmProvidersApiError::internal)?;
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
        let update = provider_update_record(&existing, request)?;
        let Some(updated) = self
            .repo
            .update_provider(provider_id, &update)
            .await
            .map_err(LlmProvidersApiError::internal)?
        else {
            return Ok(None);
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
}

impl PgLlmProviderCatalogService {
    async fn records_to_responses(
        &self,
        records: Vec<LlmProviderRecord>,
    ) -> Result<Vec<ProviderConfigResponse>, LlmProvidersApiError> {
        let mut responses = Vec::with_capacity(records.len());
        for record in records {
            responses.push(self.record_to_response(record).await?);
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
    records: Mutex<Vec<ProviderConfigResponse>>,
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
            .cloned())
    }

    async fn create_provider(
        &self,
        _user_id: &str,
        request: ProviderCreateRequest,
    ) -> Result<ProviderConfigResponse, LlmProvidersApiError> {
        let record = provider_record_from_create_for_dev(request)?;
        let response = provider_response_from_record(record, None);
        self.records.lock().await.push(response.clone());
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
        let existing = provider_record_from_response(&records[position]);
        let update = provider_update_record(&existing, request)?;
        let mut merged = existing;
        apply_update_to_dev_record(&mut merged, update);
        let response = provider_response_from_record(merged, None);
        records[position] = response.clone();
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
}

#[async_trait]
pub(crate) trait LlmProviderHealthService: Send + Sync {
    async fn latest_health(
        &self,
        provider_id: &str,
    ) -> Result<Option<ProviderHealthResponse>, LlmProvidersApiError>;
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
}

#[derive(Default)]
pub(crate) struct DevLlmProviderHealthService {
    records: BTreeMap<String, ProviderHealthResponse>,
}

#[async_trait]
impl LlmProviderHealthService for DevLlmProviderHealthService {
    async fn latest_health(
        &self,
        provider_id: &str,
    ) -> Result<Option<ProviderHealthResponse>, LlmProvidersApiError> {
        Ok(self.records.get(provider_id).cloned())
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
            "/api/v1/llm-providers/:provider_id",
            get(get_provider)
                .put(update_provider)
                .delete(delete_provider),
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
                auth_methods: if matches!(provider_type, "ollama" | "lmstudio") {
                    NO_AUTH_METHODS
                } else {
                    API_KEY_AUTH_METHODS
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

async fn get_provider_health(
    State(app): State<AppState>,
    Extension(_identity): Extension<Identity>,
    Path(provider_id): Path<String>,
) -> Result<Json<ProviderHealthResponse>, LlmProvidersApiError> {
    let provider_id = validate_provider_id(&provider_id)?;
    let health = app
        .llm_provider_health
        .latest_health(&provider_id)
        .await?
        .ok_or_else(|| {
            LlmProvidersApiError::not_found("No health data available for this provider")
        })?;
    Ok(Json(health))
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

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ProviderCreateRequest {
    name: String,
    provider_type: String,
    operation_type: Option<String>,
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

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct ProviderUpdateRequest {
    name: Option<String>,
    provider_type: Option<String>,
    operation_type: Option<String>,
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
    auth_methods: &'static [&'static str],
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct EnvDetectionResponse {
    detected_providers: BTreeMap<String, EnvProviderView>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct ProviderHealthResponse {
    provider_id: String,
    status: String,
    last_check: String,
    error_message: Option<String>,
    response_time_ms: Option<i32>,
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
    api_key_masked: String,
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
        Self {
            provider_id: record.provider_id,
            status: record.status,
            last_check: record
                .last_check
                .to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true),
            error_message: record.error_message,
            response_time_ms: record.response_time_ms,
        }
    }
}

fn provider_response_from_record(
    record: LlmProviderRecord,
    health: Option<ProviderHealthRecord>,
) -> ProviderConfigResponse {
    let embedding_config = extract_embedding_config(&record.config);
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
        base_url: record.base_url,
        llm_model: record.llm_model,
        llm_small_model: record.llm_small_model,
        embedding_model: record.embedding_model,
        embedding_config,
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
        api_key_masked: mask_api_key(&record.api_key_encrypted),
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

fn provider_record_from_response(response: &ProviderConfigResponse) -> LlmProviderRecord {
    LlmProviderRecord {
        id: response.id.clone(),
        name: response.name.clone(),
        provider_type: response.provider_type.clone(),
        operation_type: response.operation_type.clone(),
        api_key_encrypted: String::new(),
        base_url: response.base_url.clone(),
        llm_model: response.llm_model.clone(),
        llm_small_model: response.llm_small_model.clone(),
        embedding_model: response.embedding_model.clone(),
        reranker_model: response.reranker_model.clone(),
        config: response.config.clone(),
        is_active: response.is_active,
        is_default: response.is_default,
        is_enabled: response.is_enabled,
        allowed_models: response.allowed_models.clone(),
        blocked_models: response.blocked_models.clone(),
        pool_weight: response.pool_weight,
        pool_enabled: response.pool_enabled,
        model_tier: response.model_tier.clone(),
        secondary_models: response.secondary_models.clone(),
        created_at: DateTime::parse_from_rfc3339(&response.created_at)
            .map(|value| value.with_timezone(&Utc))
            .unwrap_or_else(|_| Utc::now()),
        updated_at: DateTime::parse_from_rfc3339(&response.updated_at)
            .map(|value| value.with_timezone(&Utc))
            .unwrap_or_else(|_| Utc::now()),
    }
}

fn provider_record_from_create_for_dev(
    request: ProviderCreateRequest,
) -> Result<LlmProviderRecord, LlmProvidersApiError> {
    let record = provider_create_record(request)?;
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
    if update.base_url.is_some() {
        record.base_url = update.base_url;
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
    record.updated_at = Utc::now();
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
    base_url: Option<String>,
    llm_model: Option<String>,
    llm_small_model: Option<String>,
    embedding_model: Option<String>,
    reranker_model: Option<String>,
}

impl From<EnvProviderConfig> for EnvProviderView {
    fn from(config: EnvProviderConfig) -> Self {
        let credential_configured = config
            .api_key
            .as_deref()
            .is_some_and(|api_key| !api_key.is_empty());

        Self {
            provider_type: config.provider_type,
            operation_type: config.operation_type,
            credential_source: "environment",
            credential_configured,
            base_url: config.base_url,
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

fn provider_update_record(
    existing: &LlmProviderRecord,
    request: ProviderUpdateRequest,
) -> Result<LlmProviderUpdateRecord, LlmProvidersApiError> {
    let provider_type = match request.provider_type {
        Some(value) => normalize_provider_type(value)?,
        None => existing.provider_type.clone(),
    };
    let operation_type = effective_operation_type(&provider_type, request.operation_type)?;
    let mut config = request.config.unwrap_or_else(|| existing.config.clone());
    let embedding_payload = match request.embedding_config.as_ref() {
        Some(_) => build_embedding_payload(
            request.embedding_model.as_deref(),
            request.embedding_config.as_ref(),
        ),
        None if request.embedding_model.is_some() => {
            let mut existing_embedding = existing
                .config
                .get("embedding")
                .and_then(Value::as_object)
                .map(|object| Value::Object(object.clone()))
                .unwrap_or_else(|| json!({}));
            if let Some(model) = request.embedding_model.as_deref() {
                existing_embedding["model"] = json!(model);
            }
            Some(existing_embedding)
        }
        None => extract_embedding_config(&existing.config),
    };
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
    let api_key_plaintext = request
        .api_key
        .map(|api_key| storable_api_key(&provider_type, Some(api_key)))
        .transpose()?;
    Ok(LlmProviderUpdateRecord {
        name: request.name.map(normalize_required_name).transpose()?,
        provider_type: Some(provider_type),
        operation_type: Some(operation_type),
        api_key_plaintext,
        base_url: request.base_url,
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
    if provider_type.ends_with("_embedding") {
        return Ok("embedding".to_string());
    }
    if provider_type.ends_with("_reranker") {
        return Ok("rerank".to_string());
    }
    match validate_operation_type(requested)? {
        Some(value) => Ok(value),
        None => Ok("llm".to_string()),
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
        if let Some(payload) = payload {
            config["embedding"] = payload.clone();
        }
    } else if let Some(object) = config.as_object_mut() {
        object.remove("embedding");
    }
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
        detected_providers.insert((*provider_name).to_string(), config.into());
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
            base_url: env_default(lookup, "DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            llm_model: env_default(lookup, "DEEPSEEK_MODEL", "deepseek-chat"),
            llm_small_model: env_default(lookup, "DEEPSEEK_SMALL_MODEL", "deepseek-v4-flash"),
            embedding_model: None,
            reranker_model: env_raw(lookup, "DEEPSEEK_RERANK_MODEL"),
        },
        "minimax" => EnvProviderConfig {
            provider_type: provider_name.to_string(),
            operation_type: "llm".to_string(),
            api_key: env_nonempty(lookup, "MINIMAX_API_KEY"),
            base_url: env_default(
                lookup,
                "MINIMAX_BASE_URL",
                "https://api.minimax.io/anthropic/v1",
            ),
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
    use chrono::{TimeZone, Utc};
    use serde_json::Value;

    use super::*;

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
    fn provider_type_names_are_unique() {
        let unique = PROVIDER_TYPES.iter().copied().collect::<BTreeSet<_>>();
        assert_eq!(unique.len(), PROVIDER_TYPES.len());
    }

    #[test]
    fn router_builds_with_catalog_and_provider_model_routes() {
        let _ = router();
    }

    #[test]
    fn env_detection_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/llm_env_detection_response.json"
        ))
        .expect("llm env detection golden must be valid JSON");

        let response = detect_env_provider_configs_with(|name| match name {
            "OPENAI_API_KEY" => Some("sk-openai".to_string()),
            "OPENAI_BASE_URL" => Some("https://api.openai.test/v1".to_string()),
            "OLLAMA_BASE_URL" => Some("http://ollama.test".to_string()),
            _ => None,
        });

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
        let serialized = serde_json::to_string(&value).expect("response JSON serializes");
        assert!(!serialized.contains("sk-openai"));
        assert!(!serialized.contains("\"api_key\""));
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

        let value = serde_json::to_value(ProviderHealthResponse::from(ProviderHealthRecord {
            provider_id: "11111111-2222-4333-8444-555555555555".to_string(),
            status: "healthy".to_string(),
            last_check: Utc
                .with_ymd_and_hms(2026, 1, 2, 3, 4, 5)
                .single()
                .expect("fixture timestamp is valid"),
            error_message: None,
            response_time_ms: Some(88),
        }))
        .expect("response serializes");

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
        let value = serde_json::to_value(provider_response_from_record(record, Some(health)))
            .expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn provider_create_validation_matches_python_model_rules() {
        let missing_key = provider_create_record(ProviderCreateRequest {
            name: "test-openai".to_string(),
            provider_type: "openai".to_string(),
            operation_type: None,
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
