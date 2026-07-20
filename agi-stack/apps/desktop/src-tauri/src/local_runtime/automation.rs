use axum::{
    extract::{Path, Query},
    http::StatusCode,
    Extension, Json,
};
use serde::Deserialize;
use serde_json::{json, Value};

use super::{ensure_active_project, AuthenticatedContext, LocalJsonResult};

const DEFAULT_PAGE_SIZE: i64 = 50;

#[derive(Debug, Default, Deserialize)]
pub(super) struct ListQuery {
    include_disabled: Option<bool>,
    limit: Option<i64>,
    offset: Option<i64>,
}

#[derive(Debug, Default, Deserialize)]
pub(super) struct RunListQuery {
    limit: Option<i64>,
    offset: Option<i64>,
}

fn validate_page(limit: Option<i64>, offset: Option<i64>) -> Result<(), (StatusCode, Json<Value>)> {
    for (field, value) in [
        ("limit", limit.unwrap_or(DEFAULT_PAGE_SIZE)),
        ("offset", offset.unwrap_or_default()),
    ] {
        if value < 0 {
            return Err((
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({
                    "detail": format!("{field} must be greater than or equal to 0")
                })),
            ));
        }
    }
    Ok(())
}

pub(super) async fn list(
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    Query(query): Query<ListQuery>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    validate_page(query.limit, query.offset)?;
    let _include_disabled = query.include_disabled.unwrap_or(false);
    Ok(Json(json!({ "items": [], "total": 0 })))
}

pub(super) async fn capabilities(
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    let unavailable = json!({
        "allowed": false,
        "reason_code": "durable_automation_runtime_unavailable",
    });
    Ok(Json(json!({
        "schema_version": 1,
        "read": true,
        "revision_guarded": false,
        "idempotency_guarded": false,
        "durable_execution": false,
        "supported_read_trigger_kinds": ["manual", "schedule", "event"],
        "create": unavailable,
        "edit": unavailable,
        "toggle": unavailable,
        "run_now": unavailable,
        "delete": unavailable,
    })))
}

pub(super) async fn get(
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((project_id, _automation_id)): Path<(String, String)>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    not_found()
}

pub(super) async fn list_runs(
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((project_id, _automation_id)): Path<(String, String)>,
    Query(query): Query<RunListQuery>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    validate_page(query.limit, query.offset)?;
    not_found()
}

fn not_found() -> LocalJsonResult {
    Err((
        StatusCode::NOT_FOUND,
        Json(json!({ "detail": "Cron job not found" })),
    ))
}
