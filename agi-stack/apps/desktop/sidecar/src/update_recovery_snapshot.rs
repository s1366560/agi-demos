use std::collections::HashSet;
use std::fmt::{Display, Formatter};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};

use base64::Engine as _;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use uuid::Uuid;

use crate::private_file_permissions;

const MANIFEST_SCHEMA_VERSION: u8 = 1;
const MAX_MANIFEST_BYTES: u64 = 16 * 1024 * 1024;

#[derive(Debug)]
pub(crate) struct RecoveryError(String);

impl RecoveryError {
    pub(crate) fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }

    fn io(context: &str, error: std::io::Error) -> Self {
        Self(format!("{context}: {error}"))
    }
}

impl Display for RecoveryError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for RecoveryError {}

pub(crate) type RecoveryResult<T> = Result<T, RecoveryError>;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum SnapshotTargetKind {
    File,
    Directory,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum SnapshotEntryKind {
    File,
    Directory,
    Symlink,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct SnapshotEntry {
    path: String,
    kind: SnapshotEntryKind,
    size: u64,
    sha512: Option<String>,
    link_target: Option<String>,
    mode: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct SnapshotManifest {
    schema_version: u8,
    target_kind: SnapshotTargetKind,
    entries: Vec<SnapshotEntry>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SnapshotEvidence {
    pub(crate) manifest_sha512: String,
    pub(crate) manifest_size: u64,
}

fn canonical_sha512(bytes: &[u8]) -> String {
    base64::engine::general_purpose::STANDARD.encode(Sha512::digest(bytes))
}

fn file_sha512(path: &Path) -> RecoveryResult<(String, u64)> {
    let mut file =
        File::open(path).map_err(|error| RecoveryError::io("open snapshot file", error))?;
    let mut digest = Sha512::new();
    let mut size = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| RecoveryError::io("read snapshot file", error))?;
        if read == 0 {
            break;
        }
        let read_u64 =
            u64::try_from(read).map_err(|_| RecoveryError::new("snapshot file size is invalid"))?;
        size = size
            .checked_add(read_u64)
            .ok_or_else(|| RecoveryError::new("snapshot file is too large"))?;
        digest.update(&buffer[..read]);
    }
    Ok((
        base64::engine::general_purpose::STANDARD.encode(digest.finalize()),
        size,
    ))
}

fn is_safe_relative(path: &Path) -> bool {
    !path.as_os_str().is_empty()
        && path
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
}

fn relative_string(path: &Path) -> RecoveryResult<String> {
    if !is_safe_relative(path) {
        return Err(RecoveryError::new("snapshot relative path is invalid"));
    }
    let value = path
        .to_str()
        .ok_or_else(|| RecoveryError::new("snapshot path must be UTF-8"))?;
    Ok(value.replace('\\', "/"))
}

fn path_from_relative(value: &str) -> RecoveryResult<PathBuf> {
    let path = PathBuf::from(value);
    if !is_safe_relative(&path) || value.contains('\\') {
        return Err(RecoveryError::new("snapshot manifest path is invalid"));
    }
    Ok(path)
}

#[cfg(unix)]
fn permission_mode(metadata: &fs::Metadata) -> u32 {
    use std::os::unix::fs::PermissionsExt as _;
    metadata.permissions().mode() & 0o777
}

#[cfg(not(unix))]
fn permission_mode(metadata: &fs::Metadata) -> u32 {
    if metadata.permissions().readonly() {
        0o444
    } else {
        0o666
    }
}

#[cfg(unix)]
fn set_permission_mode(path: &Path, mode: u32) -> RecoveryResult<()> {
    use std::os::unix::fs::PermissionsExt as _;
    fs::set_permissions(path, fs::Permissions::from_mode(mode))
        .map_err(|error| RecoveryError::io("set snapshot permissions", error))
}

#[cfg(not(unix))]
fn set_permission_mode(path: &Path, mode: u32) -> RecoveryResult<()> {
    let mut permissions = fs::metadata(path)
        .map_err(|error| RecoveryError::io("read snapshot permissions", error))?
        .permissions();
    permissions.set_readonly(mode & 0o200 == 0);
    fs::set_permissions(path, permissions)
        .map_err(|error| RecoveryError::io("set snapshot permissions", error))
}

fn sorted_children(path: &Path) -> RecoveryResult<Vec<PathBuf>> {
    let mut children = fs::read_dir(path)
        .map_err(|error| RecoveryError::io("read snapshot directory", error))?
        .map(|entry| {
            entry
                .map(|item| item.path())
                .map_err(|error| RecoveryError::io("read snapshot directory entry", error))
        })
        .collect::<RecoveryResult<Vec<_>>>()?;
    children.sort();
    Ok(children)
}

fn validate_symlink(source_root: &Path, link_path: &Path, target: &Path) -> RecoveryResult<()> {
    if target.is_absolute() {
        return Err(RecoveryError::new(
            "snapshot symlink target must be relative",
        ));
    }
    let resolved = link_path
        .parent()
        .ok_or_else(|| RecoveryError::new("snapshot symlink parent is invalid"))?
        .join(target)
        .canonicalize()
        .map_err(|error| RecoveryError::io("resolve snapshot symlink", error))?;
    let canonical_root = source_root
        .canonicalize()
        .map_err(|error| RecoveryError::io("resolve snapshot source", error))?;
    if !resolved.starts_with(canonical_root) {
        return Err(RecoveryError::new("snapshot symlink escapes the source"));
    }
    Ok(())
}

#[cfg(unix)]
fn create_symlink(target: &Path, destination: &Path) -> RecoveryResult<()> {
    std::os::unix::fs::symlink(target, destination)
        .map_err(|error| RecoveryError::io("create snapshot symlink", error))
}

#[cfg(windows)]
fn create_symlink(target: &Path, destination: &Path) -> RecoveryResult<()> {
    let resolved = destination
        .parent()
        .ok_or_else(|| RecoveryError::new("snapshot symlink parent is invalid"))?
        .join(target);
    if resolved.is_dir() {
        std::os::windows::fs::symlink_dir(target, destination)
            .map_err(|error| RecoveryError::io("create snapshot directory symlink", error))
    } else {
        std::os::windows::fs::symlink_file(target, destination)
            .map_err(|error| RecoveryError::io("create snapshot file symlink", error))
    }
}

fn copy_entry(
    source_root: &Path,
    source: &Path,
    destination: &Path,
    relative: &Path,
    entries: &mut Vec<SnapshotEntry>,
) -> RecoveryResult<()> {
    let metadata = fs::symlink_metadata(source)
        .map_err(|error| RecoveryError::io("read snapshot source metadata", error))?;
    let path = relative_string(relative)?;
    if metadata.file_type().is_symlink() {
        let target = fs::read_link(source)
            .map_err(|error| RecoveryError::io("read snapshot symlink", error))?;
        validate_symlink(source_root, source, &target)?;
        create_symlink(&target, destination)?;
        entries.push(SnapshotEntry {
            path,
            kind: SnapshotEntryKind::Symlink,
            size: 0,
            sha512: None,
            link_target: Some(
                target
                    .to_str()
                    .ok_or_else(|| RecoveryError::new("snapshot symlink target must be UTF-8"))?
                    .replace('\\', "/"),
            ),
            mode: 0,
        });
        return Ok(());
    }
    if metadata.is_dir() {
        fs::create_dir(destination)
            .map_err(|error| RecoveryError::io("create snapshot directory", error))?;
        entries.push(SnapshotEntry {
            path,
            kind: SnapshotEntryKind::Directory,
            size: 0,
            sha512: None,
            link_target: None,
            mode: permission_mode(&metadata),
        });
        for child in sorted_children(source)? {
            let name = child
                .file_name()
                .ok_or_else(|| RecoveryError::new("snapshot child name is invalid"))?;
            copy_entry(
                source_root,
                &child,
                &destination.join(name),
                &relative.join(name),
                entries,
            )?;
        }
        set_permission_mode(destination, permission_mode(&metadata))?;
        return Ok(());
    }
    if !metadata.is_file() {
        return Err(RecoveryError::new(
            "snapshot source contains an unsupported file type",
        ));
    }
    fs::copy(source, destination)
        .map_err(|error| RecoveryError::io("copy snapshot file", error))?;
    set_permission_mode(destination, permission_mode(&metadata))?;
    let (sha512, size) = file_sha512(destination)?;
    entries.push(SnapshotEntry {
        path,
        kind: SnapshotEntryKind::File,
        size,
        sha512: Some(sha512),
        link_target: None,
        mode: permission_mode(&metadata),
    });
    Ok(())
}

fn inspect_entry(
    source_root: &Path,
    source: &Path,
    relative: &Path,
    entries: &mut Vec<SnapshotEntry>,
) -> RecoveryResult<()> {
    let metadata = fs::symlink_metadata(source)
        .map_err(|error| RecoveryError::io("read snapshot payload metadata", error))?;
    let path = relative_string(relative)?;
    if metadata.file_type().is_symlink() {
        let target = fs::read_link(source)
            .map_err(|error| RecoveryError::io("read snapshot payload symlink", error))?;
        validate_symlink(source_root, source, &target)?;
        entries.push(SnapshotEntry {
            path,
            kind: SnapshotEntryKind::Symlink,
            size: 0,
            sha512: None,
            link_target: Some(
                target
                    .to_str()
                    .ok_or_else(|| RecoveryError::new("snapshot symlink target must be UTF-8"))?
                    .replace('\\', "/"),
            ),
            mode: 0,
        });
    } else if metadata.is_dir() {
        entries.push(SnapshotEntry {
            path,
            kind: SnapshotEntryKind::Directory,
            size: 0,
            sha512: None,
            link_target: None,
            mode: permission_mode(&metadata),
        });
        for child in sorted_children(source)? {
            let name = child
                .file_name()
                .ok_or_else(|| RecoveryError::new("snapshot child name is invalid"))?;
            inspect_entry(source_root, &child, &relative.join(name), entries)?;
        }
    } else if metadata.is_file() {
        let (sha512, size) = file_sha512(source)?;
        entries.push(SnapshotEntry {
            path,
            kind: SnapshotEntryKind::File,
            size,
            sha512: Some(sha512),
            link_target: None,
            mode: permission_mode(&metadata),
        });
    } else {
        return Err(RecoveryError::new(
            "snapshot payload contains an unsupported file type",
        ));
    }
    Ok(())
}

fn manifest_for_payload(
    payload: &Path,
    target_kind: SnapshotTargetKind,
) -> RecoveryResult<SnapshotManifest> {
    let mut entries = Vec::new();
    match target_kind {
        SnapshotTargetKind::File => inspect_entry(
            payload,
            &payload.join("item"),
            Path::new("item"),
            &mut entries,
        )?,
        SnapshotTargetKind::Directory => {
            for child in sorted_children(payload)? {
                let name = child
                    .file_name()
                    .ok_or_else(|| RecoveryError::new("snapshot payload child is invalid"))?;
                inspect_entry(payload, &child, Path::new(name), &mut entries)?;
            }
        }
    }
    entries.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(SnapshotManifest {
        schema_version: MANIFEST_SCHEMA_VERSION,
        target_kind,
        entries,
    })
}

fn assert_owned_path(owned_root: &Path, path: &Path) -> RecoveryResult<()> {
    if !owned_root.is_absolute()
        || !path.is_absolute()
        || path == owned_root
        || !path.starts_with(owned_root)
    {
        return Err(RecoveryError::new("update recovery owned path is invalid"));
    }
    Ok(())
}

fn assert_existing_ancestors_are_directories(root: &Path, path: &Path) -> RecoveryResult<()> {
    let relative = path
        .strip_prefix(root)
        .map_err(|_| RecoveryError::new("update recovery owned path is invalid"))?;
    let mut current = root.to_path_buf();
    for component in relative.components() {
        current.push(component);
        if !current.exists() {
            continue;
        }
        let metadata = fs::symlink_metadata(&current)
            .map_err(|error| RecoveryError::io("read update recovery ancestor", error))?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(RecoveryError::new(
                "update recovery path contains an unsafe ancestor",
            ));
        }
    }
    Ok(())
}

fn write_private_atomic(path: &Path, bytes: &[u8]) -> RecoveryResult<()> {
    let parent = path
        .parent()
        .ok_or_else(|| RecoveryError::new("snapshot manifest parent is invalid"))?;
    fs::create_dir_all(parent)
        .map_err(|error| RecoveryError::io("create snapshot manifest directory", error))?;
    let temporary = parent.join(format!(".manifest.{}.tmp", Uuid::new_v4()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| RecoveryError::io("create snapshot manifest", error))?;
        file.write_all(bytes)
            .map_err(|error| RecoveryError::io("write snapshot manifest", error))?;
        file.sync_all()
            .map_err(|error| RecoveryError::io("sync snapshot manifest", error))?;
        private_file_permissions::set_private_file_permissions(&temporary)
            .map_err(|error| RecoveryError::io("secure snapshot manifest", error))?;
        fs::rename(&temporary, path)
            .map_err(|error| RecoveryError::io("publish snapshot manifest", error))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

pub(crate) fn prepare_snapshot(
    target: &Path,
    owned_root: &Path,
    snapshot_root: &Path,
    manifest_path: &Path,
) -> RecoveryResult<SnapshotEvidence> {
    assert_owned_path(owned_root, snapshot_root)?;
    assert_owned_path(owned_root, manifest_path)?;
    if target.parent().is_none()
        || target == Path::new("/")
        || target.starts_with(snapshot_root)
        || snapshot_root.starts_with(target)
        || !manifest_path.starts_with(snapshot_root)
    {
        return Err(RecoveryError::new("update recovery target is invalid"));
    }
    let metadata = fs::symlink_metadata(target)
        .map_err(|error| RecoveryError::io("read update recovery target", error))?;
    if metadata.file_type().is_symlink() || (!metadata.is_file() && !metadata.is_dir()) {
        return Err(RecoveryError::new("update recovery target type is invalid"));
    }
    if snapshot_root.exists() || manifest_path.exists() {
        return Err(RecoveryError::new(
            "update recovery snapshot already exists",
        ));
    }
    fs::create_dir_all(owned_root)
        .map_err(|error| RecoveryError::io("create update recovery root", error))?;
    let owned_metadata = fs::symlink_metadata(owned_root)
        .map_err(|error| RecoveryError::io("read update recovery root", error))?;
    if !owned_metadata.is_dir() || owned_metadata.file_type().is_symlink() {
        return Err(RecoveryError::new("update recovery root is invalid"));
    }
    private_file_permissions::set_private_directory_permissions(owned_root)
        .map_err(|error| RecoveryError::io("secure update recovery root", error))?;
    let snapshot_parent = snapshot_root
        .parent()
        .ok_or_else(|| RecoveryError::new("update recovery snapshot parent is invalid"))?;
    assert_existing_ancestors_are_directories(owned_root, snapshot_parent)?;
    fs::create_dir_all(snapshot_parent)
        .map_err(|error| RecoveryError::io("create update recovery snapshot parent", error))?;
    private_file_permissions::set_private_directory_permissions(snapshot_parent)
        .map_err(|error| RecoveryError::io("secure update recovery snapshot parent", error))?;
    fs::create_dir(snapshot_root)
        .map_err(|error| RecoveryError::io("create update recovery snapshot", error))?;
    private_file_permissions::set_private_directory_permissions(snapshot_root)
        .map_err(|error| RecoveryError::io("secure update recovery snapshot", error))?;
    let payload = snapshot_root.join("payload");
    fs::create_dir(&payload)
        .map_err(|error| RecoveryError::io("create update recovery payload", error))?;
    let mut entries = Vec::new();
    let target_kind = if metadata.is_file() {
        copy_entry(
            target,
            target,
            &payload.join("item"),
            Path::new("item"),
            &mut entries,
        )?;
        SnapshotTargetKind::File
    } else {
        for child in sorted_children(target)? {
            let name = child
                .file_name()
                .ok_or_else(|| RecoveryError::new("update recovery target child is invalid"))?;
            copy_entry(
                target,
                &child,
                &payload.join(name),
                Path::new(name),
                &mut entries,
            )?;
        }
        SnapshotTargetKind::Directory
    };
    entries.sort_by(|left, right| left.path.cmp(&right.path));
    let manifest = SnapshotManifest {
        schema_version: MANIFEST_SCHEMA_VERSION,
        target_kind,
        entries,
    };
    let bytes = serde_json::to_vec(&manifest)
        .map_err(|error| RecoveryError::new(format!("serialize snapshot manifest: {error}")))?;
    let manifest_size = u64::try_from(bytes.len())
        .map_err(|_| RecoveryError::new("snapshot manifest is too large"))?;
    if manifest_size > MAX_MANIFEST_BYTES {
        return Err(RecoveryError::new("snapshot manifest is too large"));
    }
    write_private_atomic(manifest_path, &bytes)?;
    Ok(SnapshotEvidence {
        manifest_sha512: canonical_sha512(&bytes),
        manifest_size,
    })
}

fn load_verified_manifest(
    snapshot_root: &Path,
    manifest_path: &Path,
    expected: &SnapshotEvidence,
) -> RecoveryResult<SnapshotManifest> {
    let snapshot_metadata = fs::symlink_metadata(snapshot_root)
        .map_err(|error| RecoveryError::io("read snapshot root metadata", error))?;
    if !snapshot_metadata.is_dir() || snapshot_metadata.file_type().is_symlink() {
        return Err(RecoveryError::new("snapshot root identity is invalid"));
    }
    let metadata = fs::symlink_metadata(manifest_path)
        .map_err(|error| RecoveryError::io("read snapshot manifest metadata", error))?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() != expected.manifest_size
        || metadata.len() > MAX_MANIFEST_BYTES
    {
        return Err(RecoveryError::new("snapshot manifest identity is invalid"));
    }
    let bytes = fs::read(manifest_path)
        .map_err(|error| RecoveryError::io("read snapshot manifest", error))?;
    if canonical_sha512(&bytes) != expected.manifest_sha512 {
        return Err(RecoveryError::new(
            "snapshot manifest digest does not match",
        ));
    }
    let manifest: SnapshotManifest = serde_json::from_slice(&bytes)
        .map_err(|_| RecoveryError::new("snapshot manifest is invalid"))?;
    if manifest.schema_version != MANIFEST_SCHEMA_VERSION {
        return Err(RecoveryError::new("snapshot manifest version is invalid"));
    }
    let mut paths = HashSet::with_capacity(manifest.entries.len());
    for entry in &manifest.entries {
        if !paths.insert(entry.path.as_str()) || path_from_relative(&entry.path).is_err() {
            return Err(RecoveryError::new("snapshot manifest entry is invalid"));
        }
        match entry.kind {
            SnapshotEntryKind::File if entry.sha512.is_some() && entry.link_target.is_none() => {}
            SnapshotEntryKind::Directory
                if entry.sha512.is_none() && entry.link_target.is_none() => {}
            SnapshotEntryKind::Symlink if entry.sha512.is_none() && entry.link_target.is_some() => {
            }
            _ => {
                return Err(RecoveryError::new(
                    "snapshot manifest entry contract is invalid",
                ))
            }
        }
    }
    let inspected = manifest_for_payload(&snapshot_root.join("payload"), manifest.target_kind)?;
    if inspected != manifest {
        return Err(RecoveryError::new(
            "snapshot payload does not match its manifest",
        ));
    }
    Ok(manifest)
}

fn copy_payload_to_staging(
    snapshot_root: &Path,
    staging: &Path,
    target_kind: SnapshotTargetKind,
) -> RecoveryResult<()> {
    let payload = snapshot_root.join("payload");
    let mut ignored_entries = Vec::new();
    match target_kind {
        SnapshotTargetKind::File => copy_entry(
            &payload,
            &payload.join("item"),
            staging,
            Path::new("item"),
            &mut ignored_entries,
        ),
        SnapshotTargetKind::Directory => {
            fs::create_dir(staging)
                .map_err(|error| RecoveryError::io("create recovery staging directory", error))?;
            for child in sorted_children(&payload)? {
                let name = child
                    .file_name()
                    .ok_or_else(|| RecoveryError::new("recovery payload child is invalid"))?;
                copy_entry(
                    &payload,
                    &child,
                    &staging.join(name),
                    Path::new(name),
                    &mut ignored_entries,
                )?;
            }
            Ok(())
        }
    }
}

fn remove_path(path: &Path) -> RecoveryResult<()> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| RecoveryError::io("read recovery path", error))?;
    if metadata.file_type().is_symlink() || metadata.is_file() {
        fs::remove_file(path).map_err(|error| RecoveryError::io("remove recovery file", error))
    } else if metadata.is_dir() {
        fs::remove_dir_all(path)
            .map_err(|error| RecoveryError::io("remove recovery directory", error))
    } else {
        Err(RecoveryError::new("recovery path type is invalid"))
    }
}

pub(crate) fn restore_snapshot(
    target: &Path,
    snapshot_root: &Path,
    manifest_path: &Path,
    expected: &SnapshotEvidence,
    nonce: &str,
) -> RecoveryResult<()> {
    let manifest = load_verified_manifest(snapshot_root, manifest_path, expected)?;
    let parent = target
        .parent()
        .ok_or_else(|| RecoveryError::new("update recovery target parent is invalid"))?;
    let target_name = target
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| RecoveryError::new("update recovery target name is invalid"))?;
    let suffix = nonce
        .get(..12)
        .ok_or_else(|| RecoveryError::new("update recovery nonce is invalid"))?;
    let staging = parent.join(format!(".{target_name}.recovery-staging-{suffix}"));
    let backup = parent.join(format!(".{target_name}.recovery-backup-{suffix}"));
    if staging.exists() || backup.exists() {
        return Err(RecoveryError::new(
            "update recovery staging path already exists",
        ));
    }
    copy_payload_to_staging(snapshot_root, &staging, manifest.target_kind)?;
    let staged_manifest = manifest_for_payload(
        if manifest.target_kind == SnapshotTargetKind::File {
            staging
                .parent()
                .ok_or_else(|| RecoveryError::new("recovery staging parent is invalid"))?
        } else {
            &staging
        },
        manifest.target_kind,
    );
    if manifest.target_kind == SnapshotTargetKind::Directory {
        if staged_manifest? != manifest {
            let _ = remove_path(&staging);
            return Err(RecoveryError::new("recovery staging verification failed"));
        }
    } else {
        let (sha512, size) = file_sha512(&staging)?;
        let entry = manifest
            .entries
            .first()
            .ok_or_else(|| RecoveryError::new("recovery file manifest is empty"))?;
        if entry.sha512.as_deref() != Some(sha512.as_str()) || entry.size != size {
            let _ = remove_path(&staging);
            return Err(RecoveryError::new("recovery staging verification failed"));
        }
    }
    if target.exists() {
        let target_metadata = fs::symlink_metadata(target)
            .map_err(|error| RecoveryError::io("read current update target", error))?;
        if target_metadata.file_type().is_symlink() {
            let _ = remove_path(&staging);
            return Err(RecoveryError::new(
                "current update target must not be a symlink",
            ));
        }
        fs::rename(target, &backup)
            .map_err(|error| RecoveryError::io("move current update target aside", error))?;
    }
    if let Err(error) = fs::rename(&staging, target) {
        if backup.exists() {
            let _ = fs::rename(&backup, target);
        }
        let _ = remove_path(&staging);
        return Err(RecoveryError::io("publish recovered update target", error));
    }
    if backup.exists() {
        remove_path(&backup)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::PathBuf;

    use super::*;

    struct TestRoot(PathBuf);

    impl TestRoot {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!("agistack-recovery-{}", Uuid::new_v4()));
            fs::create_dir(&path).expect("create test root");
            Self(path)
        }
    }

    impl Drop for TestRoot {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn snapshot_restore_replaces_a_directory_after_manifest_verification() {
        let root = TestRoot::new();
        let target = root.0.join("MemStack.app");
        let owned = root.0.join("owned");
        let snapshot = owned.join("snapshot");
        let manifest = snapshot.join("manifest.json");
        fs::create_dir(&target).expect("create target");
        fs::write(target.join("version.txt"), "0.1.0").expect("write old version");
        let evidence =
            prepare_snapshot(&target, &owned, &snapshot, &manifest).expect("prepare snapshot");
        fs::write(target.join("version.txt"), "0.1.1").expect("write new version");
        restore_snapshot(&target, &snapshot, &manifest, &evidence, &"a".repeat(64))
            .expect("restore snapshot");
        assert_eq!(
            fs::read_to_string(target.join("version.txt")).expect("read restored version"),
            "0.1.0"
        );
    }

    #[test]
    fn snapshot_restore_rejects_tampering_without_replacing_the_target() {
        let root = TestRoot::new();
        let target = root.0.join("MemStack.AppImage");
        let owned = root.0.join("owned");
        let snapshot = owned.join("snapshot");
        let manifest = snapshot.join("manifest.json");
        fs::write(&target, "0.1.0").expect("write old version");
        let evidence =
            prepare_snapshot(&target, &owned, &snapshot, &manifest).expect("prepare snapshot");
        fs::write(snapshot.join("payload/item"), "tampered").expect("tamper snapshot");
        fs::write(&target, "0.1.1").expect("write new version");
        let error = restore_snapshot(&target, &snapshot, &manifest, &evidence, &"b".repeat(64))
            .expect_err("tampered snapshot must fail");
        assert!(error.to_string().contains("does not match"));
        assert_eq!(
            fs::read_to_string(target).expect("read current version"),
            "0.1.1"
        );
    }

    #[test]
    fn snapshot_restore_replaces_a_file_after_manifest_verification() {
        let root = TestRoot::new();
        let target = root.0.join("MemStack.AppImage");
        let owned = root.0.join("owned");
        let snapshot = owned.join("snapshot");
        let manifest = snapshot.join("manifest.json");
        fs::write(&target, "0.1.0").expect("write old version");
        let evidence =
            prepare_snapshot(&target, &owned, &snapshot, &manifest).expect("prepare snapshot");
        fs::write(&target, "0.1.1").expect("write new version");
        restore_snapshot(&target, &snapshot, &manifest, &evidence, &"c".repeat(64))
            .expect("restore snapshot");
        assert_eq!(
            fs::read_to_string(target).expect("read restored version"),
            "0.1.0"
        );
    }

    #[cfg(unix)]
    #[test]
    fn snapshot_rejects_symlinks_that_escape_the_target() {
        let root = TestRoot::new();
        let target = root.0.join("app");
        let owned = root.0.join("owned");
        fs::create_dir(&target).expect("create target");
        fs::write(root.0.join("outside"), "secret").expect("write outside file");
        std::os::unix::fs::symlink("../outside", target.join("escape"))
            .expect("create escaping symlink");
        let error = prepare_snapshot(
            &target,
            &owned,
            &owned.join("snapshot"),
            &owned.join("snapshot/manifest.json"),
        )
        .expect_err("escaping symlink must fail");
        assert!(error.to_string().contains("escapes"));
    }
}
