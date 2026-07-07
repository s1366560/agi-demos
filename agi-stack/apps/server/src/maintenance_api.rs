//! P7 maintenance status exact read slice.
//!
//! Rust owns only authenticated `GET /api/v1/maintenance/status`. Refresh,
//! optimization, invalidation, and runtime mutation siblings remain Python-owned.

use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{Duration, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;

use agistack_core::model::{GraphStats, GraphStatsScope};

use crate::auth::Identity;
use crate::data_api::DataStatsApiError;
use crate::identity::{IdentityError, ProjectListInput};
use crate::AppState;

const FANOUT_PROJECT_PAGE_SIZE: i64 = 100;
const FANOUT_PROJECT_PAGE_LIMIT: i64 = 10;

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/maintenance/status", get(get_maintenance_status))
        .route("/api/v1/maintenance/status/", get(get_maintenance_status))
}

async fn get_maintenance_status(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<MaintenanceStatusQuery>,
) -> Result<Json<MaintenanceStatusResponse>, MaintenanceApiError> {
    let scope = resolve_maintenance_scope(&app, &identity, query.project_id.as_deref()).await?;
    let now = Utc::now();
    let stats = app
        .graph
        .stats(scope.clone())
        .await
        .map_err(MaintenanceApiError::internal)?;
    let old_episode_count = app
        .graph
        .count_episodes_older_than(scope, (now - Duration::days(90)).timestamp_millis())
        .await
        .map_err(MaintenanceApiError::internal)?;
    Ok(Json(maintenance_status_response(
        stats,
        old_episode_count,
        now,
    )))
}

async fn resolve_maintenance_scope(
    app: &AppState,
    identity: &Identity,
    project_id: Option<&str>,
) -> Result<GraphStatsScope, MaintenanceApiError> {
    if let Some(project_id) = nonblank(project_id) {
        return app
            .data_stats
            .resolve_scope(&identity.user_id, None, Some(project_id))
            .await
            .map(|scope| scope.graph_scope())
            .map_err(MaintenanceApiError::from_explicit_project_scope);
    }

    match app
        .data_stats
        .resolve_scope(&identity.user_id, None, None)
        .await
    {
        Ok(scope) => {
            let graph_scope = scope.graph_scope();
            if matches!(graph_scope, GraphStatsScope::All) {
                return Ok(graph_scope);
            }
        }
        Err(error) if error.status().is_server_error() => {
            return Err(MaintenanceApiError::from_data_stats(error));
        }
        Err(_) => {}
    }

    visible_project_scope(app, &identity.user_id).await
}

async fn visible_project_scope(
    app: &AppState,
    user_id: &str,
) -> Result<GraphStatsScope, MaintenanceApiError> {
    let mut project_ids = Vec::new();
    let mut page = 1;
    while page <= FANOUT_PROJECT_PAGE_LIMIT {
        let page_result = app
            .identity
            .list_projects(
                user_id,
                ProjectListInput {
                    tenant_id: None,
                    search: None,
                    visibility: "all",
                    owner_id: None,
                    page,
                    page_size: FANOUT_PROJECT_PAGE_SIZE,
                },
            )
            .await
            .map_err(MaintenanceApiError::from_identity)?;
        let returned = page_result.projects.len() as i64;
        project_ids.extend(page_result.projects.into_iter().map(|project| project.id));
        if returned == 0 || project_ids.len() as i64 >= page_result.total {
            break;
        }
        page += 1;
    }
    project_ids.sort();
    project_ids.dedup();
    Ok(GraphStatsScope::Projects(project_ids))
}

fn maintenance_status_response(
    stats: GraphStats,
    old_episode_count: usize,
    now: chrono::DateTime<Utc>,
) -> MaintenanceStatusResponse {
    MaintenanceStatusResponse {
        stats: MaintenanceStatsView {
            entities: stats.entities,
            episodes: stats.episodes,
            communities: stats.communities,
            old_episodes: old_episode_count,
        },
        recommendations: maintenance_recommendations(
            stats.entities,
            stats.episodes,
            stats.communities,
            old_episode_count,
        ),
        last_checked: now.to_rfc3339_opts(SecondsFormat::Micros, false),
    }
}

