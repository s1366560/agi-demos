//! Shared-DB repository for the P6 workspace foundation.
//!
//! The Python backend owns these tables (`workspaces`, `workspace_tasks`,
//! `topology_*`, `blackboard_*`). Rust writes the same rows during strangler
//! cutover and keeps SQLx strictly in this server-only adapter crate.

use serde_json::Value;
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

fn json_value(row: &PgRow, name: &str) -> CoreResult<Value> {
    let Json(value): Json<Value> = row.try_get(name).map_err(storage)?;
    Ok(value)
}

fn json_vec_string(row: &PgRow, name: &str) -> CoreResult<Vec<String>> {
    let Json(value): Json<Vec<String>> = row.try_get(name).map_err(storage)?;
    Ok(value)
}

fn storage(e: impl std::fmt::Display) -> CoreError {
    CoreError::Storage(e.to_string())
}
