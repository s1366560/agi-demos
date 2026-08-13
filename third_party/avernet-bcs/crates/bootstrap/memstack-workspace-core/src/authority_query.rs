//! Batched private Workspace authority reads for platform compatibility surfaces.

use std::collections::{BTreeSet, HashSet};
use std::sync::Arc;

use axum::{Extension, Json};
use bcs_db_api::{DbRow, DbStatementBuilder};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::{ApiError, WorkspaceCoreState};

const MAX_AUTHORITY_WORKSPACES: usize = 500;
const MAX_AUTHORITY_TASK_REFS: usize = 1_000;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AuthorityQueryRequest {
    actor: AuthorityActor,
    workspace_ids: Vec<String>,
    #[serde(default)]
    task_refs: Vec<AuthorityTaskRef>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AuthorityActor {
    user_id: String,
    #[serde(default)]
    is_superuser: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq, Hash)]
#[serde(deny_unknown_fields)]
struct AuthorityTaskRef {
    workspace_id: String,
    task_id: String,
}

#[derive(Debug, Serialize)]
pub(super) struct AuthorityQueryResponse {
    profiles: Vec<AuthorityProfile>,
    task_links: Vec<AuthorityTaskLink>,
}

#[derive(Debug, Serialize)]
struct AuthorityProfile {
    workspace_id: String,
    tenant_id: String,
    project_id: String,
    name: String,
    created_by: String,
    is_archived: bool,
    metadata: Value,
    member_role: Option<String>,
}

#[derive(Debug, Serialize)]
struct AuthorityTaskLink {
    workspace_id: String,
    task_id: String,
    linked: bool,
}

pub(super) async fn query_workspace_authority(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Json(request): Json<AuthorityQueryRequest>,
) -> Result<Json<AuthorityQueryResponse>, ApiError> {
    let workspace_ids = normalized_values(
        request.workspace_ids,
        MAX_AUTHORITY_WORKSPACES,
        "workspace_ids",
    )?;
    let task_refs = normalized_task_refs(request.task_refs)?;
    let actor_id = normalized_value(request.actor.user_id, "actor.user_id")?;
    let profiles = if workspace_ids.is_empty() {
        Vec::new()
    } else {
        query_profiles(
            state.as_ref(),
            actor_id.as_str(),
            request.actor.is_superuser,
            workspace_ids.as_slice(),
        )
        .await?
    };
    let accessible = profiles
        .iter()
        .map(|profile| profile.workspace_id.as_str())
        .collect::<HashSet<_>>();
    let existing_tasks = if task_refs.is_empty() || accessible.is_empty() {
        HashSet::new()
    } else {
        query_task_links(state.as_ref(), task_refs.as_slice(), &accessible).await?
    };
    let task_links = task_refs
        .into_iter()
        .map(|task_ref| AuthorityTaskLink {
            linked: existing_tasks
                .contains(&(task_ref.workspace_id.clone(), task_ref.task_id.clone())),
            workspace_id: task_ref.workspace_id,
            task_id: task_ref.task_id,
        })
        .collect();
    Ok(Json(AuthorityQueryResponse {
        profiles,
        task_links,
    }))
}

async fn query_profiles(
    state: &WorkspaceCoreState,
    actor_id: &str,
    is_superuser: bool,
    workspace_ids: &[String],
) -> Result<Vec<AuthorityProfile>, ApiError> {
    let mut statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static(
            "SELECT p.workspace_id, p.tenant_id, p.project_id, p.name, p.created_by, \
             p.is_archived, p.metadata_json, m.role AS member_role \
             FROM workspace_profiles p LEFT JOIN workspace_members m \
               ON m.tenant_id = p.tenant_id AND m.project_id = p.project_id \
              AND m.workspace_id = p.workspace_id AND m.user_id = ",
        )
        .bind(actor_id)
        .push_static(" WHERE p.deleted_at IS NULL AND p.workspace_id IN (");
    for (index, workspace_id) in workspace_ids.iter().enumerate() {
        if index > 0 {
            statement = statement.push_static(", ");
        }
        statement = statement.bind(workspace_id.as_str());
    }
    statement = statement.push_static(")");
    if !is_superuser {
        statement = statement.push_static(" AND m.user_id IS NOT NULL");
    }
    statement = statement.push_static(" ORDER BY p.workspace_id");
    let rows = state
        .db
        .query(statement.build())
        .await
        .map_err(ApiError::Database)?;
    rows.iter().map(profile_from_row).collect()
}

