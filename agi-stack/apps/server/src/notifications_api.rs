//! P7 notifications strangler slice.
//!
//! Rust owns the exact current-user notification list/mutation API-v1 slice.

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{delete, get, post, put},
    Extension, Json, Router,
};
use chrono::{DateTime, NaiveDateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;
use uuid::Uuid;

use agistack_adapters_postgres::{
    CreateNotification as PgCreateNotification, NotificationListQuery as PgNotificationListQuery,
    NotificationRecord, PgNotificationRepository,
};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedNotifications = Arc<dyn NotificationService>;

#[async_trait]
pub(crate) trait NotificationService: Send + Sync {
    async fn list_notifications(
        &self,
        user_id: &str,
        query: ValidatedNotificationListQuery,
    ) -> Result<NotificationListResponse, NotificationsApiError>;

    async fn mark_read(
        &self,
        user_id: &str,
        notification_id: &str,
    ) -> Result<SuccessResponse, NotificationsApiError>;

    async fn mark_all_read(
        &self,
        user_id: &str,
    ) -> Result<MarkAllReadResponse, NotificationsApiError>;

    async fn delete_notification(
        &self,
        user_id: &str,
        notification_id: &str,
    ) -> Result<SuccessResponse, NotificationsApiError>;

    async fn create_notification(
        &self,
        actor_user_id: &str,
        request: CreateNotificationRequest,
    ) -> Result<CreateNotificationResponse, NotificationsApiError>;
}

pub(crate) struct PgNotificationService {
    repo: PgNotificationRepository,
}

impl PgNotificationService {
    pub(crate) fn new(repo: PgNotificationRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl NotificationService for PgNotificationService {
    async fn list_notifications(
        &self,
        user_id: &str,
        query: ValidatedNotificationListQuery,
    ) -> Result<NotificationListResponse, NotificationsApiError> {
        let rows = self
            .repo
            .list_notifications(PgNotificationListQuery {
                user_id,
                unread_only: query.unread_only,
                limit: query.limit,
            })
            .await
            .map_err(NotificationsApiError::internal)?;
        Ok(NotificationListResponse::from_records(rows, Utc::now()))
    }

    async fn mark_read(
        &self,
        user_id: &str,
        notification_id: &str,
    ) -> Result<SuccessResponse, NotificationsApiError> {
        let updated = self
            .repo
            .mark_read(user_id, notification_id)
            .await
            .map_err(NotificationsApiError::internal)?;
        if updated {
            Ok(SuccessResponse { success: true })
        } else {
            Err(NotificationsApiError::not_found("Notification not found"))
        }
    }

    async fn mark_all_read(
        &self,
        user_id: &str,
    ) -> Result<MarkAllReadResponse, NotificationsApiError> {
        let count = self
            .repo
            .mark_all_read(user_id)
            .await
            .map_err(NotificationsApiError::internal)?;
        Ok(MarkAllReadResponse {
            success: true,
            count,
        })
    }

    async fn delete_notification(
        &self,
        user_id: &str,
        notification_id: &str,
    ) -> Result<SuccessResponse, NotificationsApiError> {
        let deleted = self
            .repo
            .delete_notification(user_id, notification_id)
            .await
            .map_err(NotificationsApiError::internal)?;
        if deleted {
            Ok(SuccessResponse { success: true })
        } else {
            Err(NotificationsApiError::not_found("Notification not found"))
        }
    }

    async fn create_notification(
        &self,
        actor_user_id: &str,
        request: CreateNotificationRequest,
    ) -> Result<CreateNotificationResponse, NotificationsApiError> {
        let target_user_id = request
            .user_id
            .as_deref()
            .filter(|value| !value.is_empty())
            .unwrap_or(actor_user_id);
        let actor_is_superuser = if target_user_id == actor_user_id {
            false
        } else {
            self.repo
                .user_is_superuser(actor_user_id)
                .await
                .map_err(NotificationsApiError::internal)?
        };
        if target_user_id != actor_user_id && !actor_is_superuser {
            return Err(NotificationsApiError::forbidden(
                "Cannot create notifications for another user",
            ));
        }
        let id = Uuid::new_v4().to_string();
        let data_json = request.data;
        let expires_at = parse_expires_at(request.expires_at.as_deref())?;
        let id = self
            .repo
            .create_notification(PgCreateNotification {
                id: &id,
                user_id: target_user_id,
                notification_type: request
                    .notification_type
                    .as_deref()
                    .filter(|value| !value.is_empty())
                    .unwrap_or("general"),
                title: request
                    .title
                    .as_deref()
                    .filter(|value| !value.is_empty())
                    .unwrap_or("Notification"),
                message: request.message.as_deref().unwrap_or(""),
                data_json: &data_json,
                action_url: request.action_url.as_deref(),
                expires_at,
            })
            .await
            .map_err(NotificationsApiError::internal)?;
        Ok(CreateNotificationResponse { id, success: true })
    }
}

pub(crate) struct DevNotificationService {
    notifications: Mutex<Vec<NotificationRecord>>,
}

impl DevNotificationService {
    pub(crate) fn new(notifications: Vec<NotificationRecord>) -> Self {
        Self {
            notifications: Mutex::new(notifications),
        }
    }
}

impl Default for DevNotificationService {
    fn default() -> Self {
        Self::new(Vec::new())
    }
}

#[async_trait]
impl NotificationService for DevNotificationService {
    async fn list_notifications(
        &self,
        user_id: &str,
        query: ValidatedNotificationListQuery,
    ) -> Result<NotificationListResponse, NotificationsApiError> {
        let notifications = self
            .notifications
            .lock()
            .map_err(|_| NotificationsApiError::internal("notification store lock poisoned"))?;
        let mut rows = notifications
            .iter()
            .filter(|row| row.user_id == user_id)
            .filter(|row| !query.unread_only || !row.is_read)
            .cloned()
            .collect::<Vec<_>>();
        rows.sort_by(|left, right| {
            right
                .created_at
                .cmp(&left.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        rows.truncate(query.limit as usize);
        Ok(NotificationListResponse::from_records(rows, Utc::now()))
    }

    async fn mark_read(
        &self,
        user_id: &str,
        notification_id: &str,
    ) -> Result<SuccessResponse, NotificationsApiError> {
        let mut notifications = self
            .notifications
            .lock()
            .map_err(|_| NotificationsApiError::internal("notification store lock poisoned"))?;
        let notification = notifications
            .iter_mut()
            .find(|row| row.user_id == user_id && row.id == notification_id)
            .ok_or_else(|| NotificationsApiError::not_found("Notification not found"))?;
        notification.is_read = true;
        Ok(SuccessResponse { success: true })
    }

    async fn mark_all_read(
        &self,
        user_id: &str,
    ) -> Result<MarkAllReadResponse, NotificationsApiError> {
        let mut notifications = self
            .notifications
            .lock()
            .map_err(|_| NotificationsApiError::internal("notification store lock poisoned"))?;
        let mut count = 0_i64;
        for notification in notifications
            .iter_mut()
            .filter(|row| row.user_id == user_id && !row.is_read)
        {
            notification.is_read = true;
            count += 1;
        }
        Ok(MarkAllReadResponse {
            success: true,
            count,
        })
    }

    async fn delete_notification(
        &self,
        user_id: &str,
        notification_id: &str,
    ) -> Result<SuccessResponse, NotificationsApiError> {
        let mut notifications = self
            .notifications
            .lock()
            .map_err(|_| NotificationsApiError::internal("notification store lock poisoned"))?;
        let Some(index) = notifications
            .iter()
            .position(|row| row.user_id == user_id && row.id == notification_id)
        else {
            return Err(NotificationsApiError::not_found("Notification not found"));
        };
        notifications.remove(index);
        Ok(SuccessResponse { success: true })
    }

    async fn create_notification(
        &self,
        actor_user_id: &str,
        request: CreateNotificationRequest,
    ) -> Result<CreateNotificationResponse, NotificationsApiError> {
        let target_user_id = request
            .user_id
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| actor_user_id.to_string());
        if target_user_id != actor_user_id {
            return Err(NotificationsApiError::forbidden(
                "Cannot create notifications for another user",
            ));
        }
        let id = Uuid::new_v4().to_string();
        let notification = NotificationRecord {
            id: id.clone(),
            user_id: target_user_id,
            notification_type: request
                .notification_type
                .filter(|value| !value.is_empty())
                .unwrap_or_else(|| "general".to_string()),
            title: request
                .title
                .filter(|value| !value.is_empty())
                .unwrap_or_else(|| "Notification".to_string()),
            message: request.message.unwrap_or_default(),
            data_json: Some(request.data),
            is_read: false,
            action_url: request.action_url,
            created_at: Utc::now(),
            expires_at: parse_expires_at(request.expires_at.as_deref())?,
        };
        self.notifications
            .lock()
            .map_err(|_| NotificationsApiError::internal("notification store lock poisoned"))?
            .push(notification);
        Ok(CreateNotificationResponse { id, success: true })
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/notifications/", get(list_notifications))
        .route(
            "/api/v1/notifications/:notification_id/read",
            put(mark_notification_read),
        )
        .route("/api/v1/notifications/read-all", put(mark_all_read))
        .route(
            "/api/v1/notifications/:notification_id",
            delete(delete_notification),
        )
        .route("/api/v1/notifications/create", post(create_notification))
}

async fn list_notifications(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<NotificationListQuery>,
) -> Result<Json<NotificationListResponse>, NotificationsApiError> {
    let query = query.validated()?;
    let response = app
        .notifications
        .list_notifications(&identity.user_id, query)
        .await?;
    Ok(Json(response))
}

async fn mark_notification_read(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(notification_id): Path<String>,
) -> Result<Json<SuccessResponse>, NotificationsApiError> {
    let response = app
        .notifications
        .mark_read(&identity.user_id, &notification_id)
        .await?;
    Ok(Json(response))
}

async fn mark_all_read(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
) -> Result<Json<MarkAllReadResponse>, NotificationsApiError> {
    let response = app.notifications.mark_all_read(&identity.user_id).await?;
    Ok(Json(response))
}

async fn delete_notification(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(notification_id): Path<String>,
) -> Result<Json<SuccessResponse>, NotificationsApiError> {
    let response = app
        .notifications
        .delete_notification(&identity.user_id, &notification_id)
        .await?;
    Ok(Json(response))
}

async fn create_notification(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(request): Json<CreateNotificationRequest>,
) -> Result<Json<CreateNotificationResponse>, NotificationsApiError> {
    let response = app
        .notifications
        .create_notification(&identity.user_id, request)
        .await?;
    Ok(Json(response))
}

#[derive(Debug, Clone, Deserialize)]
struct NotificationListQuery {
    #[serde(default)]
    unread_only: bool,
    limit: Option<i64>,
}

impl NotificationListQuery {
    fn validated(self) -> Result<ValidatedNotificationListQuery, NotificationsApiError> {
        let limit = self.limit.unwrap_or(20);
        if !(1..=100).contains(&limit) {
            return Err(NotificationsApiError::unprocessable(
                "limit must be greater than or equal to 1 and less than or equal to 100",
            ));
        }
        Ok(ValidatedNotificationListQuery {
            unread_only: self.unread_only,
            limit,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedNotificationListQuery {
    unread_only: bool,
    limit: i64,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct CreateNotificationRequest {
    user_id: Option<String>,
    #[serde(rename = "type")]
    notification_type: Option<String>,
    title: Option<String>,
    message: Option<String>,
    #[serde(default = "empty_object")]
    data: serde_json::Value,
    action_url: Option<String>,
    expires_at: Option<String>,
}

fn empty_object() -> serde_json::Value {
    json!({})
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SuccessResponse {
    success: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct MarkAllReadResponse {
    success: bool,
    count: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct CreateNotificationResponse {
    id: String,
    success: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct NotificationView {
    id: String,
    #[serde(rename = "type")]
    notification_type: String,
    title: String,
    message: String,
    data: Option<serde_json::Value>,
    is_read: bool,
    action_url: Option<String>,
    created_at: String,
    expires_at: Option<String>,
}

impl NotificationView {
    fn from_record(record: NotificationRecord) -> Self {
        Self {
            id: record.id,
            notification_type: record.notification_type,
            title: record.title,
            message: record.message,
            data: record.data_json,
            is_read: record.is_read,
            action_url: record.action_url,
            created_at: iso8601(record.created_at),
            expires_at: record.expires_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct NotificationListResponse {
    notifications: Vec<NotificationView>,
}

impl NotificationListResponse {
    fn from_records(records: Vec<NotificationRecord>, now: DateTime<Utc>) -> Self {
        Self {
            notifications: records
                .into_iter()
                .filter(|record| notification_is_valid(record, now))
                .map(NotificationView::from_record)
                .collect(),
        }
    }
}

fn notification_is_valid(record: &NotificationRecord, now: DateTime<Utc>) -> bool {
    record.expires_at.is_none_or(|expires_at| expires_at > now)
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn parse_expires_at(value: Option<&str>) -> Result<Option<DateTime<Utc>>, NotificationsApiError> {
    let Some(value) = value.filter(|value| !value.is_empty()) else {
        return Ok(None);
    };
    let normalized = value.replace('Z', "+00:00");
    if let Ok(parsed) = DateTime::parse_from_rfc3339(&normalized) {
        return Ok(Some(parsed.with_timezone(&Utc)));
    }
    for format in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f"] {
        if let Ok(parsed) = NaiveDateTime::parse_from_str(value, format) {
            return Ok(Some(parsed.and_utc()));
        }
    }
    Err(NotificationsApiError::bad_request(
        "Invalid notification expiration timestamp",
    ))
}

#[derive(Debug)]
pub(crate) struct NotificationsApiError {
    status: StatusCode,
    detail: String,
}

impl NotificationsApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
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
}

impl IntoResponse for NotificationsApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use serde_json::Value;

    fn notification(
        id: &str,
        is_read: bool,
        expires_at: Option<DateTime<Utc>>,
    ) -> NotificationRecord {
        NotificationRecord {
            id: id.to_string(),
            user_id: "user-1".to_string(),
            notification_type: "system".to_string(),
            title: "System notice".to_string(),
            message: "A system event happened".to_string(),
            data_json: Some(json!({"severity": "info"})),
            is_read,
            action_url: Some("/settings".to_string()),
            created_at: Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
            expires_at,
        }
    }

    #[test]
    fn notification_list_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/notification_list_response.json"
        ))
        .expect("notification list golden must be valid JSON");
        let response = NotificationListResponse::from_records(
            vec![notification("notification-1", false, None)],
            Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0).unwrap(),
        );

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn notification_list_query_defaults_and_validates_like_python() {
        let query = NotificationListQuery {
            unread_only: true,
            limit: None,
        }
        .validated()
        .expect("query is valid");
        assert!(query.unread_only);
        assert_eq!(query.limit, 20);

        let err = NotificationListQuery {
            unread_only: false,
            limit: Some(0),
        }
        .validated()
        .expect_err("limit below minimum rejected");
        assert_eq!(err.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[test]
    fn expired_notifications_are_filtered_after_limit_like_python() {
        let response = NotificationListResponse::from_records(
            vec![
                notification(
                    "expired",
                    false,
                    Some(Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap()),
                ),
                notification(
                    "future",
                    false,
                    Some(Utc.with_ymd_and_hms(2026, 1, 3, 0, 0, 0).unwrap()),
                ),
            ],
            Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0).unwrap(),
        );

        assert_eq!(response.notifications.len(), 1);
        assert_eq!(response.notifications[0].id, "future");
    }

    #[test]
    fn notification_success_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/notification_success_response.json"
        ))
        .expect("notification success golden must be valid JSON");
        let value =
            serde_json::to_value(SuccessResponse { success: true }).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn notification_mark_all_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/notification_mark_all_response.json"
        ))
        .expect("notification mark-all golden must be valid JSON");
        let value = serde_json::to_value(MarkAllReadResponse {
            success: true,
            count: 2,
        })
        .expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn notification_create_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/notification_create_response.json"
        ))
        .expect("notification create golden must be valid JSON");
        let value = serde_json::to_value(CreateNotificationResponse {
            id: "notification-1".to_string(),
            success: true,
        })
        .expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn parse_expires_at_matches_python_timestamp_contract() {
        assert_eq!(
            parse_expires_at(Some("2026-01-01T00:00:00Z"))
                .expect("zulu timestamp parses")
                .unwrap(),
            Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap()
        );
        assert_eq!(
            parse_expires_at(Some("2026-01-01T00:00:00"))
                .expect("naive timestamp parses")
                .unwrap(),
            Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap()
        );
        let err =
            parse_expires_at(Some("not-a-timestamp")).expect_err("invalid timestamp rejected");
        assert_eq!(err.status, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn dev_notification_service_mutates_current_user_notifications() {
        let service = DevNotificationService::new(vec![
            notification("notification-1", false, None),
            notification("notification-2", false, None),
            NotificationRecord {
                user_id: "other-user".to_string(),
                ..notification("notification-other", false, None)
            },
        ]);

        let marked = service
            .mark_read("user-1", "notification-1")
            .await
            .expect("mark read succeeds");
        assert!(marked.success);

        let all = service
            .mark_all_read("user-1")
            .await
            .expect("mark all succeeds");
        assert_eq!(all.count, 1);

        let deleted = service
            .delete_notification("user-1", "notification-2")
            .await
            .expect("delete succeeds");
        assert!(deleted.success);

        let create = service
            .create_notification(
                "user-1",
                CreateNotificationRequest {
                    user_id: None,
                    notification_type: None,
                    title: None,
                    message: Some("hello".to_string()),
                    data: json!({"source":"test"}),
                    action_url: None,
                    expires_at: Some("2026-01-01T00:00:00Z".to_string()),
                },
            )
            .await
            .expect("create succeeds");
        assert!(create.success);

        let forbidden = service
            .create_notification(
                "user-1",
                CreateNotificationRequest {
                    user_id: Some("other-user".to_string()),
                    notification_type: None,
                    title: None,
                    message: None,
                    data: json!({}),
                    action_url: None,
                    expires_at: None,
                },
            )
            .await
            .expect_err("non-superuser cannot create for another user");
        assert_eq!(forbidden.status, StatusCode::FORBIDDEN);

        let missing = service
            .mark_read("user-1", "notification-other")
            .await
            .expect_err("other user's notification is hidden");
        assert_eq!(missing.status, StatusCode::NOT_FOUND);
    }
}
