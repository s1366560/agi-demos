//! Persists the irreversible Desktop Workspace Core authority transition.

use std::path::{Component, Path};

use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use tokio::io::AsyncWriteExt as _;
use uuid::Uuid;

use crate::private_file_permissions::set_private_file_permissions;
use crate::workspace_core_legacy_import::StagedLegacyWorkspaceSnapshot;

pub(crate) const CUTOVER_MARKER_FILE: &str = "workspace-core-cutover.v1.json";
const CUTOVER_MARKER_SCHEMA_VERSION: u16 = 1;
const MAX_MARKER_BYTES: usize = 16 * 1024;
const SNAPSHOT_FILE_PREFIX: &str = "legacy-workspace-import-v1";

#[derive(Debug, Clone, Copy, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum WorkspaceCoreCutoverState {
    LegacyOnly,
    Importing,
    CoreAuthoritative,
    CoreUnavailable,
}

impl WorkspaceCoreCutoverState {
    pub(crate) const fn is_cutover(self) -> bool {
        !matches!(self, Self::LegacyOnly)
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct WorkspaceCoreCutoverMarker {
    schema_version: u16,
    pub(crate) state: WorkspaceCoreCutoverState,
    snapshot_file: Option<String>,
    snapshot_sha256: Option<String>,
}

pub(crate) async fn load_cutover_marker(
    runtime_directory: &Path,
) -> Result<Option<WorkspaceCoreCutoverMarker>, String> {
    let path = runtime_directory.join(CUTOVER_MARKER_FILE);
    let metadata = match tokio::fs::symlink_metadata(&path).await {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(format!(
                "failed to inspect Workspace Core cutover marker: {error}"
            ))
        }
    };
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err("Workspace Core cutover marker must be a regular file".to_string());
    }
    let bytes = tokio::fs::read(&path)
        .await
        .map_err(|error| format!("failed to read Workspace Core cutover marker: {error}"))?;
    if bytes.is_empty() || bytes.len() > MAX_MARKER_BYTES {
        return Err("Workspace Core cutover marker is invalid".to_string());
    }
    let marker: WorkspaceCoreCutoverMarker = serde_json::from_slice(&bytes)
        .map_err(|_| "Workspace Core cutover marker is invalid".to_string())?;
    validate_marker(&marker)?;
    if marker.state.is_cutover() {
        staged_snapshot_from_marker(runtime_directory, &marker).await?;
    }
    Ok(Some(marker))
}

pub(crate) async fn persist_cutover_marker(
    runtime_directory: &Path,
    state: WorkspaceCoreCutoverState,
    snapshot: Option<&StagedLegacyWorkspaceSnapshot>,
) -> Result<(), String> {
    let snapshot_file = snapshot
        .and_then(|snapshot| snapshot.path.file_name())
        .and_then(|name| name.to_str())
        .map(ToString::to_string);
    let marker = WorkspaceCoreCutoverMarker {
        schema_version: CUTOVER_MARKER_SCHEMA_VERSION,
        state,
        snapshot_file,
        snapshot_sha256: snapshot.map(|snapshot| snapshot.sha256.clone()),
    };
    validate_marker(&marker)?;
    if state.is_cutover() {
        staged_snapshot_from_marker(runtime_directory, &marker).await?;
    }
    let encoded = serde_json::to_vec(&marker)
        .map_err(|error| format!("failed to encode Workspace Core cutover marker: {error}"))?;
    let path = runtime_directory.join(CUTOVER_MARKER_FILE);
    let temporary =
        runtime_directory.join(format!(".{CUTOVER_MARKER_FILE}.{}.tmp", Uuid::new_v4()));
    let result = async {
        let mut options = tokio::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        options.mode(0o600);
        let mut file = options
            .open(&temporary)
            .await
            .map_err(|error| format!("failed to create Workspace Core cutover marker: {error}"))?;
        file.write_all(&encoded)
            .await
            .map_err(|error| format!("failed to persist Workspace Core cutover marker: {error}"))?;
        file.flush()
            .await
            .map_err(|error| format!("failed to flush Workspace Core cutover marker: {error}"))?;
        file.sync_all()
            .await
            .map_err(|error| format!("failed to sync Workspace Core cutover marker: {error}"))?;
        drop(file);
        set_private_file_permissions(&temporary)
            .map_err(|error| format!("failed to secure Workspace Core cutover marker: {error}"))?;
        atomic_replace(&temporary, &path)
            .map_err(|error| format!("failed to publish Workspace Core cutover marker: {error}"))?;
        sync_directory(runtime_directory)
            .map_err(|error| format!("failed to sync Workspace Core cutover directory: {error}"))
    }
    .await;
    if result.is_err() {
        let _ = tokio::fs::remove_file(&temporary).await;
    }
    result
}

