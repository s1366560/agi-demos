use super::*;

impl PgWorkspaceService {
    pub(super) async fn pg_create_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: WorkspaceCreatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.ensure_project_access(
            user_id,
            tenant_id,
            project_id,
            WorkspaceProjectAccess::Write,
        )
        .await?;
        validate_non_empty(&body.name, "name")?;
        let metadata_json = compose_workspace_metadata(body.clone());
        let now = Utc::now();
        let workspace = WorkspaceRecord {
            id: new_id(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            name: body.name,
            description: body.description,
            created_by: user_id.to_string(),
            is_archived: false,
            metadata_json,
            office_status: "inactive".to_string(),
            hex_layout_config_json: json!({}),
            default_blocking_categories_json: Vec::new(),
            created_at: now,
            updated_at: None,
        };
        self.repo
            .create_workspace(workspace, new_id())
            .await
            .map(WorkspaceView::from)
            .map_err(|err| {
                if err.to_string().contains("uq_workspaces_project_name") {
                    WorkspaceApiError::conflict("Workspace already exists")
                } else {
                    WorkspaceApiError::internal(err)
                }
            })
    }

    pub(super) async fn pg_list_workspaces(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        query: WorkspaceListQuery,
    ) -> Result<Vec<WorkspaceView>, WorkspaceApiError> {
        self.ensure_project_access(user_id, tenant_id, project_id, WorkspaceProjectAccess::Read)
            .await?;
        let items = self
            .repo
            .list_workspaces_for_user(
                tenant_id,
                project_id,
                user_id,
                clamp_limit(query.limit, 50, 500),
                query.offset.unwrap_or(0).max(0),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(items.into_iter().map(WorkspaceView::from).collect())
    }

    pub(super) async fn pg_get_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        self.repo
            .get_workspace(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .map(WorkspaceView::from)
            .ok_or_else(WorkspaceApiError::workspace_not_found)
    }

    pub(super) async fn pg_authorize_workspace_event_subscription(
        &self,
        user_id: &str,
        workspace_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<String, WorkspaceApiError> {
        let Some((actual_tenant_id, actual_project_id)) = self
            .repo
            .workspace_scope(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
        else {
            return Err(WorkspaceApiError::workspace_not_found());
        };
        if actual_project_id != project_id
            || tenant_id
                .map(|requested_tenant_id| requested_tenant_id != actual_tenant_id)
                .unwrap_or(false)
        {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        Ok(actual_tenant_id)
    }

    pub(super) async fn pg_update_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: WorkspaceUpdatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let mut record = self
            .repo
            .get_workspace(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        if let Some(name) = body.name {
            validate_non_empty(&name, "name")?;
            record.name = name;
        }
        if body.description.is_some() {
            record.description = body.description;
        }
        if let Some(is_archived) = body.is_archived {
            record.is_archived = is_archived;
        }
        if let Some(metadata) = body.metadata {
            record.metadata_json = metadata;
        }
        record.updated_at = Some(Utc::now());
        self.repo
            .save_workspace(record)
            .await
            .map(WorkspaceView::from)
            .map_err(WorkspaceApiError::internal)
    }

    pub(super) async fn pg_delete_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        if self
            .repo
            .delete_workspace(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            Ok(())
        } else {
            Err(WorkspaceApiError::workspace_not_found())
        }
    }
}

impl DevWorkspaceService {
    pub(super) async fn dev_create_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: WorkspaceCreatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        validate_non_empty(&body.name, "name")?;
        let metadata_json = compose_workspace_metadata(body.clone());
        let now = Utc::now();
        let workspace = WorkspaceRecord {
            id: new_id(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            name: body.name,
            description: body.description,
            created_by: user_id.to_string(),
            is_archived: false,
            metadata_json,
            office_status: "inactive".to_string(),
            hex_layout_config_json: json!({}),
            default_blocking_categories_json: Vec::new(),
            created_at: now,
            updated_at: None,
        };
        let owner = WorkspaceMemberRecord {
            id: new_id(),
            workspace_id: workspace.id.clone(),
            user_id: user_id.to_string(),
            user_email: None,
            role: "owner".to_string(),
            invited_by: Some(user_id.to_string()),
            created_at: now,
            updated_at: None,
        };
        let mut state = self.lock_state()?;
        state
            .workspaces
            .insert(workspace.id.clone(), workspace.clone());
        state.workspace_members.push(owner);
        Ok(workspace.into())
    }

    pub(super) async fn dev_list_workspaces(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        query: WorkspaceListQuery,
    ) -> Result<Vec<WorkspaceView>, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let limit = clamp_limit(query.limit, 50, 500) as usize;
        let offset = query.offset.unwrap_or(0).max(0) as usize;
        let mut items: Vec<_> = self
            .lock_state()?
            .workspaces
            .values()
            .filter(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .cloned()
            .collect();
        items.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(a.id.cmp(&b.id)));
        Ok(items
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(WorkspaceView::from)
            .collect())
    }

    pub(super) async fn dev_get_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        let workspace = state
            .workspaces
            .get(workspace_id)
            .filter(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .cloned()
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        Ok(workspace.into())
    }

    pub(super) async fn dev_authorize_workspace_event_subscription(
        &self,
        user_id: &str,
        workspace_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<String, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        let workspace = state
            .workspaces
            .get(workspace_id)
            .filter(|workspace| workspace.project_id == project_id)
            .filter(|workspace| {
                tenant_id
                    .map(|requested_tenant_id| requested_tenant_id == workspace.tenant_id)
                    .unwrap_or(true)
            })
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        Ok(workspace.tenant_id.clone())
    }

    pub(super) async fn dev_update_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: WorkspaceUpdatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let workspace = state
            .workspaces
            .get_mut(workspace_id)
            .filter(|workspace| {
                workspace.tenant_id == tenant_id && workspace.project_id == project_id
            })
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        if let Some(name) = body.name {
            validate_non_empty(&name, "name")?;
            workspace.name = name;
        }
        if body.description.is_some() {
            workspace.description = body.description;
        }
        if let Some(is_archived) = body.is_archived {
            workspace.is_archived = is_archived;
        }
        if let Some(metadata) = body.metadata {
            workspace.metadata_json = metadata;
        }
        workspace.updated_at = Some(Utc::now());
        Ok(workspace.clone().into())
    }

    pub(super) async fn dev_delete_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let in_scope = state
            .workspaces
            .get(workspace_id)
            .map(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .unwrap_or(false);
        if !in_scope || state.workspaces.remove(workspace_id).is_none() {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        state
            .workspace_members
            .retain(|member| member.workspace_id != workspace_id);
        state
            .workspace_agents
            .retain(|agent| agent.workspace_id != workspace_id);
        state
            .workspace_agent_details
            .retain(|agent| agent.workspace_id != workspace_id);
        state
            .tasks
            .retain(|_, task| task.workspace_id != workspace_id);
        state
            .messages
            .retain(|_, message| message.workspace_id != workspace_id);
        state
            .nodes
            .retain(|_, node| node.workspace_id != workspace_id);
        state
            .edges
            .retain(|_, edge| edge.workspace_id != workspace_id);
        state
            .posts
            .retain(|_, post| post.workspace_id != workspace_id);
        state
            .replies
            .retain(|_, reply| reply.workspace_id != workspace_id);
        state
            .files
            .retain(|_, file| file.workspace_id != workspace_id);
        state
            .task_session_receipts
            .retain(|_, receipt| receipt.workspace_id != workspace_id);
        Ok(())
    }
}
