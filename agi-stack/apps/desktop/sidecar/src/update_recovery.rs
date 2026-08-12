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
    candidate_process_id: Option<u32>,
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
    let process_identity_is_valid = match record.phase.as_str() {
        "verifying" => record.candidate_process_id.is_some_and(|pid| pid > 0),
        "downloaded" | "applying" | "recovered" | "failed" => record.candidate_process_id.is_none(),
        _ => false,
    };
    if record.schema_version != JOURNAL_SCHEMA_VERSION
        || !nonce_is_valid(&record.nonce)
        || record.nonce != request.expected_nonce
        || record.launch_attempts == 0
        || record.launch_attempts > 3
        || !process_identity_is_valid
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
        || (record.phase == "applying" && deadline < recorded_at)
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
    record.candidate_process_id = None;
    record.retryable = false;
    record.allowed_actions.clear();
    write_journal(&request.journal_path, &record)
}

fn recovery_executable(request: &MonitorRequest) -> PathBuf {
    if request.launch_relative_path == "." {
        request.target_path.clone()
    } else {
        request.target_path.join(&request.launch_relative_path)
    }
}

#[cfg(target_os = "linux")]
fn process_image_path(pid: u32) -> RecoveryResult<Option<PathBuf>> {
    match fs::read_link(format!("/proc/{pid}/exe")) {
        Ok(path) => Ok(Some(path)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(RecoveryError::new(format!(
            "inspect update candidate process image: {error}"
        ))),
    }
}

#[cfg(target_os = "macos")]
fn process_image_path(pid: u32) -> RecoveryResult<Option<PathBuf>> {
    use std::ffi::OsString;
    use std::os::unix::ffi::OsStringExt as _;

    let pid = i32::try_from(pid)
        .map_err(|_| RecoveryError::new("update candidate process identity is invalid"))?;
    let mut buffer = vec![0_u8; libc::PROC_PIDPATHINFO_MAXSIZE as usize];
    // SAFETY: the buffer is writable for the supplied size and proc_pidpath does not retain it.
    let length = unsafe {
        libc::proc_pidpath(
            pid,
            buffer.as_mut_ptr().cast(),
            u32::try_from(buffer.len()).expect("process path buffer fits u32"),
        )
    };
    if length <= 0 {
        let path_error = std::io::Error::last_os_error();
        if path_error.raw_os_error() == Some(libc::ESRCH) {
            return Ok(None);
        }
        // A terminated child can remain as a zombie until its parent reaps it. It no longer owns
        // executable files and is safe to treat as stopped, even though kill(pid, 0) still sees it.
        // SAFETY: proc_pidinfo writes at most the supplied proc_bsdinfo size into a live buffer.
        let mut info = unsafe { std::mem::zeroed::<libc::proc_bsdinfo>() };
        let info_size = i32::try_from(std::mem::size_of::<libc::proc_bsdinfo>())
            .expect("proc_bsdinfo size fits i32");
        // SAFETY: info is writable for info_size bytes and proc_pidinfo does not retain it.
        let inspected = unsafe {
            libc::proc_pidinfo(
                pid,
                libc::PROC_PIDTBSDINFO,
                0,
                (&mut info as *mut libc::proc_bsdinfo).cast(),
                info_size,
            )
        };
        if inspected == info_size && info.pbi_status == libc::SZOMB {
            return Ok(None);
        }
        // SAFETY: kill(pid, 0) only checks whether this process identity still exists.
        let exists = unsafe { libc::kill(pid, 0) } == 0;
        if !exists && std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH) {
            return Ok(None);
        }
        return Err(RecoveryError::new(
            format!(
                "inspect update candidate process image failed (path error: {path_error}; status: {}; inspected: {inspected})",
                info.pbi_status
            ),
        ));
    }
    buffer.truncate(length as usize);
    Ok(Some(PathBuf::from(OsString::from_vec(buffer))))
}

