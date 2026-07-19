//! Adapter for Python-owned LLM provider rows.
//!
//! Rust owns provider metadata CRUD over the shared `llm_providers` table, but
//! provider-resolution runtime remains Python-owned because it participates in
//! Python's runtime resilience caches. API keys are written with the same Python
//! AES-GCM envelope so Python can continue to decrypt rows created by Rust.

use std::error::Error;
use std::fmt;

use sqlx::types::chrono::{DateTime, Utc};
use sqlx::{QueryBuilder, Row};

use agistack_adapters_secrets::{
    try_decrypt_python_aes256_gcm, try_encrypt_python_aes256_gcm, try_generate_uuid_v4,
};
use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const PROVIDER_COLS: &str = "id::text AS id, name, provider_type, operation_type, \
    api_key_encrypted, base_url, llm_model, llm_small_model, embedding_model, \
    reranker_model, config, is_active, is_default, is_enabled, allowed_models, \
    blocked_models, pool_weight, pool_enabled, model_tier, secondary_models, \
    created_at, updated_at";
const DEFAULT_PROVIDER_LOCK_NAMESPACE: i32 = 0x4D53_5044;
const PROVIDER_NAME_UNIQUE_CONSTRAINT: &str = "llm_providers_name_key";

#[derive(Debug)]
pub enum LlmProviderMutationError {
    NameConflict,
    Storage(CoreError),
}

impl fmt::Display for LlmProviderMutationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NameConflict => formatter.write_str("provider name already exists"),
            Self::Storage(error) => error.fmt(formatter),
        }
    }
}

impl Error for LlmProviderMutationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::NameConflict => None,
            Self::Storage(error) => Some(error),
        }
    }
}

impl From<CoreError> for LlmProviderMutationError {
    fn from(error: CoreError) -> Self {
        Self::Storage(error)
    }
}

pub type LlmProviderMutationResult<T> = Result<T, LlmProviderMutationError>;