pub(crate) async fn staged_snapshot_from_marker(
    runtime_directory: &Path,
    marker: &WorkspaceCoreCutoverMarker,
) -> Result<StagedLegacyWorkspaceSnapshot, String> {
    let (Some(snapshot_file), Some(snapshot_sha256)) =
        (&marker.snapshot_file, &marker.snapshot_sha256)
    else {
        return Err("Workspace Core cutover snapshot identity is missing".to_string());
    };
    let expected_file = format!("{SNAPSHOT_FILE_PREFIX}-{snapshot_sha256}.json");
    if snapshot_file != &expected_file
        || Path::new(snapshot_file).components().count() != 1
        || !matches!(
            Path::new(snapshot_file).components().next(),
            Some(Component::Normal(_))
        )
    {
        return Err("Workspace Core cutover snapshot path is invalid".to_string());
    }
    let path = runtime_directory.join(snapshot_file);
    let metadata = tokio::fs::symlink_metadata(&path)
        .await
        .map_err(|_| "Workspace Core cutover snapshot is unavailable".to_string())?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err("Workspace Core cutover snapshot must be a regular file".to_string());
    }
    let bytes = tokio::fs::read(&path)
        .await
        .map_err(|_| "Workspace Core cutover snapshot is unavailable".to_string())?;
    if hex_sha256(&bytes) != *snapshot_sha256 {
        return Err("Workspace Core cutover snapshot hash does not match".to_string());
    }
    Ok(StagedLegacyWorkspaceSnapshot {
        path,
        sha256: snapshot_sha256.clone(),
    })
}

fn validate_marker(marker: &WorkspaceCoreCutoverMarker) -> Result<(), String> {
    if marker.schema_version != CUTOVER_MARKER_SCHEMA_VERSION {
        return Err("Workspace Core cutover marker schema is unsupported".to_string());
    }
    if marker.state == WorkspaceCoreCutoverState::LegacyOnly {
        if marker.snapshot_file.is_some() || marker.snapshot_sha256.is_some() {
            return Err(
                "legacy-only Workspace Core marker cannot reference a snapshot".to_string(),
            );
        }
        return Ok(());
    }
    let (Some(snapshot_file), Some(snapshot_sha256)) =
        (&marker.snapshot_file, &marker.snapshot_sha256)
    else {
        return Err("Workspace Core cutover snapshot identity is missing".to_string());
    };
    if snapshot_file.is_empty()
        || snapshot_sha256.len() != 64
        || !snapshot_sha256
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("Workspace Core cutover snapshot identity is invalid".to_string());
    }
    Ok(())
}

fn hex_sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[cfg(unix)]
fn atomic_replace(source: &Path, destination: &Path) -> std::io::Result<()> {
    std::fs::rename(source, destination)
}

#[cfg(windows)]
fn atomic_replace(source: &Path, destination: &Path) -> std::io::Result<()> {
    use std::{iter, os::windows::ffi::OsStrExt as _};

    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    let source = source
        .as_os_str()
        .encode_wide()
        .chain(iter::once(0))
        .collect::<Vec<_>>();
    let destination = destination
        .as_os_str()
        .encode_wide()
        .chain(iter::once(0))
        .collect::<Vec<_>>();
    // SAFETY: both vectors are live, NUL-terminated UTF-16 paths. The operation replaces one
    // same-volume private marker and requests metadata write-through.
    if unsafe {
        MoveFileExW(
            source.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    } == 0
    {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(not(any(unix, windows)))]
fn atomic_replace(_source: &Path, _destination: &Path) -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "Workspace Core cutover marker replacement is unsupported",
    ))
}

