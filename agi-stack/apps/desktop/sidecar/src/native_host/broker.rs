use std::{
    fs::OpenOptions,
    io::Write,
    path::{Path, PathBuf},
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::private_file_permissions::{
    set_private_directory_permissions, set_private_file_permissions,
};

use super::{stage_bytes, MANIFEST_DIR_OVERRIDE_ENV};

const BROKER_DIR_OVERRIDE_ENV: &str = "AGISTACK_BROWSER_BRIDGE_BROKER_DIR";
const CURRENT_FILE_NAME: &str = "current.json";

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BrokerCurrent {
    schema_version: u32,
    version: String,
    sha256: String,
    broker_path: PathBuf,
}

#[derive(Debug)]
pub(super) struct AtomicFileUpdate {
    path: PathBuf,
    previous: Option<Vec<u8>>,
}

impl AtomicFileUpdate {
    pub(super) fn replace(path: &Path, bytes: &[u8], purpose: &str) -> Result<Self, String> {
        let directory = path
            .parent()
            .ok_or_else(|| "atomic file path has no parent directory".to_string())?;
        std::fs::create_dir_all(directory)
            .map_err(|error| format!("failed to create broker directory: {error}"))?;
        set_private_directory_permissions(directory)
            .map_err(|error| format!("failed to protect broker directory: {error}"))?;
        let previous = read_regular_file_if_present(path)?;
        let staged = stage_bytes(directory, bytes, purpose)?;
        if let Err(error) = atomic_replace(&staged, path) {
            let _ = std::fs::remove_file(&staged);
            return Err(format!(
                "failed to atomically replace {}: {error}",
                path.display()
            ));
        }
        let update = Self {
            path: path.to_path_buf(),
            previous,
        };
        let finalize = set_private_file_permissions(path)
            .map_err(|error| format!("failed to protect {}: {error}", path.display()))
            .and_then(|()| sync_directory(directory));
        if let Err(error) = finalize {
            let rollback = update.rollback();
            return Err(match rollback {
                Ok(()) => error,
                Err(rollback) => format!("{error}; rollback failed: {rollback}"),
            });
        }
        Ok(update)
    }

    pub(super) fn rollback(self) -> Result<(), String> {
        match self.previous {
            Some(previous) => {
                let directory = self
                    .path
                    .parent()
                    .ok_or_else(|| "atomic file path has no parent directory".to_string())?;
                let staged = stage_bytes(directory, &previous, "rollback")?;
                atomic_replace(&staged, &self.path).map_err(|error| {
                    format!("failed to restore {}: {error}", self.path.display())
                })?;
                set_private_file_permissions(&self.path).map_err(|error| {
                    format!(
                        "failed to protect restored {}: {error}",
                        self.path.display()
                    )
                })?;
                sync_directory(directory)
            }
            None => match std::fs::remove_file(&self.path) {
                Ok(()) => {
                    if let Some(directory) = self.path.parent() {
                        sync_directory(directory)?;
                    }
                    Ok(())
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
                Err(error) => Err(format!(
                    "failed to remove rolled-back {}: {error}",
                    self.path.display()
                )),
            },
        }
    }

    pub(super) fn commit(self) {}
}

#[derive(Debug)]
pub(super) struct BrokerInstall {
    broker_path: PathBuf,
    current: AtomicFileUpdate,
    created_broker: bool,
}

impl BrokerInstall {
    pub(super) fn broker_path(&self) -> &Path {
        &self.broker_path
    }

    pub(super) fn rollback(self) -> Result<(), String> {
        let mut errors = Vec::new();
        if let Err(error) = self.current.rollback() {
            errors.push(error);
        }
        if self.created_broker {
            if let Err(error) = std::fs::remove_file(&self.broker_path) {
                if error.kind() != std::io::ErrorKind::NotFound {
                    errors.push(format!(
                        "failed to remove rolled-back broker {}: {error}",
                        self.broker_path.display()
                    ));
                }
            }
        }
        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors.join("; "))
        }
    }

    pub(super) fn commit(self) {
        self.current.commit();
    }
}