#[derive(Debug, Clone, PartialEq)]
pub struct LlmProviderRecord {
    pub id: String,
    pub name: String,
    pub provider_type: String,
    pub operation_type: String,
    pub api_key_encrypted: String,
    pub base_url: Option<String>,
    pub llm_model: Option<String>,
    pub llm_small_model: Option<String>,
    pub embedding_model: Option<String>,
    pub reranker_model: Option<String>,
    pub config: serde_json::Value,
    pub is_active: bool,
    pub is_default: bool,
    pub is_enabled: bool,
    pub allowed_models: Vec<String>,
    pub blocked_models: Vec<String>,
    pub pool_weight: f64,
    pub pool_enabled: bool,
    pub model_tier: Option<String>,
    pub secondary_models: Vec<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LlmProviderCreateRecord {
    pub name: String,
    pub provider_type: String,
    pub operation_type: String,
    pub api_key_plaintext: String,
    pub base_url: Option<String>,
    pub llm_model: Option<String>,
    pub llm_small_model: Option<String>,
    pub embedding_model: Option<String>,
    pub reranker_model: Option<String>,
    pub config: serde_json::Value,
    pub is_active: bool,
    pub is_default: bool,
    pub is_enabled: bool,
    pub allowed_models: Vec<String>,
    pub blocked_models: Vec<String>,
    pub pool_weight: f64,
    pub pool_enabled: bool,
    pub model_tier: Option<String>,
    pub secondary_models: Vec<String>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct LlmProviderUpdateRecord {
    pub expected_updated_at: DateTime<Utc>,
    pub name: Option<String>,
    pub provider_type: Option<String>,
    pub operation_type: Option<String>,
    pub api_key_plaintext: Option<String>,
    /// `None` preserves the current value, `Some(None)` clears it, and
    /// `Some(Some(url))` replaces it.
    pub base_url: Option<Option<String>>,
    pub llm_model: Option<String>,
    pub llm_small_model: Option<String>,
    pub embedding_model: Option<String>,
    pub reranker_model: Option<String>,
    pub config: Option<serde_json::Value>,
    pub is_active: Option<bool>,
    pub is_default: Option<bool>,
    pub is_enabled: Option<bool>,
    pub allowed_models: Option<Vec<String>>,
    pub blocked_models: Option<Vec<String>>,
    pub pool_weight: Option<f64>,
    pub pool_enabled: Option<bool>,
    pub model_tier: Option<String>,
    pub secondary_models: Option<Vec<String>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProviderHealthRecord {
    pub provider_id: String,
    pub status: String,
    pub last_check: DateTime<Utc>,
    pub error_message: Option<String>,
    pub response_time_ms: Option<i32>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TenantProviderMappingRecord {
    pub id: String,
    pub tenant_id: String,
    pub provider_id: String,
    pub operation_type: String,
    pub priority: i32,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct UsageStatisticRecord {
    pub provider_id: String,
    pub tenant_id: Option<String>,
    pub operation_type: String,
    pub total_requests: i64,
    pub total_prompt_tokens: i64,
    pub total_completion_tokens: i64,
    pub total_tokens: i64,
    pub total_cost_usd: Option<f64>,
    pub avg_response_time_ms: Option<f64>,
    pub first_request_at: Option<DateTime<Utc>>,
    pub last_request_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct UsageStatisticsQuery<'a> {
    pub provider_id: Option<&'a str>,
    pub tenant_id: Option<&'a str>,
    pub operation_type: Option<&'a str>,
    pub start_date: Option<DateTime<Utc>>,
    pub end_date: Option<DateTime<Utc>>,
}

pub struct PgLlmProviderRepository {
    pool: PgPool,
}

impl PgLlmProviderRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list_providers(
        &self,
        include_inactive: bool,
    ) -> CoreResult<Vec<LlmProviderRecord>> {
        let sql = if include_inactive {
            format!("SELECT {PROVIDER_COLS} FROM llm_providers ORDER BY created_at")
        } else {
            format!("SELECT {PROVIDER_COLS} FROM llm_providers WHERE is_active ORDER BY created_at")
        };
        let rows = sqlx::query(&sql)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list llm providers: {e}")))?;
        rows.into_iter().map(row_to_provider).collect()
    }

    pub async fn get_provider(&self, provider_id: &str) -> CoreResult<Option<LlmProviderRecord>> {
        let sql = format!("SELECT {PROVIDER_COLS} FROM llm_providers WHERE id = $1::uuid");
        sqlx::query(&sql)
            .bind(provider_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("read llm provider: {e}")))?
            .map(row_to_provider)
            .transpose()
    }

    pub async fn create_provider(
        &self,
        record: &LlmProviderCreateRecord,
    ) -> LlmProviderMutationResult<LlmProviderRecord> {
        let provider_id = try_generate_uuid_v4()
            .map_err(|e| CoreError::Storage(format!("generate llm provider id: {e}")))?;
        let api_key_encrypted = encrypt_provider_api_key(&record.api_key_plaintext)?;
        let allowed_models = json_string_or_none(&record.allowed_models)?;
        let blocked_models = json_string_or_none(&record.blocked_models)?;
        let secondary_models = json_value_or_none(&record.secondary_models);
        let mut transaction = self.pool.begin().await.map_err(|error| {
            provider_mutation_storage_error("begin create llm provider transaction", error)
        })?;
        if record.is_default {
            acquire_default_operation_lock(&mut transaction, &record.operation_type).await?;
        }
        let sql = format!(
            "INSERT INTO llm_providers (\
             id, name, provider_type, operation_type, api_key_encrypted, base_url, \
             llm_model, llm_small_model, embedding_model, reranker_model, config, \
             is_active, is_default, is_enabled, allowed_models, blocked_models, \
             pool_weight, pool_enabled, model_tier, secondary_models, created_at, updated_at\
         ) VALUES (\
             $1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,now(),now()\
         ) RETURNING {PROVIDER_COLS}"
        );
        let row = sqlx::query(&sql)
            .bind(&provider_id)
            .bind(&record.name)
            .bind(&record.provider_type)
            .bind(&record.operation_type)
            .bind(api_key_encrypted)
            .bind(&record.base_url)
            .bind(&record.llm_model)
            .bind(&record.llm_small_model)
            .bind(&record.embedding_model)
            .bind(&record.reranker_model)
            .bind(&record.config)
            .bind(record.is_active)
            .bind(record.is_default)
            .bind(record.is_enabled)
            .bind(&allowed_models)
            .bind(&blocked_models)
            .bind(record.pool_weight)
            .bind(record.pool_enabled)
            .bind(&record.model_tier)
            .bind(&secondary_models)
            .fetch_one(&mut *transaction)
            .await
            .map_err(|error| provider_mutation_sqlx_error("create llm provider", error))?;
        if record.is_default {
            demote_other_operation_defaults(&mut transaction, &record.operation_type, &provider_id)
                .await?;
        }
        let created = row_to_provider(row)?;
        transaction.commit().await.map_err(|error| {
            provider_mutation_storage_error("commit create llm provider transaction", error)
        })?;
        Ok(created)
    }

    pub async fn update_provider(
        &self,
        provider_id: &str,
        update: &LlmProviderUpdateRecord,
    ) -> LlmProviderMutationResult<Option<LlmProviderRecord>> {
        let Some(existing) = self.get_provider(provider_id).await? else {
            return Ok(None);
        };

        let target_operation = update
            .operation_type
            .as_deref()
            .unwrap_or(&existing.operation_type)
            .to_string();
        let target_is_default = update.is_default.unwrap_or(existing.is_default);
        let mut transaction = self.pool.begin().await.map_err(|error| {
            provider_mutation_storage_error("begin update llm provider transaction", error)
        })?;
        if target_is_default {
            acquire_default_operation_lock(&mut transaction, &target_operation).await?;
        }
        let select_sql =
            format!("SELECT {PROVIDER_COLS} FROM llm_providers WHERE id = $1::uuid FOR UPDATE");
        let Some(row) = sqlx::query(&select_sql)
            .bind(provider_id)
            .fetch_optional(&mut *transaction)
            .await
            .map_err(|error| provider_mutation_sqlx_error("lock llm provider for update", error))?
        else {
            transaction.rollback().await.map_err(|error| {
                provider_mutation_storage_error("rollback missing llm provider update", error)
            })?;
            return Ok(None);
        };
        let existing = row_to_provider(row)?;
        if existing.updated_at != update.expected_updated_at {
            transaction.rollback().await.map_err(|error| {
                provider_mutation_storage_error("rollback stale llm provider update", error)
            })?;
            return Ok(None);
        }

        let api_key_encrypted = match update.api_key_plaintext.as_deref() {
            Some(api_key) => encrypt_provider_api_key(api_key)?,
            None => existing.api_key_encrypted,
        };
        let allowed_models = json_string_or_none(
            update
                .allowed_models
                .as_ref()
                .unwrap_or(&existing.allowed_models),
        )?;
        let blocked_models = json_string_or_none(
            update
                .blocked_models
                .as_ref()
                .unwrap_or(&existing.blocked_models),
        )?;
        let secondary_models = json_value_or_none(
            update
                .secondary_models
                .as_ref()
                .unwrap_or(&existing.secondary_models),
        );

        let provider_type = update
            .provider_type
            .as_ref()
            .unwrap_or(&existing.provider_type);
        let operation_type = update
            .operation_type
            .as_ref()
            .unwrap_or(&existing.operation_type);
        let target_is_default = update.is_default.unwrap_or(existing.is_default);
        if target_is_default {
            demote_other_operation_defaults(&mut transaction, operation_type, provider_id).await?;
        }
        let config = update.config.as_ref().unwrap_or(&existing.config);
        let base_url = match &update.base_url {
            Some(value) => value.as_ref(),
            None => existing.base_url.as_ref(),
        };
        let replace_model_fields = update.provider_type.is_some()
            || update.operation_type.is_some()
            || update.config.is_some();
        let sql = format!(
            "UPDATE llm_providers SET \
                 name=$2, provider_type=$3, operation_type=$4, api_key_encrypted=$5, \
                 base_url=$6, llm_model=$7, llm_small_model=$8, embedding_model=$9, \
                 reranker_model=$10, config=$11, is_active=$12, is_default=$13, \
                 is_enabled=$14, allowed_models=$15, blocked_models=$16, \
                 pool_weight=$17, pool_enabled=$18, model_tier=$19, \
                 secondary_models=$20, \
                 updated_at=GREATEST(now(), updated_at + interval '1 microsecond') \
             WHERE id=$1::uuid AND updated_at = $21::timestamptz \
             RETURNING {PROVIDER_COLS}"
        );
        let updated = sqlx::query(&sql)
            .bind(provider_id)
            .bind(update.name.as_ref().unwrap_or(&existing.name))
            .bind(provider_type)
            .bind(operation_type)
            .bind(api_key_encrypted)
            .bind(base_url)
            .bind(if replace_model_fields {
                update.llm_model.as_ref()
            } else {
                update.llm_model.as_ref().or(existing.llm_model.as_ref())
            })
            .bind(if replace_model_fields {
                update.llm_small_model.as_ref()
            } else {
                update
                    .llm_small_model
                    .as_ref()
                    .or(existing.llm_small_model.as_ref())
            })
            .bind(if replace_model_fields {
                update.embedding_model.as_ref()
            } else {
                update
                    .embedding_model
                    .as_ref()
                    .or(existing.embedding_model.as_ref())
            })
            .bind(if replace_model_fields {
                update.reranker_model.as_ref()
            } else {
                update
                    .reranker_model
                    .as_ref()
                    .or(existing.reranker_model.as_ref())
            })
            .bind(config)
            .bind(update.is_active.unwrap_or(existing.is_active))
            .bind(update.is_default.unwrap_or(existing.is_default))
            .bind(update.is_enabled.unwrap_or(existing.is_enabled))
            .bind(&allowed_models)
            .bind(&blocked_models)
            .bind(update.pool_weight.unwrap_or(existing.pool_weight))
            .bind(update.pool_enabled.unwrap_or(existing.pool_enabled))
            .bind(if replace_model_fields {
                update.model_tier.as_ref()
            } else {
                update.model_tier.as_ref().or(existing.model_tier.as_ref())
            })
            .bind(&secondary_models)
            .bind(update.expected_updated_at)
            .fetch_optional(&mut *transaction)
            .await
            .map_err(|error| provider_mutation_sqlx_error("update llm provider", error))?
            .map(row_to_provider)
            .transpose()?;
        transaction.commit().await.map_err(|error| {
            provider_mutation_storage_error("commit update llm provider transaction", error)
        })?;
        Ok(updated)
    }

    pub async fn soft_delete_provider(&self, provider_id: &str) -> CoreResult<bool> {
        let result = sqlx::query(
            "UPDATE llm_providers SET is_active = false, updated_at = now() WHERE id = $1::uuid",
        )
        .bind(provider_id)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("soft delete llm provider: {e}")))?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn latest_health(
        &self,
        provider_id: &str,
    ) -> CoreResult<Option<ProviderHealthRecord>> {
        let row = sqlx::query(
            "SELECT provider_id::text AS provider_id, status, last_check, error_message, response_time_ms \
             FROM provider_health \
             WHERE provider_id = $1::uuid \
             ORDER BY last_check DESC \
             LIMIT 1",
        )
        .bind(provider_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("read latest provider health: {e}")))?;

        row.map(|row| {
            Ok(ProviderHealthRecord {
                provider_id: row.try_get("provider_id")?,
                status: row.try_get("status")?,
                last_check: row.try_get("last_check")?,
                error_message: row.try_get("error_message")?,
                response_time_ms: row.try_get("response_time_ms")?,
            })
        })
        .transpose()
        .map_err(|e: sqlx::Error| CoreError::Storage(format!("decode latest provider health: {e}")))
    }

    /// Batch variant of [`latest_health`](Self::latest_health): one
    /// `DISTINCT ON` query for every provider's latest health row instead of
    /// one round-trip per provider (the list endpoint calls this per row).
    pub async fn latest_health_batch(
        &self,
        provider_ids: &[String],
    ) -> CoreResult<Vec<ProviderHealthRecord>> {
        if provider_ids.is_empty() {
            return Ok(Vec::new());
        }
        let rows = sqlx::query(
            "SELECT DISTINCT ON (provider_id) provider_id::text AS provider_id, status, last_check, error_message, response_time_ms \
             FROM provider_health \
             WHERE provider_id = ANY($1::uuid[]) \
             ORDER BY provider_id, last_check DESC",
        )
        .bind(provider_ids)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("read latest provider health batch: {e}")))?;

