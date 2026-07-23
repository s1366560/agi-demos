use std::sync::Arc;

use agistack_core::agent::types::SessionStatus;
use axum::{
    extract::{Extension, Path, State},
    http::StatusCode,
    Json,
};
use serde::Deserialize;
use serde_json::json;
use uuid::Uuid;

use super::{
    append_review_decision,
    auth_context::AuthenticatedContext,
    authority_store::{
        is_recovered_unstarted_run, DesktopExecutionEnvironment, DesktopExecutionEnvironmentKind,
        DesktopRun, DesktopRunStatus,
    },
    ensure_active_project, ensure_checkpoint_control_authority, ensure_checkpoint_run_ownership,
    ensure_run_revision, execution_environment_error,
    has_checkpoint_terminalization_recovery_error, local_store_error, now_iso, LocalJsonResult,
    LocalRuntimeState,
};

#[derive(Deserialize)]
pub(super) struct RunRevisionBody {
    expected_revision: u64,
}

pub(super) async fn pause_run(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
    Json(body): Json<RunRevisionBody>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    ensure_run_revision(&run, body.expected_revision)?;
    ensure_checkpoint_run_ownership(&state, &run)?;
    if run.status != DesktopRunStatus::Running {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "only a running execution can be paused" })),
        ));
    }
    ensure_checkpoint_control_authority(&state, &run).await?;
    let control = state.control_for_run(&run).ok_or_else(|| {
        (
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "run is not attached to this runtime; reconnect before pausing"
            })),
        )
    })?;
    control.request_pause();
    Ok(Json(json!({
        "accepted": true,
        "status": "pause_requested",
        "run": run,
    })))
}

pub(super) async fn resume_run(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
    Json(body): Json<RunRevisionBody>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    ensure_run_revision(&run, body.expected_revision)?;
    ensure_checkpoint_run_ownership(&state, &run)?;
    if !matches!(
        run.status,
        DesktopRunStatus::Paused | DesktopRunStatus::Disconnected | DesktopRunStatus::Interrupted
    ) {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run is not paused, disconnected, or interrupted" })),
        ));
    }
    if has_checkpoint_terminalization_recovery_error(&run) {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "run requires manual recovery after checkpoint persistence failed"
            })),
        ));
    }
    let conversation = state
        .session_store
        .conversation(&run.conversation_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "conversation not found" })),
            )
        })?;
    if is_recovered_unstarted_run(&run) {
        if state
            .has_terminal_authoritative_checkpoint(&run)
            .await
            .map_err(local_store_error)?
        {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({
                    "detail": "run has a terminal checkpoint awaiting startup reconciliation"
                })),
            ));
        }
        let Some(control) = state.claim_agent_run(&conversation.id, Some(&run.id)) else {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": "conversation already running" })),
            ));
        };
        let response = json!({
            "accepted": true,
            "status": "restart_requested",
            "run": run,
        });
        let runtime = Arc::clone(&state);
        let conversation_id = conversation.id;
        let project_id = conversation.project_id;
        let message = run.request_message;
        let message_id = run.message_id;
        let run_id = run.id;
        tokio::spawn(async move {
            runtime
                .run_agent_message(
                    conversation_id,
                    project_id,
                    message,
                    message_id,
                    Some(run_id),
                    Some(control),
                )
                .await;
        });
        return Ok(Json(response));
    }
    let engine = state
        .agent_engine(&conversation, Some(&run))
        .map_err(execution_environment_error)?;
    let Some(control) = state.claim_agent_run(&conversation.id, Some(&run.id)) else {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "conversation already running" })),
        ));
    };
    if let Err(error) = ensure_checkpoint_control_authority(&state, &run).await {
        state.release_agent_run_if_control(&conversation.id, &control);
        return Err(error);
    }
    let accepted = match engine.accept_controlled_resume(&conversation.id).await {
        Ok(accepted) => accepted,
        Err(error) => {
            state.release_agent_run(&conversation.id);
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": error.to_string() })),
            ));
        }
    };
    let running = match state.session_store.transition_run(
        &run.id,
        run.revision,
        DesktopRunStatus::Running,
        None,
        &now_iso(),
    ) {
        Ok(running) => running,
        Err(error) => {
            state.release_agent_run(&conversation.id);
            return Err(local_store_error(error));
        }
    };
    state.publish_run_status(&running);
    let response = json!({
        "accepted": true,
        "status": "running",
        "run": running,
    });
    let goal = accepted.goal;
    let runtime = Arc::clone(&state);
    tokio::spawn(async move {
        runtime
            .continue_after_hitl(conversation, goal, Some(running), control)
            .await;
    });
    Ok(Json(response))
}

