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

#[derive(Clone, Debug, PartialEq)]
struct DesktopLegacyWorkspaceRow {
    id: String,
    project_id: String,
    value: Value,
}

#[derive(Clone, Debug, PartialEq)]
struct DesktopLegacyWorkspaceMessageRow {
    id: String,
    workspace_id: String,
    position: i64,
    value: Value,
}

#[derive(Debug, Clone)]
pub(crate) struct StagedLegacyWorkspaceSnapshot {
    pub(crate) path: PathBuf,
    pub(crate) sha256: String,
}

pub(crate) async fn stage_legacy_workspace_snapshot(
    runtime: &LocalRuntimeService,
    runtime_directory: &Path,
) -> Result<StagedLegacyWorkspaceSnapshot, String> {
    let (workspace_rows, message_rows) =
        runtime.with_offline_workspace_import_connection(read_legacy_workspace_rows)?;
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

fn read_legacy_workspace_rows(
    connection: &rusqlite::Connection,
) -> Result<
    (
        Vec<DesktopLegacyWorkspaceRow>,
        Vec<DesktopLegacyWorkspaceMessageRow>,
    ),
    String,
> {
    if !legacy_table_exists(connection, "desktop_workspaces")?
        && !legacy_table_exists(connection, "desktop_workspace_messages")?
    {
        return Ok((Vec::new(), Vec::new()));
    }
    if !legacy_table_exists(connection, "desktop_workspaces")?
        || !legacy_table_exists(connection, "desktop_workspace_messages")?
    {
        return Err("legacy Workspace SQLite schema is incomplete".to_string());
    }
    let workspaces = {
        let mut statement = connection
            .prepare("SELECT id, project_id, value_json FROM desktop_workspaces ORDER BY rowid ASC")
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            })
            .map_err(|error| error.to_string())?
            .map(|row| {
                let (id, project_id, raw) = row.map_err(|error| error.to_string())?;
                let value = serde_json::from_str(&raw).map_err(|error| error.to_string())?;
                Ok(DesktopLegacyWorkspaceRow {
                    id,
                    project_id,
                    value,
                })
            })
            .collect::<Result<Vec<_>, String>>()?;
        rows
    };
    let messages = {
        let mut statement = connection
            .prepare(
                "SELECT id, workspace_id, position, value_json \
                 FROM desktop_workspace_messages ORDER BY workspace_id ASC, position ASC",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, String>(3)?,
                ))
            })
            .map_err(|error| error.to_string())?
            .map(|row| {
                let (id, workspace_id, position, raw) = row.map_err(|error| error.to_string())?;
                let value = serde_json::from_str(&raw).map_err(|error| error.to_string())?;
                Ok(DesktopLegacyWorkspaceMessageRow {
                    id,
                    workspace_id,
                    position,
                    value,
                })
            })
            .collect::<Result<Vec<_>, String>>()?;
        rows
    };
    Ok((workspaces, messages))
}

fn legacy_table_exists(connection: &rusqlite::Connection, name: &str) -> Result<bool, String> {
    connection
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1)",
            [name],
            |row| row.get(0),
        )
        .map_err(|error| error.to_string())
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
    fn legacy_reader_returns_empty_without_legacy_tables() {
        let connection = rusqlite::Connection::open_in_memory().expect("database");

        assert_eq!(
            read_legacy_workspace_rows(&connection).expect("empty legacy snapshot"),
            (Vec::new(), Vec::new())
        );
    }

    #[test]
    fn legacy_reader_rejects_partial_schema() {
        let connection = rusqlite::Connection::open_in_memory().expect("database");
        connection
            .execute_batch(
                "CREATE TABLE desktop_workspaces (
                   id TEXT PRIMARY KEY,
                   project_id TEXT NOT NULL,
                   value_json TEXT NOT NULL
                 );",
            )
            .expect("partial legacy schema");

        assert_eq!(
            read_legacy_workspace_rows(&connection).expect_err("partial schema must fail"),
            "legacy Workspace SQLite schema is incomplete"
        );
    }

    #[test]
    fn legacy_reader_is_the_only_sqlite_workspace_table_reader() {
        let connection = rusqlite::Connection::open_in_memory().expect("database");
        connection
            .execute_batch(
                "CREATE TABLE desktop_workspaces (
                   id TEXT PRIMARY KEY,
                   project_id TEXT NOT NULL,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE desktop_workspace_messages (
                   id TEXT PRIMARY KEY,
                   workspace_id TEXT NOT NULL,
                   position INTEGER NOT NULL,
                   value_json TEXT NOT NULL,
                   UNIQUE(workspace_id, position)
                 );",
            )
            .expect("legacy schema");
        let workspace = serde_json::json!({
            "id": "workspace-1",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
        });
        let message = serde_json::json!({
            "id": "message-1",
            "workspace_id": "workspace-1",
            "content": "hello",
        });
        connection
            .execute(
                "INSERT INTO desktop_workspaces(id, project_id, value_json) VALUES (?1, ?2, ?3)",
                rusqlite::params!["workspace-1", "project-1", workspace.to_string()],
            )
            .expect("workspace");
        connection
            .execute(
                "INSERT INTO desktop_workspace_messages(id, workspace_id, position, value_json)
                 VALUES (?1, ?2, ?3, ?4)",
                rusqlite::params!["message-1", "workspace-1", 1, message.to_string()],
            )
            .expect("message");

        let (workspaces, messages) =
            read_legacy_workspace_rows(&connection).expect("legacy snapshot");
        assert_eq!(workspaces[0].value, workspace);
        assert_eq!(messages[0].value, message);
    }

    #[test]
    fn source_hash_is_independent_of_json_object_order() {
        let left = serde_json::json!({"a": 1, "b": {"x": true, "y": false}});
        let right = serde_json::json!({"b": {"y": false, "x": true}, "a": 1});

        assert_eq!(source_hash(&left), source_hash(&right));
    }
}