pub(super) fn broker_root() -> Result<PathBuf, String> {
    if let Some(value) = std::env::var_os(BROKER_DIR_OVERRIDE_ENV) {
        let path = PathBuf::from(value);
        if !path.is_absolute() {
            return Err(format!(
                "{BROKER_DIR_OVERRIDE_ENV} must be an absolute path"
            ));
        }
        return Ok(path);
    }
    if let Some(value) = std::env::var_os(MANIFEST_DIR_OVERRIDE_ENV) {
        let hosts_dir = PathBuf::from(value);
        if !hosts_dir.is_absolute() {
            return Err(format!(
                "{MANIFEST_DIR_OVERRIDE_ENV} must be an absolute path"
            ));
        }
        let profile = hosts_dir
            .parent()
            .ok_or_else(|| "QA manifest directory has no profile parent".to_string())?;
        return Ok(profile.join("MemStackBrowserBroker"));
    }
    Ok(crate::local_runtime::browser_bridge::home_dir()?
        .join(".memstack")
        .join("browser-bridge")
        .join("host"))
}

#[cfg(test)]
pub(super) fn versioned_broker_path(
    source: &Path,
    root: &Path,
    version: &str,
) -> Result<PathBuf, String> {
    validate_install_paths(source, root, version)?;
    let bytes = read_regular_file(source)?;
    let digest = sha256_hex(&bytes);
    Ok(root
        .join("versions")
        .join(version)
        .join(&digest)
        .join(broker_file_name(source)))
}

pub(super) fn install_versioned_broker(
    source: &Path,
    root: &Path,
    version: &str,
) -> Result<BrokerInstall, String> {
    validate_install_paths(source, root, version)?;
    let bytes = read_regular_file(source)?;
    let digest = sha256_hex(&bytes);
    let broker_path = root
        .join("versions")
        .join(version)
        .join(&digest)
        .join(broker_file_name(source));
    let created_broker = install_immutable_broker(&broker_path, &bytes)?;
    let current = BrokerCurrent {
        schema_version: 1,
        version: version.to_string(),
        sha256: digest,
        broker_path: broker_path.clone(),
    };
    let current_bytes = serde_json::to_vec_pretty(&current)
        .map_err(|error| format!("failed to serialize broker current record: {error}"))?;
    let current =
        match AtomicFileUpdate::replace(&root.join(CURRENT_FILE_NAME), &current_bytes, "current") {
            Ok(current) => current,
            Err(error) => {
                if created_broker {
                    let _ = std::fs::remove_file(&broker_path);
                }
                return Err(error);
            }
        };
    Ok(BrokerInstall {
        broker_path,
        current,
        created_broker,
    })
}

pub(super) fn current_broker_path(root: &Path) -> Result<PathBuf, String> {
    let path = root.join(CURRENT_FILE_NAME);
    let bytes = read_regular_file(&path)?;
    let current: BrokerCurrent = serde_json::from_slice(&bytes)
        .map_err(|error| format!("browser broker current record is invalid: {error}"))?;
    if current.schema_version != 1
        || current.version.is_empty()
        || current.sha256.len() != 64
        || !current.sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
        || !current.broker_path.is_absolute()
        || !current.broker_path.starts_with(root.join("versions"))
    {
        return Err("browser broker current record is invalid".to_string());
    }
    let bytes = read_regular_file(&current.broker_path)?;
    if sha256_hex(&bytes) != current.sha256 {
        return Err("browser broker current binary digest does not match".to_string());
    }
    Ok(current.broker_path)
}

fn validate_install_paths(source: &Path, root: &Path, version: &str) -> Result<(), String> {
    if !source.is_absolute() || !root.is_absolute() {
        return Err("browser broker source and root must be absolute".to_string());
    }
    if version.is_empty()
        || !version
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'_'))
    {
        return Err("browser broker version is invalid".to_string());
    }
    Ok(())
}

fn broker_file_name(source: &Path) -> &'static str {
    if source
        .extension()
        .is_some_and(|extension| extension == "exe")
    {
        "agistack-browser-bridge-host.exe"
    } else {
        "agistack-browser-bridge-host"
    }
}

