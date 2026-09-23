//! Snapshot ownership and OS-held leases; only registered snapshot roots are reclaimable.
use super::*;
use std::{
    fs::{File, OpenOptions},
    path::{Path as FsPath, PathBuf},
};
#[derive(Clone, Serialize, Deserialize)]
pub(super) struct Snapshot {
    path: PathBuf,
    created_at: i64,
}
pub(in crate::local_runtime) struct Lease {
    file: Option<File>,
    lease_path: PathBuf,
    snapshot: PathBuf,
}
#[cfg(unix)]
fn lock(file: &File) -> bool {
    use std::os::fd::AsRawFd;
    unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) == 0 }
}
#[cfg(not(unix))]
fn lock(_file: &File) -> bool {
    true
}
fn open_lock(path: &FsPath, create: bool) -> std::io::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(create);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(0);
    }
    options.open(path)
}
fn paths(snapshot: &FsPath) -> PackageResult<(PathBuf, PathBuf)> {
    let id = snapshot
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or("snapshot_path_invalid")?;
    uuid::Uuid::parse_str(id).map_err(|_| "snapshot_path_invalid")?;
    let snapshots = snapshot.parent().ok_or("snapshot_path_invalid")?;
    if snapshots.file_name().and_then(|name| name.to_str()) != Some("snapshots") {
        return Err("snapshot_path_invalid".into());
    }
    let root = snapshots.parent().ok_or("snapshot_path_invalid")?;
    Ok((root.join("leases").join(id), root.join("retired").join(id)))
}
pub(in crate::local_runtime) fn lease(snapshot: &FsPath) -> PackageResult<Lease> {
    let (directory, retired) = paths(snapshot)?;
    if retired.exists() || !snapshot.is_dir() {
        return Err("snapshot_is_retired".into());
    }
    std::fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
    let lease_path = directory.join(uuid::Uuid::new_v4().to_string());
    let file = open_lock(&lease_path, true).map_err(|e| e.to_string())?;
    if !lock(&file) {
        let _ = std::fs::remove_file(&lease_path);
        return Err("snapshot_lease_unavailable".into());
    }
    // A collector that retired between the checks must observe this held lease.
    if retired.exists() {
        drop(file);
        let _ = std::fs::remove_file(&lease_path);
        return Err("snapshot_is_retired".into());
    }
    Ok(Lease {
        file: Some(file),
        lease_path,
        snapshot: snapshot.to_owned(),
    })
}
impl Drop for Lease {
    fn drop(&mut self) {
        drop(self.file.take());
        let _ = std::fs::remove_file(&self.lease_path);
        let _ = reap(&self.snapshot);
    }
}
fn busy(snapshot: &FsPath) -> PackageResult<bool> {
    let (directory, _) = paths(snapshot)?;
    if !directory.exists() {
        return Ok(false);
    }
    for entry in std::fs::read_dir(&directory).map_err(|e| e.to_string())? {
        let path = entry.map_err(|e| e.to_string())?.path();
        let file = match open_lock(&path, false) {
            Ok(file) => file,
            Err(_) => return Ok(true),
        };
        if !lock(&file) {
            return Ok(true);
        }
        drop(file);
        std::fs::remove_file(path).map_err(|e| e.to_string())?;
    }
    Ok(false)
}
fn size(path: &FsPath) -> PackageResult<u64> {
    if !path.exists() {
        return Ok(0);
    }
    let metadata = std::fs::symlink_metadata(path).map_err(|e| e.to_string())?;
    if metadata.file_type().is_symlink() {
        return Err("snapshot_symlink_rejected".into());
    }
    if metadata.is_file() {
        return Ok(metadata.len());
    }
    let mut bytes = 0;
    for entry in std::fs::read_dir(path).map_err(|e| e.to_string())? {
        bytes += size(&entry.map_err(|e| e.to_string())?.path())?;
    }
    Ok(bytes)
}
fn reap(snapshot: &FsPath) -> PackageResult<bool> {
    let (_, retired) = paths(snapshot)?;
    if !retired.is_file() || busy(snapshot)? {
        return Ok(false);
    }
    let registered = std::fs::read_to_string(&retired).map_err(|e| e.to_string())?;
    if registered != snapshot.to_string_lossy() {
        return Err("snapshot_ownership_invalid".into());
    }
    size(snapshot)?; // Reject links before removing any owned tree.
    if snapshot.exists() {
        std::fs::remove_dir_all(snapshot).map_err(|e| e.to_string())?;
    }
    std::fs::remove_file(retired).map_err(|e| e.to_string())?;
    Ok(true)
}
pub(super) fn register(data: &mut Database, path: &FsPath) {
    data.snapshots
        .entry(path.to_string_lossy().into_owned())
        .or_insert_with(|| Snapshot {
            path: path.into(),
            created_at: chrono::Utc::now().timestamp(),
        });
}
pub(super) fn collect(root: &FsPath, data: &mut Database, cleanup: bool) -> PackageResult<Value> {
    let now = chrono::Utc::now().timestamp();
    if std::fs::symlink_metadata(root.join("snapshots"))
        .is_ok_and(|metadata| metadata.file_type().is_symlink())
    {
        return Err("snapshot_symlink_rejected".into());
    }
    // Upgrade existing task-owned metadata without scanning arbitrary directories.
    let known = data
        .preflights
        .values()
        .map(|p| p.package.root.clone())
        .chain(data.installations.iter().map(|i| i.package.root.clone()))
        .collect::<Vec<_>>();
    for path in known {
        register(data, &path);
    }
    let live = data
        .installations
        .iter()
        .filter(|i| i.status != "uninstalled")
        .map(|i| i.package.root.clone())
        .chain(
            data.transition
                .iter()
                .map(|t| t.replacement.package.root.clone()),
        )
        .chain(
            data.preflights
                .values()
                .filter(|p| p.created_at + 86400 > now)
                .map(|p| p.package.root.clone()),
        )
        .collect::<std::collections::BTreeSet<_>>();
    let mut total = 0;
    let mut reclaimable = 0;
    let mut entries = 0;
    let mut removed = 0;
    let mut removed_entries = 0;
    for item in data.snapshots.values() {
        if item.path.parent() != Some(root.join("snapshots").as_path()) {
            return Err("snapshot_scope_invalid".into());
        }
        let bytes = size(&item.path)?;
        total += bytes;
        if item.path.exists() {
            entries += 1;
        }
        if live.contains(&item.path) {
            continue;
        }
        if !busy(&item.path)? {
            reclaimable += bytes;
        }
        if cleanup {
            let (_, marker) = paths(&item.path)?;
            std::fs::create_dir_all(marker.parent().ok_or("snapshot_path_invalid")?)
                .map_err(|e| e.to_string())?;
            std::fs::write(&marker, item.path.to_string_lossy().as_bytes())
                .map_err(|e| e.to_string())?;
            if reap(&item.path)? {
                removed += bytes;
                if bytes > 0 {
                    removed_entries += 1;
                }
            }
        }
    }
    if cleanup {
        data.preflights.retain(|_, p| p.created_at + 86400 > now);
        data.snapshots.retain(|_, item| item.path.exists());
    }
    Ok(
        json!({"total_bytes":total,"reclaimable_bytes":reclaimable,"entries":entries,"removed_bytes":removed,"removed_entries":removed_entries}),
    )
}
pub(super) async fn stats(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Query(scope): Query<Scope>,
) -> Response {
    authorize(&auth, &scope, false)?;
    let _guard = MUTATION.lock().await;
    let root = auth_root(&state, &auth)?;
    let mut data = load(&root).map_err(fail)?;
    Ok(Json(collect(&root, &mut data, false).map_err(fail)?))
}
pub(super) async fn cleanup(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(body): Json<Request>,
) -> Response {
    authorize(&auth, &body.scope, true)?;
    let _guard = MUTATION.lock().await;
    let root = auth_root(&state, &auth)?;
    let mut data = load(&root).map_err(fail)?;
    if let Some(result) = receipt(&data, &body, "cache:cleanup")? {
        return Ok(Json(result));
    }
    let result = collect(&root, &mut data, true).map_err(fail)?;
    finish(&root, &mut data, &body, "cache:cleanup", result)
}
