//! P3/F11 SubAgent template marketplace discovery slice.
//!
//! Rust owns only exact template category discovery. Template list/create,
//! detail, install, and SubAgent runtime paths remain Python-owned.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use serde::{Deserialize, Serialize};
use serde_json::json;

use agistack_adapters_postgres::PgSubagentTemplateRepository;

use crate::auth::Identity;
use crate::identity::IdentityError;
use crate::AppState;

pub(crate) type SharedSubagentTemplates = Arc<dyn SubagentTemplateService>;

#[async_trait]
pub(crate) trait SubagentTemplateService: Send + Sync {
    async fn list_categories(&self, tenant_id: &str) -> Result<Vec<String>, SubagentsApiError>;
}

pub(crate) struct PgSubagentTemplateService {
    repo: PgSubagentTemplateRepository,
}

impl PgSubagentTemplateService {
    pub(crate) fn new(repo: PgSubagentTemplateRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl SubagentTemplateService for PgSubagentTemplateService {
    async fn list_categories(&self, tenant_id: &str) -> Result<Vec<String>, SubagentsApiError> {
        self.repo
            .list_categories(tenant_id)
            .await
            .map_err(SubagentsApiError::internal)
    }
}

pub(crate) struct DevSubagentTemplateService {
    categories: Vec<String>,
}

impl DevSubagentTemplateService {
    pub(crate) fn new(categories: Vec<String>) -> Self {
        let mut categories: Vec<String> = categories
            .into_iter()
            .filter(|category| !category.is_empty())
            .collect();
        categories.sort();
        categories.dedup();
        Self { categories }
    }
}

impl Default for DevSubagentTemplateService {
    fn default() -> Self {
        Self::new(Vec::new())
    }
}

#[async_trait]
impl SubagentTemplateService for DevSubagentTemplateService {
    async fn list_categories(&self, _tenant_id: &str) -> Result<Vec<String>, SubagentsApiError> {
        Ok(self.categories.clone())
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new().route(
        "/api/v1/subagents/templates/categories",
        get(list_template_categories),
    )
}

async fn list_template_categories(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<TemplateCategoriesQuery>,
) -> Result<Json<TemplateCategoriesResponse>, SubagentsApiError> {
    let tenant_id = selected_tenant_id(&app, &identity.user_id, query.tenant_id.as_deref()).await?;
    let categories = app.subagent_templates.list_categories(&tenant_id).await?;
    Ok(Json(TemplateCategoriesResponse { categories }))
}

#[derive(Debug, Clone, Deserialize)]
struct TemplateCategoriesQuery {
    tenant_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct TemplateCategoriesResponse {
    categories: Vec<String>,
}

async fn selected_tenant_id(
    app: &AppState,
    user_id: &str,
    selected_tenant_id: Option<&str>,
) -> Result<String, SubagentsApiError> {
    if let Some(tenant_id) = selected_tenant_id {
        if tenant_id.is_empty() {
            return Err(SubagentsApiError::unprocessable(
                "tenant_id must be at least 1 character",
            ));
        }
        app.identity
            .get_tenant(user_id, tenant_id)
            .await
            .map_err(SubagentsApiError::from_identity)?;
        return Ok(tenant_id.to_string());
    }

    let page = app
        .identity
        .list_tenants(user_id, None, 1, 1)
        .await
        .map_err(SubagentsApiError::from_identity)?;
    page.tenants
        .into_iter()
        .next()
        .map(|tenant| tenant.id)
        .ok_or_else(|| {
            SubagentsApiError::bad_request(
                "User does not belong to any tenant. Please contact administrator.",
            )
        })
}

#[derive(Debug)]
pub(crate) struct SubagentsApiError {
    status: StatusCode,
    detail: String,
}

impl SubagentsApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }

    fn from_identity(error: IdentityError) -> Self {
        Self::new(error.status, error.detail)
    }
}

impl IntoResponse for SubagentsApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn router_builds() {
        let _ = router();
    }

    #[tokio::test]
    async fn template_categories_response_matches_golden() {
        let service = DevSubagentTemplateService::new(vec![
            "research".to_string(),
            "development".to_string(),
            "research".to_string(),
        ]);
        let response = TemplateCategoriesResponse {
            categories: service
                .list_categories("tenant-1")
                .await
                .expect("dev categories"),
        };
        let golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/subagent_template_categories_response.json"
        ))
        .expect("subagent template categories golden parses");
        let actual = serde_json::to_value(&response).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }
}