#[derive(Deserialize)]
pub(super) struct ForkRecoveryRunBody {
    expected_revision: u64,
    idempotency_key: String,
}

fn cleanup_recovery_worktree(
    state: &LocalRuntimeState,
    environment: &DesktopExecutionEnvironment,
) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
    state
        .worktree_manager()
        .cleanup_checked(environment)
        .map_err(|error| {
            eprintln!("recovery fork worktree cleanup failed: {error}");
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({
                    "detail": "recovery fork worktree cleanup failed"
                })),
            )
        })
}

pub(super) fn rollback_created_recovery_fork(
    state: &LocalRuntimeState,
    source: &DesktopRun,
    forked: &DesktopRun,
    prepared_environment: Option<&DesktopExecutionEnvironment>,
) -> Result<(), (StatusCode, Json<serde_json::Value>)> {
    let rolled_back = state
        .session_store
        .rollback_recovery_fork(source, forked, &now_iso())
        .map_err(local_store_error)?;
    if !rolled_back {
        return Err(local_store_error(
            "created recovery fork disappeared before rollback".to_string(),
        ));
    }
    if let Some(environment) = prepared_environment {
        cleanup_recovery_worktree(state, environment).map_err(|(status, _)| {
            (
                status,
                Json(json!({
                    "detail": "recovery fork rolled back but its worktree cleanup failed"
                })),
            )
        })?;
    }
    Ok(())
}

