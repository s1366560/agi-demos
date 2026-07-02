//! Shared-DB repository for the P6 workspace foundation.
//!
//! The Python backend owns these tables (`workspaces`, `workspace_tasks`,
//! `topology_*`, `blackboard_*`, `workspace_plan_*`). Rust writes the same rows
//! during strangler cutover and keeps SQLx strictly in this server-only adapter
//! crate.

use serde_json::{json, Map, Value};
use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::types::Json;
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const WORKSPACE_COLS: &str = "id, tenant_id, project_id, name, description, created_by, \
    is_archived, metadata_json, office_status, hex_layout_config_json, \
    default_blocking_categories_json, created_at, updated_at";
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

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceRecord {
    pub id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub name: String,
    pub description: Option<String>,
    pub created_by: String,
    pub is_archived: bool,
    pub metadata_json: Value,
    pub office_status: String,
    pub hex_layout_config_json: Value,
    pub default_blocking_categories_json: Vec<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceMemberRecord {
    pub id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub role: String,
    pub invited_by: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceTaskRecord {
    pub id: String,
    pub workspace_id: String,
    pub title: String,
    pub description: Option<String>,
    pub created_by: String,
    pub assignee_user_id: Option<String>,
    pub assignee_agent_id: Option<String>,
    pub status: String,
    pub priority: i32,
    pub estimated_effort: Option<String>,
    pub blocker_reason: Option<String>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub archived_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceTaskSessionAttemptRecord {
    pub id: String,
    pub workspace_task_id: String,
    pub root_goal_task_id: String,
    pub workspace_id: String,
    pub attempt_number: i32,
    pub status: String,
    pub conversation_id: Option<String>,
    pub worker_agent_id: Option<String>,
    pub leader_agent_id: Option<String>,
    pub candidate_summary: Option<String>,
    pub candidate_artifacts_json: Vec<String>,
    pub candidate_verifications_json: Vec<String>,
    pub leader_feedback: Option<String>,
    pub adjudication_reason: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TopologyNodeRecord {
    pub id: String,
    pub workspace_id: String,
    pub node_type: String,
    pub ref_id: Option<String>,
    pub title: String,
    pub position_x: f64,
    pub position_y: f64,
    pub hex_q: Option<i32>,
    pub hex_r: Option<i32>,
    pub status: String,
    pub tags_json: Vec<String>,
    pub data_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TopologyEdgeRecord {
    pub id: String,
    pub workspace_id: String,
    pub source_node_id: String,
    pub target_node_id: String,
    pub label: Option<String>,
    pub source_hex_q: Option<i32>,
    pub source_hex_r: Option<i32>,
    pub target_hex_q: Option<i32>,
    pub target_hex_r: Option<i32>,
    pub direction: Option<String>,
    pub auto_created: bool,
    pub data_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BlackboardPostRecord {
    pub id: String,
    pub workspace_id: String,
    pub author_id: String,
    pub title: String,
    pub content: String,
    pub status: String,
    pub is_pinned: bool,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BlackboardReplyRecord {
    pub id: String,
    pub post_id: String,
    pub workspace_id: String,
    pub author_id: String,
    pub content: String,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BlackboardFileRecord {
    pub id: String,
    pub workspace_id: String,
    pub parent_path: String,
    pub name: String,
    pub is_directory: bool,
    pub file_size: i32,
    pub content_type: String,
    pub storage_key: String,
    pub uploader_type: String,
    pub uploader_id: String,
    pub uploader_name: String,
    pub checksum_sha256: Option<String>,
    pub mime_type_detected: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BlackboardOutboxRecord {
    pub id: String,
    pub workspace_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub event_type: String,
    pub payload_json: Value,
    pub metadata_json: Value,
    pub correlation_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanRecord {
    pub id: String,
    pub workspace_id: String,
    pub goal_id: String,
    pub status: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanNodeRecord {
    pub id: String,
    pub plan_id: String,
    pub parent_id: Option<String>,
    pub kind: String,
    pub title: String,
    pub description: String,
    pub depends_on_json: Vec<String>,
    pub inputs_schema_json: Value,
    pub outputs_schema_json: Value,
    pub acceptance_criteria_json: Vec<Value>,
    pub feature_checkpoint_json: Option<Value>,
    pub handoff_package_json: Option<Value>,
    pub recommended_capabilities_json: Vec<Value>,
    pub preferred_agent_id: Option<String>,
    pub estimated_effort_json: Value,
    pub priority: i32,
    pub intent: String,
    pub execution: String,
    pub progress_json: Value,
    pub assignee_agent_id: Option<String>,
    pub current_attempt_id: Option<String>,
    pub workspace_task_id: Option<String>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanBlackboardEntryRecord {
    pub id: String,
    pub plan_id: String,
    pub key: String,
    pub value_json: Option<Value>,
    pub published_by: String,
    pub version: i32,
    pub schema_ref: Option<String>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanEventRecord {
    pub id: String,
    pub plan_id: String,
    pub workspace_id: String,
    pub node_id: Option<String>,
    pub attempt_id: Option<String>,
    pub event_type: String,
    pub source: String,
    pub actor_id: Option<String>,
    pub payload_json: Value,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanOutboxRecord {
    pub id: String,
    pub plan_id: Option<String>,
    pub workspace_id: String,
    pub event_type: String,
    pub payload_json: Value,
    pub status: String,
    pub attempt_count: i32,
    pub max_attempts: i32,
    pub lease_owner: Option<String>,
    pub lease_expires_at: Option<DateTime<Utc>>,
    pub last_error: Option<String>,
    pub next_attempt_at: Option<DateTime<Utc>>,
    pub processed_at: Option<DateTime<Utc>>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePipelineRunRecord {
    pub id: String,
    pub contract_id: String,
    pub workspace_id: String,
    pub plan_id: Option<String>,
    pub node_id: Option<String>,
    pub attempt_id: Option<String>,
    pub commit_ref: Option<String>,
    pub provider: String,
    pub status: String,
    pub reason: Option<String>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePipelineStageRunRecord {
    pub id: String,
    pub run_id: String,
    pub workspace_id: String,
    pub stage: String,
    pub status: String,
    pub command: Option<String>,
    pub exit_code: Option<i32>,
    pub stdout_preview: Option<String>,
    pub stderr_preview: Option<String>,
    pub log_ref: Option<String>,
    pub artifact_refs_json: Vec<String>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub duration_ms: Option<i32>,
    pub metadata_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkspaceProjectAccess {
    Read,
    Write,
    Admin,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkspaceAccess {
    Read,
    Write,
}

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
             VALUES ($1,$2,$3,'owner',NULL,$4,NULL)",
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
            "SELECT w.{cols} \
             FROM workspaces w \
             JOIN workspace_members wm ON wm.workspace_id = w.id \
             WHERE w.tenant_id = $1 AND w.project_id = $2 AND wm.user_id = $3 \
             ORDER BY w.created_at DESC, w.id ASC \
             OFFSET $4 LIMIT $5",
            cols = WORKSPACE_COLS
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

    pub async fn delete_task(&self, workspace_id: &str, task_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM workspace_tasks WHERE id = $1 AND workspace_id = $2")
            .bind(task_id)
            .bind(workspace_id)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn create_node(&self, node: TopologyNodeRecord) -> CoreResult<TopologyNodeRecord> {
        sqlx::query(&format!(
            "INSERT INTO topology_nodes \
                (id, workspace_id, node_type, ref_id, title, position_x, position_y, hex_q, \
                 hex_r, status, tags_json, data_json, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) \
             RETURNING {NODE_COLS}"
        ))
        .bind(&node.id)
        .bind(&node.workspace_id)
        .bind(&node.node_type)
        .bind(&node.ref_id)
        .bind(&node.title)
        .bind(node.position_x)
        .bind(node.position_y)
        .bind(node.hex_q)
        .bind(node.hex_r)
        .bind(&node.status)
        .bind(Json(&node.tags_json))
        .bind(Json(&node.data_json))
        .bind(node.created_at)
        .bind(node.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_node)
    }

    pub async fn list_nodes(
        &self,
        workspace_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<TopologyNodeRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {NODE_COLS} FROM topology_nodes WHERE workspace_id = $1 \
             ORDER BY created_at ASC, id ASC OFFSET $2 LIMIT $3"
        ))
        .bind(workspace_id)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_node).collect()
    }

    pub async fn get_node(
        &self,
        workspace_id: &str,
        node_id: &str,
    ) -> CoreResult<Option<TopologyNodeRecord>> {
        sqlx::query(&format!(
            "SELECT {NODE_COLS} FROM topology_nodes WHERE id = $1 AND workspace_id = $2"
        ))
        .bind(node_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_node)
        .transpose()
    }

    pub async fn save_node(&self, node: TopologyNodeRecord) -> CoreResult<TopologyNodeRecord> {
        sqlx::query(&format!(
            "UPDATE topology_nodes SET node_type=$3, ref_id=$4, title=$5, position_x=$6, \
                 position_y=$7, hex_q=$8, hex_r=$9, status=$10, tags_json=$11, data_json=$12, \
                 updated_at=$13 \
             WHERE id=$1 AND workspace_id=$2 RETURNING {NODE_COLS}"
        ))
        .bind(&node.id)
        .bind(&node.workspace_id)
        .bind(&node.node_type)
        .bind(&node.ref_id)
        .bind(&node.title)
        .bind(node.position_x)
        .bind(node.position_y)
        .bind(node.hex_q)
        .bind(node.hex_r)
        .bind(&node.status)
        .bind(Json(&node.tags_json))
        .bind(Json(&node.data_json))
        .bind(node.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_node)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("topology node update returned no row".into()))
    }

    pub async fn delete_node(&self, workspace_id: &str, node_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM topology_nodes WHERE id = $1 AND workspace_id = $2")
            .bind(node_id)
            .bind(workspace_id)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn create_edge(&self, edge: TopologyEdgeRecord) -> CoreResult<TopologyEdgeRecord> {
        sqlx::query(&format!(
            "INSERT INTO topology_edges \
                (id, workspace_id, source_node_id, target_node_id, label, source_hex_q, \
                 source_hex_r, target_hex_q, target_hex_r, direction, auto_created, data_json, \
                 created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) \
             RETURNING {EDGE_COLS}"
        ))
        .bind(&edge.id)
        .bind(&edge.workspace_id)
        .bind(&edge.source_node_id)
        .bind(&edge.target_node_id)
        .bind(&edge.label)
        .bind(edge.source_hex_q)
        .bind(edge.source_hex_r)
        .bind(edge.target_hex_q)
        .bind(edge.target_hex_r)
        .bind(&edge.direction)
        .bind(edge.auto_created)
        .bind(Json(&edge.data_json))
        .bind(edge.created_at)
        .bind(edge.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_edge)
    }

    pub async fn list_edges(
        &self,
        workspace_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<TopologyEdgeRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {EDGE_COLS} FROM topology_edges WHERE workspace_id = $1 \
             ORDER BY created_at ASC, id ASC OFFSET $2 LIMIT $3"
        ))
        .bind(workspace_id)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_edge).collect()
    }

    pub async fn get_edge(
        &self,
        workspace_id: &str,
        edge_id: &str,
    ) -> CoreResult<Option<TopologyEdgeRecord>> {
        sqlx::query(&format!(
            "SELECT {EDGE_COLS} FROM topology_edges WHERE id = $1 AND workspace_id = $2"
        ))
        .bind(edge_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_edge)
        .transpose()
    }

    pub async fn save_edge(&self, edge: TopologyEdgeRecord) -> CoreResult<TopologyEdgeRecord> {
        sqlx::query(&format!(
            "UPDATE topology_edges SET source_node_id=$3, target_node_id=$4, label=$5, \
                 source_hex_q=$6, source_hex_r=$7, target_hex_q=$8, target_hex_r=$9, \
                 direction=$10, auto_created=$11, data_json=$12, updated_at=$13 \
             WHERE id=$1 AND workspace_id=$2 RETURNING {EDGE_COLS}"
        ))
        .bind(&edge.id)
        .bind(&edge.workspace_id)
        .bind(&edge.source_node_id)
        .bind(&edge.target_node_id)
        .bind(&edge.label)
        .bind(edge.source_hex_q)
        .bind(edge.source_hex_r)
        .bind(edge.target_hex_q)
        .bind(edge.target_hex_r)
        .bind(&edge.direction)
        .bind(edge.auto_created)
        .bind(Json(&edge.data_json))
        .bind(edge.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_edge)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("topology edge update returned no row".into()))
    }

    pub async fn delete_edge(&self, workspace_id: &str, edge_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM topology_edges WHERE id = $1 AND workspace_id = $2")
            .bind(edge_id)
            .bind(workspace_id)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn edge_endpoints_in_workspace(
        &self,
        workspace_id: &str,
        source_node_id: &str,
        target_node_id: &str,
    ) -> CoreResult<Option<(Option<i32>, Option<i32>, Option<i32>, Option<i32>)>> {
        let row = sqlx::query_as::<_, (Option<i32>, Option<i32>, Option<i32>, Option<i32>)>(
            "SELECT s.hex_q, s.hex_r, t.hex_q, t.hex_r \
             FROM topology_nodes s \
             JOIN topology_nodes t ON t.id = $3 AND t.workspace_id = $1 \
             WHERE s.id = $2 AND s.workspace_id = $1",
        )
        .bind(workspace_id)
        .bind(source_node_id)
        .bind(target_node_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row)
    }

    pub async fn create_post(
        &self,
        post: BlackboardPostRecord,
    ) -> CoreResult<BlackboardPostRecord> {
        sqlx::query(&format!(
            "INSERT INTO blackboard_posts \
                (id, workspace_id, author_id, title, content, status, is_pinned, metadata_json, \
                 created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) \
             RETURNING {POST_COLS}"
        ))
        .bind(&post.id)
        .bind(&post.workspace_id)
        .bind(&post.author_id)
        .bind(&post.title)
        .bind(&post.content)
        .bind(&post.status)
        .bind(post.is_pinned)
        .bind(Json(&post.metadata_json))
        .bind(post.created_at)
        .bind(post.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_post)
    }

    pub async fn list_posts(
        &self,
        workspace_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<BlackboardPostRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {POST_COLS} FROM blackboard_posts WHERE workspace_id = $1 \
             ORDER BY is_pinned DESC, created_at DESC, id ASC OFFSET $2 LIMIT $3"
        ))
        .bind(workspace_id)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_post).collect()
    }

    pub async fn get_post(
        &self,
        workspace_id: &str,
        post_id: &str,
    ) -> CoreResult<Option<BlackboardPostRecord>> {
        sqlx::query(&format!(
            "SELECT {POST_COLS} FROM blackboard_posts WHERE id = $1 AND workspace_id = $2"
        ))
        .bind(post_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_post)
        .transpose()
    }

    pub async fn save_post(&self, post: BlackboardPostRecord) -> CoreResult<BlackboardPostRecord> {
        sqlx::query(&format!(
            "UPDATE blackboard_posts SET title=$3, content=$4, status=$5, is_pinned=$6, \
                 metadata_json=$7, updated_at=$8 \
             WHERE id=$1 AND workspace_id=$2 RETURNING {POST_COLS}"
        ))
        .bind(&post.id)
        .bind(&post.workspace_id)
        .bind(&post.title)
        .bind(&post.content)
        .bind(&post.status)
        .bind(post.is_pinned)
        .bind(Json(&post.metadata_json))
        .bind(post.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_post)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("blackboard post update returned no row".into()))
    }

    pub async fn delete_post(&self, workspace_id: &str, post_id: &str) -> CoreResult<bool> {
        let result =
            sqlx::query("DELETE FROM blackboard_posts WHERE id = $1 AND workspace_id = $2")
                .bind(post_id)
                .bind(workspace_id)
                .execute(&self.pool)
                .await
                .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn create_reply(
        &self,
        reply: BlackboardReplyRecord,
    ) -> CoreResult<BlackboardReplyRecord> {
        sqlx::query(&format!(
            "INSERT INTO blackboard_replies \
                (id, post_id, workspace_id, author_id, content, metadata_json, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8) \
             RETURNING {REPLY_COLS}"
        ))
        .bind(&reply.id)
        .bind(&reply.post_id)
        .bind(&reply.workspace_id)
        .bind(&reply.author_id)
        .bind(&reply.content)
        .bind(Json(&reply.metadata_json))
        .bind(reply.created_at)
        .bind(reply.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_reply)
    }

    pub async fn list_replies(
        &self,
        workspace_id: &str,
        post_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<BlackboardReplyRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {REPLY_COLS} FROM blackboard_replies \
             WHERE workspace_id = $1 AND post_id = $2 \
             ORDER BY created_at ASC, id ASC OFFSET $3 LIMIT $4"
        ))
        .bind(workspace_id)
        .bind(post_id)
        .bind(offset)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_reply).collect()
    }

    pub async fn get_reply(
        &self,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> CoreResult<Option<BlackboardReplyRecord>> {
        sqlx::query(&format!(
            "SELECT {REPLY_COLS} FROM blackboard_replies \
             WHERE id = $1 AND post_id = $2 AND workspace_id = $3"
        ))
        .bind(reply_id)
        .bind(post_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_reply)
        .transpose()
    }

    pub async fn save_reply(
        &self,
        reply: BlackboardReplyRecord,
    ) -> CoreResult<BlackboardReplyRecord> {
        sqlx::query(&format!(
            "UPDATE blackboard_replies SET content=$4, metadata_json=$5, updated_at=$6 \
             WHERE id=$1 AND post_id=$2 AND workspace_id=$3 RETURNING {REPLY_COLS}"
        ))
        .bind(&reply.id)
        .bind(&reply.post_id)
        .bind(&reply.workspace_id)
        .bind(&reply.content)
        .bind(Json(&reply.metadata_json))
        .bind(reply.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_reply)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("blackboard reply update returned no row".into()))
    }

    pub async fn delete_reply(
        &self,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> CoreResult<bool> {
        let result = sqlx::query(
            "DELETE FROM blackboard_replies WHERE id = $1 AND post_id = $2 AND workspace_id = $3",
        )
        .bind(reply_id)
        .bind(post_id)
        .bind(workspace_id)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn create_file(
        &self,
        file: BlackboardFileRecord,
    ) -> CoreResult<BlackboardFileRecord> {
        sqlx::query(&format!(
            "INSERT INTO blackboard_files \
                (id, workspace_id, parent_path, name, is_directory, file_size, content_type, \
                 storage_key, uploader_type, uploader_id, uploader_name, checksum_sha256, \
                 mime_type_detected, created_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) \
             RETURNING {FILE_COLS}"
        ))
        .bind(&file.id)
        .bind(&file.workspace_id)
        .bind(&file.parent_path)
        .bind(&file.name)
        .bind(file.is_directory)
        .bind(file.file_size)
        .bind(&file.content_type)
        .bind(&file.storage_key)
        .bind(&file.uploader_type)
        .bind(&file.uploader_id)
        .bind(&file.uploader_name)
        .bind(&file.checksum_sha256)
        .bind(&file.mime_type_detected)
        .bind(file.created_at)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)
        .and_then(row_to_file)
    }

    pub async fn list_files(
        &self,
        workspace_id: &str,
        parent_path: &str,
    ) -> CoreResult<Vec<BlackboardFileRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {FILE_COLS} FROM blackboard_files \
             WHERE workspace_id = $1 AND parent_path = $2 \
             ORDER BY is_directory DESC, name ASC"
        ))
        .bind(workspace_id)
        .bind(parent_path)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_file).collect()
    }

    pub async fn find_file_by_path(
        &self,
        workspace_id: &str,
        parent_path: &str,
        name: &str,
    ) -> CoreResult<Option<BlackboardFileRecord>> {
        sqlx::query(&format!(
            "SELECT {FILE_COLS} FROM blackboard_files \
             WHERE workspace_id = $1 AND parent_path = $2 AND name = $3"
        ))
        .bind(workspace_id)
        .bind(parent_path)
        .bind(name)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_file)
        .transpose()
    }

    pub async fn get_file(
        &self,
        workspace_id: &str,
        file_id: &str,
    ) -> CoreResult<Option<BlackboardFileRecord>> {
        sqlx::query(&format!(
            "SELECT {FILE_COLS} FROM blackboard_files WHERE id = $1 AND workspace_id = $2"
        ))
        .bind(file_id)
        .bind(workspace_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_file)
        .transpose()
    }

    pub async fn find_file_descendants(
        &self,
        workspace_id: &str,
        path_prefix: &str,
    ) -> CoreResult<Vec<BlackboardFileRecord>> {
        let rows = sqlx::query(&format!(
            "SELECT {FILE_COLS} FROM blackboard_files \
             WHERE workspace_id = $1 AND parent_path LIKE $2 \
             ORDER BY parent_path ASC, is_directory DESC, name ASC"
        ))
        .bind(workspace_id)
        .bind(format!("{path_prefix}%"))
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_file).collect()
    }

    pub async fn save_file(&self, file: BlackboardFileRecord) -> CoreResult<BlackboardFileRecord> {
        sqlx::query(&format!(
            "UPDATE blackboard_files SET parent_path=$3, name=$4, is_directory=$5, \
                 file_size=$6, content_type=$7, storage_key=$8, uploader_type=$9, \
                 uploader_id=$10, uploader_name=$11, checksum_sha256=$12, \
                 mime_type_detected=$13 \
             WHERE id=$1 AND workspace_id=$2 RETURNING {FILE_COLS}"
        ))
        .bind(&file.id)
        .bind(&file.workspace_id)
        .bind(&file.parent_path)
        .bind(&file.name)
        .bind(file.is_directory)
        .bind(file.file_size)
        .bind(&file.content_type)
        .bind(&file.storage_key)
        .bind(&file.uploader_type)
        .bind(&file.uploader_id)
        .bind(&file.uploader_name)
        .bind(&file.checksum_sha256)
        .bind(&file.mime_type_detected)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_file)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("blackboard file update returned no row".into()))
    }

    pub async fn bulk_update_file_parent_path(
        &self,
        workspace_id: &str,
        old_prefix: &str,
        new_prefix: &str,
    ) -> CoreResult<u64> {
        let result = sqlx::query(
            "UPDATE blackboard_files \
             SET parent_path = CASE \
                 WHEN parent_path = $2 THEN $3 \
                 ELSE concat($3, substr(parent_path, $4)) \
             END \
             WHERE workspace_id = $1 AND (parent_path = $2 OR parent_path LIKE $5)",
        )
        .bind(workspace_id)
        .bind(old_prefix)
        .bind(new_prefix)
        .bind((old_prefix.len() + 1) as i32)
        .bind(format!("{old_prefix}%"))
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(result.rows_affected())
    }

    pub async fn delete_file(&self, workspace_id: &str, file_id: &str) -> CoreResult<bool> {
        let result =
            sqlx::query("DELETE FROM blackboard_files WHERE id = $1 AND workspace_id = $2")
                .bind(file_id)
                .bind(workspace_id)
                .execute(&self.pool)
                .await
                .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

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

    pub async fn enqueue_plan_outbox(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxRecord> {
        sqlx::query(&format!(
            "INSERT INTO workspace_plan_outbox \
                (id, plan_id, workspace_id, event_type, payload_json, status, attempt_count, \
                 max_attempts, lease_owner, lease_expires_at, last_error, next_attempt_at, \
                 processed_at, metadata_json, created_at, updated_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) \
             RETURNING {PLAN_OUTBOX_COLS}"
        ))
        .bind(&item.id)
        .bind(&item.plan_id)
        .bind(&item.workspace_id)
        .bind(&item.event_type)
        .bind(Json(&item.payload_json))
        .bind(&item.status)
        .bind(item.attempt_count)
        .bind(item.max_attempts)
        .bind(&item.lease_owner)
        .bind(item.lease_expires_at)
        .bind(&item.last_error)
        .bind(item.next_attempt_at)
        .bind(item.processed_at)
        .bind(Json(&item.metadata_json))
        .bind(item.created_at)
        .bind(item.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan_outbox)
        .transpose()?
        .ok_or_else(|| CoreError::Storage("workspace plan outbox insert returned no row".into()))
    }

    pub async fn list_plan_outbox(
        &self,
        plan_id: &str,
        limit: i64,
    ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>> {
        if limit <= 0 {
            return Ok(Vec::new());
        }
        let rows = sqlx::query(&format!(
            "SELECT {PLAN_OUTBOX_COLS} FROM workspace_plan_outbox \
             WHERE plan_id = $1 ORDER BY created_at DESC, id DESC LIMIT $2"
        ))
        .bind(plan_id)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_plan_outbox).collect()
    }

    pub async fn get_plan_outbox(
        &self,
        outbox_id: &str,
    ) -> CoreResult<Option<WorkspacePlanOutboxRecord>> {
        sqlx::query(&format!(
            "SELECT {PLAN_OUTBOX_COLS} FROM workspace_plan_outbox WHERE id = $1"
        ))
        .bind(outbox_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan_outbox)
        .transpose()
    }

    pub async fn claim_due_plan_outbox(
        &self,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>> {
        if limit <= 0 {
            return Ok(Vec::new());
        }
        let lease_expires_at = add_seconds(now, lease_seconds.max(1));
        let rows = sqlx::query(&format!(
            "WITH due AS ( \
                 SELECT id FROM workspace_plan_outbox \
                 WHERE attempt_count < max_attempts \
                   AND ( \
                     (status IN ('pending', 'failed') \
                      AND (next_attempt_at IS NULL OR next_attempt_at <= $1)) \
                     OR (status = 'processing' \
                         AND lease_expires_at IS NOT NULL \
                         AND lease_expires_at <= $1) \
                   ) \
                 ORDER BY created_at ASC, id ASC \
                 LIMIT $2 \
                 FOR UPDATE SKIP LOCKED \
             ) \
             UPDATE workspace_plan_outbox AS outbox \
             SET status = 'processing', \
                 attempt_count = outbox.attempt_count + 1, \
                 lease_owner = $3, \
                 lease_expires_at = $4, \
                 next_attempt_at = NULL, \
                 last_error = NULL, \
                 updated_at = $1 \
             FROM due \
             WHERE outbox.id = due.id \
             RETURNING {PLAN_OUTBOX_COLS}"
        ))
        .bind(now)
        .bind(limit)
        .bind(lease_owner)
        .bind(lease_expires_at)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter().map(row_to_plan_outbox).collect()
    }

    pub async fn mark_plan_outbox_completed(
        &self,
        outbox_id: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut query = format!(
            "UPDATE workspace_plan_outbox \
             SET status = 'completed', lease_owner = NULL, lease_expires_at = NULL, \
                 last_error = NULL, next_attempt_at = NULL, processed_at = $2, updated_at = $2 \
             WHERE id = $1 AND status = 'processing'"
        );
        if lease_owner.is_some() {
            query.push_str(" AND lease_owner = $3");
        }
        let mut query = sqlx::query(&query).bind(outbox_id).bind(now);
        if let Some(owner) = lease_owner {
            query = query.bind(owner);
        }
        let result = query.execute(&self.pool).await.map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn mark_plan_outbox_failed(
        &self,
        outbox_id: &str,
        error_message: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let Some(item) = self.get_plan_outbox(outbox_id).await? else {
            return Ok(false);
        };
        if item.status != "processing" {
            return Ok(false);
        }
        if lease_owner.is_some() && item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        let (next_status, next_attempt_at) = if item.attempt_count >= item.max_attempts {
            ("dead_letter", None)
        } else {
            let exponent = item.attempt_count.clamp(0, 9) as u32;
            let backoff_seconds = (1_i64 << exponent).min(300);
            ("failed", Some(add_seconds(now, backoff_seconds)))
        };
        let mut query = String::from(
            "UPDATE workspace_plan_outbox \
             SET status = $2, lease_owner = NULL, lease_expires_at = NULL, \
                 last_error = $3, next_attempt_at = $4, updated_at = $5 \
             WHERE id = $1 AND status = 'processing'",
        );
        if lease_owner.is_some() {
            query.push_str(" AND lease_owner = $6");
        }
        let mut query = sqlx::query(&query)
            .bind(outbox_id)
            .bind(next_status)
            .bind(error_message)
            .bind(next_attempt_at)
            .bind(now);
        if let Some(owner) = lease_owner {
            query = query.bind(owner);
        }
        let result = query.execute(&self.pool).await.map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn release_plan_outbox_processing(
        &self,
        outbox_id: &str,
        error_message: Option<&str>,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut query = String::from(
            "UPDATE workspace_plan_outbox \
             SET status = 'pending', lease_owner = NULL, lease_expires_at = NULL, \
                 last_error = $2, next_attempt_at = NULL, \
                 attempt_count = GREATEST(attempt_count - 1, 0), updated_at = $3 \
             WHERE id = $1 AND status = 'processing'",
        );
        if lease_owner.is_some() {
            query.push_str(" AND lease_owner = $4");
        }
        let mut query = sqlx::query(&query)
            .bind(outbox_id)
            .bind(error_message)
            .bind(now);
        if let Some(owner) = lease_owner {
            query = query.bind(owner);
        }
        let result = query.execute(&self.pool).await.map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn renew_plan_outbox_lease(
        &self,
        outbox_id: &str,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let lease_expires_at = add_seconds(now, lease_seconds.max(1));
        let result = sqlx::query(
            "UPDATE workspace_plan_outbox \
             SET lease_expires_at = $3, updated_at = $4 \
             WHERE id = $1 AND status = 'processing' AND lease_owner = $2",
        )
        .bind(outbox_id)
        .bind(lease_owner)
        .bind(lease_expires_at)
        .bind(now)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn retry_plan_outbox_now(
        &self,
        outbox_id: &str,
        workspace_id: &str,
        actor_id: Option<&str>,
        reason: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<WorkspacePlanOutboxRecord>> {
        let Some(item) = self.get_plan_outbox(outbox_id).await? else {
            return Ok(None);
        };
        if item.workspace_id != workspace_id {
            return Ok(None);
        }
        let delayed_pending = item.status == "pending"
            && item
                .next_attempt_at
                .map(|next_attempt_at| next_attempt_at > now)
                .unwrap_or(false);
        if !matches!(item.status.as_str(), "failed" | "dead_letter") && !delayed_pending {
            return Err(CoreError::Storage(format!(
                "workspace plan outbox item {outbox_id} is not retryable from {}",
                item.status
            )));
        }

        let previous_status = item.status.clone();
        let previous_error = item.last_error.clone();
        let previous_next_attempt_at = item.next_attempt_at.map(|value| value.to_rfc3339());
        let mut metadata = match item.metadata_json {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        metadata.insert(
            "operator_retry".to_string(),
            json!({
                "actor_id": actor_id,
                "reason": reason,
                "retried_at": now.to_rfc3339(),
                "previous_status": previous_status,
                "previous_error": previous_error,
                "previous_next_attempt_at": previous_next_attempt_at,
            }),
        );
        let attempt_count = if previous_status == "dead_letter" {
            0
        } else {
            item.attempt_count
        };
        sqlx::query(&format!(
            "UPDATE workspace_plan_outbox \
             SET status = 'pending', attempt_count = $2, lease_owner = NULL, \
                 lease_expires_at = NULL, last_error = NULL, next_attempt_at = NULL, \
                 processed_at = NULL, metadata_json = $3, updated_at = $4 \
             WHERE id = $1 \
             RETURNING {PLAN_OUTBOX_COLS}"
        ))
        .bind(outbox_id)
        .bind(attempt_count)
        .bind(Json(Value::Object(metadata)))
        .bind(now)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(row_to_plan_outbox)
        .transpose()
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

fn row_to_workspace(row: PgRow) -> CoreResult<WorkspaceRecord> {
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

fn row_to_task(row: PgRow) -> CoreResult<WorkspaceTaskRecord> {
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

fn qualified_cols(alias: &str, cols: &str) -> String {
    cols.split(", ")
        .map(|col| format!("{alias}.{col}"))
        .collect::<Vec<_>>()
        .join(", ")
}

fn row_to_task_session_attempt(row: PgRow) -> CoreResult<WorkspaceTaskSessionAttemptRecord> {
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

fn row_to_pipeline_run(row: PgRow) -> CoreResult<WorkspacePipelineRunRecord> {
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

fn row_to_pipeline_stage_run(row: PgRow) -> CoreResult<WorkspacePipelineStageRunRecord> {
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

fn row_to_node(row: PgRow) -> CoreResult<TopologyNodeRecord> {
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

fn row_to_edge(row: PgRow) -> CoreResult<TopologyEdgeRecord> {
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

fn row_to_post(row: PgRow) -> CoreResult<BlackboardPostRecord> {
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

fn row_to_reply(row: PgRow) -> CoreResult<BlackboardReplyRecord> {
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

fn row_to_file(row: PgRow) -> CoreResult<BlackboardFileRecord> {
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

fn row_to_plan(row: PgRow) -> CoreResult<WorkspacePlanRecord> {
    Ok(WorkspacePlanRecord {
        id: row.try_get("id").map_err(storage)?,
        workspace_id: row.try_get("workspace_id").map_err(storage)?,
        goal_id: row.try_get("goal_id").map_err(storage)?,
        status: row.try_get("status").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

fn row_to_plan_node(row: PgRow) -> CoreResult<WorkspacePlanNodeRecord> {
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

fn row_to_plan_blackboard_entry(row: PgRow) -> CoreResult<WorkspacePlanBlackboardEntryRecord> {
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

fn row_to_plan_event(row: PgRow) -> CoreResult<WorkspacePlanEventRecord> {
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

fn row_to_plan_outbox(row: PgRow) -> CoreResult<WorkspacePlanOutboxRecord> {
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

fn add_seconds(value: DateTime<Utc>, seconds: i64) -> DateTime<Utc> {
    DateTime::<Utc>::from_timestamp(
        value.timestamp().saturating_add(seconds),
        value.timestamp_subsec_nanos(),
    )
    .unwrap_or(value)
}

fn storage(e: impl std::fmt::Display) -> CoreError {
    CoreError::Storage(e.to_string())
}
