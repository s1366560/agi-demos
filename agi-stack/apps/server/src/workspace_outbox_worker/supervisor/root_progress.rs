use super::*;

impl SupervisorTickAdmissionHandler {
    pub(super) async fn reconcile_root_goal_progress_for_task(
        &self,
        workspace_id: &str,
        task: &WorkspaceTaskRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let Some(root_goal_task_id) = root_goal_task_id_for_progress(task, attempt) else {
            return Ok(());
        };
        if root_goal_task_id == task.id {
            return Ok(());
        }
        self.reconcile_root_goal_progress(workspace_id, &root_goal_task_id, now)
            .await
    }

    pub(super) async fn reconcile_root_goal_progress(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let Some(mut root_task) = self.store.get_task(workspace_id, root_goal_task_id).await?
        else {
            return Ok(());
        };
        if !is_goal_root_task(&root_task) {
            return Ok(());
        }

        let mut child_tasks = self
            .store
            .list_current_plan_child_tasks_by_root_goal_task_id(workspace_id, root_goal_task_id)
            .await?;
        if child_tasks.is_empty() {
            child_tasks = select_root_progress_child_tasks(
                self.store
                    .list_tasks_by_root_goal_task_id(workspace_id, root_goal_task_id)
                    .await?,
            );
        }

        let active_child_task_ids = child_tasks
            .iter()
            .filter(|task| task.status != "done" && task.archived_at.is_none())
            .map(|task| task.id.clone())
            .collect::<Vec<_>>();
        let blocked_tasks = child_tasks
            .iter()
            .filter(|task| task.status == "blocked")
            .collect::<Vec<_>>();
        let blocked_child_task_ids = blocked_tasks
            .iter()
            .map(|task| task.id.clone())
            .collect::<Vec<_>>();
        let in_progress_count = child_tasks
            .iter()
            .filter(|task| task.status == "in_progress")
            .count();
        let done_count = child_tasks
            .iter()
            .filter(|task| task.status == "done")
            .count();
        let assigned_count = child_tasks
            .iter()
            .filter(|task| task.assignee_agent_id.is_some() || task.assignee_user_id.is_some())
            .count();
        let total_count = child_tasks.len();
        let all_children_done = total_count > 0 && done_count == total_count;

        let (goal_health, blocked_reason, remediation_status, remediation_summary) =
            if root_task.status == "done" {
                ("achieved", None, "none", None)
            } else if let Some(blocked_task) = blocked_tasks.first() {
                (
                    "blocked",
                    blocked_task
                        .blocker_reason
                        .clone()
                        .or_else(|| Some(blocked_task.title.clone())),
                    "replan_required",
                    Some(format!(
                        "{} child task(s) blocked; root goal requires replan or intervention",
                        blocked_tasks.len()
                    )),
                )
            } else if in_progress_count > 0 {
                ("healthy", None, "none", None)
            } else if all_children_done {
                (
                "achieved",
                None,
                "ready_for_completion",
                Some(
                    "All child tasks are done; root goal should now validate completion evidence"
                        .to_string(),
                ),
            )
            } else {
                ("healthy", None, "none", None)
            };

        let progress_summary = format!(
            "{done_count}/{total_count} child tasks done; {in_progress_count} in progress; {} blocked; {assigned_count}/{total_count} assigned",
            blocked_tasks.len()
        );
        let mut metadata = object_or_empty(root_task.metadata_json);
        metadata.insert("goal_progress_summary".to_string(), json!(progress_summary));
        metadata.insert("last_progress_at".to_string(), json!(now.to_rfc3339()));
        metadata.insert(
            "active_child_task_ids".to_string(),
            json!(active_child_task_ids),
        );
        metadata.insert(
            "blocked_child_task_ids".to_string(),
            json!(blocked_child_task_ids),
        );
        metadata.insert(
            "blocked_reason".to_string(),
            blocked_reason.map_or(Value::Null, Value::String),
        );
        metadata.insert("goal_health".to_string(), json!(goal_health));
        metadata.insert(REMEDIATION_STATUS.to_string(), json!(remediation_status));
        metadata.insert(
            REMEDIATION_SUMMARY.to_string(),
            remediation_summary.map_or(Value::Null, Value::String),
        );
        root_task.metadata_json = Value::Object(metadata);
        root_task.updated_at = Some(now);
        self.store.save_task(root_task).await?;
        Ok(())
    }
}