pub(super) async fn fork_recovery_run(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
    Json(body): Json<ForkRecoveryRunBody>,
) -> LocalJsonResult {
    if body.idempotency_key.trim().is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "detail": "idempotency_key is required" })),
        ));
    }
    let source = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &source.project_id)?;
    ensure_run_revision(&source, body.expected_revision)?;
    if !matches!(
        source.status,
        DesktopRunStatus::Disconnected | DesktopRunStatus::Interrupted
    ) {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "only a disconnected or interrupted run can be forked"
            })),
        ));
    }
    if has_checkpoint_terminalization_recovery_error(&source) {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "run checkpoint is quarantined and cannot seed a recovery fork"
            })),
        ));
    }
    let existing = state
        .session_store
        .run_by_idempotency_key(&body.idempotency_key)
        .map_err(local_store_error)?;
    if let Some(existing) = existing.as_ref() {
        if existing.conversation_id != source.conversation_id
            || existing.authorization_snapshot["source_run_id"].as_str() != Some(source.id.as_str())
        {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": "recovery idempotency key is already in use" })),
            ));
        }
    }

    if existing.is_none() {
        ensure_checkpoint_control_authority(&state, &source).await?;
    }
    if let Some(existing) = existing.as_ref() {
        if existing.status != DesktopRunStatus::Queued {
            return Ok(Json(json!({
                "accepted": true,
                "created": false,
                "status": existing.status,
                "source_run": source,
                "run": existing,
            })));
        }
    }

    let conversation_id = existing
        .as_ref()
        .map(|run| run.conversation_id.as_str())
        .unwrap_or(source.conversation_id.as_str());
    let conversation = state
        .session_store
        .conversation(conversation_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "conversation not found" })),
            )
        })?;
    let reserved_run_id = existing
        .as_ref()
        .map(|run| run.id.clone())
        .unwrap_or_else(|| format!("local-run-{}", Uuid::new_v4()));
    let Some(mut control) = state.claim_agent_run(&conversation.id, Some(&reserved_run_id)) else {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "conversation already running" })),
        ));
    };

    let manager = state.worktree_manager();
    let (forked, created, prepared_environment) = if let Some(existing) = existing {
        (existing, false, None)
    } else {
        let source_environment = match source.environment.as_ref() {
            Some(environment) => environment.clone(),
            None => {
                #[cfg(test)]
                state
                    .recovery_fork_prepare_attempts
                    .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                match manager.prepare(
                    DesktopExecutionEnvironmentKind::Local,
                    &format!("local-environment-{}", Uuid::new_v4()),
                    &now_iso(),
                ) {
                    Ok(prepared) => prepared.environment,
                    Err(error) => {
                        state.release_agent_run_if_control(&conversation.id, &control);
                        return Err(execution_environment_error(error));
                    }
                }
            }
        };
        #[cfg(test)]
        state
            .recovery_fork_prepare_attempts
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let prepared = match manager.prepare_recovery_fork(
            &source_environment,
            &source.id,
            &format!("local-environment-{}", Uuid::new_v4()),
            &now_iso(),
        ) {
            Ok(prepared) => prepared,
            Err(error) => {
                state.release_agent_run_if_control(&conversation.id, &control);
                return Err(execution_environment_error(error));
            }
        };
        let outcome = match state.session_store.fork_recovery_run_with_id(
            &source.id,
            source.revision,
            &body.idempotency_key,
            &reserved_run_id,
            prepared.environment.clone(),
            &now_iso(),
        ) {
            Ok(outcome) => outcome,
            Err(error) => {
                let store_error = local_store_error(error);
                state.release_agent_run_if_control(&conversation.id, &control);
                cleanup_recovery_worktree(&state, &prepared.environment)?;
                return Err(store_error);
            }
        };
        (outcome.0, outcome.1, Some(prepared.environment))
    };
    if !created {
        if let Some(prepared_environment) = prepared_environment.as_ref() {
            if let Err(error) = cleanup_recovery_worktree(&state, prepared_environment) {
                state.release_agent_run_if_control(&conversation.id, &control);
                return Err(error);
            }
        }
        if forked.id != reserved_run_id {
            state.release_agent_run_if_control(&conversation.id, &control);
            let Some(reclaimed) = state.claim_agent_run(&conversation.id, Some(&forked.id)) else {
                return Err((
                    StatusCode::CONFLICT,
                    Json(json!({ "detail": "conversation already running" })),
                ));
            };
            control = reclaimed;
        }
    }
    if forked.status != DesktopRunStatus::Queued {
        state.release_agent_run_if_control(&conversation.id, &control);
        return Ok(Json(json!({
            "accepted": true,
            "created": created,
            "status": forked.status,
            "source_run": source,
            "run": forked,
        })));
    }
    let engine = match state.agent_engine(&conversation, Some(&forked)) {
        Ok(engine) => engine,
        Err(error) => {
            state.release_agent_run_if_control(&conversation.id, &control);
            if created {
                rollback_created_recovery_fork(
                    &state,
                    &source,
                    &forked,
                    prepared_environment.as_ref(),
                )?;
            } else if let Ok(failed) = state.session_store.transition_run(
                &forked.id,
                forked.revision,
                DesktopRunStatus::Failed,
                Some(error.clone()),
                &now_iso(),
            ) {
                state.publish_run_status(&failed);
            }
            return Err(execution_environment_error(error));
        }
    };
    if let Err(error) =
        state
            .session_store
            .transfer_checkpoint_authority(&source, &forked, &now_iso())
    {
        state.release_agent_run_if_control(&conversation.id, &control);
        if created {
            rollback_created_recovery_fork(
                &state,
                &source,
                &forked,
                prepared_environment.as_ref(),
            )?;
        } else if let Ok(failed) = state.session_store.transition_run(
            &forked.id,
            forked.revision,
            DesktopRunStatus::Failed,
            Some(error.clone()),
            &now_iso(),
        ) {
            state.publish_run_status(&failed);
        }
        return Err((StatusCode::CONFLICT, Json(json!({ "detail": error }))));
    }
    if let Err(error) = ensure_checkpoint_control_authority(&state, &forked).await {
        state.release_agent_run_if_control(&conversation.id, &control);
        if created {
            rollback_created_recovery_fork(
                &state,
                &source,
                &forked,
                prepared_environment.as_ref(),
            )?;
        }
        return Err(error);
    }
    let accepted = match engine.accept_controlled_resume(&conversation.id).await {
        Ok(accepted) => accepted,
        Err(error) => {
            state.release_agent_run_if_control(&conversation.id, &control);
            if created {
                rollback_created_recovery_fork(
                    &state,
                    &source,
                    &forked,
                    prepared_environment.as_ref(),
                )?;
            } else if let Ok(failed) = state.session_store.transition_run(
                &forked.id,
                forked.revision,
                DesktopRunStatus::Failed,
                Some(error.to_string()),
                &now_iso(),
            ) {
                state.publish_run_status(&failed);
            }
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": error.to_string() })),
            ));
        }
    };
    let running = match state
        .session_store
        .prepare_run_for_execution(&forked.id, &now_iso())
    {
        Ok(Some(running)) => running,
        Ok(None) => {
            state.release_agent_run_if_control(&conversation.id, &control);
            if created {
                rollback_created_recovery_fork(
                    &state,
                    &source,
                    &forked,
                    prepared_environment.as_ref(),
                )?;
            }
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": "recovery run is no longer queued" })),
            ));
        }
        Err(error) => {
            state.release_agent_run_if_control(&conversation.id, &control);
            if created {
                rollback_created_recovery_fork(
                    &state,
                    &source,
                    &forked,
                    prepared_environment.as_ref(),
                )?;
            }
            return Err(local_store_error(error));
        }
    };
    state.publish_run_status(&running);
    let item = state.timeline_item(
        "recovery_forked",
        conversation.id.clone(),
        Some(running.message_id.clone()),
        None,
        None,
        json!({
            "source_run_id": source.id,
            "run_id": running.id,
            "environment": running.environment,
        }),
    );
    state.append_timeline(&conversation.id, item);
    let goal = accepted.goal;
    let runtime = Arc::clone(&state);
    let running_for_task = running.clone();
    tokio::spawn(async move {
        runtime
            .continue_after_hitl(conversation, goal, Some(running_for_task), control)
            .await;
    });
    Ok(Json(json!({
        "accepted": true,
        "created": created,
        "status": "running",
        "source_run": source,
        "run": running,
    })))
}

