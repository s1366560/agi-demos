use super::*;

impl PgWorkspaceRepository {
    pub async fn latest_pipeline_run_for_node(
        &self,
        plan_id: &str,
        node_id: &str,
        attempt_id: Option<&str>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
        let query = format!(
            "SELECT {PIPELINE_RUN_COLS} FROM workspace_pipeline_runs \
             WHERE plan_id = $1 AND node_id = $2 {attempt_filter} \
             ORDER BY created_at DESC, id DESC LIMIT 1",
            attempt_filter = if attempt_id.is_some() {
                "AND attempt_id = $3"
            } else {
                ""
            }
        );
        let mut query = sqlx::query(&query).bind(plan_id).bind(node_id);
        if let Some(attempt_id) = attempt_id {
            query = query.bind(attempt_id);
        }
        query
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?
            .map(row_to_pipeline_run)
            .transpose()
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn ensure_pipeline_contract(
        &self,
        contract_id: &str,
        workspace_id: &str,
        plan_id: &str,
        provider: &str,
        code_root: Option<&str>,
        commands_json: &Value,
        env_json: &Value,
        trigger_policy_json: &Value,
        timeout_seconds: i32,
        auto_deploy: bool,
        preview_port: Option<i32>,
        health_url: Option<&str>,
        metadata_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<String> {
        sqlx::query_as::<_, (String,)>(
            "INSERT INTO workspace_pipeline_contracts \
             (id, workspace_id, plan_id, provider, code_root, commands_json, env_json, \
              trigger_policy_json, timeout_seconds, auto_deploy, preview_port, health_url, \
              status, metadata_json, created_at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'active', $13, $14) \
             ON CONFLICT ON CONSTRAINT uq_workspace_pipeline_contract_workspace_plan \
             DO UPDATE SET provider = EXCLUDED.provider, code_root = EXCLUDED.code_root, \
                 commands_json = EXCLUDED.commands_json, env_json = EXCLUDED.env_json, \
                 trigger_policy_json = EXCLUDED.trigger_policy_json, \
                 timeout_seconds = EXCLUDED.timeout_seconds, auto_deploy = EXCLUDED.auto_deploy, \
                 preview_port = EXCLUDED.preview_port, health_url = EXCLUDED.health_url, \
                 metadata_json = EXCLUDED.metadata_json, status = 'active', updated_at = $14 \
             RETURNING id",
        )
        .bind(contract_id)
        .bind(workspace_id)
        .bind(plan_id)
        .bind(provider)
        .bind(code_root)
        .bind(Json(commands_json))
        .bind(Json(env_json))
        .bind(Json(trigger_policy_json))
        .bind(timeout_seconds.max(1))
        .bind(auto_deploy)
        .bind(preview_port)
        .bind(health_url)
        .bind(Json(metadata_json))
        .bind(now)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .map(|row| row.0)
    }

    pub async fn create_pipeline_run(
        &self,
        run: WorkspacePipelineRunRecord,
    ) -> CoreResult<WorkspacePipelineRunRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_pipeline_runs \
             (id, contract_id, workspace_id, plan_id, node_id, attempt_id, commit_ref, provider, \
              status, reason, started_at, completed_at, metadata_json, created_at, updated_at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15) \
             RETURNING {PIPELINE_RUN_COLS}"
        ))
        .bind(&run.id)
        .bind(&run.contract_id)
        .bind(&run.workspace_id)
        .bind(&run.plan_id)
        .bind(&run.node_id)
        .bind(&run.attempt_id)
        .bind(&run.commit_ref)
        .bind(&run.provider)
        .bind(&run.status)
        .bind(&run.reason)
        .bind(run.started_at)
        .bind(run.completed_at)
        .bind(Json(&run.metadata_json))
        .bind(run.created_at)
        .bind(run.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_pipeline_run)
    }

    pub async fn finish_pipeline_run(
        &self,
        run_id: &str,
        status: &str,
        reason: Option<&str>,
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
        sqlx::query(&format!(
            "UPDATE workspace_pipeline_runs \
             SET status = $2, reason = $3, completed_at = $4, updated_at = $4, \
                 metadata_json = metadata_json || $5 \
             WHERE id = $1 \
             RETURNING {PIPELINE_RUN_COLS}"
        ))
        .bind(run_id)
        .bind(status)
        .bind(reason)
        .bind(completed_at)
        .bind(Json(metadata_patch))
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_pipeline_run)
        .transpose()
    }

    pub async fn create_pipeline_stage_run(
        &self,
        stage_run: WorkspacePipelineStageRunRecord,
    ) -> CoreResult<WorkspacePipelineStageRunRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_pipeline_stage_runs \
             (id, run_id, workspace_id, stage, status, command, exit_code, stdout_preview, \
              stderr_preview, log_ref, artifact_refs_json, started_at, completed_at, \
              duration_ms, metadata_json, created_at, updated_at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17) \
             RETURNING {PIPELINE_STAGE_RUN_COLS}"
        ))
        .bind(&stage_run.id)
        .bind(&stage_run.run_id)
        .bind(&stage_run.workspace_id)
        .bind(&stage_run.stage)
        .bind(&stage_run.status)
        .bind(&stage_run.command)
        .bind(stage_run.exit_code)
        .bind(&stage_run.stdout_preview)
        .bind(&stage_run.stderr_preview)
        .bind(&stage_run.log_ref)
        .bind(Json(&stage_run.artifact_refs_json))
        .bind(stage_run.started_at)
        .bind(stage_run.completed_at)
        .bind(stage_run.duration_ms)
        .bind(Json(&stage_run.metadata_json))
        .bind(stage_run.created_at)
        .bind(stage_run.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_pipeline_stage_run)
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn finish_pipeline_stage_run(
        &self,
        stage_run_id: &str,
        status: &str,
        exit_code: Option<i32>,
        stdout_preview: Option<&str>,
        stderr_preview: Option<&str>,
        log_ref: Option<&str>,
        artifact_refs: &[String],
        metadata_patch: &Value,
        completed_at: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePipelineStageRunRecord>> {
        sqlx::query(&format!(
            "UPDATE workspace_pipeline_stage_runs \
             SET status = $2, exit_code = $3, stdout_preview = $4, stderr_preview = $5, \
                 log_ref = $6, artifact_refs_json = $7, completed_at = $8, updated_at = $8, \
                 duration_ms = GREATEST(0, CAST(EXTRACT(EPOCH FROM \
                     ($8 - COALESCE(started_at, $8))) * 1000 AS integer)), \
                 metadata_json = metadata_json || $9 \
             WHERE id = $1 \
             RETURNING {PIPELINE_STAGE_RUN_COLS}"
        ))
        .bind(stage_run_id)
        .bind(status)
        .bind(exit_code)
        .bind(stdout_preview)
        .bind(stderr_preview)
        .bind(log_ref)
        .bind(Json(artifact_refs))
        .bind(completed_at)
        .bind(Json(metadata_patch))
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_pipeline_stage_run)
        .transpose()
    }
}
