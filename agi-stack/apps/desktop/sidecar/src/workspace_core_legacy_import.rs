//! Stages the immutable legacy Workspace snapshot consumed by the Desktop Core helper.

use std::collections::{BTreeMap, HashSet};
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest as _, Sha256};
use tokio::io::AsyncWriteExt as _;
use uuid::Uuid;

use crate::local_runtime::LocalRuntimeService;
use crate::private_file_permissions::set_private_file_permissions;

const SNAPSHOT_SCHEMA_VERSION: u16 = 1;
const SNAPSHOT_FILE_PREFIX: &str = "legacy-workspace-import-v1";

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LegacyWorkspaceSnapshot {
    schema_version: u16,
    source: &'static str,
    workspace_count: usize,
    message_count: usize,
    workspaces: Vec<LegacyWorkspaceRecord>,
    messages: Vec<LegacyWorkspaceMessageRecord>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LegacyWorkspaceRecord {
    id: String,
    project_id: String,
    value: Value,
    source_hash: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LegacyWorkspaceMessageRecord {
    id: String,
    workspace_id: String,
    position: i64,
    value: Value,
    source_hash: String,
}

pub(crate) struct StagedLegacyWorkspaceSnapshot {
    pub(crate) path: PathBuf,
    pub(crate) sha256: String,
}

pub(crate) async fn stage_legacy_workspace_snapshot(
    runtime: &LocalRuntimeService,
    runtime_directory: &Path,
) -> Result<StagedLegacyWorkspaceSnapshot, String> {
    let (workspace_rows, message_rows) = runtime.legacy_workspace_rows()?;
    let mut workspace_ids = HashSet::with_capacity(workspace_rows.len());
    let mut workspaces = Vec::with_capacity(workspace_rows.len());
    for row in workspace_rows {
        if !workspace_ids.insert(row.id.clone()) {
            return Err("legacy Workspace snapshot contains a duplicate workspace id".to_string());
        }
        let source_hash = source_hash(&serde_json::json!({
            "id": row.id,
            "project_id": row.project_id,
            "value": row.value,
        }))?;
        workspaces.push(LegacyWorkspaceRecord {
            id: row.id,
            project_id: row.project_id,
            value: row.value,
            source_hash,
        });
    }
    let mut message_ids = HashSet::with_capacity(message_rows.len());
    let mut message_positions = HashSet::with_capacity(message_rows.len());
    let mut messages = Vec::with_capacity(message_rows.len());
    for row in message_rows {
        if !message_ids.insert(row.id.clone())
            || !message_positions.insert((row.workspace_id.clone(), row.position))
        {
            return Err(
                "legacy Workspace snapshot contains duplicate message authority".to_string(),
            );
        }
        if !workspace_ids.contains(row.workspace_id.as_str()) {
            return Err("legacy Workspace message references a missing workspace".to_string());
        }
        let source_hash = source_hash(&serde_json::json!({
            "id": row.id,
            "workspace_id": row.workspace_id,
            "position": row.position,
            "value": row.value,
        }))?;
        messages.push(LegacyWorkspaceMessageRecord {
            id: row.id,
            workspace_id: row.workspace_id,
            position: row.position,
            value: row.value,
            source_hash,
        });
    }
    let snapshot = LegacyWorkspaceSnapshot {
        schema_version: SNAPSHOT_SCHEMA_VERSION,
        source: "desktop-session-store",
        workspace_count: workspaces.len(),
        message_count: messages.len(),
        workspaces,
        messages,
    };
    let encoded = serde_json::to_vec(&snapshot)
        .map_err(|error| format!("failed to encode legacy Workspace snapshot: {error}"))?;
    let sha256 = hex_sha256(&encoded);
    let path = runtime_directory.join(format!("{SNAPSHOT_FILE_PREFIX}-{sha256}.json"));
    if path.is_file() {
        let existing = tokio::fs::read(&path)
            .await
            .map_err(|error| format!("failed to read staged legacy Workspace snapshot: {error}"))?;
        if hex_sha256(&existing) != sha256 {
            return Err("staged legacy Workspace snapshot hash conflict".to_string());
        }
        return Ok(StagedLegacyWorkspaceSnapshot { path, sha256 });
    }
    let temporary =
        runtime_directory.join(format!(".{SNAPSHOT_FILE_PREFIX}.{}.tmp", Uuid::new_v4()));
    let result = async {
        let mut options = tokio::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            options.mode(0o600);
        }
        let mut file = options
            .open(&temporary)
            .await
            .map_err(|error| format!("failed to stage legacy Workspace snapshot: {error}"))?;
        file.write_all(&encoded)
            .await
            .map_err(|error| format!("failed to persist legacy Workspace snapshot: {error}"))?;
        file.flush()
            .await
            .map_err(|error| format!("failed to flush legacy Workspace snapshot: {error}"))?;
        file.sync_all()
            .await
            .map_err(|error| format!("failed to sync legacy Workspace snapshot: {error}"))?;
        drop(file);
        set_private_file_permissions(&temporary)
            .map_err(|error| format!("failed to secure legacy Workspace snapshot: {error}"))?;
        tokio::fs::rename(&temporary, &path)
            .await
            .map_err(|error| format!("failed to publish legacy Workspace snapshot: {error}"))?;
        Ok::<(), String>(())
    }
    .await;
    if result.is_err() {
        let _ = tokio::fs::remove_file(&temporary).await;
    }
    result?;
    Ok(StagedLegacyWorkspaceSnapshot { path, sha256 })
}

fn source_hash(value: &Value) -> Result<String, String> {
    serde_json::to_vec(&canonical_json(value))
        .map(|encoded| hex_sha256(&encoded))
        .map_err(|error| format!("failed to hash legacy Workspace record: {error}"))
}

fn canonical_json(value: &Value) -> Value {
    match value {
        Value::Object(object) => Value::Object(
            object
                .iter()
                .map(|(key, value)| (key.clone(), canonical_json(value)))
                .collect::<BTreeMap<_, _>>()
                .into_iter()
                .collect(),
        ),
        Value::Array(values) => Value::Array(values.iter().map(canonical_json).collect()),
        _ => value.clone(),
    }
}

fn hex_sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_hash_is_independent_of_json_object_order() {
        let left = serde_json::json!({"a": 1, "b": {"x": true, "y": false}});
        let right = serde_json::json!({"b": {"y": false, "x": true}, "a": 1});

        assert_eq!(source_hash(&left), source_hash(&right));
    }
}
