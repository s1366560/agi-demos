//! P7 deploy read-side strangler slice.
//!
//! Rust owns only deploy list/detail/latest reads. Deploy creation, lifecycle
//! status transitions, cancellation, and Redis/SSE progress stay Python-owned.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde::Serialize;
use serde_json::{json, Value};

use agistack_adapters_postgres::{
    DeployAccess, DeployListQuery as PgDeployListQuery, DeployRecord, PgDeployRepository,
};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedDeploys = Arc<dyn DeployService>;

#[async_trait]
pub(crate) trait DeployService: Send + Sync {
    async fn list_deploys(
        &self,
        user_id: &str,
        query: ValidatedDeployListQuery,
    ) -> Result<DeployListResponse, DeployApiError>;

    async fn get_latest_deploy(
        &self,
        user_id: &str,
        instance_id: &str,
    ) -> Result<DeployView, DeployApiError>;

    async fn get_deploy(
        &self,
        user_id: &str,
        deploy_id: &str,
    ) -> Result<DeployView, DeployApiError>;
}

pub(crate) struct PgDeployService {
    repo: PgDeployRepository,
}

impl PgDeployService {
    pub(crate) fn new(repo: PgDeployRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl DeployService for PgDeployService {
    async fn list_deploys(
        &self,
        user_id: &str,
        query: ValidatedDeployListQuery,
    ) -> Result<DeployListResponse, DeployApiError> {
        require_instance_access(&self.repo, user_id, &query.instance_id).await?;
        let (records, total) = self
            .repo
            .list_deploys(PgDeployListQuery {
                instance_id: &query.instance_id,
                limit: query.page_size,
                offset: query.offset,
            })
            .await
            .map_err(DeployApiError::internal)?;
        Ok(DeployListResponse::from_records(
            records,
            total,
            query.page,
            query.page_size,
        ))
    }

    async fn get_latest_deploy(
        &self,
        user_id: &str,
        instance_id: &str,
    ) -> Result<DeployView, DeployApiError> {
        require_instance_access(&self.repo, user_id, instance_id).await?;
        self.repo
            .latest_deploy(instance_id)
            .await
            .map_err(DeployApiError::internal)?
            .map(DeployView::from)
            .ok_or_else(|| DeployApiError::not_found("Deploy not found"))
    }

    async fn get_deploy(
        &self,
        user_id: &str,
        deploy_id: &str,
    ) -> Result<DeployView, DeployApiError> {
        require_deploy_access(&self.repo, user_id, deploy_id).await?;
        self.repo
            .get_deploy(deploy_id)
            .await
            .map_err(DeployApiError::internal)?
            .map(DeployView::from)
            .ok_or_else(|| DeployApiError::not_found("Deploy not found"))
    }
}

#[derive(Default)]
pub(crate) struct DevDeployService {
    deploys: Vec<DeployRecord>,
}

impl DevDeployService {
    #[cfg(test)]
    pub(crate) fn new(deploys: Vec<DeployRecord>) -> Self {
        Self { deploys }
    }
}

#[async_trait]
impl DeployService for DevDeployService {
    async fn list_deploys(
        &self,
        _user_id: &str,
        query: ValidatedDeployListQuery,
    ) -> Result<DeployListResponse, DeployApiError> {
        let mut deploys = self
            .deploys
            .iter()
            .filter(|deploy| deploy.instance_id == query.instance_id)
            .cloned()
            .collect::<Vec<_>>();
        sort_deploys(&mut deploys);
        let total = deploys.len() as i64;
        let page = page(deploys, query.page_size, query.offset);
        Ok(DeployListResponse::from_records(
            page,
            total,
            query.page,
            query.page_size,
        ))
    }

    async fn get_latest_deploy(
        &self,
        _user_id: &str,
        instance_id: &str,
    ) -> Result<DeployView, DeployApiError> {
        let mut deploys = self
            .deploys
            .iter()
            .filter(|deploy| deploy.instance_id == instance_id)
            .cloned()
            .collect::<Vec<_>>();
        sort_deploys(&mut deploys);
        deploys
            .into_iter()
            .next()
            .map(DeployView::from)
            .ok_or_else(|| DeployApiError::not_found("Deploy not found"))
    }

    async fn get_deploy(
        &self,
        _user_id: &str,
        deploy_id: &str,
    ) -> Result<DeployView, DeployApiError> {
        self.deploys
            .iter()
            .find(|deploy| deploy.id == deploy_id)
            .cloned()
            .map(DeployView::from)
            .ok_or_else(|| DeployApiError::not_found("Deploy not found"))
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/deploys/", get(list_deploys))
        .route(
            "/api/v1/deploys/instances/:instance_id/latest",
            get(get_latest_deploy),
        )
        .route("/api/v1/deploys/:deploy_id", get(get_deploy))
}

async fn list_deploys(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<DeployListQuery>,
) -> Result<Json<DeployListResponse>, DeployApiError> {
    let query = query.validated()?;
    let response = app.deploys.list_deploys(&identity.user_id, query).await?;
    Ok(Json(response))
}

async fn get_latest_deploy(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
) -> Result<Json<DeployView>, DeployApiError> {
    let response = app
        .deploys
        .get_latest_deploy(&identity.user_id, &instance_id)
        .await?;
    Ok(Json(response))
}

async fn get_deploy(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(deploy_id): Path<String>,
) -> Result<Json<DeployView>, DeployApiError> {
    let response = app
        .deploys
        .get_deploy(&identity.user_id, &deploy_id)
        .await?;
    Ok(Json(response))
}

async fn require_instance_access(
    repo: &PgDeployRepository,
    user_id: &str,
    instance_id: &str,
) -> Result<(), DeployApiError> {
    match repo
        .access_for_instance(user_id, instance_id)
        .await
        .map_err(DeployApiError::internal)?
    {
        DeployAccess::Allowed => Ok(()),
        DeployAccess::Forbidden => Err(DeployApiError::forbidden("Access denied to tenant")),
        DeployAccess::NotFound => Err(DeployApiError::not_found("Instance not found")),
    }
}

async fn require_deploy_access(
    repo: &PgDeployRepository,
    user_id: &str,
    deploy_id: &str,
) -> Result<(), DeployApiError> {
    match repo
        .access_for_deploy(user_id, deploy_id)
        .await
        .map_err(DeployApiError::internal)?
    {
        DeployAccess::Allowed => Ok(()),
        DeployAccess::Forbidden => Err(DeployApiError::forbidden("Access denied to tenant")),
        DeployAccess::NotFound => Err(DeployApiError::not_found("Deploy not found")),
    }
}

#[derive(Debug, Clone, Deserialize)]
struct DeployListQuery {
    instance_id: Option<String>,
    page: Option<i64>,
    page_size: Option<i64>,
}

impl DeployListQuery {
    fn validated(self) -> Result<ValidatedDeployListQuery, DeployApiError> {
        let instance_id = self
            .instance_id
            .filter(|value| !value.trim().is_empty())
            .ok_or_else(|| DeployApiError::unprocessable("instance_id is required"))?;
        let page = validate_range(self.page.unwrap_or(1), "page", 1, i64::MAX)?;
        let page_size = validate_range(self.page_size.unwrap_or(20), "page_size", 1, 100)?;
        let offset = page
            .checked_sub(1)
            .and_then(|value| value.checked_mul(page_size))
            .ok_or_else(|| DeployApiError::unprocessable("pagination offset is too large"))?;
        Ok(ValidatedDeployListQuery {
            instance_id,
            page,
            page_size,
            offset,
        })
    }
}

#[derive(Debug, Clone)]
pub(crate) struct ValidatedDeployListQuery {
    instance_id: String,
    page: i64,
    page_size: i64,
    offset: i64,
}

fn validate_range(value: i64, field: &str, min: i64, max: i64) -> Result<i64, DeployApiError> {
    if value < min || value > max {
        Err(DeployApiError::unprocessable(format!(
            "{field} must be between {min} and {max}"
        )))
    } else {
        Ok(value)
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct DeployView {
    id: String,
    instance_id: String,
    action: String,
    revision: i32,
    status: String,
    message: Option<String>,
    image_version: Option<String>,
    replicas: Option<i32>,
    config_snapshot: Value,
    triggered_by: Option<String>,
    started_at: Option<String>,
    finished_at: Option<String>,
    created_at: String,
}

impl From<DeployRecord> for DeployView {
    fn from(record: DeployRecord) -> Self {
        Self {
            id: record.id,
            instance_id: record.instance_id,
            action: record.action,
            revision: record.revision,
            status: record.status,
            message: record.message,
            image_version: record.image_version,
            replicas: record.replicas,
            config_snapshot: record.config_snapshot,
            triggered_by: record.triggered_by,
            started_at: record.started_at.map(iso8601),
            finished_at: record.finished_at.map(iso8601),
            created_at: iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct DeployListResponse {
    deploys: Vec<DeployView>,
    total: i64,
    page: i64,
    page_size: i64,
}

impl DeployListResponse {
    fn from_records(records: Vec<DeployRecord>, total: i64, page: i64, page_size: i64) -> Self {
        Self {
            deploys: records.into_iter().map(DeployView::from).collect(),
            total,
            page,
            page_size,
        }
    }
}

fn sort_deploys(records: &mut [DeployRecord]) {
    records.sort_by(|left, right| {
        right
            .created_at
            .cmp(&left.created_at)
            .then_with(|| left.id.cmp(&right.id))
    });
}

fn page<T>(records: Vec<T>, limit: i64, offset: i64) -> Vec<T> {
    records
        .into_iter()
        .skip(offset as usize)
        .take(limit as usize)
        .collect()
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

#[derive(Debug)]
pub(crate) struct DeployApiError {
    status: StatusCode,
    detail: String,
}

impl DeployApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for DeployApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn deploy(
        id: &str,
        instance_id: &str,
        revision: i32,
        created_at: DateTime<Utc>,
    ) -> DeployRecord {
        DeployRecord {
            id: id.to_string(),
            instance_id: instance_id.to_string(),
            revision,
            action: "update".to_string(),
            image_version: Some(format!("1.{revision}.0")),
            replicas: Some(3),
            config_snapshot: json!({"cpu_limit": "1000m", "mem_limit": "1Gi"}),
            status: "success".to_string(),
            message: Some("Deploy completed successfully".to_string()),
            triggered_by: Some("user-1".to_string()),
            started_at: Some(Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap()),
            finished_at: Some(Utc.with_ymd_and_hms(2024, 1, 15, 10, 32, 0).unwrap()),
            created_at,
        }
    }

    #[test]
    fn list_query_validates_pagination() {
        let query = DeployListQuery {
            instance_id: Some("inst-1".to_string()),
            page: Some(2),
            page_size: Some(25),
        }
        .validated()
        .expect("valid query");

        assert_eq!(query.instance_id, "inst-1");
        assert_eq!(query.page, 2);
        assert_eq!(query.page_size, 25);
        assert_eq!(query.offset, 25);

        let err = DeployListQuery {
            instance_id: None,
            page: None,
            page_size: None,
        }
        .validated()
        .expect_err("missing instance_id should reject");
        assert_eq!(err.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn dev_service_lists_details_and_latest() {
        let old = deploy(
            "deploy-old",
            "inst-1",
            1,
            Utc.with_ymd_and_hms(2024, 1, 15, 9, 30, 0).unwrap(),
        );
        let latest = deploy(
            "deploy-latest",
            "inst-1",
            2,
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
        );
        let other = deploy(
            "deploy-other",
            "inst-2",
            1,
            Utc.with_ymd_and_hms(2024, 1, 15, 11, 30, 0).unwrap(),
        );
        let service = DevDeployService::new(vec![old, latest.clone(), other]);

        let list = service
            .list_deploys(
                "user-1",
                ValidatedDeployListQuery {
                    instance_id: "inst-1".to_string(),
                    page: 1,
                    page_size: 10,
                    offset: 0,
                },
            )
            .await
            .expect("list deploys");
        assert_eq!(list.total, 2);
        assert_eq!(list.deploys[0].id, "deploy-latest");

        let detail = service
            .get_deploy("user-1", "deploy-latest")
            .await
            .expect("deploy detail");
        assert_eq!(detail.revision, 2);

        let latest_view = service
            .get_latest_deploy("user-1", "inst-1")
            .await
            .expect("latest deploy");
        assert_eq!(latest_view.id, latest.id);
    }

    #[test]
    fn deploy_list_response_matches_golden() {
        let response = DeployListResponse::from_records(
            vec![deploy(
                "deploy_abc123",
                "inst_550e8400",
                5,
                Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
            )],
            1,
            1,
            20,
        );
        let value = serde_json::to_value(response).expect("deploy list must serialize");
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/deploy_list_response.json"))
                .expect("deploy list golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }
}