#[cfg(unix)]
fn sync_directory(directory: &Path) -> std::io::Result<()> {
    std::fs::File::open(directory)?.sync_all()
}

#[cfg(windows)]
fn sync_directory(_directory: &Path) -> std::io::Result<()> {
    Ok(())
}

#[cfg(not(any(unix, windows)))]
fn sync_directory(_directory: &Path) -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "Workspace Core cutover directory sync is unsupported",
    ))
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use sha2::{Digest as _, Sha256};
    use uuid::Uuid;

    use super::*;

    async fn snapshot(directory: &Path, bytes: &[u8]) -> StagedLegacyWorkspaceSnapshot {
        let sha256: String = Sha256::digest(bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        let path = directory.join(format!("legacy-workspace-import-v1-{sha256}.json"));
        tokio::fs::write(&path, bytes).await.expect("snapshot");
        StagedLegacyWorkspaceSnapshot { path, sha256 }
    }

    #[tokio::test]
    async fn cutover_marker_round_trips_all_states_and_reuses_snapshot_identity() {
        let directory = std::env::temp_dir().join(format!("workspace-cutover-{}", Uuid::new_v4()));
        tokio::fs::create_dir_all(&directory)
            .await
            .expect("directory");
        let staged = snapshot(&directory, br#"{"schemaVersion":1}"#).await;

        persist_cutover_marker(&directory, WorkspaceCoreCutoverState::LegacyOnly, None)
            .await
            .expect("legacy-only marker");
        assert_eq!(
            load_cutover_marker(&directory)
                .await
                .expect("load")
                .expect("marker")
                .state,
            WorkspaceCoreCutoverState::LegacyOnly
        );
        for state in [
            WorkspaceCoreCutoverState::Importing,
            WorkspaceCoreCutoverState::CoreAuthoritative,
            WorkspaceCoreCutoverState::CoreUnavailable,
        ] {
            persist_cutover_marker(&directory, state, Some(&staged))
                .await
                .expect("cutover marker");
            let marker = load_cutover_marker(&directory)
                .await
                .expect("load")
                .expect("marker");
            assert_eq!(marker.state, state);
            let reused = staged_snapshot_from_marker(&directory, &marker)
                .await
                .expect("reuse snapshot");
            assert_eq!(reused.path, staged.path);
            assert_eq!(reused.sha256, staged.sha256);
        }
    }

    #[tokio::test]
    async fn invalid_marker_snapshot_paths_and_hashes_fail_closed() {
        let directory = std::env::temp_dir().join(format!("workspace-cutover-{}", Uuid::new_v4()));
        tokio::fs::create_dir_all(&directory)
            .await
            .expect("directory");
        tokio::fs::write(
            directory.join(CUTOVER_MARKER_FILE),
            br#"{"schemaVersion":1,"state":"importing","snapshotFile":"../legacy.json","snapshotSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#,
        )
        .await
        .expect("marker");
        assert!(load_cutover_marker(&directory).await.is_err());

        let staged = snapshot(&directory, b"original").await;
        persist_cutover_marker(
            &directory,
            WorkspaceCoreCutoverState::CoreAuthoritative,
            Some(&staged),
        )
        .await
        .expect("marker");
        tokio::fs::write(&staged.path, b"tampered")
            .await
            .expect("tamper");
        assert!(load_cutover_marker(&directory).await.is_err());

        tokio::fs::write(directory.join(CUTOVER_MARKER_FILE), b"not-json")
            .await
            .expect("invalid marker");
        assert!(load_cutover_marker(&directory).await.is_err());
    }
}