        rows.into_iter()
            .map(|row| {
                Ok(ProviderHealthRecord {
                    provider_id: row.try_get("provider_id")?,
                    status: row.try_get("status")?,
                    last_check: row.try_get("last_check")?,
                    error_message: row.try_get("error_message")?,
                    response_time_ms: row.try_get("response_time_ms")?,
                })
            })
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("decode latest provider health batch: {e}")))
    }

    pub async fn record_health(
        &self,
        record: &ProviderHealthRecord,
    ) -> CoreResult<ProviderHealthRecord> {
        sqlx::query(
            "INSERT INTO provider_health (\
                 provider_id, status, last_check, error_message, response_time_ms\
             ) VALUES ($1::uuid, $2, $3, $4, $5) \
             RETURNING provider_id::text AS provider_id, status, last_check, \
                       error_message, response_time_ms",
        )
        .bind(&record.provider_id)
        .bind(&record.status)
        .bind(record.last_check)
        .bind(&record.error_message)
        .bind(record.response_time_ms)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("record provider health: {e}")))
        .and_then(|row| {
            Ok(ProviderHealthRecord {
                provider_id: row.try_get("provider_id").map_err(storage)?,
                status: row.try_get("status").map_err(storage)?,
                last_check: row.try_get("last_check").map_err(storage)?,
                error_message: row.try_get("error_message").map_err(storage)?,
                response_time_ms: row.try_get("response_time_ms").map_err(storage)?,
            })
        })
    }

    pub async fn user_can_read_tenant_assignments(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> CoreResult<bool> {
        let is_admin = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM user_roles \
             JOIN roles ON roles.id = user_roles.role_id \
             WHERE user_roles.user_id = $1 \
               AND roles.name = 'admin'",
        )
        .bind(user_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read llm provider admin access: {e}")))?;
        if is_admin {
            return Ok(true);
        }

        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read llm provider tenant access: {e}")))
    }

    pub async fn user_has_provider_admin_role(&self, user_id: &str) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) \
             FROM user_roles \
             JOIN roles ON roles.id = user_roles.role_id \
             WHERE user_roles.user_id = $1 \
               AND roles.name = 'admin'",
        )
        .bind(user_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read llm provider admin role: {e}")))
    }

    pub async fn default_tenant_for_user(&self, user_id: &str) -> CoreResult<Option<String>> {
        sqlx::query_as::<_, (String,)>(
            "SELECT tenant_id \
             FROM user_tenants \
             WHERE user_id = $1 \
             ORDER BY created_at ASC, id ASC \
             LIMIT 1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(tenant_id,)| tenant_id))
        .map_err(|e| CoreError::Storage(format!("read llm provider default tenant: {e}")))
    }

    pub async fn list_tenant_assignments(
        &self,
        tenant_id: &str,
        operation_type: Option<&str>,
    ) -> CoreResult<Vec<TenantProviderMappingRecord>> {
        let rows = sqlx::query(
            "SELECT id::text AS id, tenant_id, provider_id::text AS provider_id, \
                    operation_type, priority, created_at \
             FROM tenant_provider_mappings \
             WHERE tenant_id = $1 \
               AND ($2::text IS NULL OR operation_type = $2::text) \
             ORDER BY priority",
        )
        .bind(tenant_id)
        .bind(operation_type)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("list tenant provider assignments: {e}")))?;

        rows.into_iter()
            .map(|row| {
                Ok(TenantProviderMappingRecord {
                    id: row.try_get("id")?,
                    tenant_id: row.try_get("tenant_id")?,
                    provider_id: row.try_get("provider_id")?,
                    operation_type: row.try_get("operation_type")?,
                    priority: row.try_get("priority")?,
                    created_at: row.try_get("created_at")?,
                })
            })
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("decode tenant provider assignments: {e}")))
    }

    pub async fn usage_statistics(
        &self,
        query: UsageStatisticsQuery<'_>,
    ) -> CoreResult<Vec<UsageStatisticRecord>> {
        let mut builder = QueryBuilder::new(
            "SELECT provider_id::text AS provider_id, tenant_id, operation_type, \
                    count(id)::bigint AS total_requests, \
                    COALESCE(sum(prompt_tokens), 0)::bigint AS total_prompt_tokens, \
                    COALESCE(sum(completion_tokens), 0)::bigint AS total_completion_tokens, \
                    COALESCE(sum(prompt_tokens + completion_tokens), 0)::bigint AS total_tokens, \
                    sum(cost_usd)::float8 AS total_cost_usd, \
                    NULL::float8 AS avg_response_time_ms, \
                    min(created_at) AS first_request_at, \
                    max(created_at) AS last_request_at \
             FROM llm_usage_logs \
             WHERE 1 = 1",
        );
        if let Some(provider_id) = query.provider_id {
            builder
                .push(" AND provider_id = ")
                .push_bind(provider_id)
                .push("::uuid");
        }
        if let Some(tenant_id) = query.tenant_id {
            builder.push(" AND tenant_id = ").push_bind(tenant_id);
        }
        if let Some(operation_type) = query.operation_type {
            builder
                .push(" AND operation_type = ")
                .push_bind(operation_type);
        }
        if let Some(start_date) = query.start_date {
            builder.push(" AND created_at >= ").push_bind(start_date);
        }
        if let Some(end_date) = query.end_date {
            builder.push(" AND created_at <= ").push_bind(end_date);
        }
        builder.push(" GROUP BY provider_id, tenant_id, operation_type");

        let rows =
            builder.build().fetch_all(&self.pool).await.map_err(|e| {
                CoreError::Storage(format!("list llm provider usage statistics: {e}"))
            })?;

        rows.into_iter()
            .map(|row| {
                Ok(UsageStatisticRecord {
                    provider_id: row.try_get("provider_id")?,
                    tenant_id: row.try_get("tenant_id")?,
                    operation_type: row.try_get("operation_type")?,
                    total_requests: row.try_get("total_requests")?,
                    total_prompt_tokens: row.try_get("total_prompt_tokens")?,
                    total_completion_tokens: row.try_get("total_completion_tokens")?,
                    total_tokens: row.try_get("total_tokens")?,
                    total_cost_usd: row.try_get("total_cost_usd")?,
                    avg_response_time_ms: row.try_get("avg_response_time_ms")?,
                    first_request_at: row.try_get("first_request_at")?,
                    last_request_at: row.try_get("last_request_at")?,
                })
            })
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("decode llm provider usage statistics: {e}")))
    }
}

