use super::super::*;

pub(super) async fn find_active_task_session_attempt(
    store: &FakeWorkspacePlanDispatchStore,
    workspace_task_id: &str,
) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
    let mut attempts = store
        .attempts
        .lock()
        .unwrap()
        .values()
        .filter(|attempt| {
            attempt.workspace_task_id == workspace_task_id
                && matches!(
                    attempt.status.as_str(),
                    "pending" | "running" | "awaiting_leader_adjudication"
                )
        })
        .cloned()
        .collect::<Vec<_>>();
    attempts.sort_by(|left, right| {
        right
            .attempt_number
            .cmp(&left.attempt_number)
            .then_with(|| left.id.cmp(&right.id))
    });
    Ok(attempts.into_iter().next())
}

pub(super) async fn find_latest_accepted_task_session_attempt(
    store: &FakeWorkspacePlanDispatchStore,
    workspace_id: &str,
    workspace_task_id: &str,
) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
    let mut attempts = store
        .attempts
        .lock()
        .unwrap()
        .values()
        .filter(|attempt| {
            attempt.workspace_id == workspace_id
                && attempt.workspace_task_id == workspace_task_id
                && attempt.status == ACCEPTED_ATTEMPT_STATUS
        })
        .cloned()
        .collect::<Vec<_>>();
    attempts.sort_by(|left, right| {
        right
            .attempt_number
            .cmp(&left.attempt_number)
            .then_with(|| left.id.cmp(&right.id))
    });
    Ok(attempts.into_iter().next())
}

pub(super) async fn get_task_session_attempt(
    store: &FakeWorkspacePlanDispatchStore,
    attempt_id: &str,
) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
    Ok(store.attempts.lock().unwrap().get(attempt_id).cloned())
}

pub(super) async fn latest_task_session_attempt_number(
    store: &FakeWorkspacePlanDispatchStore,
    workspace_task_id: &str,
) -> CoreResult<i32> {
    Ok(store
        .attempts
        .lock()
        .unwrap()
        .values()
        .filter(|attempt| attempt.workspace_task_id == workspace_task_id)
        .map(|attempt| attempt.attempt_number)
        .max()
        .unwrap_or(0))
}

pub(super) async fn create_task_session_attempt(
    store: &FakeWorkspacePlanDispatchStore,
    attempt: WorkspaceTaskSessionAttemptRecord,
) -> CoreResult<WorkspaceTaskSessionAttemptRecord> {
    store
        .attempts
        .lock()
        .unwrap()
        .insert(attempt.id.clone(), attempt.clone());
    Ok(attempt)
}

pub(super) async fn mark_task_session_attempt_running(
    store: &FakeWorkspacePlanDispatchStore,
    attempt_id: &str,
    now: DateTime<Utc>,
) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
    let mut attempts = store.attempts.lock().unwrap();
    let Some(attempt) = attempts.get_mut(attempt_id) else {
        return Ok(None);
    };
    attempt.status = "running".to_string();
    attempt.updated_at = Some(now);
    Ok(Some(attempt.clone()))
}

pub(super) async fn bind_task_session_attempt_conversation(
    store: &FakeWorkspacePlanDispatchStore,
    attempt_id: &str,
    conversation_id: &str,
    now: DateTime<Utc>,
) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
    let mut attempts = store.attempts.lock().unwrap();
    let Some(attempt) = attempts.get_mut(attempt_id) else {
        return Ok(None);
    };
    attempt.status = "running".to_string();
    attempt.conversation_id = Some(conversation_id.to_string());
    attempt.updated_at = Some(now);
    Ok(Some(attempt.clone()))
}

pub(super) async fn finish_task_session_attempt(
    store: &FakeWorkspacePlanDispatchStore,
    attempt_id: &str,
    status: &str,
    leader_feedback: Option<&str>,
    adjudication_reason: Option<&str>,
    completed_at: DateTime<Utc>,
) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
    let mut attempts = store.attempts.lock().unwrap();
    let Some(attempt) = attempts.get_mut(attempt_id) else {
        return Ok(None);
    };
    attempt.status = status.to_string();
    attempt.leader_feedback = leader_feedback.map(ToOwned::to_owned);
    attempt.adjudication_reason = adjudication_reason.map(ToOwned::to_owned);
    attempt.completed_at = Some(completed_at);
    attempt.updated_at = Some(completed_at);
    Ok(Some(attempt.clone()))
}

pub(super) async fn record_task_session_attempt_candidate_output(
    store: &FakeWorkspacePlanDispatchStore,
    attempt_id: &str,
    summary: Option<&str>,
    artifacts_json: &[String],
    verifications_json: &[String],
    conversation_id: Option<&str>,
    updated_at: DateTime<Utc>,
) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
    let mut attempts = store.attempts.lock().unwrap();
    let Some(attempt) = attempts.get_mut(attempt_id) else {
        return Ok(None);
    };
    if matches!(
        attempt.status.as_str(),
        "accepted" | "rejected" | "blocked" | "cancelled"
    ) {
        return Ok(Some(attempt.clone()));
    }
    attempt.status = AWAITING_LEADER_ADJUDICATION_STATUS.to_string();
    if let Some(conversation_id) = conversation_id {
        attempt.conversation_id = Some(conversation_id.to_string());
    }
    attempt.candidate_summary = summary.map(ToOwned::to_owned);
    attempt.candidate_artifacts_json = artifacts_json.to_vec();
    attempt.candidate_verifications_json = verifications_json.to_vec();
    attempt.updated_at = Some(updated_at);
    Ok(Some(attempt.clone()))
}

pub(super) async fn count_recent_running_task_session_attempts_with_conversation(
    store: &FakeWorkspacePlanDispatchStore,
) -> CoreResult<i64> {
    Ok(*store.active_worker_conversations.lock().unwrap())
}

pub(super) async fn has_supervisor_dispose_decision_for_node(
    store: &FakeWorkspacePlanDispatchStore,
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
) -> CoreResult<bool> {
    Ok(store.supervisor_dispose_nodes.lock().unwrap().contains(&(
        workspace_id.to_string(),
        plan_id.to_string(),
        node_id.to_string(),
    )))
}