async fn query_task_links(
    state: &WorkspaceCoreState,
    task_refs: &[AuthorityTaskRef],
    accessible: &HashSet<&str>,
) -> Result<HashSet<(String, String)>, ApiError> {
    let workspace_ids = task_refs
        .iter()
        .filter(|task_ref| accessible.contains(task_ref.workspace_id.as_str()))
        .map(|task_ref| task_ref.workspace_id.as_str())
        .collect::<BTreeSet<_>>();
    let task_ids = task_refs
        .iter()
        .map(|task_ref| task_ref.task_id.as_str())
        .collect::<BTreeSet<_>>();
    if workspace_ids.is_empty() || task_ids.is_empty() {
        return Ok(HashSet::new());
    }
    let mut statement = DbStatementBuilder::new(state.sql_flavor)
        .push_static("SELECT workspace_id, task_id FROM workspace_tasks WHERE workspace_id IN (");
    for (index, workspace_id) in workspace_ids.iter().enumerate() {
        if index > 0 {
            statement = statement.push_static(", ");
        }
        statement = statement.bind(*workspace_id);
    }
    statement = statement.push_static(") AND task_id IN (");
    for (index, task_id) in task_ids.iter().enumerate() {
        if index > 0 {
            statement = statement.push_static(", ");
        }
        statement = statement.bind(*task_id);
    }
    let rows = state
        .db
        .query(statement.push_static(")").build())
        .await
        .map_err(ApiError::Database)?;
    rows.iter()
        .map(|row| {
            Ok((
                required_string(row, "workspace_id")?,
                required_string(row, "task_id")?,
            ))
        })
        .collect()
}

fn profile_from_row(row: &DbRow) -> Result<AuthorityProfile, ApiError> {
    let metadata_json = required_string(row, "metadata_json")?;
    let metadata: Value = serde_json::from_str(&metadata_json).map_err(ApiError::Json)?;
    if !metadata.is_object() {
        return Err(ApiError::InvalidDatabase(
            "metadata_json is not a JSON object".to_string(),
        ));
    }
    Ok(AuthorityProfile {
        workspace_id: required_string(row, "workspace_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        name: required_string(row, "name")?,
        created_by: required_string(row, "created_by")?,
        is_archived: row
            .get_bool("is_archived")
            .map_err(ApiError::Database)?
            .ok_or_else(|| ApiError::InvalidDatabase("is_archived is missing".to_string()))?,
        metadata,
        member_role: row.get_string("member_role").map_err(ApiError::Database)?,
    })
}

fn required_string(row: &DbRow, column: &str) -> Result<String, ApiError> {
    row.get_string(column)
        .map_err(ApiError::Database)?
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| ApiError::InvalidDatabase(format!("{column} is missing")))
}

fn normalized_values(
    values: Vec<String>,
    limit: usize,
    field: &'static str,
) -> Result<Vec<String>, ApiError> {
    if values.len() > limit {
        return Err(ApiError::InvalidRequest(format!(
            "{field} exceeds the maximum of {limit} items"
        )));
    }
    values
        .into_iter()
        .map(|value| normalized_value(value, field))
        .collect::<Result<BTreeSet<_>, _>>()
        .map(|values| values.into_iter().collect())
}

fn normalized_task_refs(
    task_refs: Vec<AuthorityTaskRef>,
) -> Result<Vec<AuthorityTaskRef>, ApiError> {
    if task_refs.len() > MAX_AUTHORITY_TASK_REFS {
        return Err(ApiError::InvalidRequest(format!(
            "task_refs exceeds the maximum of {MAX_AUTHORITY_TASK_REFS} items"
        )));
    }
    let mut normalized = Vec::with_capacity(task_refs.len());
    for task_ref in task_refs {
        normalized.push(AuthorityTaskRef {
            workspace_id: normalized_value(task_ref.workspace_id, "task_refs.workspace_id")?,
            task_id: normalized_value(task_ref.task_id, "task_refs.task_id")?,
        });
    }
    normalized.sort_by(|left, right| {
        (&left.workspace_id, &left.task_id).cmp(&(&right.workspace_id, &right.task_id))
    });
    normalized.dedup();
    Ok(normalized)
}

fn normalized_value(value: String, field: &'static str) -> Result<String, ApiError> {
    let value = value.trim();
    if value.is_empty() {
        return Err(ApiError::InvalidRequest(format!(
            "{field} must not be blank"
        )));
    }
    Ok(value.to_string())
}
