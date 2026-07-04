use super::*;

impl PgWorkspaceRepository {
    pub async fn find_active_task_session_attempt(
        &self,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        sqlx::query(&format!(
            "SELECT {TASK_SESSION_ATTEMPT_COLS} FROM workspace_task_session_attempts \
             WHERE workspace_task_id = $1 \
               AND status IN ('pending', 'running', 'awaiting_leader_adjudication') \
             ORDER BY attempt_number DESC, id ASC LIMIT 1"
        ))
        .bind(workspace_task_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_task_session_attempt)
        .transpose()
    }

    pub async fn find_latest_accepted_task_session_attempt(
        &self,
        workspace_id: &str,
        workspace_task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        sqlx::query(&format!(
            "SELECT {TASK_SESSION_ATTEMPT_COLS} FROM workspace_task_session_attempts \
             WHERE workspace_id = $1 \
               AND workspace_task_id = $2 \
               AND status = 'accepted' \
             ORDER BY attempt_number DESC, id ASC LIMIT 1"
        ))
        .bind(workspace_id)
        .bind(workspace_task_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_task_session_attempt)
        .transpose()
    }

    pub async fn get_task_session_attempt(
        &self,
        attempt_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        sqlx::query(&format!(
            "SELECT {TASK_SESSION_ATTEMPT_COLS} FROM workspace_task_session_attempts WHERE id = $1"
        ))
        .bind(attempt_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_task_session_attempt)
        .transpose()
    }
    pub async fn latest_task_session_attempt_number(
        &self,
        workspace_task_id: &str,
    ) -> CoreResult<i32> {
        let row = sqlx::query_as::<_, (Option<i32>,)>(
            "SELECT MAX(attempt_number) FROM workspace_task_session_attempts \
             WHERE workspace_task_id = $1",
        )
        .bind(workspace_task_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row.0.unwrap_or(0))
    }

