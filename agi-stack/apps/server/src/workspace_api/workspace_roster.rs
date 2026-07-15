use super::*;

fn validated_roster_pagination(
    limit: Option<i64>,
    offset: Option<i64>,
) -> Result<(i64, i64), WorkspaceApiError> {
    let limit = limit.unwrap_or(100);
    if !(1..=500).contains(&limit) {
        return Err(WorkspaceApiError::unprocessable(
            "limit must be between 1 and 500",
        ));
    }
    let offset = offset.unwrap_or(0);
    if offset < 0 {
        return Err(WorkspaceApiError::unprocessable(
            "offset must be greater than or equal to 0",
        ));
    }
    Ok((limit, offset))
}

impl PgWorkspaceService {
    pub(super) async fn pg_list_workspace_members(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<WorkspaceMemberView>, WorkspaceApiError> {
        let (limit, offset) = validated_roster_pagination(query.limit, query.offset)?;
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        self.repo
            .list_workspace_members(workspace_id, limit, offset)
            .await
            .map_err(WorkspaceApiError::internal)
            .map(|items| items.into_iter().map(WorkspaceMemberView::from).collect())
    }

    pub(super) async fn pg_list_workspace_agents(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: WorkspaceAgentListQuery,
    ) -> Result<Vec<WorkspaceAgentView>, WorkspaceApiError> {
        let (limit, offset) = validated_roster_pagination(query.limit, query.offset)?;
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        self.repo
            .list_workspace_agents(workspace_id, query.active_only, limit, offset)
            .await
            .map_err(WorkspaceApiError::internal)
            .map(|items| items.into_iter().map(WorkspaceAgentView::from).collect())
    }
}

impl DevWorkspaceService {
    pub(super) async fn dev_list_workspace_members(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<WorkspaceMemberView>, WorkspaceApiError> {
        let (limit, offset) = validated_roster_pagination(query.limit, query.offset)?;
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        state
            .workspaces
            .get(workspace_id)
            .filter(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        let mut items: Vec<_> = state
            .workspace_members
            .iter()
            .filter(|member| member.workspace_id == workspace_id)
            .cloned()
            .collect();
        items.sort_by(|left, right| {
            left.created_at
                .cmp(&right.created_at)
                .then(left.id.cmp(&right.id))
        });
        Ok(items
            .into_iter()
            .skip(offset as usize)
            .take(limit as usize)
            .map(WorkspaceMemberView::from)
            .collect())
    }

    pub(super) async fn dev_list_workspace_agents(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: WorkspaceAgentListQuery,
    ) -> Result<Vec<WorkspaceAgentView>, WorkspaceApiError> {
        let (limit, offset) = validated_roster_pagination(query.limit, query.offset)?;
        self.require_dev_user(user_id)?;
        let state = self.lock_state()?;
        state
            .workspaces
            .get(workspace_id)
            .filter(|workspace| self.workspace_matches(workspace, tenant_id, project_id))
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        let mut items: Vec<_> = state
            .workspace_agent_details
            .iter()
            .filter(|agent| agent.workspace_id == workspace_id)
            .filter(|agent| !query.active_only || agent.is_active)
            .cloned()
            .collect();
        items.sort_by(|left, right| {
            left.created_at
                .cmp(&right.created_at)
                .then(left.id.cmp(&right.id))
        });
        Ok(items
            .into_iter()
            .skip(offset as usize)
            .take(limit as usize)
            .map(WorkspaceAgentView::from)
            .collect())
    }
}
