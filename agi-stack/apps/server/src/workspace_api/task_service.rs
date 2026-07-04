use super::*;

impl PgWorkspaceService {
    pub(super) async fn pg_create_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspaceTaskCreatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        validate_non_empty(&body.title, "title")?;
        let now = Utc::now();
        let mut metadata = object_or_empty(body.metadata);
        if let Some(language) = body.preferred_language {
            metadata["preferred_language"] = json!(language);
        }
        let task = WorkspaceTaskRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            title: body.title,
            description: body.description,
            created_by: user_id.to_string(),
            assignee_user_id: body.assignee_user_id,
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority: priority_rank(body.priority.as_deref())?,
            estimated_effort: body.estimated_effort,
            blocker_reason: body.blocker_reason,
            metadata_json: metadata,
            created_at: now,
            updated_at: None,
            completed_at: None,
            archived_at: None,
        };
        self.repo
            .create_task(task)
            .await
            .map(WorkspaceTaskView::from)
            .map_err(WorkspaceApiError::internal)
    }

    pub(super) async fn pg_list_tasks(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: TaskListQuery,
    ) -> Result<Vec<WorkspaceTaskView>, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        if let Some(status) = query.status_filter.as_deref() {
            validate_task_status(status)?;
        }
        let tasks = self
            .repo
            .list_tasks(
                workspace_id,
                query.status_filter.as_deref(),
                clamp_limit(query.limit, 100, 500),
                query.offset.unwrap_or(0).max(0),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(tasks.into_iter().map(WorkspaceTaskView::from).collect())
    }

    pub(super) async fn pg_get_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        self.repo
            .get_task(workspace_id, task_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .map(WorkspaceTaskView::from)
            .ok_or_else(WorkspaceApiError::task_not_found)
    }

    pub(super) async fn pg_update_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        body: WorkspaceTaskUpdatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut task = self
            .repo
            .get_task(workspace_id, task_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::task_not_found)?;
        apply_task_update(&mut task, body)?;
        self.repo
            .save_task(task)
            .await
            .map(WorkspaceTaskView::from)
            .map_err(WorkspaceApiError::internal)
    }

    pub(super) async fn pg_delete_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        if self
            .repo
            .delete_task(workspace_id, task_id)
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            Ok(())
        } else {
            Err(WorkspaceApiError::task_not_found())
        }
    }

    pub(super) async fn pg_transition_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        action: TaskTransitionAction,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut task = self
            .repo
            .get_task(workspace_id, task_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::task_not_found)?;
        apply_task_transition(&mut task, action, user_id);
        self.repo
            .save_task(task)
            .await
            .map(WorkspaceTaskView::from)
            .map_err(WorkspaceApiError::internal)
    }
}

impl DevWorkspaceService {
    pub(super) async fn dev_create_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspaceTaskCreatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        validate_non_empty(&body.title, "title")?;
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut metadata = object_or_empty(body.metadata);
        if let Some(language) = body.preferred_language {
            metadata["preferred_language"] = json!(language);
        }
        let task = WorkspaceTaskRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            title: body.title,
            description: body.description,
            created_by: user_id.to_string(),
            assignee_user_id: body.assignee_user_id,
            assignee_agent_id: None,
            status: "todo".to_string(),
            priority: priority_rank(body.priority.as_deref())?,
            estimated_effort: body.estimated_effort,
            blocker_reason: body.blocker_reason,
            metadata_json: metadata,
            created_at: Utc::now(),
            updated_at: None,
            completed_at: None,
            archived_at: None,
        };
        state.tasks.insert(task.id.clone(), task.clone());
        Ok(task.into())
    }

    pub(super) async fn dev_list_tasks(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: TaskListQuery,
    ) -> Result<Vec<WorkspaceTaskView>, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        if let Some(status) = query.status_filter.as_deref() {
            validate_task_status(status)?;
        }
        let limit = clamp_limit(query.limit, 100, 500) as usize;
        let offset = query.offset.unwrap_or(0).max(0) as usize;
        let mut tasks: Vec<_> = self
            .lock_state()?
            .tasks
            .values()
            .filter(|task| {
                task.workspace_id == workspace_id
                    && query
                        .status_filter
                        .as_ref()
                        .map(|status| task.status == *status)
                        .unwrap_or(true)
            })
            .cloned()
            .collect();
        tasks.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(a.id.cmp(&b.id)));
        Ok(tasks
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(WorkspaceTaskView::from)
            .collect())
    }

    pub(super) async fn dev_get_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        state
            .tasks
            .get(task_id)
            .filter(|task| task.workspace_id == workspace_id)
            .cloned()
            .map(WorkspaceTaskView::from)
            .ok_or_else(WorkspaceApiError::task_not_found)
    }

    pub(super) async fn dev_update_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        body: WorkspaceTaskUpdatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let task = state
            .tasks
            .get_mut(task_id)
            .filter(|task| task.workspace_id == workspace_id)
            .ok_or_else(WorkspaceApiError::task_not_found)?;
        apply_task_update(task, body)?;
        Ok(task.clone().into())
    }

    pub(super) async fn dev_delete_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let in_scope = state
            .tasks
            .get(task_id)
            .map(|task| task.workspace_id == workspace_id)
            .unwrap_or(false);
        if !in_scope || state.tasks.remove(task_id).is_none() {
            return Err(WorkspaceApiError::task_not_found());
        }
        Ok(())
    }

    pub(super) async fn dev_transition_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        action: TaskTransitionAction,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let task = state
            .tasks
            .get_mut(task_id)
            .filter(|task| task.workspace_id == workspace_id)
            .ok_or_else(WorkspaceApiError::task_not_found)?;
        apply_task_transition(task, action, user_id);
        Ok(task.clone().into())
    }
}
