//! Stages an empty Workspace snapshot so Desktop Core can start without copying
//! retired local workspace or message history into its database.

use std::path::{Path, PathBuf};

use serde::Serialize;
use sha2::{Digest as _, Sha256};
use tokio::io::AsyncWriteExt as _;
use uuid::Uuid;

use crate::private_file_permissions::set_private_file_permissions;

const SNAPSHOT_SCHEMA_VERSION: u16 = 1;
const SNAPSHOT_FILE_PREFIX: &str = "legacy-workspace-import-v1";
const SNAPSHOT_SOURCE: &str = "desktop-session-store";

/// Tables that used to hold Desktop workspace history. Retirement deletes them.
/// They stay named here so production runtime code does not treat them as a source.
pub(crate) const LEGACY_WORKSPACE_HISTORY_TABLES: &[&str] =
    &["desktop_workspace_messages", "desktop_workspaces"];

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct EmptyWorkspaceSnapshot {
    schema_version: u16,
    source: &'static str,
    workspace_count: usize,
    message_count: usize,
    workspaces: Vec<()>,
    messages: Vec<()>,
}

#[derive(Debug, Clone)]
pub(crate) struct StagedLegacyWorkspaceSnapshot {
    pub(crate) path: PathBuf,
    pub(crate) sha256: String,
}

pub(crate) async fn stage_empty_workspace_history_snapshot(
    runtime_directory: &Path,
) -> Result<StagedLegacyWorkspaceSnapshot, String> {
    let snapshot = EmptyWorkspaceSnapshot {
        schema_version: SNAPSHOT_SCHEMA_VERSION,
        source: SNAPSHOT_SOURCE,
        workspace_count: 0,
        message_count: 0,
        workspaces: Vec::new(),
        messages: Vec::new(),
    };
    let encoded = serde_json::to_vec(&snapshot)
        .map_err(|error| format!("failed to encode empty Workspace snapshot: {error}"))?;
    let sha256 = hex_sha256(&encoded);
    let path = runtime_directory.join(format!("{SNAPSHOT_FILE_PREFIX}-{sha256}.json"));
    if path.is_file() {
        let existing = tokio::fs::read(&path)
            .await
            .map_err(|error| format!("failed to read empty Workspace snapshot: {error}"))?;
        if hex_sha256(&existing) != sha256 {
            return Err("empty Workspace snapshot hash conflict".to_string());
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
            .map_err(|error| format!("failed to stage empty Workspace snapshot: {error}"))?;
        file.write_all(&encoded)
            .await
            .map_err(|error| format!("failed to persist empty Workspace snapshot: {error}"))?;
        file.flush()
            .await
            .map_err(|error| format!("failed to flush empty Workspace snapshot: {error}"))?;
        file.sync_all()
            .await
            .map_err(|error| format!("failed to sync empty Workspace snapshot: {error}"))?;
        drop(file);
        set_private_file_permissions(&temporary)
            .map_err(|error| format!("failed to secure empty Workspace snapshot: {error}"))?;
        tokio::fs::rename(&temporary, &path)
            .await
            .map_err(|error| format!("failed to publish empty Workspace snapshot: {error}"))?;
        Ok::<(), String>(())
    }
    .await;
    if result.is_err() {
        let _ = tokio::fs::remove_file(&temporary).await;
    }
    result?;
    Ok(StagedLegacyWorkspaceSnapshot { path, sha256 })
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
    fn empty_snapshot_declares_no_workspaces_or_messages() {
        let encoded = serde_json::to_vec(&EmptyWorkspaceSnapshot {
            schema_version: SNAPSHOT_SCHEMA_VERSION,
            source: SNAPSHOT_SOURCE,
            workspace_count: 0,
            message_count: 0,
            workspaces: Vec::new(),
            messages: Vec::new(),
        })
        .expect("encode");
        let value: serde_json::Value = serde_json::from_slice(&encoded).expect("json");
        assert_eq!(value["schemaVersion"], 1);
        assert_eq!(value["source"], "desktop-session-store");
        assert_eq!(value["workspaceCount"], 0);
        assert_eq!(value["messageCount"], 0);
        assert_eq!(value["workspaces"], serde_json::json!([]));
        assert_eq!(value["messages"], serde_json::json!([]));
    }

    #[tokio::test]
    async fn staging_writes_the_same_empty_snapshot_twice() {
        let directory =
            std::env::temp_dir().join(format!("agistack-empty-workspace-{}", Uuid::new_v4()));
        tokio::fs::create_dir(&directory).await.expect("dir");
        let first = stage_empty_workspace_history_snapshot(&directory)
            .await
            .expect("first");
        let second = stage_empty_workspace_history_snapshot(&directory)
            .await
            .expect("second");
        assert_eq!(first.sha256, second.sha256);
        assert_eq!(first.path, second.path);
        let _ = tokio::fs::remove_dir_all(&directory).await;
    }
}
