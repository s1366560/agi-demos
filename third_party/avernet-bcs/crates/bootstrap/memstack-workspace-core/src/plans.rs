//! Legacy-compatible Workspace Plan HTTP routes.

use std::sync::Arc;

use axum::extract::rejection::JsonRejection;
use axum::extract::{Path, Query, Request, State};
use axum::http::{HeaderMap, header};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_service::{
    PublicWorkspacePlanAction, PublicWorkspacePlanActionResult, PublicWorkspacePlanContext,
    PublicWorkspacePlanService, PublicWorkspacePlanSnapshot, PublicWorkspacePlanSnapshotInput,
};
use memstack_workspace_service_api::WorkspacePlanJudgePort;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::WorkspaceCoreState;
use crate::plan_http_models::{
    ActionBody, PlanHttpError, RawSnapshotQuery, action_input, map_service_error,
    parse_action_body, parse_snapshot_query, plan_caller, plan_context,
};
use crate::workspace_scope::{WorkspaceScopeError, resolve_workspace_scope};

/// Dependencies for the independently mountable Plan compatibility surface.
pub struct PlanHttpState {
    db: Arc<dyn DbPlugin>,
    sql_flavor: DbSqlFlavor,
    judge: Arc<dyn WorkspacePlanJudgePort>,
    service_token: String,
    scope_state: WorkspaceCoreState,
}

impl PlanHttpState {
    /// Construct Cloud or Desktop Plan HTTP state without exposing its token.
    ///
    /// # Errors
    ///
    /// Returns an error for a blank token or unsupported SQL flavor.
    pub fn new(
        db: Arc<dyn DbPlugin>,
        service_token: String,
        sql_flavor: DbSqlFlavor,
        judge: Arc<dyn WorkspacePlanJudgePort>,
    ) -> Result<Self, &'static str> {
        let scope_state = WorkspaceCoreState::new_with_sql_flavor(
            Arc::clone(&db),
            service_token.clone(),
            sql_flavor,
        )?;
        Ok(Self {
            db,
            sql_flavor,
            judge,
            service_token,
            scope_state,
        })
    }
}

/// Mount all eleven frozen Workspace Plan routes behind service authentication.
pub fn plan_routes(state: Arc<PlanHttpState>) -> Router {
    Router::new()
        .route("/api/v1/workspaces/{workspace_id}/plan", get(get_plan))
        .route(
            "/api/v1/workspaces/{workspace_id}/plan/recover-stale-attempts",
            post(recover_stale_attempts),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/plan/outbox/{outbox_id}/retry",
            post(retry_outbox),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/plan/iteration/pause",
            post(pause_iteration),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/plan/iteration/resume",
            post(resume_iteration),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/plan/iteration/trigger-next",
            post(trigger_next_iteration),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/plan/delivery/run-pipeline",
            post(run_pipeline),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/plan/delivery/regenerate-contract",
            post(regenerate_delivery_contract),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/plan/nodes/{node_id}/request-replan",
            post(request_node_replan),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/plan/nodes/{node_id}/reopen",
            post(reopen_node),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/plan/nodes/{node_id}/accept-review",
            post(accept_node_review),
        )
        .route_layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            require_service_token,
        ))
        .with_state(state)
}

async fn get_plan(
    State(state): State<Arc<PlanHttpState>>,
    Path(workspace_id): Path<String>,
    Query(raw_query): Query<RawSnapshotQuery>,
    headers: HeaderMap,
) -> Result<Json<PublicWorkspacePlanSnapshot>, PlanHttpError> {
    let query = parse_snapshot_query(raw_query)?;
    let context = resolve_context(&state, &headers, &workspace_id).await?;
    if query.recover_stale_attempts {
        let input = action_input(
            context.clone(),
            PublicWorkspacePlanAction::RecoverStaleAttempts,
            empty_action_body(),
            None,
            None,
            &headers,
        )?;
        plan_service(&state)
            .act(&input)
            .await
            .map_err(map_service_error)?;
    }
    plan_service(&state)
        .snapshot(&PublicWorkspacePlanSnapshotInput {
            context,
            plan_id: query.plan_id,
            include_details: query.include_details,
            outbox_limit: query.outbox_limit,
            event_limit: query.event_limit,
        })
        .await
        .map(Json)
        .map_err(map_service_error)
}

async fn recover_stale_attempts(
    state: State<Arc<PlanHttpState>>,
    path: Path<String>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_workspace_action(
        state.0,
        path.0,
        headers,
        request,
        PublicWorkspacePlanAction::RecoverStaleAttempts,
        None,
        None,
        false,
    )
    .await
}

async fn retry_outbox(
    State(state): State<Arc<PlanHttpState>>,
    Path((workspace_id, outbox_id)): Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_workspace_action(
        state,
        workspace_id,
        headers,
        request,
        PublicWorkspacePlanAction::RetryOutbox,
        None,
        Some(outbox_id),
        false,
    )
    .await
}

async fn pause_iteration(
    state: State<Arc<PlanHttpState>>,
    path: Path<String>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_simple_action(
        state,
        path,
        headers,
        request,
        PublicWorkspacePlanAction::PauseIteration,
    )
    .await
}

