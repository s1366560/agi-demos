use super::*;

impl PgWorkspaceRepository {
    pub async fn create_plan(&self, plan: WorkspacePlanRecord) -> CoreResult<WorkspacePlanRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_plans \
                (id, workspace_id, goal_id, status, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6) RETURNING {PLAN_COLS}"
        ))
        .bind(&plan.id)
        .bind(&plan.workspace_id)
        .bind(&plan.goal_id)
        .bind(&plan.status)
        .bind(plan.created_at)
        .bind(plan.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("workspace plan insert returned no row".into()))
    }

    pub async fn save_plan(&self, plan: WorkspacePlanRecord) -> CoreResult<WorkspacePlanRecord> {
        sqlx::query(&format!(
            "UPDATE workspace_plans SET status=$3, updated_at=$4 \
             WHERE id=$1 AND workspace_id=$2 RETURNING {PLAN_COLS}"
        ))
        .bind(&plan.id)
        .bind(&plan.workspace_id)
        .bind(&plan.status)
        .bind(plan.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("workspace plan update returned no row".into()))
    }

    pub async fn list_plans(
        &self,
        workspace_id: &str,
        limit: i64,
    ) -> CoreResult<Vec<WorkspacePlanRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {PLAN_COLS} FROM workspace_plans \
             WHERE workspace_id = $1 \
             ORDER BY created_at DESC, id DESC LIMIT $2"
        ))
        .bind(workspace_id)
        .bind(limit.max(1))
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_plan).collect()
    }

    pub async fn get_plan(&self, plan_id: &str) -> CoreResult<Option<WorkspacePlanRecord>> {
        sqlx::query(&format!(
            "SELECT {PLAN_COLS} FROM workspace_plans WHERE id = $1"
        ))
        .bind(plan_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan)
        .transpose()
    }

    pub async fn create_plan_node(
        &self,
        node: WorkspacePlanNodeRecord,
    ) -> CoreResult<WorkspacePlanNodeRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_plan_nodes \
                (id, plan_id, parent_id, kind, title, description, depends_on, inputs_schema, \
                 outputs_schema, acceptance_criteria, feature_checkpoint, handoff_package, \
                 recommended_capabilities, preferred_agent_id, estimated_effort, priority, \
                 intent, execution, progress, assignee_agent_id, current_attempt_id, \
                 workspace_task_id, metadata_json, created_at, updated_at, completed_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,\
                     $21,$22,$23,$24,$25,$26) \
             RETURNING {PLAN_NODE_COLS}"
        ))
        .bind(&node.id)
        .bind(&node.plan_id)
        .bind(&node.parent_id)
        .bind(&node.kind)
        .bind(&node.title)
        .bind(&node.description)
        .bind(Json(&node.depends_on_json))
        .bind(Json(&node.inputs_schema_json))
        .bind(Json(&node.outputs_schema_json))
        .bind(Json(&node.acceptance_criteria_json))
        .bind(node.feature_checkpoint_json.as_ref().map(Json))
        .bind(node.handoff_package_json.as_ref().map(Json))
        .bind(Json(&node.recommended_capabilities_json))
        .bind(&node.preferred_agent_id)
        .bind(Json(&node.estimated_effort_json))
        .bind(node.priority)
        .bind(&node.intent)
        .bind(&node.execution)
        .bind(Json(&node.progress_json))
        .bind(&node.assignee_agent_id)
        .bind(&node.current_attempt_id)
        .bind(&node.workspace_task_id)
        .bind(Json(&node.metadata_json))
        .bind(node.created_at)
        .bind(node.updated_at)
        .bind(node.completed_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan_node)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("workspace plan node insert returned no row".into()))
    }

    pub async fn save_plan_node(
        &self,
        node: WorkspacePlanNodeRecord,
    ) -> CoreResult<WorkspacePlanNodeRecord> {
        sqlx::query(&format!(
            "UPDATE workspace_plan_nodes SET parent_id=$3, kind=$4, title=$5, description=$6, \
                 depends_on=$7, inputs_schema=$8, outputs_schema=$9, acceptance_criteria=$10, \
                 feature_checkpoint=$11, handoff_package=$12, recommended_capabilities=$13, \
                 preferred_agent_id=$14, estimated_effort=$15, priority=$16, intent=$17, \
                 execution=$18, progress=$19, assignee_agent_id=$20, current_attempt_id=$21, \
                 workspace_task_id=$22, metadata_json=$23, updated_at=$24, completed_at=$25 \
             WHERE id=$1 AND plan_id=$2 RETURNING {PLAN_NODE_COLS}"
        ))
        .bind(&node.id)
        .bind(&node.plan_id)
        .bind(&node.parent_id)
        .bind(&node.kind)
        .bind(&node.title)
        .bind(&node.description)
        .bind(Json(&node.depends_on_json))
        .bind(Json(&node.inputs_schema_json))
        .bind(Json(&node.outputs_schema_json))
        .bind(Json(&node.acceptance_criteria_json))
        .bind(node.feature_checkpoint_json.as_ref().map(Json))
        .bind(node.handoff_package_json.as_ref().map(Json))
        .bind(Json(&node.recommended_capabilities_json))
        .bind(&node.preferred_agent_id)
        .bind(Json(&node.estimated_effort_json))
        .bind(node.priority)
        .bind(&node.intent)
        .bind(&node.execution)
        .bind(Json(&node.progress_json))
        .bind(&node.assignee_agent_id)
        .bind(&node.current_attempt_id)
        .bind(&node.workspace_task_id)
        .bind(Json(&node.metadata_json))
        .bind(node.updated_at)
        .bind(node.completed_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan_node)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("workspace plan node update returned no row".into()))
    }

    pub async fn list_plan_nodes(&self, plan_id: &str) -> CoreResult<Vec<WorkspacePlanNodeRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {PLAN_NODE_COLS} FROM workspace_plan_nodes \
             WHERE plan_id = $1 ORDER BY kind ASC, priority ASC, id ASC"
        ))
        .bind(plan_id)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_plan_node).collect()
    }

    /// Batch variant of [`list_plan_nodes`](Self::list_plan_nodes): one
    /// round-trip for many plans instead of one per plan (the autonomy tick
    /// scans up to 50 candidate plans). Same per-plan ordering
    /// (`kind ASC, priority ASC, id ASC`); callers group rows by `plan_id`.
    pub async fn list_plan_nodes_by_plan_ids(
        &self,
        plan_ids: &[String],
    ) -> CoreResult<Vec<WorkspacePlanNodeRecord>> {
        if plan_ids.is_empty() {
            return Ok(Vec::new());
        }
        let rows = sqlx::query(&format!(
            "SELECT {PLAN_NODE_COLS} FROM workspace_plan_nodes \
             WHERE plan_id = ANY($1) ORDER BY kind ASC, priority ASC, id ASC"
        ))
        .bind(plan_ids)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_plan_node).collect()
    }

    pub async fn create_plan_blackboard_entry(
        &self,
        entry: WorkspacePlanBlackboardEntryRecord,
    ) -> CoreResult<WorkspacePlanBlackboardEntryRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_plan_blackboard_entries \
                (id, plan_id, key, value_json, published_by, version, schema_ref, metadata_json, \
                 created_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING {PLAN_BLACKBOARD_COLS}"
        ))
        .bind(&entry.id)
        .bind(&entry.plan_id)
        .bind(&entry.key)
        .bind(entry.value_json.as_ref().map(Json))
        .bind(&entry.published_by)
        .bind(entry.version)
        .bind(&entry.schema_ref)
        .bind(Json(&entry.metadata_json))
        .bind(entry.created_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan_blackboard_entry)
        .transpose()?
        .ok_or_else(|| {
            CoreError::Storage("workspace plan blackboard insert returned no row".into())
        })
    }

    pub async fn list_plan_blackboard_latest(
        &self,
        plan_id: &str,
    ) -> CoreResult<Vec<WorkspacePlanBlackboardEntryRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT DISTINCT ON (key) {PLAN_BLACKBOARD_COLS} \
             FROM workspace_plan_blackboard_entries \
             WHERE plan_id = $1 \
             ORDER BY key ASC, version DESC, created_at DESC"
        ))
        .bind(plan_id)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_plan_blackboard_entry).collect()
    }

    pub async fn create_plan_event(
        &self,
        event: WorkspacePlanEventRecord,
    ) -> CoreResult<WorkspacePlanEventRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_plan_events \
                (id, plan_id, workspace_id, node_id, attempt_id, event_type, source, actor_id, \
                 payload_json, created_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING {PLAN_EVENT_COLS}"
        ))
        .bind(&event.id)
        .bind(&event.plan_id)
        .bind(&event.workspace_id)
        .bind(&event.node_id)
        .bind(&event.attempt_id)
        .bind(&event.event_type)
        .bind(&event.source)
        .bind(&event.actor_id)
        .bind(Json(&event.payload_json))
        .bind(event.created_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan_event)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("workspace plan event insert returned no row".into()))
    }

    pub async fn list_plan_events(
        &self,
        plan_id: &str,
        limit: i64,
    ) -> CoreResult<Vec<WorkspacePlanEventRecord>> {
        if limit <= 0 {
            return Ok(Vec::new());
        }
        let rows = sqlx::query(&format!(
            "SELECT {PLAN_EVENT_COLS} FROM workspace_plan_events \
             WHERE plan_id = $1 ORDER BY created_at DESC, id DESC LIMIT $2"
        ))
        .bind(plan_id)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_plan_event).collect()
    }

    pub async fn has_supervisor_dispose_decision_for_node(
        &self,
        workspace_id: &str,
        plan_id: &str,
        node_id: &str,
    ) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (Option<String>,)>(
            "SELECT id FROM workspace_plan_events \
             WHERE workspace_id = $1 \
               AND plan_id = $2 \
               AND node_id = $3 \
               AND event_type = 'supervisor_decision_completed' \
               AND payload_json->>'action' = 'dispose_node' \
             LIMIT 1",
        )
        .bind(workspace_id)
        .bind(plan_id)
        .bind(node_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row.is_some())
    }
}
