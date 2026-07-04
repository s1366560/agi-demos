//! P5 tenant skill config foundation.
//!
//! Mirrors Python's `/api/v1/tenant/skills/config` router for database-backed
//! tenant overrides of system skills. Filesystem skill loading remains in the
//! skill service; this module only persists tenant-level disable/override rows.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use chrono::Utc;
use serde_json::json;

use agistack_adapters_postgres::{PgTenantSkillConfigRepository, TenantSkillConfigRecord};
use agistack_adapters_secrets::generate_uuid_v4;

use crate::auth::Identity;
use crate::AppState;

mod dev_service;
#[cfg(test)]
mod tests;
mod views;

pub(crate) use dev_service::DevTenantSkillConfigService;
use views::*;

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

fn present(value: Option<&str>) -> Option<&str> {
    value.map(str::trim).filter(|value| !value.is_empty())
}
