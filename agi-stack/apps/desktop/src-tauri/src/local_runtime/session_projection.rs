use std::sync::Arc;

use axum::{
    extract::{Extension, Path, State},
    http::StatusCode,
    Json,
};
use serde::Serialize;
use serde_json::{json, Value};

use super::{
    auth_context::AuthenticatedContext,
    authority_store::{DesktopArtifactStatus, DesktopPlanStatus, DesktopRun, DesktopRunStatus},
    local_store_error, scoped_conversation,
    session_store::ConversationSessionSnapshot,
    tool_authority::{self, InvocationStatus},
    ConversationRunMode, LocalJsonResult, LocalRuntimeState,
};

pub(super) async fn conversation_session(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
) -> LocalJsonResult {
    scoped_conversation(&state, &authenticated, &conversation_id)?;
    let snapshot = state
        .session_store
        .conversation_session_snapshot(&conversation_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "conversation not found" })),
            )
        })?;

    let run_actions = run_actions(snapshot.current_run.as_ref());
    let can_send_message = snapshot.conversation.current_mode == ConversationRunMode::Plan;
    let can_approve_plan = can_send_message
        && snapshot
            .current_plan
            .as_ref()
            .is_some_and(|plan| plan.status == DesktopPlanStatus::Draft);
    let can_respond_to_hitl = !snapshot.pending_hitl.is_empty();
    let run_accepts_input = snapshot
        .current_run
        .as_ref()
        .is_some_and(|run| run.status == DesktopRunStatus::Running);
    let can_steer_now = snapshot
        .current_run
        .as_ref()
        .is_some_and(|run| run_accepts_input && state.control_for_run(run).is_some());
    let can_review_artifacts = snapshot
        .artifact_versions
        .iter()
        .any(|artifact| artifact.status.can_review());
    let can_deliver_artifacts = snapshot
        .artifact_versions
        .iter()
        .any(|artifact| artifact.status == DesktopArtifactStatus::Approved);
    let availability = ActionAvailability {
        can_send_message,
        can_approve_plan,
        can_respond_to_hitl,
        can_steer_now,
        can_queue_next: run_accepts_input,
        can_review_artifacts,
        can_deliver_artifacts,
    };
    let allowed_actions = allowed_actions(&availability, &run_actions);

    let artifact_check_count = snapshot
        .artifact_versions
        .iter()
        .map(|artifact| artifact.checks.len())
        .sum::<usize>();
    let artifact_version_count = snapshot.artifact_versions.len();
    let artifact_delivery_count = snapshot.artifact_deliveries.len();
    let tool_invocation_count = snapshot.tool_invocations.len();
    let artifacts_without_checks = snapshot
        .artifact_versions
        .iter()
        .filter(|artifact| artifact.checks.is_empty())
        .count();
    let artifact_source_count = snapshot
        .artifact_versions
        .iter()
        .map(|artifact| artifact.sources.len())
        .sum::<usize>();
    let unknown_outcome_count = snapshot
        .tool_invocations
        .iter()
        .filter(|invocation| invocation.status == InvocationStatus::UnknownOutcome)
        .count();
    let checks = (!snapshot.artifact_versions.is_empty()).then(|| {
        json!({
            "total": artifact_check_count,
            "artifact_versions_without_checks": artifacts_without_checks,
        })
    });
    let updated_at = snapshot_updated_at(&snapshot);
    let mut payload = json!({
        "schema_version": 1,
        "conversation": state.conversation_value(&snapshot.conversation),
        "current_run": snapshot.current_run,
        "run_history": snapshot.run_history,
        "current_plan": snapshot.current_plan,
        "plan_history": snapshot.plan_history,
        "tasks": snapshot.tasks,
        "pending_hitl": snapshot.pending_hitl,
        "artifact_versions": snapshot.artifact_versions,
        "artifact_deliveries": snapshot.artifact_deliveries,
        "tool_invocations": snapshot.tool_invocations,
        "evidence_summary": {
            "artifact_version_count": artifact_version_count,
            "artifact_delivery_count": artifact_delivery_count,
            "artifact_source_count": artifact_source_count,
            "tool_invocation_count": tool_invocation_count,
            "unknown_outcome_count": unknown_outcome_count,
            "checks": checks,
            "changes": Value::Null,
        },
        "capabilities": {
            "can_send_message": availability.can_send_message,
            "can_approve_plan": availability.can_approve_plan,
            "can_respond_to_hitl": availability.can_respond_to_hitl,
            "can_steer_now": availability.can_steer_now,
            "can_queue_next": availability.can_queue_next,
            "can_review_artifacts": availability.can_review_artifacts,
            "can_deliver_artifacts": availability.can_deliver_artifacts,
            "run_actions": run_actions,
            "allowed_actions": allowed_actions,
        },
        "updated_at": updated_at,
    });
    let snapshot_revision = tool_authority::canonical_json_digest(&payload)
        .map_err(|error| local_store_error(error.to_string()))?;
    payload["snapshot_revision"] = json!(snapshot_revision);
    Ok(Json(payload))
}

