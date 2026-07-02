//! P2 memory sharing endpoints.
//!
//! These routes mirror `routers/shares.py` while keeping persistence behind a
//! server-only service: shared Postgres in production, deterministic in-memory
//! storage for offline `cargo run` and unit tests.

use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

use async_trait::async_trait;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{delete, get, post},
    Extension, Json, Router,
};
use chrono::{DateTime, NaiveDateTime, TimeDelta, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use agistack_adapters_postgres::{
    NewShareRecord, PgShareRepository, ShareMemoryRecord, ShareRecord,
};
use agistack_adapters_secrets::{generate_urlsafe_token, generate_uuid_v4};

use crate::{auth::Identity, AppState};

pub(crate) type SharedShares = Arc<dyn ShareService>;

#[async_trait]
pub(crate) trait ShareService: Send + Sync {
    async fn create_share(
        &self,
        memory_id: &str,
        user_id: &str,
        req: ShareCreatePayload,
    ) -> Result<ShareView, ShareError>;

    async fn list_shares(&self, memory_id: &str, user_id: &str) -> Result<ShareList, ShareError>;

    async fn delete_share(
        &self,
        memory_id: &str,
        share_id: &str,
        user_id: &str,
    ) -> Result<(), ShareError>;

    async fn get_shared_memory(&self, share_token: &str) -> Result<SharedMemoryView, ShareError>;
}

#[derive(Debug)]
pub(crate) struct ShareError {
    status: StatusCode,
    detail: String,
}

impl ShareError {
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
}

impl IntoResponse for ShareError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[derive(Clone, Debug, Default, Deserialize)]
pub(crate) struct ShareCreatePayload {
    #[serde(default)]
    target_type: Option<Value>,
    #[serde(default)]
    permission_level: Option<Value>,
    #[serde(default)]
    target_id: Option<Value>,
    #[serde(default)]
    permissions: Option<Value>,
    #[serde(default)]
    expires_at: Option<Value>,
    #[serde(default)]
    expires_in_days: Option<Value>,
}

#[derive(Debug, Serialize)]
pub(crate) struct ShareView {
    id: String,
    share_token: Option<String>,
    memory_id: String,
    shared_with_user_id: Option<String>,
    shared_with_project_id: Option<String>,
    permissions: Value,
    expires_at: Option<String>,
    created_at: String,
    access_count: i32,
}

impl From<ShareRecord> for ShareView {
    fn from(record: ShareRecord) -> Self {
        Self {
            id: record.id,
            share_token: record.share_token,
            memory_id: record.memory_id,
            shared_with_user_id: record.shared_with_user_id,
            shared_with_project_id: record.shared_with_project_id,
            permissions: record.permissions,
            expires_at: record.expires_at.map(iso8601),
            created_at: iso8601(record.created_at),
            access_count: record.access_count,
        }
    }
}

#[derive(Debug, Serialize)]
pub(crate) struct ShareList {
    shares: Vec<ShareListItem>,
}

#[derive(Debug, Serialize)]
struct ShareListItem {
    id: String,
    share_token: Option<String>,
    permissions: Value,
    expires_at: Option<String>,
    created_at: String,
    access_count: i32,
}

impl From<ShareRecord> for ShareListItem {
    fn from(record: ShareRecord) -> Self {
        Self {
            id: record.id,
            share_token: record.share_token,
            permissions: record.permissions,
            expires_at: record.expires_at.map(iso8601),
            created_at: iso8601(record.created_at),
            access_count: record.access_count,
        }
    }
}

#[derive(Debug, Serialize)]
pub(crate) struct SharedMemoryView {
    memory: SharedMemoryBody,
    share: SharedMemoryShareBody,
}

#[derive(Debug, Serialize)]
struct SharedMemoryBody {
    id: String,
    title: String,
    content: String,
    tags: Value,
    created_at: String,
    updated_at: Option<String>,
}

impl From<ShareMemoryRecord> for SharedMemoryBody {
    fn from(record: ShareMemoryRecord) -> Self {
        Self {
            id: record.id,
            title: record.title,
            content: record.content,
            tags: record.tags,
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

#[derive(Debug, Serialize)]
struct SharedMemoryShareBody {
    permissions: Value,
    expires_at: Option<String>,
}

#[derive(Debug)]
enum TargetKind {
    User,
    Project,
}

impl TargetKind {
    fn as_str(&self) -> &'static str {
        match self {
            Self::User => "user",
            Self::Project => "project",
        }
    }
}

#[derive(Debug)]
struct ValidatedTarget {
    kind: TargetKind,
    id: String,
}

pub(crate) struct PgShareService {
    repo: PgShareRepository,
}

impl PgShareService {
    pub(crate) fn new(repo: PgShareRepository) -> Self {
        Self { repo }
    }

    async fn ensure_target_authorized(
        &self,
        user_id: &str,
        target: &ValidatedTarget,
    ) -> Result<(), ShareError> {
        match target.kind {
            TargetKind::User => {
                if self
                    .repo
                    .user_exists(&target.id)
                    .await
                    .map_err(ShareError::internal)?
                {
                    Ok(())
                } else {
                    Err(ShareError::not_found("Target user not found"))
                }
            }
            TargetKind::Project => {
                if !self
                    .repo
                    .project_exists(&target.id)
                    .await
                    .map_err(ShareError::internal)?
                {
                    return Err(ShareError::not_found("Target project not found"));
                }
                if self
                    .repo
                    .user_can_admin_project(user_id, &target.id)
                    .await
                    .map_err(ShareError::internal)?
                {
                    Ok(())
                } else {
                    Err(ShareError::forbidden("Access denied"))
                }
            }
        }
    }

    async fn ensure_share_admin(
        &self,
        memory_id: &str,
        user_id: &str,
    ) -> Result<ShareMemoryRecord, ShareError> {
        let memory = self
            .repo
            .find_memory(memory_id)
            .await
            .map_err(ShareError::internal)?
            .ok_or_else(|| ShareError::not_found("Memory not found"))?;
        if memory.author_id == user_id {
            return Ok(memory);
        }
        if self
            .repo
            .user_can_admin_project(user_id, &memory.project_id)
            .await
            .map_err(ShareError::internal)?
        {
            Ok(memory)
        } else {
            Err(ShareError::forbidden("Access denied"))
        }
    }
}

#[async_trait]
impl ShareService for PgShareService {
    async fn create_share(
        &self,
        memory_id: &str,
        user_id: &str,
        req: ShareCreatePayload,
    ) -> Result<ShareView, ShareError> {
        let memory = self
            .repo
            .find_memory(memory_id)
            .await
            .map_err(ShareError::internal)?
            .ok_or_else(|| ShareError::not_found("Memory not found"))?;
        if memory.author_id != user_id {
            return Err(ShareError::forbidden("Access denied"));
        }

        let target = validate_target(&req)?;
        if let Some(target) = target.as_ref() {
            self.ensure_target_authorized(user_id, target).await?;
            let exists = self
                .repo
                .explicit_target_share_exists(memory_id, target.kind.as_str(), &target.id)
                .await
                .map_err(ShareError::internal)?;
            if exists {
                return Err(ShareError::bad_request(
                    "Memory already shared with this target",
                ));
            }
        }

        let expires_at = parse_share_expiration(&req)?;
        let permissions = share_permissions(&req);
        let record = self
            .repo
            .create_share(NewShareRecord {
                id: generate_uuid_v4(),
                memory_id: memory_id.to_string(),
                share_token: generate_urlsafe_token(32),
                shared_with_user_id: target.as_ref().and_then(|t| match t.kind {
                    TargetKind::User => Some(t.id.clone()),
                    TargetKind::Project => None,
                }),
                shared_with_project_id: target.as_ref().and_then(|t| match t.kind {
                    TargetKind::User => None,
                    TargetKind::Project => Some(t.id.clone()),
                }),
                permissions,
                shared_by: user_id.to_string(),
                expires_at,
            })
            .await
            .map_err(ShareError::internal)?;

        Ok(ShareView::from(record))
    }

    async fn list_shares(&self, memory_id: &str, user_id: &str) -> Result<ShareList, ShareError> {
        self.ensure_share_admin(memory_id, user_id).await?;
        let shares = self
            .repo
            .list_for_memory(memory_id)
            .await
            .map_err(ShareError::internal)?
            .into_iter()
            .map(ShareListItem::from)
            .collect();
        Ok(ShareList { shares })
    }

    async fn delete_share(
        &self,
        memory_id: &str,
        share_id: &str,
        user_id: &str,
    ) -> Result<(), ShareError> {
        self.ensure_share_admin(memory_id, user_id).await?;
        let share = self
            .repo
            .find_share_by_id(share_id)
            .await
            .map_err(ShareError::internal)?
            .ok_or_else(|| ShareError::not_found("Share not found"))?;
        if share.memory_id != memory_id {
            return Err(ShareError::bad_request(
                "Share does not belong to this memory",
            ));
        }
        self.repo
            .delete_share(share_id)
            .await
            .map_err(ShareError::internal)?;
        Ok(())
    }

    async fn get_shared_memory(&self, share_token: &str) -> Result<SharedMemoryView, ShareError> {
        let share = self
            .repo
            .find_share_by_token(share_token)
            .await
            .map_err(ShareError::internal)?
            .ok_or_else(|| ShareError::not_found("Share link not found"))?;

        reject_expired(&share)?;
        if !share_can_view(&share.permissions) {
            return Err(ShareError::forbidden("Share link does not allow viewing"));
        }

        let memory = self
            .repo
            .find_memory(&share.memory_id)
            .await
            .map_err(ShareError::internal)?
            .ok_or_else(|| ShareError::not_found("Memory not found"))?;
        self.repo
            .increment_access_count(&share.id)
            .await
            .map_err(ShareError::internal)?;

        Ok(shared_memory_view(memory, share))
    }
}

pub(crate) struct DevShareService {
    dev_user_id: String,
    memories: Mutex<HashMap<String, ShareMemoryRecord>>,
    shares: Mutex<HashMap<String, ShareRecord>>,
}

impl DevShareService {
    pub(crate) fn new(dev_user_id: impl Into<String>) -> Self {
        let dev_user_id = dev_user_id.into();
        let created_at = sample_dt();
        let mut memories = HashMap::new();
        memories.insert(
            "dev-memory".to_string(),
            ShareMemoryRecord {
                id: "dev-memory".to_string(),
                project_id: "dev-project".to_string(),
                title: "Dev memory".to_string(),
                content: "Shared dev memory".to_string(),
                author_id: dev_user_id.clone(),
                tags: json!([]),
                created_at,
                updated_at: None,
            },
        );
        Self {
            dev_user_id,
            memories: Mutex::new(memories),
            shares: Mutex::new(HashMap::new()),
        }
    }

    fn find_memory(&self, memory_id: &str) -> Result<ShareMemoryRecord, ShareError> {
        self.memories
            .lock()
            .map_err(ShareError::internal)?
            .get(memory_id)
            .cloned()
            .ok_or_else(|| ShareError::not_found("Memory not found"))
    }

    fn ensure_share_admin(
        &self,
        memory_id: &str,
        user_id: &str,
    ) -> Result<ShareMemoryRecord, ShareError> {
        let memory = self.find_memory(memory_id)?;
        if memory.author_id == user_id || user_id == self.dev_user_id {
            Ok(memory)
        } else {
            Err(ShareError::forbidden("Access denied"))
        }
    }
}

#[async_trait]
impl ShareService for DevShareService {
    async fn create_share(
        &self,
        memory_id: &str,
        user_id: &str,
        req: ShareCreatePayload,
    ) -> Result<ShareView, ShareError> {
        let memory = self.find_memory(memory_id)?;
        if memory.author_id != user_id {
            return Err(ShareError::forbidden("Access denied"));
        }

        let target = validate_target(&req)?;
        if let Some(target) = target.as_ref() {
            let duplicate = self
                .shares
                .lock()
                .map_err(ShareError::internal)?
                .values()
                .any(|s| {
                    s.memory_id == memory_id
                        && match target.kind {
                            TargetKind::User => {
                                s.shared_with_user_id.as_deref() == Some(&target.id)
                            }
                            TargetKind::Project => {
                                s.shared_with_project_id.as_deref() == Some(&target.id)
                            }
                        }
                });
            if duplicate {
                return Err(ShareError::bad_request(
                    "Memory already shared with this target",
                ));
            }
        }

        let record = ShareRecord {
            id: generate_uuid_v4(),
            memory_id: memory_id.to_string(),
            share_token: Some(generate_urlsafe_token(32)),
            shared_with_user_id: target.as_ref().and_then(|t| match t.kind {
                TargetKind::User => Some(t.id.clone()),
                TargetKind::Project => None,
            }),
            shared_with_project_id: target.as_ref().and_then(|t| match t.kind {
                TargetKind::User => None,
                TargetKind::Project => Some(t.id.clone()),
            }),
            permissions: share_permissions(&req),
            shared_by: user_id.to_string(),
            created_at: Utc::now(),
            expires_at: parse_share_expiration(&req)?,
            access_count: 0,
        };
        self.shares
            .lock()
            .map_err(ShareError::internal)?
            .insert(record.id.clone(), record.clone());
        Ok(ShareView::from(record))
    }

    async fn list_shares(&self, memory_id: &str, user_id: &str) -> Result<ShareList, ShareError> {
        self.ensure_share_admin(memory_id, user_id)?;
        let mut shares = self
            .shares
            .lock()
            .map_err(ShareError::internal)?
            .values()
            .filter(|s| s.memory_id == memory_id)
            .cloned()
            .collect::<Vec<_>>();
        shares.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        Ok(ShareList {
            shares: shares.into_iter().map(ShareListItem::from).collect(),
        })
    }

    async fn delete_share(
        &self,
        memory_id: &str,
        share_id: &str,
        user_id: &str,
    ) -> Result<(), ShareError> {
        self.ensure_share_admin(memory_id, user_id)?;
        let mut shares = self.shares.lock().map_err(ShareError::internal)?;
        let share = shares
            .get(share_id)
            .ok_or_else(|| ShareError::not_found("Share not found"))?;
        if share.memory_id != memory_id {
            return Err(ShareError::bad_request(
                "Share does not belong to this memory",
            ));
        }
        shares.remove(share_id);
        Ok(())
    }

    async fn get_shared_memory(&self, share_token: &str) -> Result<SharedMemoryView, ShareError> {
        let share = {
            let shares = self.shares.lock().map_err(ShareError::internal)?;
            shares
                .values()
                .find(|s| s.share_token.as_deref() == Some(share_token))
                .cloned()
                .ok_or_else(|| ShareError::not_found("Share link not found"))?
        };
        reject_expired(&share)?;
        if !share_can_view(&share.permissions) {
            return Err(ShareError::forbidden("Share link does not allow viewing"));
        }
        let memory = self.find_memory(&share.memory_id)?;
        {
            let mut shares = self.shares.lock().map_err(ShareError::internal)?;
            if let Some(stored) = shares.get_mut(&share.id) {
                stored.access_count += 1;
            }
        }
        Ok(shared_memory_view(memory, share))
    }
}

fn validate_target(req: &ShareCreatePayload) -> Result<Option<ValidatedTarget>, ShareError> {
    let Some(target_value) = req.target_type.as_ref().filter(|v| python_truthy(v)) else {
        return Ok(None);
    };
    let target_type = target_value
        .as_str()
        .ok_or_else(|| ShareError::bad_request("target_type must be 'user' or 'project'"))?;
    let kind = match target_type {
        "user" => TargetKind::User,
        "project" => TargetKind::Project,
        _ => {
            return Err(ShareError::bad_request(
                "target_type must be 'user' or 'project'",
            ))
        }
    };
    let _permission_level = req
        .permission_level
        .as_ref()
        .and_then(Value::as_str)
        .filter(|p| matches!(*p, "view" | "edit"))
        .ok_or_else(|| ShareError::bad_request("permission_level must be 'view' or 'edit'"))?
        .to_string();
    let id = req
        .target_id
        .as_ref()
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| ShareError::bad_request("target_id is required"))?
        .to_string();
    Ok(Some(ValidatedTarget { kind, id }))
}

fn share_permissions(req: &ShareCreatePayload) -> Value {
    if let Some(permissions) = req.permissions.clone() {
        return permissions;
    }
    let edit = req
        .permission_level
        .as_ref()
        .filter(|v| python_truthy(v))
        .and_then(Value::as_str)
        == Some("edit");
    json!({ "view": true, "edit": edit })
}

fn parse_share_expiration(req: &ShareCreatePayload) -> Result<Option<DateTime<Utc>>, ShareError> {
    if let Some(value) = req.expires_at.as_ref().filter(|v| python_truthy(v)) {
        let Some(raw) = value.as_str() else {
            return Err(ShareError::bad_request("Invalid expires_at format"));
        };
        return parse_datetime(raw)
            .map(Some)
            .map_err(|_| ShareError::bad_request("Invalid expires_at format"));
    }

    let Some(days) = req.expires_in_days.as_ref().and_then(value_as_positive_i64) else {
        return Ok(None);
    };
    Ok(Some(Utc::now() + TimeDelta::days(days)))
}

fn parse_datetime(raw: &str) -> Result<DateTime<Utc>, chrono::ParseError> {
    if let Ok(dt) = DateTime::parse_from_rfc3339(raw) {
        return Ok(dt.with_timezone(&Utc));
    }
    for fmt in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f"] {
        if let Ok(naive) = NaiveDateTime::parse_from_str(raw, fmt) {
            return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
        }
    }
    DateTime::parse_from_rfc3339(raw).map(|dt| dt.with_timezone(&Utc))
}

fn value_as_positive_i64(value: &Value) -> Option<i64> {
    match value {
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_u64().and_then(|u| i64::try_from(u).ok()))
            .filter(|n| *n > 0),
        _ => None,
    }
}