pub(super) async fn cancel_run(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
    Json(body): Json<RunRevisionBody>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    ensure_run_revision(&run, body.expected_revision)?;
    ensure_checkpoint_run_ownership(&state, &run)?;
    if run.status == DesktopRunStatus::Running {
        ensure_checkpoint_control_authority(&state, &run).await?;
        let control = state.control_for_run(&run).ok_or_else(|| {
            (
                StatusCode::CONFLICT,
                Json(json!({
                    "detail": "run is not attached to this runtime; reconnect before cancelling"
                })),
            )
        })?;
        control.request_cancel();
        return Ok(Json(json!({
            "accepted": true,
            "status": "cancel_requested",
            "run": run,
        })));
    }
    if !matches!(
        run.status,
        DesktopRunStatus::Paused | DesktopRunStatus::Disconnected | DesktopRunStatus::Interrupted
    ) {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run cannot be cancelled from its current status" })),
        ));
    }
    if is_recovered_unstarted_run(&run) {
        let Some(control) = state.claim_agent_run(&run.conversation_id, Some(&run.id)) else {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": "conversation already running" })),
            ));
        };
        if let Err(error) = state.ensure_authoritative_launch_checkpoint(&run).await {
            state.release_agent_run_if_control(&run.conversation_id, &control);
            return Err(local_store_error(error));
        }
        if let Err(error) = state
            .terminalize_authoritative_checkpoint(&run, SessionStatus::Cancelled)
            .await
        {
            state.release_agent_run_if_control(&run.conversation_id, &control);
            return Err(local_store_error(error));
        }
        let cancelled = state.session_store.transition_run(
            &run.id,
            run.revision,
            DesktopRunStatus::Cancelled,
            None,
            &now_iso(),
        );
        state.release_agent_run_if_control(&run.conversation_id, &control);
        let cancelled = cancelled.map_err(local_store_error)?;
        state.publish_run_status(&cancelled);
        return Ok(Json(json!({
            "accepted": true,
            "status": "cancelled",
            "run": cancelled,
        })));
    }
    let conversation = state
        .session_store
        .conversation(&run.conversation_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "conversation not found" })),
            )
        })?;
    let engine = state
        .agent_engine(&conversation, Some(&run))
        .map_err(execution_environment_error)?;
    let Some(control) = state.claim_agent_run(&conversation.id, Some(&run.id)) else {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "conversation already running" })),
        ));
    };
    if let Err(error) = ensure_checkpoint_control_authority(&state, &run).await {
        state.release_agent_run_if_control(&conversation.id, &control);
        return Err(error);
    }
    if let Err(error) = engine.accept_controlled_cancel(&conversation.id).await {
        state.release_agent_run_if_control(&conversation.id, &control);
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": error.to_string() })),
        ));
    }
    let cancelled = state.session_store.transition_run(
        &run.id,
        run.revision,
        DesktopRunStatus::Cancelled,
        None,
        &now_iso(),
    );
    state.release_agent_run_if_control(&conversation.id, &control);
    let cancelled = cancelled.map_err(local_store_error)?;
    state.publish_run_status(&cancelled);
    Ok(Json(json!({
        "accepted": true,
        "status": "cancelled",
        "run": cancelled,
    })))
}