async fn resume_iteration(
    state: State<Arc<PlanHttpState>>,
    path: Path<String>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_simple_action(
        state,
        path,
        headers,
        request,
        PublicWorkspacePlanAction::ResumeIteration,
    )
    .await
}

async fn trigger_next_iteration(
    state: State<Arc<PlanHttpState>>,
    path: Path<String>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_simple_action(
        state,
        path,
        headers,
        request,
        PublicWorkspacePlanAction::TriggerNextIteration,
    )
    .await
}

async fn run_pipeline(
    state: State<Arc<PlanHttpState>>,
    path: Path<String>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_workspace_action(
        state.0,
        path.0,
        headers,
        request,
        PublicWorkspacePlanAction::RunPipeline,
        None,
        None,
        true,
    )
    .await
}

async fn regenerate_delivery_contract(
    state: State<Arc<PlanHttpState>>,
    path: Path<String>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_simple_action(
        state,
        path,
        headers,
        request,
        PublicWorkspacePlanAction::RegenerateDeliveryContract,
    )
    .await
}

async fn request_node_replan(
    state: State<Arc<PlanHttpState>>,
    path: Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_node_action(
        state,
        path,
        headers,
        request,
        PublicWorkspacePlanAction::RequestNodeReplan,
    )
    .await
}

async fn reopen_node(
    state: State<Arc<PlanHttpState>>,
    path: Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_node_action(
        state,
        path,
        headers,
        request,
        PublicWorkspacePlanAction::ReopenNode,
    )
    .await
}

async fn accept_node_review(
    state: State<Arc<PlanHttpState>>,
    path: Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_node_action(
        state,
        path,
        headers,
        request,
        PublicWorkspacePlanAction::AcceptNodeReview,
    )
    .await
}

async fn run_simple_action(
    State(state): State<Arc<PlanHttpState>>,
    Path(workspace_id): Path<String>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
    action: PublicWorkspacePlanAction,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_workspace_action(
        state,
        workspace_id,
        headers,
        request,
        action,
        None,
        None,
        false,
    )
    .await
}

async fn run_node_action(
    State(state): State<Arc<PlanHttpState>>,
    Path((workspace_id, node_id)): Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
    action: PublicWorkspacePlanAction,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    run_workspace_action(
        state,
        workspace_id,
        headers,
        request,
        action,
        Some(node_id),
        None,
        false,
    )
    .await
}

#[allow(clippy::too_many_arguments)]
async fn run_workspace_action(
    state: Arc<PlanHttpState>,
    workspace_id: String,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
    action: PublicWorkspacePlanAction,
    node_id: Option<String>,
    outbox_id: Option<String>,
    allow_body_node_id: bool,
) -> Result<Json<PublicWorkspacePlanActionResult>, PlanHttpError> {
    let body = parse_action_body(request, allow_body_node_id)?;
    let context = resolve_context(&state, &headers, &workspace_id).await?;
    let input = action_input(context, action, body, node_id, outbox_id, &headers)?;
    plan_service(&state)
        .act(&input)
        .await
        .map(Json)
        .map_err(map_service_error)
}

async fn resolve_context(
    state: &PlanHttpState,
    headers: &HeaderMap,
    workspace_id: &str,
) -> Result<PublicWorkspacePlanContext, PlanHttpError> {
    let caller = plan_caller(headers)?;
    let scope = resolve_workspace_scope(&state.scope_state, workspace_id, &caller.user_id)
        .await
        .map_err(map_scope_error)?;
    plan_context(headers, caller, scope)
}

fn plan_service(state: &PlanHttpState) -> PublicWorkspacePlanService<'_> {
    PublicWorkspacePlanService::new(state.db.as_ref(), state.sql_flavor, state.judge.as_ref())
}

fn empty_action_body() -> ActionBody {
    ActionBody {
        reason: None,
        evidence_refs: Vec::new(),
        node_id: None,
    }
}

fn map_scope_error(error: WorkspaceScopeError) -> PlanHttpError {
    match error {
        WorkspaceScopeError::NotFound => PlanHttpError::not_found("Workspace not found"),
        WorkspaceScopeError::AccessRequired => PlanHttpError::forbidden("Access denied"),
        WorkspaceScopeError::InvalidRecord(_) | WorkspaceScopeError::Database(_) => {
            PlanHttpError::unavailable()
        }
    }
}

async fn require_service_token(
    State(state): State<Arc<PlanHttpState>>,
    request: Request,
    next: Next,
) -> Response {
    let supplied = request
        .headers()
        .get(header::AUTHORIZATION)
        .map(axum::http::HeaderValue::as_bytes)
        .unwrap_or_default();
    let expected = format!("Bearer {}", state.service_token);
    if !secret_matches(supplied, expected.as_bytes()) {
        return PlanHttpError::unauthorized().into_response();
    }
    next.run(request).await
}

fn secret_matches(left: &[u8], right: &[u8]) -> bool {
    let left = Sha256::digest(left);
    let right = Sha256::digest(right);
    left.iter()
        .zip(right.iter())
        .fold(0_u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}
