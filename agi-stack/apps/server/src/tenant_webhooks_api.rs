//! P7 tenant webhook strangler slice.
//!
//! Rust owns tenant webhook CRUD. Webhook provider delivery execution remains
//! Python-owned.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;
use tokio::sync::Mutex;
use uuid::Uuid;

use agistack_adapters_postgres::{
    CreateTenantWebhook, PgTenantWebhookRepository, TenantWebhookRecord,
};
use agistack_adapters_secrets::{generate_api_key, API_KEY_PREFIX};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedTenantWebhooks = Arc<dyn TenantWebhookService>;

#[async_trait]
pub(crate) trait TenantWebhookService: Send + Sync {
    async fn list_webhooks(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<Vec<TenantWebhookView>, TenantWebhookApiError>;

    async fn create_webhook(
        &self,
        user_id: &str,
        tenant_id: &str,
        body: TenantWebhookCreateRequest,
    ) -> Result<TenantWebhookView, TenantWebhookApiError>;

    async fn update_webhook(
        &self,
        user_id: &str,
        webhook_id: &str,
        body: TenantWebhookUpdateRequest,
    ) -> Result<TenantWebhookView, TenantWebhookApiError>;

    async fn delete_webhook(
        &self,
        user_id: &str,
        webhook_id: &str,
    ) -> Result<(), TenantWebhookApiError>;
}

pub(crate) struct PgTenantWebhookService {
    repo: PgTenantWebhookRepository,
}

impl PgTenantWebhookService {
    pub(crate) fn new(repo: PgTenantWebhookRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl TenantWebhookService for PgTenantWebhookService {
    async fn list_webhooks(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<Vec<TenantWebhookView>, TenantWebhookApiError> {
        require_tenant_webhook_admin(&self.repo, user_id, tenant_id).await?;
        let records = self
            .repo
            .list_webhooks(tenant_id)
            .await
            .map_err(TenantWebhookApiError::internal)?;
        Ok(records
            .into_iter()
            .map(TenantWebhookView::redacted)
            .collect())
    }

    async fn create_webhook(
        &self,
        user_id: &str,
        tenant_id: &str,
        body: TenantWebhookCreateRequest,
    ) -> Result<TenantWebhookView, TenantWebhookApiError> {
        require_tenant_webhook_admin(&self.repo, user_id, tenant_id).await?;
        let id = Uuid::new_v4().to_string();
        let secret = generate_webhook_secret();
        let record = self
            .repo
            .create_webhook(CreateTenantWebhook {
                id: &id,
                tenant_id,
                name: &body.name,
                url: &body.url,
                secret: &secret,
                events: &body.events,
                is_active: body.is_active,
            })
            .await
            .map_err(TenantWebhookApiError::internal)?;
        Ok(TenantWebhookView::with_secret(record))
    }

    async fn update_webhook(
        &self,
        user_id: &str,
        webhook_id: &str,
        body: TenantWebhookUpdateRequest,
    ) -> Result<TenantWebhookView, TenantWebhookApiError> {
        require_existing_webhook_admin(&self.repo, user_id, webhook_id).await?;
        let record = self
            .repo
            .update_webhook(
                webhook_id,
                &body.name,
                &body.url,
                &body.events,
                body.is_active,
            )
            .await
            .map_err(TenantWebhookApiError::internal)?
            .ok_or_else(|| TenantWebhookApiError::not_found("Webhook not found"))?;
        Ok(TenantWebhookView::redacted(record))
    }

    async fn delete_webhook(
        &self,
        user_id: &str,
        webhook_id: &str,
    ) -> Result<(), TenantWebhookApiError> {
        require_existing_webhook_admin(&self.repo, user_id, webhook_id).await?;
        if self
            .repo
            .delete_webhook(webhook_id)
            .await
            .map_err(TenantWebhookApiError::internal)?
        {
            Ok(())
        } else {
            Err(TenantWebhookApiError::not_found("Webhook not found"))
        }
    }
}

pub(crate) struct DevTenantWebhookService {
    webhooks: Mutex<Vec<TenantWebhookRecord>>,
}

impl DevTenantWebhookService {
    pub(crate) fn new(webhooks: Vec<TenantWebhookRecord>) -> Self {
        Self {
            webhooks: Mutex::new(webhooks),
        }
    }
}

impl Default for DevTenantWebhookService {
    fn default() -> Self {
        Self::new(Vec::new())
    }
}

#[async_trait]
impl TenantWebhookService for DevTenantWebhookService {
    async fn list_webhooks(
        &self,
        _user_id: &str,
        tenant_id: &str,
    ) -> Result<Vec<TenantWebhookView>, TenantWebhookApiError> {
        let mut webhooks = self
            .webhooks
            .lock()
            .await
            .iter()
            .filter(|webhook| webhook.tenant_id == tenant_id)
            .cloned()
            .collect::<Vec<_>>();
        webhooks.sort_by(|left, right| {
            right
                .created_at
                .cmp(&left.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(webhooks
            .into_iter()
            .map(TenantWebhookView::redacted)
            .collect())
    }

    async fn create_webhook(
        &self,
        _user_id: &str,
        tenant_id: &str,
        body: TenantWebhookCreateRequest,
    ) -> Result<TenantWebhookView, TenantWebhookApiError> {
        let record = TenantWebhookRecord {
            id: Uuid::new_v4().to_string(),
            tenant_id: tenant_id.to_string(),
            name: body.name,
            url: body.url,
            secret: Some(generate_webhook_secret()),
            events: body.events,
            is_active: body.is_active,
            created_at: Utc::now(),
            updated_at: None,
        };
        self.webhooks.lock().await.push(record.clone());
        Ok(TenantWebhookView::with_secret(record))
    }

    async fn update_webhook(
        &self,
        _user_id: &str,
        webhook_id: &str,
        body: TenantWebhookUpdateRequest,
    ) -> Result<TenantWebhookView, TenantWebhookApiError> {
        let mut webhooks = self.webhooks.lock().await;
        let webhook = webhooks
            .iter_mut()
            .find(|webhook| webhook.id == webhook_id)
            .ok_or_else(|| TenantWebhookApiError::not_found("Webhook not found"))?;
        webhook.name = body.name;
        webhook.url = body.url;
        webhook.events = body.events;
        webhook.is_active = body.is_active;
        webhook.updated_at = Some(Utc::now());
        Ok(TenantWebhookView::redacted(webhook.clone()))
    }

    async fn delete_webhook(
        &self,
        _user_id: &str,
        webhook_id: &str,
    ) -> Result<(), TenantWebhookApiError> {
        let mut webhooks = self.webhooks.lock().await;
        let before = webhooks.len();
        webhooks.retain(|webhook| webhook.id != webhook_id);
        if webhooks.len() == before {
            Err(TenantWebhookApiError::not_found("Webhook not found"))
        } else {
            Ok(())
        }
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new().route(
        "/api/v1/tenant-webhooks/:id",
        get(list_webhooks)
            .post(create_webhook)
            .put(update_webhook)
            .delete(delete_webhook),
    )
}

async fn list_webhooks(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(id): Path<String>,
) -> Result<Json<Vec<TenantWebhookView>>, TenantWebhookApiError> {
    let response = app
        .tenant_webhooks
        .list_webhooks(&identity.user_id, &id)
        .await?;
    Ok(Json(response))
}

async fn create_webhook(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(id): Path<String>,
    Json(body): Json<TenantWebhookCreateRequest>,
) -> Result<Json<TenantWebhookView>, TenantWebhookApiError> {
    let response = app
        .tenant_webhooks
        .create_webhook(&identity.user_id, &id, body)
        .await?;
    Ok(Json(response))
}

async fn update_webhook(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(id): Path<String>,
    Json(body): Json<TenantWebhookUpdateRequest>,
) -> Result<Json<TenantWebhookView>, TenantWebhookApiError> {
    let response = app
        .tenant_webhooks
        .update_webhook(&identity.user_id, &id, body)
        .await?;
    Ok(Json(response))
}

async fn delete_webhook(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(id): Path<String>,
) -> Result<StatusCode, TenantWebhookApiError> {
    app.tenant_webhooks
        .delete_webhook(&identity.user_id, &id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn require_tenant_webhook_admin(
    repo: &PgTenantWebhookRepository,
    user_id: &str,
    tenant_id: &str,
) -> Result<(), TenantWebhookApiError> {
    if !repo
        .tenant_exists(tenant_id)
        .await
        .map_err(TenantWebhookApiError::internal)?
    {
        return Err(TenantWebhookApiError::not_found("Tenant not found"));
    }

    if repo
        .user_has_global_admin(user_id)
        .await
        .map_err(TenantWebhookApiError::internal)?
    {
        return Ok(());
    }

    match repo
        .tenant_member_role(user_id, tenant_id)
        .await
        .map_err(TenantWebhookApiError::internal)?
        .as_deref()
    {
        Some("admin" | "owner") => Ok(()),
        Some(_) => Err(TenantWebhookApiError::forbidden("Admin access required")),
        None => Err(TenantWebhookApiError::forbidden("Tenant access required")),
    }
}

async fn require_existing_webhook_admin(
    repo: &PgTenantWebhookRepository,
    user_id: &str,
    webhook_id: &str,
) -> Result<TenantWebhookRecord, TenantWebhookApiError> {
    let webhook = repo
        .get_webhook(webhook_id)
        .await
        .map_err(TenantWebhookApiError::internal)?
        .ok_or_else(|| TenantWebhookApiError::not_found("Webhook not found"))?;
    require_tenant_webhook_admin(repo, user_id, &webhook.tenant_id).await?;
    Ok(webhook)
}

fn generate_webhook_secret() -> String {
    generate_api_key().replacen(API_KEY_PREFIX, "whsec_", 1)
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TenantWebhookCreateRequest {
    name: String,
    url: String,
    events: Vec<String>,
    #[serde(default = "default_true")]
    is_active: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TenantWebhookUpdateRequest {
    name: String,
    url: String,
    events: Vec<String>,
    is_active: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct TenantWebhookView {
    id: String,
    tenant_id: String,
    name: String,
    url: String,
    secret: Option<String>,
    events: Vec<String>,
    is_active: bool,
    created_at: Option<String>,
    updated_at: Option<String>,
}

impl TenantWebhookView {
    fn redacted(record: TenantWebhookRecord) -> Self {
        Self::from_record(record, None)
    }

    fn with_secret(record: TenantWebhookRecord) -> Self {
        let secret = record.secret.clone();
        Self::from_record(record, secret)
    }

    fn from_record(record: TenantWebhookRecord, secret: Option<String>) -> Self {
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            name: record.name,
            url: record.url,
            secret,
            events: record.events,
            is_active: record.is_active,
            created_at: Some(iso8601(record.created_at)),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

impl From<TenantWebhookRecord> for TenantWebhookView {
    fn from(record: TenantWebhookRecord) -> Self {
        Self::redacted(record)
    }
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

#[derive(Debug)]
pub(crate) struct TenantWebhookApiError {
    status: StatusCode,
    detail: String,
}

impl TenantWebhookApiError {
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

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for TenantWebhookApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use serde_json::Value;

    fn webhook(
        id: &str,
        tenant_id: &str,
        created_at: DateTime<Utc>,
        updated_at: Option<DateTime<Utc>>,
    ) -> TenantWebhookRecord {
        TenantWebhookRecord {
            id: id.to_string(),
            tenant_id: tenant_id.to_string(),
            name: "Workspace Events".to_string(),
            url: "https://hooks.example.test/workspace".to_string(),
            secret: Some("secret-value".to_string()),
            events: vec![
                "workspace.message.created".to_string(),
                "workspace.task.completed".to_string(),
            ],
            is_active: true,
            created_at,
            updated_at,
        }
    }

    #[test]
    fn tenant_webhook_list_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/tenant_webhook_list_response.json"
        ))
        .expect("tenant webhook list golden must be valid JSON");
        let response = vec![TenantWebhookView::from(webhook(
            "webhook-1",
            "tenant-1",
            Utc.with_ymd_and_hms(2026, 1, 5, 0, 0, 0).unwrap(),
            Some(Utc.with_ymd_and_hms(2026, 1, 6, 0, 0, 0).unwrap()),
        ))];

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn tenant_webhook_create_response_returns_secret_once() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/tenant_webhook_create_response.json"
        ))
        .expect("tenant webhook create golden must be valid JSON");
        let mut record = webhook(
            "webhook-1",
            "tenant-1",
            Utc.with_ymd_and_hms(2026, 1, 5, 0, 0, 0).unwrap(),
            None,
        );
        record.secret = Some(
            "whsec_0000000000000000000000000000000000000000000000000000000000000000".to_string(),
        );
        let value =
            serde_json::to_value(TenantWebhookView::with_secret(record)).expect("serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn tenant_webhook_update_response_redacts_secret() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/tenant_webhook_update_response.json"
        ))
        .expect("tenant webhook update golden must be valid JSON");
        let value = serde_json::to_value(TenantWebhookView::redacted(webhook(
            "webhook-1",
            "tenant-1",
            Utc.with_ymd_and_hms(2026, 1, 5, 0, 0, 0).unwrap(),
            Some(Utc.with_ymd_and_hms(2026, 1, 6, 0, 0, 0).unwrap()),
        )))
        .expect("serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[tokio::test]
    async fn dev_tenant_webhook_service_filters_orders_and_redacts() {
        let service = DevTenantWebhookService::new(vec![
            webhook(
                "webhook-old",
                "tenant-1",
                Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
                None,
            ),
            webhook(
                "webhook-new",
                "tenant-1",
                Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0).unwrap(),
                None,
            ),
            webhook(
                "webhook-other",
                "tenant-2",
                Utc.with_ymd_and_hms(2026, 1, 3, 0, 0, 0).unwrap(),
                None,
            ),
        ]);

        let response = service
            .list_webhooks("user-1", "tenant-1")
            .await
            .expect("dev list succeeds");

        assert_eq!(response.len(), 2);
        assert_eq!(response[0].id, "webhook-new");
        assert_eq!(response[1].id, "webhook-old");
        assert_eq!(response[0].secret, None);
    }

    #[tokio::test]
    async fn dev_tenant_webhook_service_mutates_and_preserves_secret_rules() {
        let service = DevTenantWebhookService::default();

        let created = service
            .create_webhook(
                "user-1",
                "tenant-1",
                TenantWebhookCreateRequest {
                    name: "Deploy".to_string(),
                    url: "https://example.test/hook".to_string(),
                    events: vec!["memory.created".to_string()],
                    is_active: true,
                },
            )
            .await
            .expect("dev create succeeds");
        let secret = created.secret.expect("create returns secret once");
        assert!(secret.starts_with("whsec_"));
        assert_eq!(secret.len(), "whsec_".len() + 64);

        let listed = service
            .list_webhooks("user-1", "tenant-1")
            .await
            .expect("dev list succeeds");
        assert_eq!(listed.len(), 1);
        assert_eq!(listed[0].secret, None);

        let updated = service
            .update_webhook(
                "user-1",
                &created.id,
                TenantWebhookUpdateRequest {
                    name: "Deploy Updated".to_string(),
                    url: "https://example.test/updated".to_string(),
                    events: vec!["memory.updated".to_string()],
                    is_active: false,
                },
            )
            .await
            .expect("dev update succeeds");
        assert_eq!(updated.name, "Deploy Updated");
        assert_eq!(updated.secret, None);
        assert!(!updated.is_active);
        assert!(updated.updated_at.is_some());

        service
            .delete_webhook("user-1", &created.id)
            .await
            .expect("dev delete succeeds");
        let listed_after_delete = service
            .list_webhooks("user-1", "tenant-1")
            .await
            .expect("dev list after delete succeeds");
        assert!(listed_after_delete.is_empty());

        let missing = service
            .delete_webhook("user-1", &created.id)
            .await
            .expect_err("missing delete returns 404");
        assert_eq!(missing.status, StatusCode::NOT_FOUND);
        assert_eq!(missing.detail, "Webhook not found");
    }
}