#[cfg(all(unix, not(any(target_os = "linux", target_os = "macos"))))]
fn process_image_path(_pid: u32) -> RecoveryResult<Option<PathBuf>> {
    Err(RecoveryError::new(
        "update candidate process inspection is unsupported",
    ))
}

#[cfg(target_os = "linux")]
fn linux_appimage_process_matches(pid: u32, target: &Path, image: &Path) -> RecoveryResult<bool> {
    use std::ffi::OsString;
    use std::os::unix::ffi::{OsStrExt as _, OsStringExt as _};

    const MAX_ENVIRONMENT_BYTES: u64 = 256 * 1024;
    let environment = match read_bounded(
        Path::new(&format!("/proc/{pid}/environ")),
        MAX_ENVIRONMENT_BYTES,
        "update candidate process environment",
    ) {
        Ok(bytes) => bytes,
        Err(error) if process_image_path(pid)?.is_none() => return Ok(false),
        Err(error) => return Err(error),
    };
    let value = |name: &[u8]| {
        environment
            .split(|byte| *byte == 0)
            .find_map(|entry| entry.strip_prefix(name))
    };
    let Some(appimage) = value(b"APPIMAGE=") else {
        return Ok(false);
    };
    let Some(appdir) = value(b"APPDIR=") else {
        return Ok(false);
    };
    let appimage = PathBuf::from(OsString::from_vec(appimage.to_vec()));
    let appdir = PathBuf::from(OsString::from_vec(appdir.to_vec()));
    let target = fs::canonicalize(target)
        .map_err(|error| RecoveryError::new(format!("resolve update target: {error}")))?;
    let appimage = fs::canonicalize(appimage).map_err(|error| {
        RecoveryError::new(format!("resolve update candidate AppImage: {error}"))
    })?;
    let appdir = fs::canonicalize(appdir)
        .map_err(|error| RecoveryError::new(format!("resolve AppImage mount: {error}")))?;
    Ok(
        appimage == target
            && image.starts_with(&appdir)
            && !image.as_os_str().as_bytes().is_empty(),
    )
}

#[cfg(unix)]
fn candidate_process_matches(request: &MonitorRequest, pid: u32) -> RecoveryResult<Option<bool>> {
    let Some(image) = process_image_path(pid)? else {
        return Ok(None);
    };
    #[cfg(target_os = "linux")]
    let target_metadata = fs::symlink_metadata(&request.target_path)
        .map_err(|error| RecoveryError::new(format!("read update target: {error}")))?;
    #[cfg(target_os = "linux")]
    if target_metadata.is_file() && request.launch_relative_path == "." {
        return linux_appimage_process_matches(pid, &request.target_path, &image).map(Some);
    }
    let expected = fs::canonicalize(recovery_executable(request)).map_err(|error| {
        RecoveryError::new(format!("resolve update candidate executable: {error}"))
    })?;
    let image = fs::canonicalize(image).map_err(|error| {
        RecoveryError::new(format!("resolve update candidate process image: {error}"))
    })?;
    Ok(Some(image == expected))
}