    pub async fn create_task_session_attempt(
        &self,
        attempt: WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<WorkspaceTaskSessionAttemptRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_task_session_attempts \
                (id, workspace_task_id, root_goal_task_id, workspace_id, attempt_number, status, \
                 conversation_id, worker_agent_id, leader_agent_id, candidate_summary, \
                 candidate_artifacts_json, candidate_verifications_json, leader_feedback, \
                 adjudication_reason, created_at, updated_at, completed_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17) \
             RETURNING {TASK_SESSION_ATTEMPT_COLS}"
        ))
        .bind(&attempt.id)
        .bind(&attempt.workspace_task_id)
        .bind(&attempt.root_goal_task_id)
        .bind(&attempt.workspace_id)
        .bind(attempt.attempt_number)
        .bind(&attempt.status)
        .bind(&attempt.conversation_id)
        .bind(&attempt.worker_agent_id)
        .bind(&attempt.leader_agent_id)
        .bind(&attempt.candidate_summary)
        .bind(Json(&attempt.candidate_artifacts_json))
        .bind(Json(&attempt.candidate_verifications_json))
        .bind(&attempt.leader_feedback)
        .bind(&attempt.adjudication_reason)
        .bind(attempt.created_at)
        .bind(attempt.updated_at)
        .bind(attempt.completed_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_task_session_attempt)
        .transpose()?
        .ok_or_else(|| {
            CoreError::Storage("workspace task session attempt insert returned no row".into())
        })
    }

    pub async fn mark_task_session_attempt_running(
        &self,
        attempt_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        sqlx::query(&format!(
            "UPDATE workspace_task_session_attempts \
             SET status = 'running', updated_at = $2 \
             WHERE id = $1 RETURNING {TASK_SESSION_ATTEMPT_COLS}"
        ))
        .bind(attempt_id)
        .bind(now)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_task_session_attempt)
        .transpose()
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn ensure_worker_launch_conversation(
        &self,
        conversation_id: &str,
        project_id: &str,
        tenant_id: &str,
        user_id: &str,
        title: &str,
        agent_config_json: &Value,
        metadata_json: &Value,
        participant_agents_json: &[String],
        focused_agent_id: &str,
        workspace_id: &str,
        linked_workspace_task_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let existing = sqlx::query(
            "SELECT workspace_id, linked_workspace_task_id \
             FROM conversations WHERE id = $1",
        )
        .bind(conversation_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        if let Some(row) = existing {
            let existing_workspace_id: Option<String> =
                row.try_get("workspace_id").map_err(storage)?;
            let existing_task_id: Option<String> =
                row.try_get("linked_workspace_task_id").map_err(storage)?;
            if existing_workspace_id
                .as_deref()
                .is_some_and(|candidate| candidate != workspace_id)
                || existing_task_id
                    .as_deref()
                    .is_some_and(|candidate| candidate != linked_workspace_task_id)
            {
                return Err(CoreError::Storage(format!(
                    "worker launch conversation {conversation_id} is linked to another workspace task"
                )));
            }
            sqlx::query(
                "UPDATE conversations \
                 SET agent_config = $2, meta = $3, participant_agents = $4, \
                     conversation_mode = 'isolated', focused_agent_id = $5, \
                     workspace_id = $6, linked_workspace_task_id = $7, updated_at = $8 \
                 WHERE id = $1",
            )
            .bind(conversation_id)
            .bind(Json(agent_config_json))
            .bind(Json(metadata_json))
            .bind(Json(participant_agents_json))
            .bind(focused_agent_id)
            .bind(workspace_id)
            .bind(linked_workspace_task_id)
            .bind(now)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
            return Ok(());
        }

        sqlx::query(
            "INSERT INTO conversations \
                (id, project_id, tenant_id, user_id, title, status, agent_config, meta, \
                 message_count, current_mode, participant_agents, conversation_mode, \
                 focused_agent_id, workspace_id, linked_workspace_task_id, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,'active',$6,$7,0,'build',$8,'isolated',$9,$10,$11,$12,$12)",
        )
        .bind(conversation_id)
        .bind(project_id)
        .bind(tenant_id)
        .bind(user_id)
        .bind(title)
        .bind(Json(agent_config_json))
        .bind(Json(metadata_json))
        .bind(Json(participant_agents_json))
        .bind(focused_agent_id)
        .bind(workspace_id)
        .bind(linked_workspace_task_id)
        .bind(now)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn ensure_workspace_agent_conversation(
        &self,
        conversation_id: &str,
        project_id: &str,
        tenant_id: &str,
        user_id: &str,
        title: &str,
        agent_config_json: &Value,
        metadata_json: &Value,
        workspace_id: &str,
        linked_workspace_task_id: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let existing = sqlx::query(
            "SELECT workspace_id \
             FROM conversations WHERE id = $1",
        )
        .bind(conversation_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        if let Some(row) = existing {
            let existing_workspace_id: Option<String> =
                row.try_get("workspace_id").map_err(storage)?;
            if existing_workspace_id
                .as_deref()
                .is_some_and(|candidate| candidate != workspace_id)
            {
                return Err(CoreError::Storage(format!(
                    "workspace agent conversation {conversation_id} is linked to another workspace"
                )));
            }
            sqlx::query(
                "UPDATE conversations \
                 SET agent_config = $2, meta = $3, workspace_id = $4, \
                     linked_workspace_task_id = COALESCE($5, linked_workspace_task_id), \
                     updated_at = $6 \
                 WHERE id = $1",
            )
            .bind(conversation_id)
            .bind(Json(agent_config_json))
            .bind(Json(metadata_json))
            .bind(workspace_id)
            .bind(linked_workspace_task_id)
            .bind(now)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
            return Ok(());
        }

        sqlx::query(
            "INSERT INTO conversations \
                (id, project_id, tenant_id, user_id, title, status, agent_config, meta, \
                 message_count, current_mode, workspace_id, linked_workspace_task_id, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,'active',$6,$7,0,'build',$8,$9,$10,$10)",
        )
        .bind(conversation_id)
        .bind(project_id)
        .bind(tenant_id)
        .bind(user_id)
        .bind(title)
        .bind(Json(agent_config_json))
        .bind(Json(metadata_json))
        .bind(workspace_id)
        .bind(linked_workspace_task_id)
        .bind(now)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(())
    }

    pub async fn bind_task_session_attempt_conversation(
        &self,
        attempt_id: &str,
        conversation_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        sqlx::query(&format!(
            "UPDATE workspace_task_session_attempts \
             SET status = 'running', conversation_id = $2, updated_at = $3 \
             WHERE id = $1 RETURNING {TASK_SESSION_ATTEMPT_COLS}"
        ))
        .bind(attempt_id)
        .bind(conversation_id)
        .bind(now)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_task_session_attempt)
        .transpose()
    }

    pub async fn finish_task_session_attempt(
        &self,
        attempt_id: &str,
        status: &str,
        leader_feedback: Option<&str>,
        adjudication_reason: Option<&str>,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        sqlx::query(&format!(
            "UPDATE workspace_task_session_attempts \
             SET status = $2, leader_feedback = $3, adjudication_reason = $4, \
                 completed_at = $5, updated_at = $5 \
             WHERE id = $1 RETURNING {TASK_SESSION_ATTEMPT_COLS}"
        ))
        .bind(attempt_id)
        .bind(status)
        .bind(leader_feedback)
        .bind(adjudication_reason)
        .bind(completed_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_task_session_attempt)
        .transpose()
    }

    pub async fn record_task_session_attempt_candidate_output(
        &self,
        attempt_id: &str,
        summary: Option<&str>,
        artifacts_json: &[String],
        verifications_json: &[String],
        conversation_id: Option<&str>,
        updated_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspaceTaskSessionAttemptRecord>> {
        let Some(existing) = self.get_task_session_attempt(attempt_id).await? else {
            return Ok(None);
        };
        if matches!(
            existing.status.as_str(),
            "accepted" | "rejected" | "blocked" | "cancelled"
        ) {
            return Ok(Some(existing));
        }
        sqlx::query(&format!(
            "UPDATE workspace_task_session_attempts \
             SET status = 'awaiting_leader_adjudication', \
                 conversation_id = COALESCE($2, conversation_id), \
                 candidate_summary = $3, candidate_artifacts_json = $4, \
                 candidate_verifications_json = $5, updated_at = $6 \
             WHERE id = $1 RETURNING {TASK_SESSION_ATTEMPT_COLS}"
        ))
        .bind(attempt_id)
        .bind(conversation_id)
        .bind(summary)
        .bind(Json(artifacts_json))
        .bind(Json(verifications_json))
        .bind(updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_task_session_attempt)
        .transpose()
    }

    pub async fn count_recent_running_task_session_attempts_with_conversation(
        &self,
        workspace_id: &str,
        active_after: DateTime<Utc>,
    ) -> CoreResult<i64> {
        let row = sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*)::bigint FROM workspace_task_session_attempts \
             WHERE workspace_id = $1 \
               AND status = 'running' \
               AND conversation_id IS NOT NULL \
               AND COALESCE(updated_at, created_at) >= $2",
        )
        .bind(workspace_id)
        .bind(active_after)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row.0)
    }
}
