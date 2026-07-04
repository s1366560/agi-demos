use super::*;

use sqlx::postgres::PgRow;

pub(super) fn row_to_workspace(row: PgRow) -> CoreResult<WorkspaceRecord> {
    Ok(WorkspaceRecord {
        id: row.try_get("id").map_err(storage)?,
        tenant_id: row.try_get("tenant_id").map_err(storage)?,
        project_id: row.try_get("project_id").map_err(storage)?,
        name: row.try_get("name").map_err(storage)?,
        description: row.try_get("description").map_err(storage)?,
        created_by: row.try_get("created_by").map_err(storage)?,
        is_archived: row.try_get("is_archived").map_err(storage)?,
        metadata_json: json_value(&row, "metadata_json")?,
        office_status: row.try_get("office_status").map_err(storage)?,
        hex_layout_config_json: json_value(&row, "hex_layout_config_json")?,
        default_blocking_categories_json: json_vec_string(
            &row,
            "default_blocking_categories_json",
        )?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

pub(super) fn row_to_task(row: PgRow) -> CoreResult<WorkspaceTaskRecord> {
    Ok(WorkspaceTaskRecord {
        id: row.try_get("id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        title: row.try_get("title").map_err(storage)?,
        description: row.try_get("description").map_err(storage)?,
        created_by: row.try_get("created_by").map_err(storage)?,
        assignee_user_id: row.try_get("assignee_user_id").map_err(storage)?,
        assignee_agent_id: row.try_get("assignee_agent_id").map_err(storage)?,
        status: row.try_get("status").map_err(storage)?,
        priority: row.try_get("priority").map_err(storage)?,
        estimated_effort: row.try_get("estimated_effort").map_err(storage)?,
        blocker_reason: row.try_get("blocker_reason").map_err(storage)?,
        metadata_json: json_value(&row, "metadata_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
        completed_at: row.try_get("completed_at").map_err(storage)?,
        archived_at: row.try_get("archived_at").map_err(storage)?,
    })
}

pub(super) fn qualified_cols(alias: &str, cols: &str) -> String {
    cols.split(", ")
        .map(|col| format!("{alias}.{col}"))
        .collect::<Vec<_>>()
        .join(", ")
}

pub(super) fn row_to_task_session_attempt(
    row: PgRow,
) -> CoreResult<WorkspaceTaskSessionAttemptRecord> {
    Ok(WorkspaceTaskSessionAttemptRecord {
        id: row.try_get("id").map_err(storage)?,
        workspace_task_id: row.try_get("workspace_task_id").map_err(storage)?,
        root_goal_task_id: row.try_get("root_goal_task_id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        attempt_number: row.try_get("attempt_number").map_err(storage)?,
        status: row.try_get("status").map_err(storage)?,
        conversation_id: row.try_get("conversation_id").map_err(storage)?,
        worker_agent_id: row.try_get("worker_agent_id").map_err(storage)?,
        leader_agent_id: row.try_get("leader_agent_id").map_err(storage)?,
        candidate_summary: row.try_get("candidate_summary").map_err(storage)?,
        candidate_artifacts_json: row
            .try_get::<Json<Vec<String>>, _>("candidate_artifacts_json")
            .map_err(storage)?
            .0,
        candidate_verifications_json: row
            .try_get::<Json<Vec<String>>, _>("candidate_verifications_json")
            .map_err(storage)?
            .0,
        leader_feedback: row.try_get("leader_feedback").map_err(storage)?,
        adjudication_reason: row.try_get("adjudication_reason").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
        completed_at: row.try_get("completed_at").map_err(storage)?,
    })
}

pub(super) fn row_to_workspace_message(row: PgRow) -> CoreResult<WorkspaceMessageRecord> {
    Ok(WorkspaceMessageRecord {
        id: row.try_get("id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        sender_id: row.try_get("sender_id").map_err(storage)?,
        sender_type: row.try_get("sender_type").map_err(storage)?,
        content: row.try_get("content").map_err(storage)?,
        mentions_json: json_vec_string(&row, "mentions_json")?,
        parent_message_id: row.try_get("parent_message_id").map_err(storage)?,
        metadata_json: json_value(&row, "metadata_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
    })
}

pub(super) fn row_to_pipeline_run(row: PgRow) -> CoreResult<WorkspacePipelineRunRecord> {
    Ok(WorkspacePipelineRunRecord {
        id: row.try_get("id").map_err(storage)?,
        contract_id: row.try_get("contract_id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        plan_id: row.try_get("plan_id").map_err(storage)?,
        node_id: row.try_get("node_id").map_err(storage)?,
        attempt_id: row.try_get("attempt_id").map_err(storage)?,
        commit_ref: row.try_get("commit_ref").map_err(storage)?,
        provider: row.try_get("provider").map_err(storage)?,
        status: row.try_get("status").map_err(storage)?,
        reason: row.try_get("reason").map_err(storage)?,
        started_at: row.try_get("started_at").map_err(storage)?,
        completed_at: row.try_get("completed_at").map_err(storage)?,
        metadata_json: json_value(&row, "metadata_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

pub(super) fn row_to_pipeline_stage_run(row: PgRow) -> CoreResult<WorkspacePipelineStageRunRecord> {
    Ok(WorkspacePipelineStageRunRecord {
        id: row.try_get("id").map_err(storage)?,
        run_id: row.try_get("run_id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        stage: row.try_get("stage").map_err(storage)?,
        status: row.try_get("status").map_err(storage)?,
        command: row.try_get("command").map_err(storage)?,
        exit_code: row.try_get("exit_code").map_err(storage)?,
        stdout_preview: row.try_get("stdout_preview").map_err(storage)?,
        stderr_preview: row.try_get("stderr_preview").map_err(storage)?,
        log_ref: row.try_get("log_ref").map_err(storage)?,
        artifact_refs_json: json_vec_string(&row, "artifact_refs_json")?,
        started_at: row.try_get("started_at").map_err(storage)?,
        completed_at: row.try_get("completed_at").map_err(storage)?,
        duration_ms: row.try_get("duration_ms").map_err(storage)?,
        metadata_json: json_value(&row, "metadata_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

pub(super) fn row_to_node(row: PgRow) -> CoreResult<TopologyNodeRecord> {
    Ok(TopologyNodeRecord {
        id: row.try_get("id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        node_type: row.try_get("node_type").map_err(storage)?,
        ref_id: row.try_get("ref_id").map_err(storage)?,
        title: row.try_get("title").map_err(storage)?,
        position_x: row.try_get("position_x").map_err(storage)?,
        position_y: row.try_get("position_y").map_err(storage)?,
        hex_q: row.try_get("hex_q").map_err(storage)?,
        hex_r: row.try_get("hex_r").map_err(storage)?,
        status: row.try_get("status").map_err(storage)?,
        tags_json: json_vec_string(&row, "tags_json")?,
        data_json: json_value(&row, "data_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

pub(super) fn row_to_edge(row: PgRow) -> CoreResult<TopologyEdgeRecord> {
    Ok(TopologyEdgeRecord {
        id: row.try_get("id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        source_node_id: row.try_get("source_node_id").map_err(storage)?,
        target_node_id: row.try_get("target_node_id").map_err(storage)?,
        label: row.try_get("label").map_err(storage)?,
        source_hex_q: row.try_get("source_hex_q").map_err(storage)?,
        source_hex_r: row.try_get("source_hex_r").map_err(storage)?,
        target_hex_q: row.try_get("target_hex_q").map_err(storage)?,
        target_hex_r: row.try_get("target_hex_r").map_err(storage)?,
        direction: row.try_get("direction").map_err(storage)?,
        auto_created: row.try_get("auto_created").map_err(storage)?,
        data_json: json_value(&row, "data_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

pub(super) fn row_to_post(row: PgRow) -> CoreResult<BlackboardPostRecord> {
    Ok(BlackboardPostRecord {
        id: row.try_get("id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        author_id: row.try_get("author_id").map_err(storage)?,
        title: row.try_get("title").map_err(storage)?,
        content: row.try_get("content").map_err(storage)?,
        status: row.try_get("status").map_err(storage)?,
        is_pinned: row.try_get("is_pinned").map_err(storage)?,
        metadata_json: json_value(&row, "metadata_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

pub(super) fn row_to_reply(row: PgRow) -> CoreResult<BlackboardReplyRecord> {
    Ok(BlackboardReplyRecord {
        id: row.try_get("id").map_err(storage)?,
        post_id: row.try_get("post_id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        author_id: row.try_get("author_id").map_err(storage)?,
        content: row.try_get("content").map_err(storage)?,
        metadata_json: json_value(&row, "metadata_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

pub(super) fn row_to_file(row: PgRow) -> CoreResult<BlackboardFileRecord> {
    Ok(BlackboardFileRecord {
        id: row.try_get("id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        parent_path: row.try_get("parent_path").map_err(storage)?,
        name: row.try_get("name").map_err(storage)?,
        is_directory: row.try_get("is_directory").map_err(storage)?,
        file_size: row.try_get("file_size").map_err(storage)?,
        content_type: row.try_get("content_type").map_err(storage)?,
        storage_key: row.try_get("storage_key").map_err(storage)?,
        uploader_type: row.try_get("uploader_type").map_err(storage)?,
        uploader_id: row.try_get("uploader_id").map_err(storage)?,
        uploader_name: row.try_get("uploader_name").map_err(storage)?,
        checksum_sha256: row.try_get("checksum_sha256").map_err(storage)?,
        mime_type_detected: row.try_get("mime_type_detected").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
    })
}

pub(super) fn row_to_plan(row: PgRow) -> CoreResult<WorkspacePlanRecord> {
    Ok(WorkspacePlanRecord {
        id: row.try_get("id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        goal_id: row.try_get("goal_id").map_err(storage)?,
        status: row.try_get("status").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

pub(super) fn row_to_plan_node(row: PgRow) -> CoreResult<WorkspacePlanNodeRecord> {
    Ok(WorkspacePlanNodeRecord {
        id: row.try_get("id").map_err(storage)?,
        plan_id: row.try_get("plan_id").map_err(storage)?,
        parent_id: row.try_get("parent_id").map_err(storage)?,
        kind: row.try_get("kind").map_err(storage)?,
        title: row.try_get("title").map_err(storage)?,
        description: row.try_get("description").map_err(storage)?,
        depends_on_json: json_vec_string(&row, "depends_on")?,
        inputs_schema_json: json_value(&row, "inputs_schema")?,
        outputs_schema_json: json_value(&row, "outputs_schema")?,
        acceptance_criteria_json: json_vec_value(&row, "acceptance_criteria")?,
        feature_checkpoint_json: json_optional_value(&row, "feature_checkpoint")?,
        handoff_package_json: json_optional_value(&row, "handoff_package")?,
        recommended_capabilities_json: json_vec_value(&row, "recommended_capabilities")?,
        preferred_agent_id: row.try_get("preferred_agent_id").map_err(storage)?,
        estimated_effort_json: json_value(&row, "estimated_effort")?,
        priority: row.try_get("priority").map_err(storage)?,
        intent: row.try_get("intent").map_err(storage)?,
        execution: row.try_get("execution").map_err(storage)?,
        progress_json: json_value(&row, "progress")?,
        assignee_agent_id: row.try_get("assignee_agent_id").map_err(storage)?,
        current_attempt_id: row.try_get("current_attempt_id").map_err(storage)?,
        workspace_task_id: row.try_get("workspace_task_id").map_err(storage)?,
        metadata_json: json_value(&row, "metadata_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
        completed_at: row.try_get("completed_at").map_err(storage)?,
    })
}

pub(super) fn row_to_plan_blackboard_entry(
    row: PgRow,
) -> CoreResult<WorkspacePlanBlackboardEntryRecord> {
    Ok(WorkspacePlanBlackboardEntryRecord {
        id: row.try_get("id").map_err(storage)?,
        plan_id: row.try_get("plan_id").map_err(storage)?,
        key: row.try_get("key").map_err(storage)?,
        value_json: json_optional_value(&row, "value_json")?,
        published_by: row.try_get("published_by").map_err(storage)?,
        version: row.try_get("version").map_err(storage)?,
        schema_ref: row.try_get("schema_ref").map_err(storage)?,
        metadata_json: json_value(&row, "metadata_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
    })
}

pub(super) fn row_to_plan_event(row: PgRow) -> CoreResult<WorkspacePlanEventRecord> {
    Ok(WorkspacePlanEventRecord {
        id: row.try_get("id").map_err(storage)?,
        plan_id: row.try_get("plan_id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        node_id: row.try_get("node_id").map_err(storage)?,
        attempt_id: row.try_get("attempt_id").map_err(storage)?,
        event_type: row.try_get("event_type").map_err(storage)?,
        source: row.try_get("source").map_err(storage)?,
        actor_id: row.try_get("actor_id").map_err(storage)?,
        payload_json: json_value(&row, "payload_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
    })
}

pub(super) fn row_to_plan_outbox(row: PgRow) -> CoreResult<WorkspacePlanOutboxRecord> {
    Ok(WorkspacePlanOutboxRecord {
        id: row.try_get("id").map_err(storage)?,
        plan_id: row.try_get("plan_id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        event_type: row.try_get("event_type").map_err(storage)?,
        payload_json: json_value(&row, "payload_json")?,
        status: row.try_get("status").map_err(storage)?,
        attempt_count: row.try_get("attempt_count").map_err(storage)?,
        max_attempts: row.try_get("max_attempts").map_err(storage)?,
        lease_owner: row.try_get("lease_owner").map_err(storage)?,
        lease_expires_at: row.try_get("lease_expires_at").map_err(storage)?,
        last_error: row.try_get("last_error").map_err(storage)?,
        next_attempt_at: row.try_get("next_attempt_at").map_err(storage)?,
        processed_at: row.try_get("processed_at").map_err(storage)?,
        metadata_json: json_value(&row, "metadata_json")?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

fn json_value(row: &PgRow, name: &str) -> CoreResult<Value> {
    let Json(value): Json<Value> = row.try_get(name).map_err(storage)?;
    Ok(value)
}

fn json_optional_value(row: &PgRow, name: &str) -> CoreResult<Option<Value>> {
    let value: Option<Json<Value>> = row.try_get(name).map_err(storage)?;
    Ok(value.map(|Json(value)| value))
}

fn json_vec_value(row: &PgRow, name: &str) -> CoreResult<Vec<Value>> {
    let Json(value): Json<Vec<Value>> = row.try_get(name).map_err(storage)?;
    Ok(value)
}

fn json_vec_string(row: &PgRow, name: &str) -> CoreResult<Vec<String>> {
    let Json(value): Json<Vec<String>> = row.try_get(name).map_err(storage)?;
    Ok(value)
}

pub(super) fn add_seconds(value: DateTime<Utc>, seconds: i64) -> DateTime<Utc> {
    DateTime::<Utc>::from_timestamp(
        value.timestamp().saturating_add(seconds),
        value.timestamp_subsec_nanos(),
    )
    .unwrap_or(value)
}
