use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

use base64::Engine as _;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::private_file_permissions;
use crate::update_recovery_snapshot::{
    prepare_snapshot, restore_snapshot, RecoveryError, RecoveryResult, SnapshotEvidence,
};

const REQUEST_ENV: &str = "AGISTACK_UPDATE_RECOVERY_REQUEST";
const REQUEST_SCHEMA_VERSION: u8 = 1;
const JOURNAL_SCHEMA_VERSION: u8 = 2;
const MAX_REQUEST_BYTES: u64 = 32 * 1024;
const MAX_JOURNAL_BYTES: u64 = 64 * 1024;
const POLL_INTERVAL: Duration = Duration::from_millis(500);

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct PrepareRequest {
    schema_version: u8,
    target_path: PathBuf,
    owned_root: PathBuf,
    snapshot_root: PathBuf,
    manifest_path: PathBuf,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct MonitorRequest {
    schema_version: u8,
    journal_path: PathBuf,
    expected_nonce: String,
    owned_root: PathBuf,
    snapshot_root: PathBuf,
    manifest_path: PathBuf,
    manifest_sha512: String,
    manifest_size: u64,
    target_path: PathBuf,
    launch_relative_path: String,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case")]
enum RecoveryRequest {
    Prepare(PrepareRequest),
    Monitor(MonitorRequest),
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct JournalPayload {
    sha512: String,
    size: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct JournalSnapshot {
    manifest_sha512: String,
    manifest_size: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct JournalRecord {
    schema_version: u8,
    phase: String,
    current_version: String,
    candidate_version: String,
    recovery_version: String,
    nonce: String,
    deadline_at: String,
    launch_attempts: u8,
    payloads: Vec<JournalPayload>,
    snapshot: JournalSnapshot,
    recorded_at: String,
    reason_code: Option<String>,
    retryable: bool,
    allowed_actions: Vec<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PrepareOutput {
    schema_version: u8,
    manifest_sha512: String,
    manifest_size: u64,
}

fn canonical_digest(value: &str) -> bool {
    base64::engine::general_purpose::STANDARD
        .decode(value)
        .map(|bytes| bytes.len() == 64)
        .unwrap_or(false)
}

fn nonce_is_valid(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn safe_relative_path(value: &str) -> bool {
    let path = Path::new(value);
    value != "."
        && !value.contains('\\')
        && !path.as_os_str().is_empty()
        && path
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
}

fn owned_path(root: &Path, path: &Path) -> bool {
    root.is_absolute() && path.is_absolute() && path != root && path.starts_with(root)
}

fn read_bounded(path: &Path, limit: u64, label: &str) -> RecoveryResult<Vec<u8>> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| RecoveryError::new(format!("read {label} metadata: {error}")))?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > limit {
        return Err(RecoveryError::new(format!("{label} identity is invalid")));
    }
    fs::read(path).map_err(|error| RecoveryError::new(format!("read {label}: {error}")))
}

#[cfg(unix)]
fn assert_private_file(path: &Path, label: &str) -> RecoveryResult<()> {
    use std::os::unix::fs::{MetadataExt as _, PermissionsExt as _};

    let metadata = fs::symlink_metadata(path)
        .map_err(|error| RecoveryError::new(format!("read {label} permissions: {error}")))?;
    // SAFETY: geteuid has no preconditions and does not dereference pointers.
    let current_user = unsafe { libc::geteuid() };
    if metadata.uid() != current_user || metadata.permissions().mode() & 0o077 != 0 {
        return Err(RecoveryError::new(format!(
            "{label} must be current-user-only"
        )));
    }
    Ok(())
}

#[cfg(not(unix))]
fn assert_private_file(path: &Path, label: &str) -> RecoveryResult<()> {
    private_file_permissions::set_private_file_permissions(path)
        .map_err(|error| RecoveryError::new(format!("secure {label}: {error}")))
}

fn load_request() -> RecoveryResult<RecoveryRequest> {
    let request_path = std::env::var_os(REQUEST_ENV)
        .map(PathBuf::from)
        .ok_or_else(|| RecoveryError::new("update recovery request is unavailable"))?;
    std::env::remove_var(REQUEST_ENV);
    if !request_path.is_absolute() {
        return Err(RecoveryError::new(
            "update recovery request path is invalid",
        ));
    }
    assert_private_file(&request_path, "update recovery request")?;
    let bytes = read_bounded(&request_path, MAX_REQUEST_BYTES, "update recovery request")?;
    let request = serde_json::from_slice(&bytes)
        .map_err(|_| RecoveryError::new("update recovery request is invalid"))?;
    fs::remove_file(&request_path)
        .map_err(|error| RecoveryError::new(format!("remove update recovery request: {error}")))?;
    Ok(request)
}

fn validate_prepare(request: &PrepareRequest) -> RecoveryResult<()> {
    if request.schema_version != REQUEST_SCHEMA_VERSION
        || !request.target_path.is_absolute()
        || !owned_path(&request.owned_root, &request.snapshot_root)
        || !owned_path(&request.owned_root, &request.manifest_path)
    {
        return Err(RecoveryError::new(
            "update recovery prepare request is invalid",
        ));
    }
    Ok(())
}

fn validate_monitor(request: &MonitorRequest) -> RecoveryResult<()> {
    if request.schema_version != REQUEST_SCHEMA_VERSION
        || !request.journal_path.is_absolute()
        || !request.target_path.is_absolute()
        || !owned_path(&request.owned_root, &request.snapshot_root)
        || !owned_path(&request.owned_root, &request.manifest_path)
        || !nonce_is_valid(&request.expected_nonce)
        || !canonical_digest(&request.manifest_sha512)
        || request.manifest_size == 0
        || !(request.launch_relative_path == "."
            || safe_relative_path(&request.launch_relative_path))
    {
        return Err(RecoveryError::new(
            "update recovery monitor request is invalid",
        ));
    }
    Ok(())
}

fn validate_journal(record: &JournalRecord, request: &MonitorRequest) -> RecoveryResult<()> {
    let deadline = DateTime::parse_from_rfc3339(&record.deadline_at)
        .map_err(|_| RecoveryError::new("update recovery journal deadline is invalid"))?;
    let recorded_at = DateTime::parse_from_rfc3339(&record.recorded_at)
        .map_err(|_| RecoveryError::new("update recovery journal timestamp is invalid"))?;
    if record.schema_version != JOURNAL_SCHEMA_VERSION
        || !nonce_is_valid(&record.nonce)
        || record.nonce != request.expected_nonce
        || record.launch_attempts == 0
        || record.launch_attempts > 3
        || record.payloads.is_empty()
        || record
            .payloads
            .iter()
            .any(|payload| payload.size == 0 || !canonical_digest(&payload.sha512))
        || record.snapshot.manifest_sha512 != request.manifest_sha512
        || record.snapshot.manifest_size != request.manifest_size
        || record.current_version.is_empty()
        || record.candidate_version.is_empty()
        || record.recovery_version.is_empty()
        || deadline < recorded_at
    {
        return Err(RecoveryError::new("update recovery journal is invalid"));
    }
    Ok(())
}

fn load_journal(request: &MonitorRequest) -> RecoveryResult<JournalRecord> {
    assert_private_file(&request.journal_path, "update recovery journal")?;
    let bytes = read_bounded(
        &request.journal_path,
        MAX_JOURNAL_BYTES,
        "update recovery journal",
    )?;
    let record: JournalRecord = serde_json::from_slice(&bytes)
        .map_err(|_| RecoveryError::new("update recovery journal is invalid"))?;
    validate_journal(&record, request)?;
    Ok(record)
}

fn write_journal(path: &Path, record: &JournalRecord) -> RecoveryResult<()> {
    let parent = path
        .parent()
        .ok_or_else(|| RecoveryError::new("update recovery journal parent is invalid"))?;
    let bytes = serde_json::to_vec(record).map_err(|error| {
        RecoveryError::new(format!("serialize update recovery journal: {error}"))
    })?;
    let temporary = parent.join(format!(".recovery-journal.{}.tmp", Uuid::new_v4()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| {
                RecoveryError::new(format!("create update recovery journal: {error}"))
            })?;
        file.write_all(&bytes).map_err(|error| {
            RecoveryError::new(format!("write update recovery journal: {error}"))
        })?;
        file.sync_all().map_err(|error| {
            RecoveryError::new(format!("sync update recovery journal: {error}"))
        })?;
        private_file_permissions::set_private_file_permissions(&temporary).map_err(|error| {
            RecoveryError::new(format!("secure update recovery journal: {error}"))
        })?;
        fs::rename(&temporary, path).map_err(|error| {
            RecoveryError::new(format!("publish update recovery journal: {error}"))
        })?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn mark_failed(request: &MonitorRequest, mut record: JournalRecord) -> RecoveryResult<()> {
    record.phase = "failed".to_owned();
    record.recorded_at = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);
    record.reason_code = Some("update_recovery_restore_failed".to_owned());
    record.retryable = false;
    record.allowed_actions.clear();
    write_journal(&request.journal_path, &record)
}

fn launch_recovered_application(request: &MonitorRequest) -> RecoveryResult<()> {
    let executable = if request.launch_relative_path == "." {
        request.target_path.clone()
    } else {
        request.target_path.join(&request.launch_relative_path)
    };
    let metadata = fs::symlink_metadata(&executable)
        .map_err(|error| RecoveryError::new(format!("read recovered executable: {error}")))?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(RecoveryError::new(
            "recovered executable identity is invalid",
        ));
    }
    Command::new(executable)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| RecoveryError::new(format!("launch recovered application: {error}")))?;
    Ok(())
}

fn recover(request: &MonitorRequest, mut record: JournalRecord) -> RecoveryResult<()> {
    let evidence = SnapshotEvidence {
        manifest_sha512: request.manifest_sha512.clone(),
        manifest_size: request.manifest_size,
    };
    restore_snapshot(
        &request.target_path,
        &request.snapshot_root,
        &request.manifest_path,
        &evidence,
        &request.expected_nonce,
    )?;
    record.phase = "recovered".to_owned();
    record.current_version.clone_from(&record.recovery_version);
    record.recorded_at = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true);
    record.reason_code = None;
    record.retryable = false;
    record.allowed_actions = vec!["check".to_owned()];
    write_journal(&request.journal_path, &record)?;
    launch_recovered_application(request)
}

fn monitor(request: &MonitorRequest) -> RecoveryResult<()> {
    validate_monitor(request)?;
    loop {
        let record = load_journal(request)?;
        match record.phase.as_str() {
            "recovered" => return Ok(()),
            "failed" => return Err(RecoveryError::new("update recovery journal is failed")),
            "applying" | "verifying" => {}
            _ => {
                return Err(RecoveryError::new(
                    "update recovery journal phase is invalid",
                ))
            }
        }
        let deadline = DateTime::parse_from_rfc3339(&record.deadline_at)
            .map_err(|_| RecoveryError::new("update recovery journal deadline is invalid"))?
            .with_timezone(&Utc);
        if Utc::now() <= deadline {
            thread::sleep(POLL_INTERVAL);
            continue;
        }
        if let Err(error) = recover(request, record.clone()) {
            let _ = mark_failed(request, record);
            return Err(error);
        }
        return Ok(());
    }
}

pub(crate) fn run_from_environment() -> RecoveryResult<()> {
    match load_request()? {
        RecoveryRequest::Prepare(request) => {
            validate_prepare(&request)?;
            let evidence = prepare_snapshot(
                &request.target_path,
                &request.owned_root,
                &request.snapshot_root,
                &request.manifest_path,
            )?;
            let output = PrepareOutput {
                schema_version: REQUEST_SCHEMA_VERSION,
                manifest_sha512: evidence.manifest_sha512,
                manifest_size: evidence.manifest_size,
            };
            let source = serde_json::to_string(&output).map_err(|error| {
                RecoveryError::new(format!("serialize recovery output: {error}"))
            })?;
            println!("{source}");
            Ok(())
        }
        RecoveryRequest::Monitor(request) => monitor(&request),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn monitor_request_rejects_path_escape_and_invalid_nonce() {
        let request = MonitorRequest {
            schema_version: REQUEST_SCHEMA_VERSION,
            journal_path: PathBuf::from("/tmp/journal"),
            expected_nonce: "z".repeat(64),
            owned_root: PathBuf::from("/tmp/owned"),
            snapshot_root: PathBuf::from("/tmp/other/snapshot"),
            manifest_path: PathBuf::from("/tmp/owned/manifest"),
            manifest_sha512: base64::engine::general_purpose::STANDARD.encode([0_u8; 64]),
            manifest_size: 10,
            target_path: PathBuf::from("/Applications/MemStack.app"),
            launch_relative_path: "Contents/MacOS/MemStack".to_owned(),
        };
        assert!(validate_monitor(&request).is_err());
    }
}
