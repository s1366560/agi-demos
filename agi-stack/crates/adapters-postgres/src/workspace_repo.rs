//! Shared-DB repository for the P6 workspace foundation.
//!
//! The Python backend owns these tables (`workspaces`, `workspace_tasks`,
//! `topology_*`, `blackboard_*`, `workspace_plan_*`). Rust writes the same rows
//! during strangler cutover and keeps SQLx strictly in this server-only adapter
//! crate.

use serde_json::{json, Map, Value};
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::types::Json;
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

mod blackboard;
mod pipeline;
mod plan;
mod plan_outbox;
mod records;
mod rows;
mod task_attempts;
mod topology;

use rows::*;

const WORKSPACE_COLS: &str = "id, tenant_id, project_id, name, description, created_by, \
    is_archived, metadata_json, office_status, hex_layout_config_json, \
    default_blocking_categories_json, created_at, updated_at";
const WORKSPACE_COLS_W: &str = "w.id, w.tenant_id, w.project_id, w.name, w.description, \
    w.created_by, w.is_archived, w.metadata_json, w.office_status, w.hex_layout_config_json, \
    w.default_blocking_categories_json, w.created_at, w.updated_at";
const TASK_COLS: &str = "id, workspace_id, title, description, created_by, assignee_user_id, \
    assignee_agent_id, status, priority, estimated_effort, blocker_reason, metadata_json, \
    created_at, updated_at, completed_at, archived_at";
const TASK_SESSION_ATTEMPT_COLS: &str = "id, workspace_task_id, root_goal_task_id, workspace_id, \
    attempt_number, status, conversation_id, worker_agent_id, leader_agent_id, candidate_summary, \
    candidate_artifacts_json, candidate_verifications_json, leader_feedback, adjudication_reason, \
    created_at, updated_at, completed_at";
const NODE_COLS: &str = "id, workspace_id, node_type, ref_id, title, position_x, position_y, \
    hex_q, hex_r, status, tags_json, data_json, created_at, updated_at";
const EDGE_COLS: &str = "id, workspace_id, source_node_id, target_node_id, label, \
    source_hex_q, source_hex_r, target_hex_q, target_hex_r, direction, auto_created, data_json, \
    created_at, updated_at";
const POST_COLS: &str = "id, workspace_id, author_id, title, content, status, is_pinned, \
    metadata_json, created_at, updated_at";
const REPLY_COLS: &str = "id, post_id, workspace_id, author_id, content, metadata_json, \
    created_at, updated_at";
const FILE_COLS: &str = "id, workspace_id, parent_path, name, is_directory, file_size, \
    content_type, storage_key, uploader_type, uploader_id, uploader_name, checksum_sha256, \
    mime_type_detected, created_at";
const MESSAGE_COLS: &str = "id, workspace_id, sender_id, sender_type, content, mentions_json, \
    parent_message_id, metadata_json, created_at";
const PLAN_COLS: &str = "id, workspace_id, goal_id, status, created_at, updated_at";
const PLAN_NODE_COLS: &str = "id, plan_id, parent_id, kind, title, description, depends_on, \
    inputs_schema, outputs_schema, acceptance_criteria, feature_checkpoint, handoff_package, \
    recommended_capabilities, preferred_agent_id, estimated_effort, priority, intent, execution, \
    progress, assignee_agent_id, current_attempt_id, workspace_task_id, metadata_json, created_at, \
    updated_at, completed_at";
const PLAN_BLACKBOARD_COLS: &str = "id, plan_id, key, value_json, published_by, version, \
    schema_ref, metadata_json, created_at";
const PLAN_EVENT_COLS: &str = "id, plan_id, workspace_id, node_id, attempt_id, event_type, \
    source, actor_id, payload_json, created_at";
const PLAN_OUTBOX_COLS: &str = "id, plan_id, workspace_id, event_type, payload_json, status, \
    attempt_count, max_attempts, lease_owner, lease_expires_at, last_error, next_attempt_at, \
    processed_at, metadata_json, created_at, updated_at";