fn provider_mutation_storage_error(context: &str, error: sqlx::Error) -> LlmProviderMutationError {
    LlmProviderMutationError::Storage(CoreError::Storage(format!("{context}: {error}")))
}

fn provider_mutation_sqlx_error(context: &str, error: sqlx::Error) -> LlmProviderMutationError {
    let is_provider_name_conflict = error.as_database_error().is_some_and(|database_error| {
        database_error.code().as_deref() == Some("23505")
            && database_error.constraint() == Some(PROVIDER_NAME_UNIQUE_CONSTRAINT)
    });
    if is_provider_name_conflict {
        LlmProviderMutationError::NameConflict
    } else {
        provider_mutation_storage_error(context, error)
    }
}

fn default_operation_lock_id(operation_type: &str) -> Result<i32, LlmProviderMutationError> {
    match operation_type {
        "llm" => Ok(1),
        "embedding" => Ok(2),
        "rerank" => Ok(3),
        _ => Err(LlmProviderMutationError::Storage(CoreError::Storage(
            "invalid provider operation type for default transition".to_string(),
        ))),
    }
}

async fn acquire_default_operation_lock(
    transaction: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    operation_type: &str,
) -> LlmProviderMutationResult<()> {
    let operation_lock_id = default_operation_lock_id(operation_type)?;
    sqlx::query("SELECT pg_advisory_xact_lock($1, $2)")
        .bind(DEFAULT_PROVIDER_LOCK_NAMESPACE)
        .bind(operation_lock_id)
        .execute(&mut **transaction)
        .await
        .map_err(|error| {
            provider_mutation_storage_error("acquire provider default operation lock", error)
        })?;
    Ok(())
}