fn install_immutable_broker(path: &Path, bytes: &[u8]) -> Result<bool, String> {
    let directory = path
        .parent()
        .ok_or_else(|| "versioned broker path has no parent directory".to_string())?;
    std::fs::create_dir_all(directory)
        .map_err(|error| format!("failed to create versioned broker directory: {error}"))?;
    set_private_directory_permissions(directory)
        .map_err(|error| format!("failed to protect versioned broker directory: {error}"))?;
    match read_regular_file_if_present(path)? {
        Some(existing) if existing == bytes => {
            set_executable_permissions(path)?;
            Ok(false)
        }
        Some(_) => Err(format!(
            "versioned browser broker collision at {}",
            path.display()
        )),
        None => {
            let staged = path.with_extension(format!(
                "{}.{}.install.tmp",
                std::process::id(),
                super::TEMP_FILE_SEQUENCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
            ));
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&staged)
                .map_err(|error| format!("failed to stage browser broker: {error}"))?;
            file.write_all(bytes)
                .map_err(|error| format!("failed to write staged browser broker: {error}"))?;
            file.sync_all()
                .map_err(|error| format!("failed to sync staged browser broker: {error}"))?;
            set_executable_permissions(&staged)?;
            std::fs::rename(&staged, path)
                .map_err(|error| format!("failed to commit versioned browser broker: {error}"))?;
            sync_directory(directory)?;
            Ok(true)
        }
    }
}

fn read_regular_file(path: &Path) -> Result<Vec<u8>, String> {
    read_regular_file_if_present(path)?
        .ok_or_else(|| format!("browser broker file {} does not exist", path.display()))
}

fn read_regular_file_if_present(path: &Path) -> Result<Option<Vec<u8>>, String> {
    let metadata = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(format!(
                "failed to inspect browser broker file {}: {error}",
                path.display()
            ));
        }
    };
    if metadata.file_type().is_symlink() || !metadata.file_type().is_file() {
        return Err(format!(
            "browser broker file {} must be a regular file",
            path.display()
        ));
    }
    std::fs::read(path).map(Some).map_err(|error| {
        format!(
            "failed to read browser broker file {}: {error}",
            path.display()
        )
    })
}

pub(super) fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[cfg(unix)]
fn set_executable_permissions(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;

    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
        .map_err(|error| format!("failed to protect versioned browser broker: {error}"))
}

#[cfg(windows)]
fn set_executable_permissions(path: &Path) -> Result<(), String> {
    set_private_file_permissions(path)
        .map_err(|error| format!("failed to protect versioned browser broker: {error}"))
}

#[cfg(not(any(unix, windows)))]
fn set_executable_permissions(_path: &Path) -> Result<(), String> {
    Err("browser broker executable permissions are unsupported".to_string())
}

#[cfg(unix)]
fn atomic_replace(source: &Path, destination: &Path) -> std::io::Result<()> {
    std::fs::rename(source, destination)
}

#[cfg(windows)]
fn atomic_replace(source: &Path, destination: &Path) -> std::io::Result<()> {
    use std::{iter, os::windows::ffi::OsStrExt};

    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    let source: Vec<u16> = source
        .as_os_str()
        .encode_wide()
        .chain(iter::once(0))
        .collect();
    let destination: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(iter::once(0))
        .collect();
    // SAFETY: both vectors are live, NUL-terminated UTF-16 paths. The flags request an atomic
    // same-volume replacement and synchronous metadata flush.
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
        "atomic browser broker replacement is unsupported",
    ))
}

#[cfg(unix)]
fn sync_directory(directory: &Path) -> Result<(), String> {
    OpenOptions::new()
        .read(true)
        .open(directory)
        .and_then(|file| file.sync_all())
        .map_err(|error| {
            format!(
                "failed to sync broker directory {}: {error}",
                directory.display()
            )
        })
}

#[cfg(not(unix))]
fn sync_directory(_directory: &Path) -> Result<(), String> {
    Ok(())
}