#[derive(Deserialize)]
pub(super) struct ReviewRunBody {
    action: String,
    expected_revision: u64,
    #[serde(default)]
    feedback: Option<String>,
}

pub(super) async fn review_run(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
    Json(body): Json<ReviewRunBody>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    ensure_run_revision(&run, body.expected_revision)?;
    ensure_checkpoint_run_ownership(&state, &run)?;
    if run.status != DesktopRunStatus::ReadyReview {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run is not ready for review" })),
        ));
    }
    match body.action.as_str() {
        "approve" => {
            let (completed, decision) = state
                .session_store
                .transition_review_run(
                    &run.id,
                    run.revision,
                    DesktopRunStatus::Completed,
                    &body.action,
                    None,
                    &now_iso(),
                )
                .map_err(local_store_error)?;
            state.publish_run_status(&completed);
            append_review_decision(&state, &completed, &decision, &body.action, None);
            Ok(Json(json!({
                "accepted": true,
                "status": "completed",
                "run": completed,
            })))
        }
        "request_changes" => {
            let feedback = body
                .feedback
                .as_deref()
                .map(str::trim)
                .filter(|feedback| !feedback.is_empty())
                .ok_or_else(|| {
                    (
                        StatusCode::BAD_REQUEST,
                        Json(json!({ "detail": "review feedback is required" })),
                    )
                })?
                .to_string();
            let conversation = state
                .session_store
                .conversation(&run.conversation_id)
                .map_err(local_store_error)?
                .ok_or_else(|| {
                    (
                        StatusCode::NOT_FOUND,
                        Json(json!({ "detail": "conversation not found" })),
                    )
                })?;
            let engine = state
                .agent_engine(&conversation, Some(&run))
                .map_err(execution_environment_error)?;
            let Some(control) = state.claim_agent_run(&conversation.id, Some(&run.id)) else {
                return Err((
                    StatusCode::CONFLICT,
                    Json(json!({ "detail": "conversation already running" })),
                ));
            };
            if let Err(error) = ensure_checkpoint_control_authority(&state, &run).await {
                state.release_agent_run_if_control(&conversation.id, &control);
                return Err(error);
            }
            let accepted = match engine
                .accept_review_changes(&conversation.id, &feedback)
                .await
            {
                Ok(accepted) => accepted,
                Err(error) => {
                    state.release_agent_run(&conversation.id);
                    return Err((
                        StatusCode::CONFLICT,
                        Json(json!({ "detail": error.to_string() })),
                    ));
                }
            };
            let (running, decision) = match state.session_store.transition_review_run(
                &run.id,
                run.revision,
                DesktopRunStatus::Running,
                "request_changes",
                Some(&feedback),
                &now_iso(),
            ) {
                Ok(running) => running,
                Err(error) => {
                    state.release_agent_run(&conversation.id);
                    return Err(local_store_error(error));
                }
            };
            state.publish_run_status(&running);
            append_review_decision(
                &state,
                &running,
                &decision,
                "request_changes",
                Some(&feedback),
            );
            let response = json!({
                "accepted": true,
                "status": "running",
                "run": running,
            });
            let goal = accepted.goal;
            let runtime = Arc::clone(&state);
            tokio::spawn(async move {
                runtime
                    .continue_after_hitl(conversation, goal, Some(running), control)
                    .await;
            });
            Ok(Json(response))
        }
        _ => Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "detail": "review action must be approve or request_changes" })),
        )),
    }
}
