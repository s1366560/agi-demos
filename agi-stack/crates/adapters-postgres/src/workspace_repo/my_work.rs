use super::*;

impl PgWorkspaceRepository {
    /// Require both project and tenant membership for the project-scoped queue.
    pub async fn user_can_access_project_my_work(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> CoreResult<bool> {
        sqlx::query_scalar::<_, bool>(
            "SELECT EXISTS(\
                 SELECT 1 FROM projects AS project \
                 WHERE project.id = $2 \
                   AND EXISTS (\
                       SELECT 1 FROM user_projects AS membership \
                       WHERE membership.project_id = project.id \
                         AND membership.user_id = $1\
                   ) \
                   AND EXISTS (\
                       SELECT 1 FROM user_tenants AS membership \
                       WHERE membership.tenant_id = project.tenant_id \
                         AND membership.user_id = $1\
                   )\
             )",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
    }

    /// Return only the latest attempt for each task after enforcing the complete
    /// project, tenant, workspace, conversation, and task scope.
    pub async fn list_latest_project_my_work_attempts(
        &self,
        project_id: &str,
        user_id: &str,
    ) -> CoreResult<Vec<ProjectMyWorkWorkspaceAttemptRecord>> {
        sqlx::query_as::<_, ProjectMyWorkWorkspaceAttemptRecord>(
            "WITH ranked_attempts AS (\
                 SELECT attempt.id AS authority_id, attempt.workspace_task_id, \
                        attempt.conversation_id, attempt.workspace_id, attempt.status, \
                        attempt.attempt_number, attempt.created_at, attempt.updated_at, \
                        row_number() OVER (\
                            PARTITION BY attempt.workspace_task_id \
                            ORDER BY attempt.attempt_number DESC, attempt.created_at DESC, \
                                     attempt.id ASC\
                        ) AS authority_rank \
                 FROM workspace_task_session_attempts AS attempt\
             ) \
             SELECT ranked.authority_id, ranked.conversation_id, ranked.workspace_id, \
                    workspace.project_id, task.title, ranked.status, ranked.attempt_number, \
                    conversation.agent_config AS conversation_agent_config, \
                    workspace.metadata_json AS workspace_metadata, ranked.created_at, \
                    ranked.updated_at \
             FROM ranked_attempts AS ranked \
             JOIN workspace_tasks AS task \
               ON task.id = ranked.workspace_task_id \
              AND task.workspace_id = ranked.workspace_id \
             JOIN workspaces AS workspace ON workspace.id = ranked.workspace_id \
             JOIN conversations AS conversation \
               ON conversation.id = ranked.conversation_id \
              AND conversation.project_id = workspace.project_id \
              AND conversation.tenant_id = workspace.tenant_id \
              AND conversation.workspace_id = workspace.id \
              AND conversation.linked_workspace_task_id = task.id \
              AND conversation.user_id = $2 \
             JOIN projects AS project \
               ON project.id = workspace.project_id \
              AND project.tenant_id = workspace.tenant_id \
             WHERE ranked.authority_rank = 1 \
               AND project.id = $1 \
               AND workspace.is_archived = false \
               AND task.archived_at IS NULL \
               AND EXISTS (\
                   SELECT 1 FROM user_projects AS membership \
                   WHERE membership.project_id = project.id \
                     AND membership.user_id = $2\
               ) \
               AND EXISTS (\
                   SELECT 1 FROM user_tenants AS membership \
                   WHERE membership.tenant_id = project.tenant_id \
                     AND membership.user_id = $2\
               ) \
               AND EXISTS (\
                   SELECT 1 FROM workspace_members AS membership \
                   WHERE membership.workspace_id = workspace.id \
                     AND membership.user_id = $2\
               )",
        )
        .bind(project_id)
        .bind(user_id)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)
    }

    /// Return unexpired pending HITL authorities from the same complete scope.
    pub async fn list_pending_project_my_work_hitl(
        &self,
        project_id: &str,
        user_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<ProjectMyWorkHitlAuthorityRecord>> {
        sqlx::query_as::<_, ProjectMyWorkHitlAuthorityRecord>(
            "SELECT hitl.id AS authority_id, hitl.request_type, hitl.conversation_id, \
                    conversation.workspace_id, hitl.project_id, conversation.title, \
                    conversation.agent_config AS conversation_agent_config, \
                    hitl.request_metadata, workspace.metadata_json AS workspace_metadata, \
                    hitl.created_at, hitl.expires_at \
             FROM hitl_requests AS hitl \
             JOIN conversations AS conversation \
               ON conversation.id = hitl.conversation_id \
              AND conversation.project_id = hitl.project_id \
              AND conversation.tenant_id = hitl.tenant_id \
              AND conversation.user_id = $2 \
             JOIN workspaces AS workspace \
               ON workspace.id = conversation.workspace_id \
              AND workspace.project_id = conversation.project_id \
              AND workspace.tenant_id = conversation.tenant_id \
             JOIN projects AS project \
               ON project.id = workspace.project_id \
              AND project.tenant_id = workspace.tenant_id \
             WHERE project.id = $1 \
               AND workspace.is_archived = false \
               AND hitl.status = 'pending' \
               AND hitl.expires_at > $3 \
               AND (hitl.user_id IS NULL OR hitl.user_id = $2) \
               AND EXISTS (\
                   SELECT 1 FROM user_projects AS membership \
                   WHERE membership.project_id = project.id \
                     AND membership.user_id = $2\
               ) \
               AND EXISTS (\
                   SELECT 1 FROM user_tenants AS membership \
                   WHERE membership.tenant_id = project.tenant_id \
                     AND membership.user_id = $2\
               ) \
               AND EXISTS (\
                   SELECT 1 FROM workspace_members AS membership \
                   WHERE membership.workspace_id = workspace.id \
                     AND membership.user_id = $2\
               ) \
             ORDER BY hitl.created_at DESC, hitl.id DESC",
        )
        .bind(project_id)
        .bind(user_id)
        .bind(now)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)
    }
}
