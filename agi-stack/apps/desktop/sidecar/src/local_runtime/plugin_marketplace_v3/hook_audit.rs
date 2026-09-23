//! Bounded, scoped diagnostics independent of the private sidecar control pipes.
use serde::Serialize;
use std::{fs::OpenOptions, io::Write, path::Path, sync::Mutex};

const MAX_BYTES: u64 = 1024 * 1024;
static WRITER: Mutex<()> = Mutex::new(());

#[derive(Serialize)]
pub(super) struct Record {
    pub timestamp_ms: i64,
    pub installation_id: String,
    pub plugin_id: String,
    pub version: String,
    pub event: String,
    pub success: bool,
    pub latency_ms: u64,
}

pub(super) fn append(path: &Path, record: &Record) -> std::io::Result<()> {
    let _guard = WRITER
        .lock()
        .map_err(|_| std::io::Error::other("audit writer unavailable"))?;
    let mut bytes = serde_json::to_vec(record)?;
    bytes.push(b'\n');
    if let Ok(metadata) = std::fs::symlink_metadata(path) {
        if !metadata.is_file() {
            return Err(std::io::Error::other(
                "audit destination must be a regular file",
            ));
        }
        if metadata.len() + bytes.len() as u64 > MAX_BYTES {
            std::fs::rename(path, path.with_extension("previous.jsonl"))?;
        }
    }
    let mut options = OpenOptions::new();
    options.create(true).append(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
    }
    let mut file = options.open(path)?;
    file.write_all(&bytes)?;
    file.sync_data()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record() -> Record {
        Record {
            timestamp_ms: 1,
            installation_id: "install".into(),
            plugin_id: "plugin".into(),
            version: "1.0.0".into(),
            event: "session_start".into(),
            success: true,
            latency_ms: 1,
        }
    }

    #[test]
    fn rotates_only_owned_audit_file_and_keeps_new_record() {
        let dir = super::super::sources::Scratch::new(&std::env::temp_dir()).unwrap();
        let path = dir.0.join("hooks-audit.jsonl");
        std::fs::write(&path, vec![b' '; MAX_BYTES as usize]).unwrap();
        append(&path, &record()).unwrap();
        assert_eq!(
            std::fs::metadata(path.with_extension("previous.jsonl"))
                .unwrap()
                .len(),
            MAX_BYTES
        );
        let value: serde_json::Value =
            serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
        assert_eq!(value["event"], "session_start");
    }

    #[cfg(unix)]
    #[test]
    fn refuses_symlink_destination() {
        let dir = super::super::sources::Scratch::new(&std::env::temp_dir()).unwrap();
        let other = dir.0.join("other");
        std::fs::write(&other, "preserve").unwrap();
        let path = dir.0.join("hooks-audit.jsonl");
        std::os::unix::fs::symlink(&other, &path).unwrap();
        assert!(append(&path, &record()).is_err());
        assert_eq!(std::fs::read_to_string(other).unwrap(), "preserve");
    }
}