const PIPELINE_RUN_COLS: &str = "id, contract_id, workspace_id, plan_id, node_id, attempt_id, \
    commit_ref, provider, status, reason, started_at, completed_at, metadata_json, created_at, \
    updated_at";
const PIPELINE_STAGE_RUN_COLS: &str = "id, run_id, workspace_id, stage, status, command, \
    exit_code, stdout_preview, stderr_preview, log_ref, artifact_refs_json, started_at, \
    completed_at, duration_ms, metadata_json, created_at, updated_at";

pub use records::*;

pub struct PgWorkspaceRepository {
    pool: PgPool,
}

impl PgWorkspaceRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn user_can_access_project(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        access: WorkspaceProjectAccess,
    ) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (String, String)>(
            "SELECT COALESCE(up.role, ''), p.owner_id \
             FROM projects p \
             LEFT JOIN user_projects up ON up.project_id = p.id AND up.user_id = $1 \
             WHERE p.id = $2 AND p.tenant_id = $3 \
             LIMIT 1",
        )
        .bind(user_id)
        .bind(project_id)
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        let Some((role, owner_id)) = row else {
            return Ok(false);
        };
        if owner_id == user_id {
            return Ok(true);
        }
        Ok(match access {
            WorkspaceProjectAccess::Read => !role.is_empty(),
            WorkspaceProjectAccess::Write => matches!(role.as_str(), "owner" | "admin" | "editor"),
            WorkspaceProjectAccess::Admin => matches!(role.as_str(), "owner" | "admin"),
        })
    }

    pub async fn workspace_scope(
        &self,
        workspace_id: &str,
    ) -> CoreResult<Option<(String, String)>> {
        let row = sqlx::query_as::<_, (String, String)>(
            "SELECT tenant_id, project_id FROM workspaces WHERE id = $1",
        )
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row)
    }

    pub async fn workspace_in_scope(
        &self,
        workspace_id: &str,
        tenant_id: &str,
        project_id: &str,
    ) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM workspaces WHERE id = $1 AND tenant_id = $2 AND project_id = $3",
        )
        .bind(workspace_id)
        .bind(tenant_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row.0 > 0)
    }

    pub async fn user_can_access_workspace(
        &self,
        user_id: &str,
        workspace_id: &str,
        access: WorkspaceAccess,
    ) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (String,)>(
            "SELECT role FROM workspace_members WHERE workspace_id = $1 AND user_id = $2 LIMIT 1",
        )
        .bind(workspace_id)
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        let Some((role,)) = row else {
            return Ok(false);
        };
        Ok(match access {
            WorkspaceAccess::Read => true,
            WorkspaceAccess::Write => matches!(role.as_str(), "owner" | "admin" | "editor"),
        })
    }

    pub async fn create_workspace(
        &self,
        workspace: WorkspaceRecord,
        owner_member_id: String,
    ) -> CoreResult<WorkspaceRecord> {
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let row = sqlx::query(&format!(
            "INSERT INTO workspaces \
                (id, tenant_id, project_id, name, description, created_by, is_archived, \
                 metadata_json, office_status, hex_layout_config_json, \
                 default_blocking_categories_json, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) \
             RETURNING {WORKSPACE_COLS}"
        ))
        .bind(&workspace.id)
        .bind(&workspace.tenant_id)
        .bind(&workspace.project_id)
        .bind(&workspace.name)
        .bind(&workspace.description)
        .bind(&workspace.created_by)
        .bind(workspace.is_archived)
        .bind(Json(&workspace.metadata_json))
        .bind(&workspace.office_status)
        .bind(Json(&workspace.hex_layout_config_json))
        .bind(Json(&workspace.default_blocking_categories_json))
        .bind(workspace.created_at)
        .bind(workspace.updated_at)
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "INSERT INTO workspace_members \
                (id, workspace_id, user_id, role, invited_by, created_at, updated_at) \
             VALUES ($1,$2,$3,'owner',$3,$4,NULL)",
        )
        .bind(owner_member_id)
        .bind(&workspace.id)
        .bind(&workspace.created_by)
        .bind(workspace.created_at)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        row_to_workspace(row)
    }

    pub async fn list_workspaces_for_user(
        &self,
        tenant_id: &str,
        project_id: &str,
        user_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<WorkspaceRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {cols} \
             FROM workspaces w \
             JOIN workspace_members wm ON wm.workspace_id = w.id \
             WHERE w.tenant_id = $1 AND w.project_id = $2 AND wm.user_id = $3 \
             ORDER BY w.created_at DESC, w.id ASC \
             OFFSET $4 LIMIT $5",
            cols = WORKSPACE_COLS_W
        ))
        .bind(tenant_id)
        .bind(project_id)
        .bind(user_id)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_workspace).collect()
    }

    pub async fn get_workspace(&self, workspace_id: &str) -> CoreResult<Option<WorkspaceRecord>> {
        sqlx::query(&format!(
            "SELECT {WORKSPACE_COLS} FROM workspaces WHERE id = $1"
        ))
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_workspace)
        .transpose()
    }

    pub async fn list_workspace_member_user_ids(
        &self,
        workspace_id: &str,
    ) -> CoreResult<Vec<String>> {
        let rows = sqlx::query_as::<_, (String,)>(
            "SELECT user_id FROM workspace_members WHERE workspace_id = $1 ORDER BY created_at ASC, id ASC",
        )
        .bind(workspace_id)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        Ok(rows.into_iter().map(|(user_id,)| user_id).collect())
    }

    pub async fn list_workspace_members(
        &self,
        workspace_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<WorkspaceMemberRecord>> {
        let rows = sqlx::query(
            "SELECT wm.id, wm.workspace_id, wm.user_id, u.email AS user_email, wm.role, \
                    wm.invited_by, wm.created_at, wm.updated_at \
             FROM workspace_members wm \
             LEFT JOIN users u ON u.id = wm.user_id \
             WHERE wm.workspace_id = $1 \
             ORDER BY wm.created_at ASC, wm.id ASC \
             OFFSET $2 LIMIT $3",
        )
        .bind(workspace_id)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter()
            .map(|row| {
                Ok(WorkspaceMemberRecord {
                    id: row.try_get("id").map_err(storage)?,
                    workspace_id: row.try_get("workspace_id").map_err(storage)?,
                    user_id: row.try_get("user_id").map_err(storage)?,
                    user_email: row.try_get("user_email").map_err(storage)?,
                    role: row.try_get("role").map_err(storage)?,
                    invited_by: row.try_get("invited_by").map_err(storage)?,
                    created_at: row.try_get("created_at").map_err(storage)?,
                    updated_at: row.try_get("updated_at").map_err(storage)?,
                })
            })
            .collect()
    }

    pub async fn list_workspace_agent_ids(&self, workspace_id: &str) -> CoreResult<Vec<String>> {
        Ok(self
            .list_active_workspace_agents(workspace_id)
            .await?
            .into_iter()
            .map(|agent| agent.agent_id)
            .collect())
    }

    pub async fn list_active_workspace_agents(
        &self,
        workspace_id: &str,
    ) -> CoreResult<Vec<WorkspaceAgentRecord>> {
        let rows = sqlx::query(
            "SELECT id, workspace_id, agent_id, display_name FROM workspace_agents \
             WHERE workspace_id = $1 AND is_active = true \
             ORDER BY created_at ASC, id ASC",
        )
        .bind(workspace_id)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter()
            .map(|row| {
                Ok(WorkspaceAgentRecord {
                    id: row.try_get("id").map_err(storage)?,
                    workspace_id: row.try_get("workspace_id").map_err(storage)?,
                    agent_id: row.try_get("agent_id").map_err(storage)?,
                    display_name: row.try_get("display_name").map_err(storage)?,
                })
            })
            .collect()
    }

    pub async fn list_workspace_agents(
        &self,
        workspace_id: &str,
        active_only: bool,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<WorkspaceAgentDetailRecord>> {
        let rows = sqlx::query(
            "SELECT id, workspace_id, agent_id, display_name, description, \
                    COALESCE(config_json, '{}'::json) AS config_json, \
                    is_active, hex_q, hex_r, theme_color, label, status, created_at, updated_at \
             FROM workspace_agents \
             WHERE workspace_id = $1 AND ($2 = false OR is_active = true) \
             ORDER BY created_at ASC, id ASC \
             OFFSET $3 LIMIT $4",
        )
        .bind(workspace_id)
        .bind(active_only)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter()
            .map(|row| {
                let Json(config_json): Json<Value> = row.try_get("config_json").map_err(storage)?;
                Ok(WorkspaceAgentDetailRecord {
                    id: row.try_get("id").map_err(storage)?,
                    workspace_id: row.try_get("workspace_id").map_err(storage)?,
                    agent_id: row.try_get("agent_id").map_err(storage)?,
                    display_name: row.try_get("display_name").map_err(storage)?,
                    description: row.try_get("description").map_err(storage)?,
                    config_json,
                    is_active: row.try_get("is_active").map_err(storage)?,
                    hex_q: row.try_get("hex_q").map_err(storage)?,
                    hex_r: row.try_get("hex_r").map_err(storage)?,
                    theme_color: row.try_get("theme_color").map_err(storage)?,
                    label: row.try_get("label").map_err(storage)?,
                    status: row.try_get("status").map_err(storage)?,
                    created_at: row.try_get("created_at").map_err(storage)?,
                    updated_at: row.try_get("updated_at").map_err(storage)?,
                })
            })
            .collect()
    }

    pub async fn get_user_email(&self, user_id: &str) -> CoreResult<Option<String>> {
        sqlx::query_as::<_, (String,)>("SELECT email FROM users WHERE id = $1 LIMIT 1")
            .bind(user_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)
            .map(|row| row.map(|(email,)| email))
    }

    pub async fn save_workspace(&self, workspace: WorkspaceRecord) -> CoreResult<WorkspaceRecord> {
        sqlx::query(&format!(
            "UPDATE workspaces SET name=$2, description=$3, is_archived=$4, metadata_json=$5, \
                 office_status=$6, hex_layout_config_json=$7, \
                 default_blocking_categories_json=$8, updated_at=$9 \
             WHERE id=$1 \
             RETURNING {WORKSPACE_COLS}"
        ))
        .bind(&workspace.id)
        .bind(&workspace.name)
        .bind(&workspace.description)
        .bind(workspace.is_archived)
        .bind(Json(&workspace.metadata_json))
        .bind(&workspace.office_status)
        .bind(Json(&workspace.hex_layout_config_json))
        .bind(Json(&workspace.default_blocking_categories_json))
        .bind(workspace.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_workspace)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("workspace update returned no row".into()))
    }

    pub async fn delete_workspace(&self, workspace_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM workspaces WHERE id = $1")
            .bind(workspace_id)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn create_task(&self, task: WorkspaceTaskRecord) -> CoreResult<WorkspaceTaskRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_tasks \
                (id, workspace_id, title, description, created_by, assignee_user_id, \
                 assignee_agent_id, status, priority, estimated_effort, blocker_reason, \
                 metadata_json, created_at, updated_at, completed_at, archived_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) \
             RETURNING {TASK_COLS}"
        ))
        .bind(&task.id)
        .bind(&task.workspace_id)
        .bind(&task.title)
        .bind(&task.description)
        .bind(&task.created_by)
        .bind(&task.assignee_user_id)
        .bind(&task.assignee_agent_id)
        .bind(&task.status)
        .bind(task.priority)
        .bind(&task.estimated_effort)
        .bind(&task.blocker_reason)
        .bind(Json(&task.metadata_json))
        .bind(task.created_at)
        .bind(task.updated_at)
        .bind(task.completed_at)
        .bind(task.archived_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_task)
    }

    pub async fn create_message(
        &self,
        message: WorkspaceMessageRecord,
    ) -> CoreResult<WorkspaceMessageRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_messages \
                (id, workspace_id, sender_id, sender_type, content, mentions_json, \
                 parent_message_id, metadata_json, created_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) \
             RETURNING {MESSAGE_COLS}"
        ))
        .bind(&message.id)
        .bind(&message.workspace_id)
        .bind(&message.sender_id)
        .bind(&message.sender_type)
        .bind(&message.content)
        .bind(Json(&message.mentions_json))
        .bind(&message.parent_message_id)
        .bind(Json(&message.metadata_json))
        .bind(message.created_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_workspace_message)
    }

    pub async fn list_messages(
        &self,
        workspace_id: &str,
        limit: i64,
        before: Option<&str>,
    ) -> CoreResult<Vec<WorkspaceMessageRecord>> {
        let rows = if let Some(before) = before {
            sqlx::query(&format!(
                "WITH before_message AS ( \
                    SELECT created_at FROM workspace_messages \
                    WHERE workspace_id = $1 AND id = $2 \
                 ) \
                 SELECT {MESSAGE_COLS} FROM workspace_messages \
                 WHERE workspace_id = $1 \
                   AND ( \
                     NOT EXISTS (SELECT 1 FROM before_message) \
                     OR created_at < (SELECT created_at FROM before_message) \
                     OR (created_at = (SELECT created_at FROM before_message) AND id < $2) \
                   ) \
                 ORDER BY created_at ASC, id ASC \
                 LIMIT $3"
            ))
            .bind(workspace_id)
            .bind(before)
            .bind(limit)
            .fetch_all(&self.pool)
            .await
            .map_err(storage)?
        } else {
            sqlx::query(&format!(
                "SELECT {MESSAGE_COLS} FROM workspace_messages \
                 WHERE workspace_id = $1 \
                 ORDER BY created_at ASC, id ASC \
                 LIMIT $2"
            ))
            .bind(workspace_id)
            .bind(limit)
            .fetch_all(&self.pool)
            .await
            .map_err(storage)?
        };
        rows.into_iter().map(row_to_workspace_message).collect()
    }

    pub async fn list_messages_mentioning(
        &self,
        workspace_id: &str,
        target_id: &str,
        limit: i64,
    ) -> CoreResult<Vec<WorkspaceMessageRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {MESSAGE_COLS} FROM workspace_messages \
             WHERE workspace_id = $1 AND mentions_json::jsonb @> $2::jsonb \
             ORDER BY created_at ASC, id ASC \
             LIMIT $3"
        ))
        .bind(workspace_id)
        .bind(serde_json::to_string(&vec![target_id]).map_err(storage)?)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_workspace_message).collect()
    }

    pub async fn list_tasks(
        &self,
        workspace_id: &str,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        let rows = match status {
            Some(status) => {
                sqlx::query(&format!(
                    "SELECT {TASK_COLS} FROM workspace_tasks \
                     WHERE workspace_id = $1 AND status = $2 \
                     ORDER BY created_at DESC, id ASC OFFSET $3 LIMIT $4"
                ))
                .bind(workspace_id)
                .bind(status)
                .bind(offset)
                .bind(limit)
                .fetch_all(&self.pool)
                .await
            }
            None => {
                sqlx::query(&format!(
                    "SELECT {TASK_COLS} FROM workspace_tasks \
                     WHERE workspace_id = $1 \
                     ORDER BY created_at DESC, id ASC OFFSET $2 LIMIT $3"
                ))
                .bind(workspace_id)
                .bind(offset)
                .bind(limit)
                .fetch_all(&self.pool)
                .await
            }
        }
        .map_err(storage)?;
        rows.into_iter().map(row_to_task).collect()
    }

    pub async fn list_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {TASK_COLS} FROM workspace_tasks \
             WHERE workspace_id = $1 \
               AND metadata_json->>'root_goal_task_id' = $2 \
               AND archived_at IS NULL \
             ORDER BY created_at ASC, id ASC"
        ))
        .bind(workspace_id)
        .bind(root_goal_task_id)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_task).collect()
    }

    pub async fn list_current_plan_child_tasks_by_root_goal_task_id(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
    ) -> CoreResult<Vec<WorkspaceTaskRecord>> {
        let task_cols = qualified_cols("workspace_tasks", TASK_COLS);
        let rows = sqlx::query(&format!(
            "SELECT {task_cols} FROM workspace_tasks \
             JOIN workspace_plan_nodes \
               ON workspace_plan_nodes.workspace_task_id = workspace_tasks.id \
             WHERE workspace_tasks.workspace_id = $1 \
               AND workspace_tasks.metadata_json->>'root_goal_task_id' = $2 \
               AND workspace_tasks.archived_at IS NULL \
               AND workspace_plan_nodes.plan_id = workspace_tasks.metadata_json->>'workspace_plan_id' \
               AND workspace_plan_nodes.id = workspace_tasks.metadata_json->>'workspace_plan_node_id' \
             ORDER BY workspace_tasks.created_at ASC, workspace_tasks.id ASC"
        ))
        .bind(workspace_id)
        .bind(root_goal_task_id)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_task).collect()
    }

    pub async fn get_task(
        &self,
        workspace_id: &str,
        task_id: &str,
    ) -> CoreResult<Option<WorkspaceTaskRecord>> {
        sqlx::query(&format!(
            "SELECT {TASK_COLS} FROM workspace_tasks WHERE id = $1 AND workspace_id = $2"
        ))
        .bind(task_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_task)
        .transpose()
    }

    pub async fn save_task(&self, task: WorkspaceTaskRecord) -> CoreResult<WorkspaceTaskRecord> {
        sqlx::query(&format!(
            "UPDATE workspace_tasks SET title=$3, description=$4, assignee_user_id=$5, \
                 assignee_agent_id=$6, status=$7, priority=$8, estimated_effort=$9, \
                 blocker_reason=$10, metadata_json=$11, updated_at=$12, completed_at=$13, \
                 archived_at=$14 \
             WHERE id=$1 AND workspace_id=$2 RETURNING {TASK_COLS}"
        ))
        .bind(&task.id)
        .bind(&task.workspace_id)
        .bind(&task.title)
        .bind(&task.description)
        .bind(&task.assignee_user_id)
        .bind(&task.assignee_agent_id)
        .bind(&task.status)
        .bind(task.priority)
        .bind(&task.estimated_effort)
        .bind(&task.blocker_reason)
        .bind(Json(&task.metadata_json))
        .bind(task.updated_at)
        .bind(task.completed_at)
        .bind(task.archived_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_task)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("workspace task update returned no row".into()))
    }

    pub async fn delete_task(&self, workspace_id: &str, task_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM workspace_tasks WHERE id = $1 AND workspace_id = $2")
            .bind(task_id)
            .bind(workspace_id)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn enqueue_blackboard_outbox(
        &self,
        outbox: BlackboardOutboxRecord,
    ) -> CoreResult<()> {
        sqlx::query(
            "INSERT INTO workspace_blackboard_outbox \
                (id, workspace_id, tenant_id, project_id, event_type, payload_json, metadata_json, \
                 correlation_id, status, attempt_count, max_attempts, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'pending',0,10,now(),NULL)",
        )
        .bind(outbox.id)
        .bind(outbox.workspace_id)
        .bind(outbox.tenant_id)
        .bind(outbox.project_id)
        .bind(outbox.event_type)
        .bind(Json(outbox.payload_json))
        .bind(Json(outbox.metadata_json))
        .bind(outbox.correlation_id)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(())
    }
}

fn storage(e: impl std::fmt::Display) -> CoreError {
    CoreError::Storage(e.to_string())
}