#[cfg(unix)]
fn terminate_candidate_process(request: &MonitorRequest, pid: Option<u32>) -> RecoveryResult<()> {
    let Some(pid) = pid else {
        return Ok(());
    };
    if candidate_process_matches(request, pid)? != Some(true) {
        return if process_image_path(pid)?.is_none() {
            Ok(())
        } else {
            Err(RecoveryError::new(
                "update candidate process image does not match",
            ))
        };
    }
    let pid = i32::try_from(pid)
        .map_err(|_| RecoveryError::new("update candidate process identity is invalid"))?;
    // SAFETY: the PID was read from a current-user-only journal and its executable was verified.
    if unsafe { libc::kill(pid, libc::SIGTERM) } != 0 {
        let error = std::io::Error::last_os_error();
        if error.raw_os_error() != Some(libc::ESRCH) {
            return Err(RecoveryError::new(format!(
                "terminate update candidate process: {error}"
            )));
        }
        return Ok(());
    }
    for _ in 0..100 {
        if process_image_path(pid as u32)?.is_none() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    if candidate_process_matches(request, pid as u32)? != Some(true) {
        return Err(RecoveryError::new(
            "update candidate process changed identity before forced termination",
        ));
    }
    // SAFETY: the same PID and executable identity were revalidated after the graceful timeout.
    if unsafe { libc::kill(pid, libc::SIGKILL) } != 0 {
        let error = std::io::Error::last_os_error();
        if error.raw_os_error() != Some(libc::ESRCH) {
            return Err(RecoveryError::new(format!(
                "force terminate update candidate process: {error}"
            )));
        }
    }
    for _ in 0..50 {
        if process_image_path(pid as u32)?.is_none() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err(RecoveryError::new(
        "update candidate process did not terminate",
    ))
}

#[cfg(windows)]
fn terminate_candidate_process(request: &MonitorRequest, pid: Option<u32>) -> RecoveryResult<()> {
    use std::ffi::OsString;
    use std::os::windows::ffi::OsStringExt as _;

    use windows_sys::Win32::Foundation::{CloseHandle, ERROR_INVALID_PARAMETER, WAIT_OBJECT_0};
    use windows_sys::Win32::System::Threading::{
        OpenProcess, QueryFullProcessImageNameW, TerminateProcess, WaitForSingleObject,
        PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE,
    };

    let Some(pid) = pid else {
        return Ok(());
    };
    // SAFETY: OpenProcess is called with a numeric PID and the minimum query/termination rights.
    let handle = unsafe {
        OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE,
            0,
            pid,
        )
    };
    if handle.is_null() {
        let error = std::io::Error::last_os_error();
        return if error.raw_os_error() == Some(ERROR_INVALID_PARAMETER as i32) {
            Ok(())
        } else {
            Err(RecoveryError::new(format!(
                "open update candidate process: {error}"
            )))
        };
    }
    let result = (|| {
        let mut buffer = vec![0_u16; 32_768];
        let mut length = u32::try_from(buffer.len())
            .map_err(|_| RecoveryError::new("process image buffer is invalid"))?;
        // SAFETY: handle is live and the UTF-16 buffer is writable for `length` elements.
        if unsafe { QueryFullProcessImageNameW(handle, 0, buffer.as_mut_ptr(), &mut length) } == 0 {
            return Err(RecoveryError::new(format!(
                "inspect update candidate process image: {}",
                std::io::Error::last_os_error()
            )));
        }
        buffer.truncate(length as usize);
        let image =
            fs::canonicalize(PathBuf::from(OsString::from_wide(&buffer))).map_err(|error| {
                RecoveryError::new(format!("resolve update candidate process image: {error}"))
            })?;
        let expected = fs::canonicalize(recovery_executable(request)).map_err(|error| {
            RecoveryError::new(format!("resolve update candidate executable: {error}"))
        })?;
        if image != expected {
            return Err(RecoveryError::new(
                "update candidate process image does not match",
            ));
        }
        // SAFETY: the process image was verified against the private recovery plan target.
        if unsafe { TerminateProcess(handle, 70) } == 0 {
            return Err(RecoveryError::new(format!(
                "terminate update candidate process: {}",
                std::io::Error::last_os_error()
            )));
        }
        // SAFETY: handle remains live until the closure returns.
        if unsafe { WaitForSingleObject(handle, 15_000) } != WAIT_OBJECT_0 {
            return Err(RecoveryError::new(
                "update candidate process did not terminate",
            ));
        }
        Ok(())
    })();
    // SAFETY: handle was returned by OpenProcess and is closed exactly once.
    unsafe { CloseHandle(handle) };
    result
}

fn launch_recovered_application(request: &MonitorRequest) -> RecoveryResult<()> {
    let executable = recovery_executable(request);
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
    terminate_candidate_process(request, record.candidate_process_id)?;
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
    record.candidate_process_id = None;
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
