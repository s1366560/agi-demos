//! Reconnect inputs are freshly read capabilities, never a cached fallback.

use super::{BridgeRegistry, BridgeTransport};
use std::{fs::Metadata, io::Read, path::Path};

const MAX_REGISTRY_BYTES: u64 = 64 * 1024;

pub(super) fn load_registry(path: &Path) -> Result<BridgeRegistry, String> {
    let directory = path
        .parent()
        .ok_or("browser bridge registry has no directory")?;
    let parent = private_metadata(directory, FileKind::Directory)?;
    let named = private_metadata(path, FileKind::Regular)?;
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    let file = options
        .open(path)
        .map_err(|_| "browser bridge registry is unreadable")?;
    let opened = file
        .metadata()
        .map_err(|_| "browser bridge registry metadata is unreadable")?;
    validate_metadata(&opened, FileKind::Regular)?;
    ensure_same_file(&named, &opened)?;
    let mut bytes = Vec::new();
    (&file)
        .take(MAX_REGISTRY_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "browser bridge registry is unreadable")?;
    if bytes.len() as u64 > MAX_REGISTRY_BYTES {
        return Err("browser bridge registry exceeds its size limit".into());
    }
    let after = file
        .metadata()
        .map_err(|_| "browser bridge registry metadata is unreadable")?;
    ensure_same_file(&opened, &after)?;
    ensure_same_file(&after, &private_metadata(path, FileKind::Regular)?)?;
    ensure_same_file(&parent, &private_metadata(directory, FileKind::Directory)?)?;
    // Parser diagnostics may quote input. Never include them in credential logs.
    let registry: BridgeRegistry = serde_json::from_slice(&bytes)
        .map_err(|_| "browser bridge registry is invalid".to_string())?;
    crate::local_runtime::browser_bridge::validate_registry(&registry)?;
    Ok(registry)
}

/// An advertised private socket must remain private. Missing, replaced or
/// invalid sockets retry later; they never cause a downgrade to loopback TCP.
pub(super) fn transport(path: &Path, registry: &BridgeRegistry) -> Result<BridgeTransport, String> {
    match &registry.socket_path {
        Some(socket) => {
            #[cfg(unix)]
            {
                if path
                    .parent()
                    .map(|parent| parent.join("bridge.sock"))
                    .as_deref()
                    != Some(Path::new(socket))
                {
                    return Err("browser bridge socket is outside its registry directory".into());
                }
                socket_identity(Path::new(socket))?;
                Ok(BridgeTransport::Unix(socket.clone()))
            }
            #[cfg(not(unix))]
            {
                Err("browser bridge unix transport is unsupported on this platform".into())
            }
        }
        None => Ok(BridgeTransport::Tcp(registry.ws_url.clone())),
    }
}

#[derive(Clone, Copy)]
enum FileKind {
    Regular,
    Directory,
    #[cfg(unix)]
    Socket,
}

fn private_metadata(path: &Path, kind: FileKind) -> Result<Metadata, String> {
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|_| "browser bridge private path is unavailable")?;
    validate_metadata(&metadata, kind)?;
    Ok(metadata)
}

fn validate_metadata(metadata: &Metadata, kind: FileKind) -> Result<(), String> {
    let correct_kind = match kind {
        FileKind::Regular => metadata.file_type().is_file(),
        FileKind::Directory => metadata.file_type().is_dir(),
        #[cfg(unix)]
        FileKind::Socket => {
            use std::os::unix::fs::FileTypeExt;
            metadata.file_type().is_socket()
        }
    };
    if !correct_kind {
        return Err("browser bridge private path has an invalid file type".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.uid() != effective_uid() || metadata.mode() & 0o077 != 0 {
            return Err("browser bridge private path has invalid owner or permissions".into());
        }
    }
    Ok(())
}

fn ensure_same_file(before: &Metadata, after: &Metadata) -> Result<(), String> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if (before.dev(), before.ino(), before.uid(), before.mode())
            != (after.dev(), after.ino(), after.uid(), after.mode())
        {
            return Err("browser bridge private path changed during access".into());
        }
    }
    if before.len() != after.len() || before.modified().ok() != after.modified().ok() {
        return Err("browser bridge private path changed during access".into());
    }
    Ok(())
}

#[cfg(unix)]
fn effective_uid() -> u32 {
    // SAFETY: geteuid has no preconditions and cannot fail.
    unsafe { libc::geteuid() }
}

#[cfg(unix)]
pub(super) fn socket_identity(path: &Path) -> Result<(Metadata, Metadata), String> {
    let parent = path
        .parent()
        .ok_or("browser bridge socket has no directory")?;
    Ok((
        private_metadata(parent, FileKind::Directory)?,
        private_metadata(path, FileKind::Socket)?,
    ))
}

#[cfg(unix)]
pub(super) fn verify_connected_socket(
    path: &Path,
    before: &(Metadata, Metadata),
    peer_uid: u32,
) -> Result<(), String> {
    if peer_uid != effective_uid() {
        return Err("browser bridge socket peer belongs to a different user".into());
    }
    let after = socket_identity(path)?;
    ensure_same_file(&before.0, &after.0)?;
    ensure_same_file(&before.1, &after.1)
}

#[cfg(all(test, unix))]
#[path = "connection_tests.rs"]
mod tests;
