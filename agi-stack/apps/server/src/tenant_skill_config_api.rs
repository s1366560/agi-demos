//! P5 tenant skill config foundation.
//!
//! Mirrors Python's `/api/v1/tenant/skills/config` router for database-backed
//! tenant overrides of system skills. Filesystem skill loading remains in the
//! skill service; this module only persists tenant-level disable/override rows.

use std::cmp::Reverse;
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;

use agistack_adapters_postgres::{PgTenantSkillConfigRepository, TenantSkillConfigRecord};
use agistack_adapters_secrets::generate_uuid_v4;

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedTenantSkillConfigs = Arc<dyn TenantSkillConfigService>;

#[async_trait]
pub(crate) trait TenantSkillConfigService: Send + Sync {
    async fn list_configs(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<TenantSkillConfigListView, TenantSkillConfigApiError>;

    async fn get_config(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError>;

    async fn disable_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillPayload,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError>;

    async fn override_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: OverrideSkillPayload,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError>;

    async fn enable_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillPayload,
    ) -> Result<(), TenantSkillConfigApiError>;

    async fn delete_config(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<(), TenantSkillConfigApiError>;

    async fn skill_status(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<TenantSkillStatusView, TenantSkillConfigApiError>;
}

#[derive(Debug)]
pub(crate) struct TenantSkillConfigApiError {
    status: StatusCode,
    detail: String,
}

impl TenantSkillConfigApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }

    pub(crate) fn into_parts(self) -> (StatusCode, String) {
        (self.status, self.detail)
    }
}

impl IntoResponse for TenantSkillConfigApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[derive(Debug, Clone, Deserialize)]
struct TenantQuery {
    #[serde(default)]
    tenant_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SystemSkillPayload {
    system_skill_name: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct OverrideSkillPayload {
    system_skill_name: String,
    override_skill_id: String,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TenantSkillConfigView {
    id: String,
    tenant_id: String,
    system_skill_name: String,
    action: String,
    override_skill_id: Option<String>,
    created_at: String,
    updated_at: String,
}

impl From<TenantSkillConfigRecord> for TenantSkillConfigView {
    fn from(record: TenantSkillConfigRecord) -> Self {
        let updated_at = record.updated_at.unwrap_or(record.created_at);
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            system_skill_name: record.system_skill_name,
            action: record.action,
            override_skill_id: record.override_skill_id,
            created_at: iso8601(record.created_at),
            updated_at: iso8601(updated_at),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TenantSkillConfigListView {
    configs: Vec<TenantSkillConfigView>,
    total: i64,
}

impl TenantSkillConfigListView {
    pub(crate) fn disabled_system_skill_names(&self) -> HashSet<String> {
        self.configs
            .iter()
            .filter(|config| config.action == "disable")
            .map(|config| config.system_skill_name.clone())
            .collect()
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TenantSkillStatusView {
    system_skill_name: String,
    status: String,
    action: Option<String>,
    override_skill_id: Option<String>,
}

pub(crate) struct PgTenantSkillConfigService {
    repo: PgTenantSkillConfigRepository,
}

impl PgTenantSkillConfigService {
    pub(crate) fn new(repo: PgTenantSkillConfigRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl TenantSkillConfigService for PgTenantSkillConfigService {
    async fn list_configs(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<TenantSkillConfigListView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let configs = self
            .repo
            .list_by_tenant(&tenant_id)
            .await
            .map_err(TenantSkillConfigApiError::internal)?;
        let total = self
            .repo
            .count_by_tenant(&tenant_id)
            .await
            .map_err(TenantSkillConfigApiError::internal)?;
        Ok(TenantSkillConfigListView {
            configs: configs
                .into_iter()
                .map(TenantSkillConfigView::from)
                .collect(),
            total,
        })
    }

    async fn get_config(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let config = self
            .repo
            .get_by_tenant_and_skill(&tenant_id, system_skill_name)
            .await
            .map_err(TenantSkillConfigApiError::internal)?
            .ok_or_else(|| TenantSkillConfigApiError::not_found("Skill configuration not found"))?;
        Ok(config.into())
    }

    async fn disable_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillPayload,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let system_skill_name = validate_system_skill_name(&body.system_skill_name)?;
        let existing = self
            .repo
            .get_by_tenant_and_skill(&tenant_id, system_skill_name)
            .await
            .map_err(TenantSkillConfigApiError::internal)?;
        let now = Utc::now();
        let record = match existing {
            Some(mut record) => {
                record.action = "disable".to_string();
                record.override_skill_id = None;
                record.updated_at = Some(now);
                self.repo
                    .update(&record)
                    .await
                    .map_err(TenantSkillConfigApiError::internal)?
            }
            None => {
                let record = TenantSkillConfigRecord {
                    id: generate_uuid_v4(),
                    tenant_id,
                    system_skill_name: system_skill_name.to_string(),
                    action: "disable".to_string(),
                    override_skill_id: None,
                    created_at: now,
                    updated_at: Some(now),
                };
                self.repo
                    .create(&record)
                    .await
                    .map_err(TenantSkillConfigApiError::internal)?
            }
        };
        Ok(record.into())
    }

    async fn override_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: OverrideSkillPayload,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let system_skill_name = validate_system_skill_name(&body.system_skill_name)?;
        let override_skill_id = validate_system_skill_name(&body.override_skill_id)?;
        match self
            .repo
            .override_skill_belongs_to_tenant(override_skill_id, &tenant_id)
            .await
            .map_err(TenantSkillConfigApiError::internal)?
        {
            Some(true) => {}
            Some(false) => {
                return Err(TenantSkillConfigApiError::forbidden(
                    "Override skill must belong to your tenant",
                ));
            }
            None => {
                return Err(TenantSkillConfigApiError::not_found(
                    "Override skill not found",
                ));
            }
        }

        let existing = self
            .repo
            .get_by_tenant_and_skill(&tenant_id, system_skill_name)
            .await
            .map_err(TenantSkillConfigApiError::internal)?;
        let now = Utc::now();
        let record = match existing {
            Some(mut record) => {
                record.action = "override".to_string();
                record.override_skill_id = Some(override_skill_id.to_string());
                record.updated_at = Some(now);
                self.repo
                    .update(&record)
                    .await
                    .map_err(TenantSkillConfigApiError::internal)?
            }
            None => {
                let record = TenantSkillConfigRecord {
                    id: generate_uuid_v4(),
                    tenant_id,
                    system_skill_name: system_skill_name.to_string(),
                    action: "override".to_string(),
                    override_skill_id: Some(override_skill_id.to_string()),
                    created_at: now,
                    updated_at: Some(now),
                };
                self.repo
                    .create(&record)
                    .await
                    .map_err(TenantSkillConfigApiError::internal)?
            }
        };
        Ok(record.into())
    }

    async fn enable_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillPayload,
    ) -> Result<(), TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let system_skill_name = validate_system_skill_name(&body.system_skill_name)?;
        let deleted = self
            .repo
            .delete_by_tenant_and_skill(&tenant_id, system_skill_name)
            .await
            .map_err(TenantSkillConfigApiError::internal)?;
        if deleted {
            Ok(())
        } else {
            Err(TenantSkillConfigApiError::not_found(
                "Skill configuration not found",
            ))
        }
    }

    async fn delete_config(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<(), TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let system_skill_name = validate_system_skill_name(system_skill_name)?;
        let existing = self
            .repo
            .get_by_tenant_and_skill(&tenant_id, system_skill_name)
            .await
            .map_err(TenantSkillConfigApiError::internal)?
            .ok_or_else(|| TenantSkillConfigApiError::not_found("Skill configuration not found"))?;
        self.repo
            .delete(&existing.id)
            .await
            .map_err(TenantSkillConfigApiError::internal)?;
        Ok(())
    }

    async fn skill_status(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<TenantSkillStatusView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let system_skill_name = validate_system_skill_name(system_skill_name)?;
        let config = self
            .repo
            .get_by_tenant_and_skill(&tenant_id, system_skill_name)
            .await
            .map_err(TenantSkillConfigApiError::internal)?;
        Ok(skill_status_view(system_skill_name, config))
    }
}

impl PgTenantSkillConfigService {
    async fn resolve_tenant(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<String, TenantSkillConfigApiError> {
        if let Some(tenant_id) = present(tenant_id) {
            let allowed = self
                .repo
                .user_has_tenant_access(user_id, tenant_id)
                .await
                .map_err(TenantSkillConfigApiError::internal)?;
            if allowed {
                return Ok(tenant_id.to_string());
            }
            return Err(TenantSkillConfigApiError::forbidden("Access denied"));
        }
        self.repo
            .first_tenant_for_user(user_id)
            .await
            .map_err(TenantSkillConfigApiError::internal)?
            .ok_or_else(|| TenantSkillConfigApiError::forbidden("Access denied"))
    }
}

#[derive(Default)]
pub(crate) struct DevTenantSkillConfigService {
    tenant_id: String,
    configs: Mutex<HashMap<String, TenantSkillConfigRecord>>,
    override_skills: Mutex<HashSet<String>>,
}

impl DevTenantSkillConfigService {
    pub(crate) fn new(tenant_id: impl Into<String>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            configs: Mutex::new(HashMap::new()),
            override_skills: Mutex::new(HashSet::new()),
        }
    }

    #[cfg(test)]
    fn with_override_skill(
        self,
        skill_id: impl Into<String>,
    ) -> Result<Self, TenantSkillConfigApiError> {
        self.override_skills
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?
            .insert(skill_id.into());
        Ok(self)
    }

    fn resolve_tenant(&self, tenant_id: Option<&str>) -> String {
        present(tenant_id)
            .map(ToString::to_string)
            .unwrap_or_else(|| self.tenant_id.clone())
    }

    fn find_config(
        &self,
        tenant_id: &str,
        system_skill_name: &str,
    ) -> Result<Option<TenantSkillConfigRecord>, TenantSkillConfigApiError> {
        Ok(self
            .configs
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?
            .values()
            .find(|config| {
                config.tenant_id == tenant_id && config.system_skill_name == system_skill_name
            })
            .cloned())
    }

    fn write_config(
        &self,
        record: TenantSkillConfigRecord,
    ) -> Result<TenantSkillConfigRecord, TenantSkillConfigApiError> {
        self.configs
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?
            .insert(record.id.clone(), record.clone());
        Ok(record)
    }
}

#[async_trait]
impl TenantSkillConfigService for DevTenantSkillConfigService {
    async fn list_configs(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<TenantSkillConfigListView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let mut configs: Vec<_> = self
            .configs
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?
            .values()
            .filter(|config| config.tenant_id == tenant_id)
            .cloned()
            .collect();
        configs.sort_by_key(|config| Reverse(config.created_at));
        let total = configs.len() as i64;
        Ok(TenantSkillConfigListView {
            configs: configs
                .into_iter()
                .map(TenantSkillConfigView::from)
                .collect(),
            total,
        })
    }

    async fn get_config(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let system_skill_name = validate_system_skill_name(system_skill_name)?;
        let config = self
            .find_config(&tenant_id, system_skill_name)?
            .ok_or_else(|| TenantSkillConfigApiError::not_found("Skill configuration not found"))?;
        Ok(config.into())
    }

    async fn disable_skill(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillPayload,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let system_skill_name = validate_system_skill_name(&body.system_skill_name)?;
        let now = Utc::now();
        let record = match self.find_config(&tenant_id, system_skill_name)? {
            Some(mut record) => {
                record.action = "disable".to_string();
                record.override_skill_id = None;
                record.updated_at = Some(now);
                record
            }
            None => TenantSkillConfigRecord {
                id: generate_uuid_v4(),
                tenant_id,
                system_skill_name: system_skill_name.to_string(),
                action: "disable".to_string(),
                override_skill_id: None,
                created_at: now,
                updated_at: Some(now),
            },
        };
        Ok(self.write_config(record)?.into())
    }

    async fn override_skill(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        body: OverrideSkillPayload,
    ) -> Result<TenantSkillConfigView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let system_skill_name = validate_system_skill_name(&body.system_skill_name)?;
        let override_skill_id = validate_system_skill_name(&body.override_skill_id)?;
        if !self
            .override_skills
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?
            .contains(override_skill_id)
        {
            return Err(TenantSkillConfigApiError::not_found(
                "Override skill not found",
            ));
        }
        let now = Utc::now();
        let record = match self.find_config(&tenant_id, system_skill_name)? {
            Some(mut record) => {
                record.action = "override".to_string();
                record.override_skill_id = Some(override_skill_id.to_string());
                record.updated_at = Some(now);
                record
            }
            None => TenantSkillConfigRecord {
                id: generate_uuid_v4(),
                tenant_id,
                system_skill_name: system_skill_name.to_string(),
                action: "override".to_string(),
                override_skill_id: Some(override_skill_id.to_string()),
                created_at: now,
                updated_at: Some(now),
            },
        };
        Ok(self.write_config(record)?.into())
    }

    async fn enable_skill(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillPayload,
    ) -> Result<(), TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let system_skill_name = validate_system_skill_name(&body.system_skill_name)?;
        let mut configs = self
            .configs
            .lock()
            .map_err(TenantSkillConfigApiError::internal)?;
        let id = configs
            .values()
            .find(|config| {
                config.tenant_id == tenant_id && config.system_skill_name == system_skill_name
            })
            .map(|config| config.id.clone())
            .ok_or_else(|| TenantSkillConfigApiError::not_found("Skill configuration not found"))?;
        configs.remove(&id);
        Ok(())
    }

    async fn delete_config(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<(), TenantSkillConfigApiError> {
        self.enable_skill(
            user_id,
            tenant_id,
            SystemSkillPayload {
                system_skill_name: system_skill_name.to_string(),
            },
        )
        .await
    }

    async fn skill_status(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        system_skill_name: &str,
    ) -> Result<TenantSkillStatusView, TenantSkillConfigApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let system_skill_name = validate_system_skill_name(system_skill_name)?;
        let config = self.find_config(&tenant_id, system_skill_name)?;
        Ok(skill_status_view(system_skill_name, config))
    }
}

async fn list_tenant_skill_configs(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
) -> Result<Json<TenantSkillConfigListView>, TenantSkillConfigApiError> {
    Ok(Json(
        app.tenant_skill_configs
            .list_configs(&identity.user_id, q.tenant_id.as_deref())
            .await?,
    ))
}

async fn get_tenant_skill_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(system_skill_name): Path<String>,
) -> Result<Json<TenantSkillConfigView>, TenantSkillConfigApiError> {
    Ok(Json(
        app.tenant_skill_configs
            .get_config(
                &identity.user_id,
                q.tenant_id.as_deref(),
                &system_skill_name,
            )
            .await?,
    ))
}

async fn disable_system_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<SystemSkillPayload>,
) -> Result<(StatusCode, Json<TenantSkillConfigView>), TenantSkillConfigApiError> {
    let view = app
        .tenant_skill_configs
        .disable_skill(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn override_system_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<OverrideSkillPayload>,
) -> Result<(StatusCode, Json<TenantSkillConfigView>), TenantSkillConfigApiError> {
    let view = app
        .tenant_skill_configs
        .override_skill(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn enable_system_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<SystemSkillPayload>,
) -> Result<StatusCode, TenantSkillConfigApiError> {
    app.tenant_skill_configs
        .enable_skill(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn delete_tenant_skill_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(system_skill_name): Path<String>,
) -> Result<StatusCode, TenantSkillConfigApiError> {
    app.tenant_skill_configs
        .delete_config(
            &identity.user_id,
            q.tenant_id.as_deref(),
            &system_skill_name,
        )
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn get_skill_status(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(system_skill_name): Path<String>,
) -> Result<Json<TenantSkillStatusView>, TenantSkillConfigApiError> {
    Ok(Json(
        app.tenant_skill_configs
            .skill_status(
                &identity.user_id,
                q.tenant_id.as_deref(),
                &system_skill_name,
            )
            .await?,
    ))
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/tenant/skills/config/",
            get(list_tenant_skill_configs),
        )
        .route(
            "/api/v1/tenant/skills/config",
            get(list_tenant_skill_configs),
        )
        .route(
            "/api/v1/tenant/skills/config/disable",
            post(disable_system_skill),
        )
        .route(
            "/api/v1/tenant/skills/config/override",
            post(override_system_skill),
        )
        .route(
            "/api/v1/tenant/skills/config/enable",
            post(enable_system_skill),
        )
        .route(
            "/api/v1/tenant/skills/config/status/:system_skill_name",
            get(get_skill_status),
        )
        .route(
            "/api/v1/tenant/skills/config/:system_skill_name",
            get(get_tenant_skill_config).delete(delete_tenant_skill_config),
        )
}

fn skill_status_view(
    system_skill_name: &str,
    config: Option<TenantSkillConfigRecord>,
) -> TenantSkillStatusView {
    match config {
        Some(config) => TenantSkillStatusView {
            system_skill_name: system_skill_name.to_string(),
            status: if config.action == "disable" {
                "disabled".to_string()
            } else {
                "overridden".to_string()
            },
            action: Some(config.action),
            override_skill_id: config.override_skill_id,
        },
        None => TenantSkillStatusView {
            system_skill_name: system_skill_name.to_string(),
            status: "enabled".to_string(),
            action: None,
            override_skill_id: None,
        },
    }
}

fn validate_system_skill_name(raw: &str) -> Result<&str, TenantSkillConfigApiError> {
    present(Some(raw)).ok_or_else(|| {
        TenantSkillConfigApiError::bad_request("Invalid tenant skill config request")
    })
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn present(value: Option<&str>) -> Option<&str> {
    value.map(str::trim).filter(|value| !value.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_config_record() -> TenantSkillConfigRecord {
        let at = DateTime::<Utc>::from_timestamp(1_700_000_000, 0).unwrap();
        TenantSkillConfigRecord {
            id: "33333333-3333-4333-8333-333333333333".to_string(),
            tenant_id: "tenant-1".to_string(),
            system_skill_name: "code-review".to_string(),
            action: "override".to_string(),
            override_skill_id: Some("skill-override-1".to_string()),
            created_at: at,
            updated_at: Some(at),
        }
    }

    #[test]
    fn tenant_skill_config_response_matches_golden() {
        let actual =
            serde_json::to_value(TenantSkillConfigView::from(sample_config_record())).unwrap();
        let golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/tenant_skill_config_response.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn tenant_skill_config_list_matches_golden() {
        let actual = serde_json::to_value(TenantSkillConfigListView {
            configs: vec![TenantSkillConfigView::from(sample_config_record())],
            total: 1,
        })
        .unwrap();
        let golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/tenant_skill_config_list.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn tenant_skill_status_matches_goldens() {
        let actual = serde_json::to_value(skill_status_view(
            "code-review",
            Some(sample_config_record()),
        ))
        .unwrap();
        let golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/tenant_skill_config_status_overridden.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&golden, &actual);

        let actual = serde_json::to_value(skill_status_view("code-review", None)).unwrap();
        let golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/tenant_skill_config_status_enabled.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[tokio::test]
    async fn dev_service_disable_override_enable_and_delete_roundtrip() {
        let service = DevTenantSkillConfigService::new("tenant-1")
            .with_override_skill("skill-override-1")
            .unwrap();

        let disabled = service
            .disable_skill(
                "u1",
                Some("tenant-1"),
                SystemSkillPayload {
                    system_skill_name: "code-review".to_string(),
                },
            )
            .await
            .unwrap();
        assert_eq!(disabled.action, "disable");
        assert_eq!(disabled.override_skill_id, None);

        let overridden = service
            .override_skill(
                "u1",
                Some("tenant-1"),
                OverrideSkillPayload {
                    system_skill_name: "code-review".to_string(),
                    override_skill_id: "skill-override-1".to_string(),
                },
            )
            .await
            .unwrap();
        assert_eq!(overridden.action, "override");
        assert_eq!(
            overridden.override_skill_id.as_deref(),
            Some("skill-override-1")
        );

        let status = service
            .skill_status("u1", Some("tenant-1"), "code-review")
            .await
            .unwrap();
        assert_eq!(status.status, "overridden");

        service
            .enable_skill(
                "u1",
                Some("tenant-1"),
                SystemSkillPayload {
                    system_skill_name: "code-review".to_string(),
                },
            )
            .await
            .unwrap();
        let status = service
            .skill_status("u1", Some("tenant-1"), "code-review")
            .await
            .unwrap();
        assert_eq!(status.status, "enabled");

        let missing = service
            .delete_config("u1", Some("tenant-1"), "code-review")
            .await;
        assert!(matches!(
            missing,
            Err(TenantSkillConfigApiError {
                status: StatusCode::NOT_FOUND,
                ..
            })
        ));
    }

    #[test]
    fn tenant_skill_config_router_builds() {
        let _router: Router<AppState> = router();
    }
}
