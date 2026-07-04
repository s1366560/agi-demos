use super::*;

pub(super) async fn roundtrip_tasks_and_attempts(
    repo: &PgWorkspaceRepository,
    created_at: DateTime<Utc>,
) {
    let task = repo
        .create_task(WorkspaceTaskRecord {
            id: "task_p6_repo".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            title: "Implement P6".to_string(),
            description: None,
            created_by: "u_p6_owner".to_string(),
            assignee_user_id: Some("u_p6_viewer".to_string()),
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority: 1,
            estimated_effort: Some("M".to_string()),
            blocker_reason: None,
            metadata_json: json!({"leader_only": true}),
            created_at,
            updated_at: None,
            completed_at: None,
            archived_at: None,
        })
        .await
        .unwrap();
    assert_eq!(task.priority, 1);
    let mut task = repo
        .get_task("ws_p6_repo", "task_p6_repo")
        .await
        .unwrap()
        .expect("task");
    task.status = "done".to_string();
    task.completed_at = Some(created_at);
    let saved_task = repo.save_task(task).await.unwrap();
    assert_eq!(saved_task.status, "done");

    let attempt = repo
        .create_task_session_attempt(WorkspaceTaskSessionAttemptRecord {
            id: "attempt_p6_repo_1".to_string(),
            workspace_task_id: "task_p6_repo".to_string(),
            root_goal_task_id: "task_p6_repo".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            attempt_number: 1,
            status: "pending".to_string(),
            conversation_id: None,
            worker_agent_id: Some("agent_p6_worker".to_string()),
            leader_agent_id: None,
            candidate_summary: None,
            candidate_artifacts_json: Vec::new(),
            candidate_verifications_json: Vec::new(),
            leader_feedback: None,
            adjudication_reason: None,
            created_at,
            updated_at: Some(created_at),
            completed_at: None,
        })
        .await
        .unwrap();
    assert_eq!(attempt.status, "pending");
    assert_eq!(
        repo.latest_task_session_attempt_number("task_p6_repo")
            .await
            .unwrap(),
        1
    );
    let running = repo
        .mark_task_session_attempt_running("attempt_p6_repo_1", created_at)
        .await
        .unwrap()
        .expect("attempt should update");
    assert_eq!(running.status, "running");
    let active = repo
        .find_active_task_session_attempt("task_p6_repo")
        .await
        .unwrap()
        .expect("active attempt");
    assert_eq!(active.id, "attempt_p6_repo_1");
    let loaded_attempt = repo
        .get_task_session_attempt("attempt_p6_repo_1")
        .await
        .unwrap()
        .expect("loaded attempt by id");
    assert_eq!(loaded_attempt.workspace_task_id, "task_p6_repo");
    let reported_attempt = repo
        .record_task_session_attempt_candidate_output(
            "attempt_p6_repo_1",
            Some("worker stream completed"),
            &["commit_ref:abcdef1234567890".to_string()],
            &["worker_report:completed".to_string()],
            Some("conv_p6_worker_reported"),
            created_at,
        )
        .await
        .unwrap()
        .expect("reported attempt should update");
    assert_eq!(reported_attempt.status, "awaiting_leader_adjudication");
    assert_eq!(
        reported_attempt.conversation_id.as_deref(),
        Some("conv_p6_worker_reported")
    );
    assert_eq!(
        reported_attempt.candidate_summary.as_deref(),
        Some("worker stream completed")
    );
    assert_eq!(
        reported_attempt.candidate_artifacts_json,
        vec!["commit_ref:abcdef1234567890".to_string()]
    );
    assert_eq!(
        reported_attempt.candidate_verifications_json,
        vec!["worker_report:completed".to_string()]
    );
    repo.create_task_session_attempt(WorkspaceTaskSessionAttemptRecord {
        id: "attempt_p6_repo_2".to_string(),
        workspace_task_id: "task_p6_repo".to_string(),
        root_goal_task_id: "task_p6_repo".to_string(),
        workspace_id: "ws_p6_repo".to_string(),
        attempt_number: 2,
        status: "running".to_string(),
        conversation_id: Some("conv_p6_worker_active".to_string()),
        worker_agent_id: Some("agent_p6_worker".to_string()),
        leader_agent_id: Some("agent_p6_leader".to_string()),
        candidate_summary: None,
        candidate_artifacts_json: Vec::new(),
        candidate_verifications_json: Vec::new(),
        leader_feedback: None,
        adjudication_reason: None,
        created_at,
        updated_at: Some(created_at),
        completed_at: None,
    })
    .await
    .unwrap();
    let active_worker_count = repo
        .count_recent_running_task_session_attempts_with_conversation(
            "ws_p6_repo",
            ts(2026, 1, 2, 3, 4, 4),
        )
        .await
        .unwrap();
    assert_eq!(active_worker_count, 1);
    let expired_worker_count = repo
        .count_recent_running_task_session_attempts_with_conversation(
            "ws_p6_repo",
            ts(2026, 1, 2, 3, 4, 6),
        )
        .await
        .unwrap();
    assert_eq!(expired_worker_count, 0);
}