async fn demote_other_operation_defaults(
    transaction: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    operation_type: &str,
    provider_id: &str,
) -> LlmProviderMutationResult<()> {
    sqlx::query(
        "UPDATE llm_providers SET \
             is_default = false, \
             updated_at = GREATEST(now(), updated_at + interval '1 microsecond') \
         WHERE operation_type = $1 AND is_default AND id <> $2::uuid",
    )
    .bind(operation_type)
    .bind(provider_id)
    .execute(&mut **transaction)
    .await
    .map_err(|error| {
        provider_mutation_storage_error("demote previous llm provider defaults", error)
    })?;
    Ok(())
}

fn row_to_provider(row: sqlx::postgres::PgRow) -> CoreResult<LlmProviderRecord> {
    let allowed_models: Option<String> = row.try_get("allowed_models").map_err(storage)?;
    let blocked_models: Option<String> = row.try_get("blocked_models").map_err(storage)?;
    let secondary_models: Option<serde_json::Value> =
        row.try_get("secondary_models").map_err(storage)?;
    Ok(LlmProviderRecord {
        id: row.try_get("id").map_err(storage)?,
        name: row.try_get("name").map_err(storage)?,
        provider_type: row.try_get("provider_type").map_err(storage)?,
        operation_type: row.try_get("operation_type").map_err(storage)?,
        api_key_encrypted: row.try_get("api_key_encrypted").map_err(storage)?,
        base_url: row.try_get("base_url").map_err(storage)?,
        llm_model: row.try_get("llm_model").map_err(storage)?,
        llm_small_model: row.try_get("llm_small_model").map_err(storage)?,
        embedding_model: row.try_get("embedding_model").map_err(storage)?,
        reranker_model: row.try_get("reranker_model").map_err(storage)?,
        config: row
            .try_get("config")
            .map_err(storage)
            .unwrap_or_else(|_| serde_json::json!({})),
        is_active: row.try_get("is_active").map_err(storage)?,
        is_default: row.try_get("is_default").map_err(storage)?,
        is_enabled: row.try_get("is_enabled").map_err(storage)?,
        allowed_models: parse_string_array(allowed_models.as_deref()),
        blocked_models: parse_string_array(blocked_models.as_deref()),
        pool_weight: row.try_get("pool_weight").map_err(storage)?,
        pool_enabled: row.try_get("pool_enabled").map_err(storage)?,
        model_tier: row.try_get("model_tier").map_err(storage)?,
        secondary_models: parse_value_array(secondary_models.as_ref()),
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

fn parse_string_array(value: Option<&str>) -> Vec<String> {
    value
        .and_then(|raw| serde_json::from_str::<Vec<String>>(raw).ok())
        .unwrap_or_default()
}

fn parse_value_array(value: Option<&serde_json::Value>) -> Vec<String> {
    value
        .and_then(serde_json::Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(serde_json::Value::as_str)
                .map(ToOwned::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

fn json_string_or_none(values: &[String]) -> CoreResult<Option<String>> {
    if values.is_empty() {
        Ok(None)
    } else {
        serde_json::to_string(values)
            .map(Some)
            .map_err(|e| CoreError::Storage(format!("encode llm provider model filter: {e}")))
    }
}

fn json_value_or_none(values: &[String]) -> Option<serde_json::Value> {
    (!values.is_empty()).then(|| serde_json::json!(values))
}

fn encrypt_provider_api_key(plaintext: &str) -> CoreResult<String> {
    let key = std::env::var("LLM_ENCRYPTION_KEY").map_err(|_| {
        CoreError::Storage("LLM_ENCRYPTION_KEY is required to write llm provider keys".to_string())
    })?;
    try_encrypt_python_aes256_gcm(plaintext, &key)
        .map_err(|e| CoreError::Storage(format!("encrypt llm provider api key: {e}")))
}

pub fn decrypt_provider_api_key_for_mask(encrypted: &str) -> Option<String> {
    let key = std::env::var("LLM_ENCRYPTION_KEY").ok()?;
    try_decrypt_python_aes256_gcm(encrypted, &key).ok()
}

fn storage(e: sqlx::Error) -> CoreError {
    CoreError::Storage(e.to_string())
}