fn python_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(n) => n.as_i64().unwrap_or(1) != 0,
        Value::String(s) => !s.is_empty(),
        Value::Array(items) => !items.is_empty(),
        Value::Object(map) => !map.is_empty(),
    }
}

fn reject_expired(share: &ShareRecord) -> Result<(), ShareError> {
    if share
        .expires_at
        .map(|expires_at| expires_at < Utc::now())
        .unwrap_or(false)
    {
        Err(ShareError::forbidden("Share link has expired"))
    } else {
        Ok(())
    }
}

fn share_can_view(permissions: &Value) -> bool {
    permissions.as_object().and_then(|map| map.get("view")) == Some(&Value::Bool(true))
}

fn shared_memory_view(memory: ShareMemoryRecord, share: ShareRecord) -> SharedMemoryView {
    SharedMemoryView {
        memory: SharedMemoryBody::from(memory),
        share: SharedMemoryShareBody {
            permissions: share.permissions,
            expires_at: share.expires_at.map(iso8601),
        },
    }
}

fn iso8601(dt: DateTime<Utc>) -> String {
    dt.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn sample_dt() -> DateTime<Utc> {
    DateTime::<Utc>::from_timestamp_millis(1_700_000_000_000).unwrap()
}

async fn create_share(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(memory_id): Path<String>,
    Json(req): Json<ShareCreatePayload>,
) -> Result<impl IntoResponse, ShareError> {
    let view = app
        .shares
        .create_share(&memory_id, &identity.user_id, req)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn list_shares(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(memory_id): Path<String>,
) -> Result<Json<ShareList>, ShareError> {
    app.shares
        .list_shares(&memory_id, &identity.user_id)
        .await
        .map(Json)
}

async fn delete_share(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((memory_id, share_id)): Path<(String, String)>,
) -> Result<Response, ShareError> {
    app.shares
        .delete_share(&memory_id, &share_id, &identity.user_id)
        .await?;
    Ok(StatusCode::NO_CONTENT.into_response())
}

async fn get_shared_memory(
    State(app): State<AppState>,
    Path(share_token): Path<String>,
) -> Result<Json<SharedMemoryView>, ShareError> {
    app.shares.get_shared_memory(&share_token).await.map(Json)
}

pub(crate) fn router_authed() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/memories/:memory_id/shares",
            post(create_share).get(list_shares),
        )
        .route(
            "/api/v1/memories/:memory_id/shares/:share_id",
            delete(delete_share),
        )
}