fn run_actions(run: Option<&DesktopRun>) -> Vec<&'static str> {
    match run.map(|run| run.status) {
        Some(DesktopRunStatus::Running) => vec!["pause", "cancel"],
        Some(DesktopRunStatus::Paused) => vec!["resume", "cancel"],
        Some(DesktopRunStatus::Disconnected | DesktopRunStatus::Interrupted) => {
            vec!["reconnect", "fork", "cancel"]
        }
        Some(DesktopRunStatus::ReadyReview) => vec!["request_changes", "approve"],
        _ => Vec::new(),
    }
}

#[derive(Clone, Copy, Debug, Serialize)]
struct ActionAvailability {
    can_send_message: bool,
    can_approve_plan: bool,
    can_respond_to_hitl: bool,
    can_steer_now: bool,
    can_queue_next: bool,
    can_review_artifacts: bool,
    can_deliver_artifacts: bool,
}

fn allowed_actions(
    availability: &ActionAvailability,
    run_actions: &[&'static str],
) -> Vec<&'static str> {
    let candidates = [
        (availability.can_send_message, "send_message"),
        (availability.can_approve_plan, "approve_plan_and_start"),
        (availability.can_respond_to_hitl, "respond_to_hitl"),
        (availability.can_steer_now, "steer_now"),
        (availability.can_queue_next, "queue_next"),
        (availability.can_review_artifacts, "review_artifact"),
        (availability.can_deliver_artifacts, "deliver_artifact"),
    ];
    candidates
        .into_iter()
        .filter_map(|(allowed, action)| allowed.then_some(action))
        .chain(run_actions.iter().copied())
        .collect()
}

fn snapshot_updated_at(snapshot: &ConversationSessionSnapshot) -> String {
    let mut latest = snapshot.conversation.updated_at.as_str();
    for candidate in snapshot
        .run_history
        .iter()
        .map(|run| run.updated_at.as_str())
        .chain(snapshot.plan_history.iter().flat_map(|plan| {
            [Some(plan.created_at.as_str()), plan.approved_at.as_deref()]
                .into_iter()
                .flatten()
        }))
        .chain(
            snapshot
                .tasks
                .iter()
                .filter_map(|task| task.get("updated_at").and_then(Value::as_str)),
        )
        .chain(snapshot.pending_hitl.iter().flat_map(|request| {
            [
                Some(request.created_at.as_str()),
                request.responded_at.as_deref(),
            ]
            .into_iter()
            .flatten()
        }))
        .chain(
            snapshot
                .artifact_versions
                .iter()
                .map(|artifact| artifact.updated_at.as_str()),
        )
        .chain(
            snapshot
                .artifact_deliveries
                .iter()
                .map(|delivery| delivery.created_at.as_str()),
        )
    {
        if candidate > latest {
            latest = candidate;
        }
    }
    latest.to_string()
}