fn maintenance_recommendations(
    entity_count: usize,
    episode_count: usize,
    community_count: usize,
    old_episode_count: usize,
) -> Vec<MaintenanceRecommendation> {
    let mut recommendations = Vec::new();
    if old_episode_count > 1000 {
        recommendations.push(MaintenanceRecommendation {
            recommendation_type: "cleanup",
            priority: "medium",
            message: format!(
                "Consider cleaning up {old_episode_count} episodes older than 90 days"
            ),
        });
    }
    if entity_count > 10000 {
        recommendations.push(MaintenanceRecommendation {
            recommendation_type: "deduplicate",
            priority: "low",
            message: "Large number of entities detected. Consider running deduplication"
                .to_string(),
        });
    }
    if community_count == 0 && episode_count > 100 {
        recommendations.push(MaintenanceRecommendation {
            recommendation_type: "rebuild_communities",
            priority: "high",
            message: "No communities detected. Consider rebuilding communities".to_string(),
        });
    }
    recommendations
}

fn nonblank(value: Option<&str>) -> Option<&str> {
    value.map(str::trim).filter(|value| !value.is_empty())
}

#[derive(Debug)]
struct MaintenanceApiError {
    status: StatusCode,
    detail: String,
}

impl MaintenanceApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }

    fn from_data_stats(error: DataStatsApiError) -> Self {
        Self::new(error.status(), error.detail().to_string())
    }

    fn from_explicit_project_scope(error: DataStatsApiError) -> Self {
        if error.status() == StatusCode::FORBIDDEN {
            return Self::forbidden("Access denied to project");
        }
        Self::from_data_stats(error)
    }

    fn from_identity(error: IdentityError) -> Self {
        Self::new(error.status, error.detail)
    }
}

impl IntoResponse for MaintenanceApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[derive(Debug, Clone, Deserialize)]
struct MaintenanceStatusQuery {
    project_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct MaintenanceStatusResponse {
    stats: MaintenanceStatsView,
    recommendations: Vec<MaintenanceRecommendation>,
    last_checked: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct MaintenanceStatsView {
    entities: usize,
    episodes: usize,
    communities: usize,
    old_episodes: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct MaintenanceRecommendation {
    #[serde(rename = "type")]
    recommendation_type: &'static str,
    priority: &'static str,
    message: String,
}

#[cfg(test)]
mod tests {
    use chrono::TimeZone;
    use serde_json::Value;

    use super::*;

    #[test]
    fn maintenance_status_response_matches_golden() {
        let response = maintenance_status_response(
            GraphStats {
                entities: 10_001,
                episodes: 101,
                communities: 0,
                relationships: 12,
                total_nodes: 10_102,
            },
            1_001,
            Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0)
                .single()
                .expect("valid timestamp"),
        );
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/maintenance_status_response.json"
        ))
        .expect("maintenance status golden must be valid JSON");
        let actual = serde_json::to_value(response).expect("response must serialize");
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn maintenance_recommendation_thresholds_match_python_contract() {
        assert!(maintenance_recommendations(10_000, 100, 0, 1_000).is_empty());
        assert_eq!(
            maintenance_recommendations(10_001, 101, 0, 1_001)
                .into_iter()
                .map(|recommendation| recommendation.recommendation_type)
                .collect::<Vec<_>>(),
            vec!["cleanup", "deduplicate", "rebuild_communities"]
        );
    }

    #[test]
    fn blank_project_id_is_treated_as_omitted() {
        assert_eq!(nonblank(Some("  project-1  ")), Some("project-1"));
        assert_eq!(nonblank(Some("   ")), None);
        assert_eq!(nonblank(None), None);
    }
}