pub(crate) fn router_public() -> Router<AppState> {
    Router::new().route("/api/v1/shared/:share_token", get(get_shared_memory))
}

#[cfg(test)]
mod unit {
    use super::*;

    fn sample_share() -> ShareRecord {
        ShareRecord {
            id: "11111111-1111-4111-8111-111111111111".into(),
            memory_id: "22222222-2222-4222-8222-222222222222".into(),
            share_token: Some("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into()),
            shared_with_user_id: None,
            shared_with_project_id: None,
            permissions: json!({"view": true, "edit": false}),
            shared_by: "33333333-3333-4333-8333-333333333333".into(),
            created_at: sample_dt(),
            expires_at: None,
            access_count: 0,
        }
    }

    fn sample_memory() -> ShareMemoryRecord {
        ShareMemoryRecord {
            id: "22222222-2222-4222-8222-222222222222".into(),
            project_id: "44444444-4444-4444-8444-444444444444".into(),
            title: "Shared memory".into(),
            content: "Rust serves a Python-compatible share link.".into(),
            author_id: "33333333-3333-4333-8333-333333333333".into(),
            tags: json!(["rust", "share"]),
            created_at: sample_dt(),
            updated_at: None,
        }
    }

    #[test]
    fn share_response_matches_golden() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/share_response.json")).unwrap();
        let actual = serde_json::to_value(ShareView::from(sample_share())).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn share_list_matches_golden() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/share_list.json")).unwrap();
        let actual = serde_json::to_value(ShareList {
            shares: vec![ShareListItem::from(sample_share())],
        })
        .unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn shared_memory_matches_golden() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/shared_memory.json")).unwrap();
        let actual =
            serde_json::to_value(shared_memory_view(sample_memory(), sample_share())).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn target_validation_matches_python_errors() {
        let req: ShareCreatePayload =
            serde_json::from_value(json!({"target_type": "team"})).unwrap();
        let err = validate_target(&req).unwrap_err();
        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.detail, "target_type must be 'user' or 'project'");

        let req: ShareCreatePayload =
            serde_json::from_value(json!({"target_type": "user"})).unwrap();
        let err = validate_target(&req).unwrap_err();
        assert_eq!(err.detail, "permission_level must be 'view' or 'edit'");

        let req: ShareCreatePayload =
            serde_json::from_value(json!({"target_type": "user", "permission_level": "view"}))
                .unwrap();
        let err = validate_target(&req).unwrap_err();
        assert_eq!(err.detail, "target_id is required");
    }

    #[test]
    fn share_can_view_requires_explicit_true() {
        assert!(share_can_view(&json!({"view": true})));
        assert!(!share_can_view(&json!({"view": false})));
        assert!(!share_can_view(&json!({"view": "true"})));
        assert!(!share_can_view(&json!(["view"])));
    }
}
