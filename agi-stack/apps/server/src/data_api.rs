//! P7 data export/stats/cleanup exact slices.
//!
//! Rust owns `GET /api/v1/data/stats`, `POST /api/v1/data/export`, and
//! `POST /api/v1/data/cleanup`.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use serde::Deserialize;
use serde::Serialize;
use serde_json::{json, Map, Value};

use agistack_adapters_postgres::{
    DataStatsAccess, DataStatsScopeError, DataStatsScopeRecord, PgDataStatsRepository,
};
use agistack_core::model::{GraphEntity, GraphExport, GraphStats, GraphStatsScope, Relationship};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedDataStats = Arc<dyn DataStatsScopeService>;

#[async_trait]
pub(crate) trait DataStatsScopeService: Send + Sync {
    async fn resolve_scope(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        project_id: Option<&str>,
    ) -> Result<DataStatsScope, DataStatsApiError>;

    async fn resolve_scope_with_admin_requirement(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        project_id: Option<&str>,
        require_admin: bool,
    ) -> Result<DataStatsScope, DataStatsApiError>;
}

pub(crate) struct PgDataStatsScopeService {
    repo: PgDataStatsRepository,
}

impl PgDataStatsScopeService {
    pub(crate) fn new(repo: PgDataStatsRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl DataStatsScopeService for PgDataStatsScopeService {
    async fn resolve_scope(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        project_id: Option<&str>,
    ) -> Result<DataStatsScope, DataStatsApiError> {
        self.repo
            .resolve_scope(user_id, tenant_id, project_id)
            .await
            .map_err(DataStatsApiError::internal)?
            .map(DataStatsScope::from)
            .map_err(DataStatsApiError::from_scope)
    }

    async fn resolve_scope_with_admin_requirement(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        project_id: Option<&str>,
        require_admin: bool,
    ) -> Result<DataStatsScope, DataStatsApiError> {
        self.repo
            .resolve_scope_with_admin_requirement(user_id, tenant_id, project_id, require_admin)
            .await
            .map_err(DataStatsApiError::internal)?
            .map(DataStatsScope::from)
            .map_err(DataStatsApiError::from_scope)
    }
}

#[derive(Default)]
pub(crate) struct DevDataStatsScopeService {
    tenant_project_ids: Vec<String>,
}

impl DevDataStatsScopeService {
    #[cfg(test)]
    pub(crate) fn new(tenant_project_ids: Vec<String>) -> Self {
        Self { tenant_project_ids }
    }
}

#[async_trait]
impl DataStatsScopeService for DevDataStatsScopeService {
    async fn resolve_scope(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        project_id: Option<&str>,
    ) -> Result<DataStatsScope, DataStatsApiError> {
        if let Some(project_id) = project_id {
            return Ok(DataStatsScope {
                tenant_id: tenant_id.map(str::to_string),
                project_id: Some(project_id.to_string()),
                graph_scope: GraphStatsScope::Projects(vec![project_id.to_string()]),
            });
        }
        Ok(DataStatsScope {
            tenant_id: tenant_id.map(str::to_string),
            project_id: None,
            graph_scope: if tenant_id.is_some() && !self.tenant_project_ids.is_empty() {
                GraphStatsScope::Projects(self.tenant_project_ids.clone())
            } else {
                GraphStatsScope::All
            },
        })
    }

    async fn resolve_scope_with_admin_requirement(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        project_id: Option<&str>,
        _require_admin: bool,
    ) -> Result<DataStatsScope, DataStatsApiError> {
        self.resolve_scope(user_id, tenant_id, project_id).await
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct DataStatsScope {
    tenant_id: Option<String>,
    project_id: Option<String>,
    graph_scope: GraphStatsScope,
}

impl From<DataStatsScopeRecord> for DataStatsScope {
    fn from(record: DataStatsScopeRecord) -> Self {
        Self {
            tenant_id: record.tenant_id,
            project_id: record.project_id,
            graph_scope: match record.access {
                DataStatsAccess::AllProjects => GraphStatsScope::All,
                DataStatsAccess::ProjectIds(project_ids) => GraphStatsScope::Projects(project_ids),
            },
        }
    }
}

impl DataStatsScope {
    pub(crate) fn graph_scope(&self) -> GraphStatsScope {
        self.graph_scope.clone()
    }
}

#[derive(Debug)]
pub(crate) struct DataStatsApiError {
    status: StatusCode,
    detail: String,
}

impl DataStatsApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }

    fn from_scope(error: DataStatsScopeError) -> Self {
        match error {
            DataStatsScopeError::ProjectNotFound => {
                Self::new(StatusCode::NOT_FOUND, "Project not found")
            }
            DataStatsScopeError::ProjectTenantMismatch => {
                Self::new(StatusCode::BAD_REQUEST, "Project does not belong to tenant")
            }
            DataStatsScopeError::ProjectAccessRequired => {
                Self::new(StatusCode::FORBIDDEN, "Project access required")
            }
            DataStatsScopeError::TenantAccessRequired => {
                Self::new(StatusCode::FORBIDDEN, "Tenant access required")
            }
            DataStatsScopeError::AdminAccessRequired => {
                Self::new(StatusCode::FORBIDDEN, "Admin access required")
            }
        }
    }

    pub(crate) fn status(&self) -> StatusCode {
        self.status
    }

    pub(crate) fn detail(&self) -> &str {
        &self.detail
    }
}

impl IntoResponse for DataStatsApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/data/stats", get(get_data_stats))
        .route("/api/v1/data/export", post(export_data))
        .route("/api/v1/data/cleanup", post(cleanup_data))
}

async fn export_data(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    body: Option<Json<DataExportRequest>>,
) -> Result<Json<DataExportResponse>, DataStatsApiError> {
    let request = body.map(|Json(request)| request).unwrap_or_default();
    let scope = app
        .data_stats
        .resolve_scope(
            &identity.user_id,
            request.tenant_id.as_deref(),
            request.project_id.as_deref(),
        )
        .await?;
    let export = app
        .graph
        .export(scope.graph_scope)
        .await
        .map_err(DataStatsApiError::internal)?;
    Ok(Json(DataExportResponse::from_export(
        export,
        &request,
        scope.tenant_id,
        scope.project_id,
        now_exported_at(),
    )))
}

async fn get_data_stats(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<DataStatsQuery>,
) -> Result<Json<DataStatsResponse>, DataStatsApiError> {
    let scope = app
        .data_stats
        .resolve_scope(
            &identity.user_id,
            query.tenant_id.as_deref(),
            query.project_id.as_deref(),
        )
        .await?;
    let stats = app
        .graph
        .stats(scope.graph_scope)
        .await
        .map_err(DataStatsApiError::internal)?;
    Ok(Json(DataStatsResponse::from_stats(
        stats,
        scope.tenant_id,
        scope.project_id,
    )))
}

async fn cleanup_data(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<DataCleanupQuery>,
    body: Option<Json<Value>>,
) -> Result<Json<DataCleanupResponse>, DataStatsApiError> {
    let body = match body {
        Some(Json(Value::Object(body))) => Some(body),
        Some(Json(Value::Null)) | None => None,
        Some(Json(_)) => {
            return Err(DataStatsApiError::unprocessable(
                "Invalid cleanup request body",
            ))
        }
    };
    let body = body.as_ref();
    let dry_run =
        normalize_cleanup_dry_run(cleanup_value(body, "dry_run", query.dry_run.as_deref()))?;
    let older_than_days = normalize_cleanup_days(cleanup_value(
        body,
        "older_than_days",
        query.older_than_days.as_deref(),
    ))?;
    let tenant_id = normalize_cleanup_optional_string(
        cleanup_value(body, "tenant_id", query.tenant_id.as_deref()),
        "Invalid tenant_id value",
    )?;
    let project_id = normalize_cleanup_optional_string(
        cleanup_value(body, "project_id", query.project_id.as_deref()),
        "Invalid project_id value",
    )?;
    let scope = app
        .data_stats
        .resolve_scope_with_admin_requirement(
            &identity.user_id,
            tenant_id.as_deref(),
            project_id.as_deref(),
            !dry_run,
        )
        .await?;
    let cutoff = cutoff_for_days(older_than_days)?;
    let cutoff_ms = cutoff.timestamp_millis();
    let cutoff_date = cutoff.to_rfc3339_opts(chrono::SecondsFormat::Secs, false);
    if dry_run {
        let count = app
            .graph
            .count_episodes_older_than(scope.graph_scope, cutoff_ms)
            .await
            .map_err(DataStatsApiError::internal)?;
        Ok(Json(DataCleanupResponse::dry_run(
            count,
            cutoff_date,
            scope.tenant_id,
            scope.project_id,
            older_than_days,
        )))
    } else {
        let deleted = app
            .graph
            .delete_episodes_older_than(scope.graph_scope, cutoff_ms)
            .await
            .map_err(DataStatsApiError::internal)?;
        Ok(Json(DataCleanupResponse::deleted(
            deleted,
            cutoff_date,
            scope.tenant_id,
            scope.project_id,
            older_than_days,
        )))
    }
}

#[derive(Debug, Clone, Deserialize)]
struct DataStatsQuery {
    tenant_id: Option<String>,
    project_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct DataCleanupQuery {
    dry_run: Option<String>,
    older_than_days: Option<String>,
    tenant_id: Option<String>,
    project_id: Option<String>,
}

enum CleanupValue<'a> {
    Missing,
    Query(&'a str),
    Body(&'a Value),
}

fn cleanup_value<'a>(
    body: Option<&'a Map<String, Value>>,
    key: &str,
    query_value: Option<&'a str>,
) -> CleanupValue<'a> {
    if let Some(value) = body.and_then(|body| body.get(key)) {
        CleanupValue::Body(value)
    } else if let Some(value) = query_value {
        CleanupValue::Query(value)
    } else {
        CleanupValue::Missing
    }
}

fn normalize_cleanup_dry_run(value: CleanupValue<'_>) -> Result<bool, DataStatsApiError> {
    match value {
        CleanupValue::Missing | CleanupValue::Body(Value::Null) => Ok(true),
        CleanupValue::Body(Value::Bool(value)) => Ok(*value),
        CleanupValue::Query(value) => match value.trim().to_ascii_lowercase().as_str() {
            "true" | "1" | "yes" | "on" => Ok(true),
            "false" | "0" | "no" | "off" => Ok(false),
            _ => Err(DataStatsApiError::unprocessable("Invalid dry_run value")),
        },
        CleanupValue::Body(Value::String(value)) => {
            match value.trim().to_ascii_lowercase().as_str() {
                "true" | "1" | "yes" | "on" => Ok(true),
                "false" | "0" | "no" | "off" => Ok(false),
                _ => Err(DataStatsApiError::unprocessable("Invalid dry_run value")),
            }
        }
        CleanupValue::Body(_) => Err(DataStatsApiError::unprocessable("Invalid dry_run value")),
    }
}

fn normalize_cleanup_days(value: CleanupValue<'_>) -> Result<usize, DataStatsApiError> {
    match value {
        CleanupValue::Missing | CleanupValue::Body(Value::Null) => Ok(90),
        CleanupValue::Query(value) => parse_cleanup_days(value),
        CleanupValue::Body(Value::String(value)) => parse_cleanup_days(value),
        CleanupValue::Body(Value::Number(value)) => {
            let Some(days) = value.as_u64() else {
                return Err(invalid_cleanup_days());
            };
            if days == 0 {
                return Err(invalid_cleanup_days());
            }
            usize::try_from(days).map_err(|_| invalid_cleanup_days())
        }
        CleanupValue::Body(Value::Bool(_)) | CleanupValue::Body(_) => Err(invalid_cleanup_days()),
    }
}

fn parse_cleanup_days(value: &str) -> Result<usize, DataStatsApiError> {
    let value = value.trim();
    if value.is_empty() || !value.chars().all(|ch| ch.is_ascii_digit()) {
        return Err(invalid_cleanup_days());
    }
    let days = value.parse::<usize>().map_err(|_| invalid_cleanup_days())?;
    if days == 0 {
        return Err(invalid_cleanup_days());
    }
    Ok(days)
}

fn invalid_cleanup_days() -> DataStatsApiError {
    DataStatsApiError::unprocessable("older_than_days must be a positive integer")
}

fn normalize_cleanup_optional_string(
    value: CleanupValue<'_>,
    invalid_detail: &'static str,
) -> Result<Option<String>, DataStatsApiError> {
    match value {
        CleanupValue::Missing | CleanupValue::Body(Value::Null) => Ok(None),
        CleanupValue::Query(value) => Ok(Some(value.to_string())),
        CleanupValue::Body(Value::String(value)) => Ok(Some(value.to_string())),
        CleanupValue::Body(_) => Err(DataStatsApiError::unprocessable(invalid_detail)),
    }
}

fn cutoff_for_days(days: usize) -> Result<chrono::DateTime<chrono::Utc>, DataStatsApiError> {
    let days = i64::try_from(days).map_err(|_| invalid_cleanup_days())?;
    let duration = chrono::TimeDelta::try_days(days).ok_or_else(invalid_cleanup_days)?;
    chrono::Utc::now()
        .checked_sub_signed(duration)
        .ok_or_else(invalid_cleanup_days)
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
struct DataExportRequest {
    #[serde(default)]
    tenant_id: Option<String>,
    #[serde(default)]
    project_id: Option<String>,
    #[serde(default = "default_true")]
    include_episodes: bool,
    #[serde(default = "default_true")]
    include_entities: bool,
    #[serde(default = "default_true")]
    include_relationships: bool,
    #[serde(default = "default_true")]
    include_communities: bool,
}

impl Default for DataExportRequest {
    fn default() -> Self {
        Self {
            tenant_id: None,
            project_id: None,
            include_episodes: true,
            include_entities: true,
            include_relationships: true,
            include_communities: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct DataStatsResponse {
    entities: usize,
    episodes: usize,
    communities: usize,
    relationships: usize,
    total_nodes: usize,
    tenant_id: Option<String>,
    project_id: Option<String>,
}

impl DataStatsResponse {
    fn from_stats(
        stats: GraphStats,
        tenant_id: Option<String>,
        project_id: Option<String>,
    ) -> Self {
        Self {
            entities: stats.entities,
            episodes: stats.episodes,
            communities: stats.communities,
            relationships: stats.relationships,
            total_nodes: stats.total_nodes,
            tenant_id,
            project_id,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct DataCleanupResponse {
    dry_run: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    would_delete: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    deleted: Option<usize>,
    cutoff_date: String,
    tenant_id: Option<String>,
    project_id: Option<String>,
    message: String,
}

impl DataCleanupResponse {
    fn dry_run(
        would_delete: usize,
        cutoff_date: String,
        tenant_id: Option<String>,
        project_id: Option<String>,
        older_than_days: usize,
    ) -> Self {
        Self {
            dry_run: true,
            would_delete: Some(would_delete),
            deleted: None,
            cutoff_date,
            tenant_id,
            project_id,
            message: format!(
                "Would delete {would_delete} episodes older than {older_than_days} days"
            ),
        }
    }

    fn deleted(
        deleted: usize,
        cutoff_date: String,
        tenant_id: Option<String>,
        project_id: Option<String>,
        older_than_days: usize,
    ) -> Self {
        Self {
            dry_run: false,
            would_delete: None,
            deleted: Some(deleted),
            cutoff_date,
            tenant_id,
            project_id,
            message: format!("Deleted {deleted} episodes older than {older_than_days} days"),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct DataExportResponse {
    exported_at: String,
    tenant_id: Option<String>,
    project_id: Option<String>,
    episodes: Vec<Value>,
    entities: Vec<Value>,
    relationships: Vec<Value>,
    communities: Vec<Value>,
}

impl DataExportResponse {
    fn from_export(
        mut export: GraphExport,
        request: &DataExportRequest,
        tenant_id: Option<String>,
        project_id: Option<String>,
        exported_at: String,
    ) -> Self {
        export.entities.sort_by(|a, b| {
            a.project_id
                .cmp(&b.project_id)
                .then_with(|| a.entity_type.cmp(&b.entity_type))
                .then_with(|| a.uuid.cmp(&b.uuid))
        });
        export.relationships.sort_by(|a, b| {
            a.project_id
                .cmp(&b.project_id)
                .then_with(|| a.uuid.cmp(&b.uuid))
        });

        let episodes = if request.include_episodes {
            export
                .entities
                .iter()
                .filter(|entity| entity.entity_type == "Episodic")
                .map(entity_properties)
                .collect()
        } else {
            Vec::new()
        };
        let entities = if request.include_entities {
            export
                .entities
                .iter()
                .filter(|entity| {
                    entity.entity_type != "Episodic" && entity.entity_type != "Community"
                })
                .map(entity_export_properties)
                .collect()
        } else {
            Vec::new()
        };
        let communities = if request.include_communities {
            export
                .entities
                .iter()
                .filter(|entity| entity.entity_type == "Community")
                .map(entity_properties)
                .collect()
        } else {
            Vec::new()
        };
        let relationships = if request.include_relationships {
            export
                .relationships
                .iter()
                .map(relationship_export_properties)
                .collect()
        } else {
            Vec::new()
        };

        Self {
            exported_at,
            tenant_id,
            project_id,
            episodes,
            entities,
            relationships,
            communities,
        }
    }
}

fn now_exported_at() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn entity_properties(entity: &GraphEntity) -> Value {
    let mut out = Map::new();
    out.insert("uuid".to_string(), json!(&entity.uuid));
    out.insert("name".to_string(), json!(&entity.name));
    out.insert("entity_type".to_string(), json!(&entity.entity_type));
    out.insert("summary".to_string(), json!(&entity.summary));
    out.insert("project_id".to_string(), json!(&entity.project_id));
    if let Some(tenant_id) = &entity.tenant_id {
        out.insert("tenant_id".to_string(), json!(tenant_id));
    }
    out.insert("created_at_ms".to_string(), json!(entity.created_at_ms));
    if let Some(name_embedding) = &entity.name_embedding {
        out.insert("name_embedding".to_string(), json!(name_embedding));
    }
    Value::Object(out)
}

fn entity_export_properties(entity: &GraphEntity) -> Value {
    let mut value = entity_properties(entity);
    if let Value::Object(ref mut object) = value {
        object.insert("labels".to_string(), json!(["Entity"]));
    }
    value
}

fn relationship_export_properties(relationship: &Relationship) -> Value {
    json!({
        "edge_id": &relationship.uuid,
        "type": &relationship.relation_type,
        "properties": {
            "uuid": &relationship.uuid,
            "fact": &relationship.fact,
            "score": relationship.score,
            "project_id": &relationship.project_id,
            "created_at_ms": relationship.created_at_ms,
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn dev_scope_uses_exact_project_or_configured_tenant_projects() {
        let service = DevDataStatsScopeService::new(vec!["p1".to_string(), "p2".to_string()]);
        let project_scope = service
            .resolve_scope("user", Some("t1"), Some("p3"))
            .await
            .expect("scope resolves");
        assert_eq!(project_scope.tenant_id.as_deref(), Some("t1"));
        assert_eq!(project_scope.project_id.as_deref(), Some("p3"));
        assert_eq!(
            project_scope.graph_scope,
            GraphStatsScope::Projects(vec!["p3".to_string()])
        );

        let tenant_scope = service
            .resolve_scope("user", Some("t1"), None)
            .await
            .expect("scope resolves");
        assert_eq!(
            tenant_scope.graph_scope,
            GraphStatsScope::Projects(vec!["p1".to_string(), "p2".to_string()])
        );
    }

    #[test]
    fn data_stats_response_matches_golden() {
        let response = DataStatsResponse::from_stats(
            GraphStats {
                entities: 3,
                episodes: 2,
                communities: 1,
                relationships: 4,
                total_nodes: 6,
            },
            Some("tenant-1".to_string()),
            Some("project-1".to_string()),
        );
        let expected: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/data_stats_response.json"))
                .expect("data stats golden must be valid JSON");
        let actual = serde_json::to_value(response).expect("response must serialize");
        assert_eq!(actual, expected);
    }

    #[test]
    fn data_export_response_matches_golden_and_include_flags() {
        let export = GraphExport {
            entities: vec![
                GraphEntity {
                    uuid: "entity-1".to_string(),
                    name: "Rust".to_string(),
                    entity_type: "Concept".to_string(),
                    summary: "Portable runtime".to_string(),
                    project_id: "project-1".to_string(),
                    tenant_id: Some("tenant-1".to_string()),
                    created_at_ms: 1_700_000_000_000,
                    name_embedding: None,
                },
                GraphEntity {
                    uuid: "episode-1".to_string(),
                    name: "Episode".to_string(),
                    entity_type: "Episodic".to_string(),
                    summary: "Imported episode".to_string(),
                    project_id: "project-1".to_string(),
                    tenant_id: Some("tenant-1".to_string()),
                    created_at_ms: 1_700_000_001_000,
                    name_embedding: None,
                },
                GraphEntity {
                    uuid: "community-1".to_string(),
                    name: "Community".to_string(),
                    entity_type: "Community".to_string(),
                    summary: "Stable community".to_string(),
                    project_id: "project-1".to_string(),
                    tenant_id: Some("tenant-1".to_string()),
                    created_at_ms: 1_700_000_002_000,
                    name_embedding: None,
                },
            ],
            relationships: vec![Relationship {
                uuid: "rel-1".to_string(),
                source_uuid: "entity-1".to_string(),
                target_uuid: "episode-1".to_string(),
                relation_type: "MENTIONS".to_string(),
                fact: "Rust is mentioned".to_string(),
                score: 0.75,
                project_id: "project-1".to_string(),
                created_at_ms: 1_700_000_003_000,
            }],
        };
        let response = DataExportResponse::from_export(
            export,
            &DataExportRequest {
                include_communities: false,
                ..DataExportRequest::default()
            },
            Some("tenant-1".to_string()),
            Some("project-1".to_string()),
            "2026-01-01T00:00:00Z".to_string(),
        );
        let expected: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/data_export_response.json"))
                .expect("data export golden must be valid JSON");
        let actual = serde_json::to_value(response).expect("response must serialize");
        assert_eq!(actual, expected);
    }

    #[test]
    fn data_cleanup_response_matches_golden() {
        let response = DataCleanupResponse::dry_run(
            2,
            "2026-01-01T00:00:00+00:00".to_string(),
            Some("tenant-1".to_string()),
            Some("project-1".to_string()),
            90,
        );
        let expected: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/data_cleanup_response.json"))
                .expect("data cleanup golden must be valid JSON");
        let actual = serde_json::to_value(response).expect("response must serialize");
        assert_eq!(actual, expected);

        let deleted =
            DataCleanupResponse::deleted(1, "2026-01-01T00:00:00+00:00".to_string(), None, None, 7);
        let deleted = serde_json::to_value(deleted).expect("response must serialize");
        assert_eq!(deleted["deleted"], 1);
        assert!(deleted.get("would_delete").is_none());
        assert_eq!(deleted["message"], "Deleted 1 episodes older than 7 days");
    }

    #[test]
    fn cleanup_normalizers_match_python_defaults_and_overrides() {
        let dry_run = normalize_cleanup_dry_run(CleanupValue::Query("yes"))
            .expect("yes should parse as true");
        assert!(dry_run);
        let dry_run = normalize_cleanup_dry_run(CleanupValue::Body(&json!("off")))
            .expect("off should parse as false");
        assert!(!dry_run);
        assert!(normalize_cleanup_dry_run(CleanupValue::Body(&json!("maybe"))).is_err());

        assert_eq!(
            normalize_cleanup_days(CleanupValue::Missing).expect("default days"),
            90
        );
        assert_eq!(
            normalize_cleanup_days(CleanupValue::Body(&json!("007"))).expect("string days"),
            7
        );
        assert!(normalize_cleanup_days(CleanupValue::Body(&json!(true))).is_err());
        assert!(normalize_cleanup_days(CleanupValue::Query("0")).is_err());
        assert!(normalize_cleanup_days(CleanupValue::Query("1.5")).is_err());
    }
}
