//! Large audio crosses the interpreter boundary as a private-directory basename.
//! Opening relative to a pinned directory descriptor excludes path/symlink races.
use agistack_core::agent::types::MediaAttachment;
use serde_json::Value;
use std::path::Path;

pub(super) async fn materialize(
    destination: &Path,
    temporary: &Path,
    output: &Value,
) -> Result<(MediaAttachment, usize), String> {
    if output["type"] != "audio" || output["mimeType"] != "audio/wav" {
        return Err("repl_file_media_type_invalid".into());
    }
    let name = output["filename"]
        .as_str()
        .filter(|name| {
            !name.is_empty() && *name != "." && *name != ".." && !name.contains(['/', '\\', '\0'])
        })
        .ok_or("repl_file_media_name_invalid")?
        .to_owned();
    let root = temporary.to_path_buf();
    let destination = destination.to_path_buf();
    tokio::task::spawn_blocking(move || copy_audio(&root, &destination, &name))
        .await
        .map_err(|_| "repl_file_media_worker_failed")?
}

#[cfg(unix)]
fn copy_audio(
    root: &Path,
    destination: &Path,
    name: &str,
) -> Result<(MediaAttachment, usize), String> {
    use std::{
        ffi::CString,
        fs::OpenOptions,
        io::{Read, Seek, SeekFrom},
        os::{
            fd::{AsRawFd, FromRawFd},
            unix::fs::OpenOptionsExt,
        },
    };
    let directory = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW)
        .open(root)
        .map_err(|_| "repl_file_media_directory_invalid")?;
    let name = CString::new(name).map_err(|_| "repl_file_media_name_invalid")?;
    // SAFETY: both descriptors remain owned by File, and CString is NUL terminated.
    let fd = unsafe {
        libc::openat(
            directory.as_raw_fd(),
            name.as_ptr(),
            libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK,
        )
    };
    if fd < 0 {
        return Err("repl_file_media_not_owned".into());
    }
    // SAFETY: openat returned a fresh descriptor exclusively owned here.
    let mut input = unsafe { std::fs::File::from_raw_fd(fd) };
    let metadata = input
        .metadata()
        .map_err(|_| "repl_file_media_unavailable")?;
    if !metadata.is_file() || !(44..=64 * 1024 * 1024).contains(&metadata.len()) {
        return Err("repl_file_media_invalid".into());
    }
    let mut header = [0; 12];
    input
        .read_exact(&mut header)
        .map_err(|_| "repl_file_media_invalid")?;
    if &header[..4] != b"RIFF" || &header[8..] != b"WAVE" {
        return Err("repl_file_media_invalid".into());
    }
    input
        .seek(SeekFrom::Start(0))
        .map_err(|_| "repl_file_media_invalid")?;
    std::fs::create_dir_all(destination).map_err(|_| "repl_artifact_storage_failed")?;
    let path = destination.join(format!("{}.wav", uuid::Uuid::new_v4()));
    let mut target = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .map_err(|_| "repl_artifact_write_failed")?;
    let copied = std::io::copy(&mut input.take(64 * 1024 * 1024 + 1), &mut target);
    if copied.as_ref().is_err() || copied.ok() != Some(metadata.len()) {
        let _ = std::fs::remove_file(&path);
        return Err("repl_file_media_changed".into());
    }
    Ok((
        MediaAttachment {
            artifact_path: path.to_string_lossy().into_owned(),
            mime_type: "audio/wav".into(),
        },
        usize::try_from(metadata.len()).map_err(|_| "repl_file_media_invalid")?,
    ))
}

#[cfg(not(unix))]
fn copy_audio(_: &Path, _: &Path, _: &str) -> Result<(MediaAttachment, usize), String> {
    Err("repl_file_media_unsupported".into())
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use serde_json::json;

    #[tokio::test]
    async fn large_private_wave_is_copied_without_a_large_control_frame() {
        let root = std::env::temp_dir().join(format!("cua-file-media-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let source = root.join("owned.wav");
        let mut header = b"RIFF".to_vec();
        header.extend_from_slice(&28_800_036u32.to_le_bytes());
        header.extend_from_slice(b"WAVE");
        std::fs::write(&source, header).unwrap();
        std::fs::OpenOptions::new()
            .write(true)
            .open(&source)
            .unwrap()
            .set_len(28_800_044)
            .unwrap();
        let output = json!({"type":"audio","mimeType":"audio/wav","filename":"owned.wav"});
        assert!(output.to_string().len() < 128);
        let (media, bytes) = materialize(&root.join("output"), &root, &output)
            .await
            .unwrap();
        assert_eq!(bytes, 28_800_044);
        assert_eq!(
            std::fs::metadata(media.artifact_path).unwrap().len(),
            28_800_044
        );
        for name in [
            "../owned.wav",
            "/etc/passwd",
            "output/owned.wav",
            ".",
            "..",
            "",
        ] {
            assert!(materialize(
                &root.join("output"),
                &root,
                &json!({"type":"audio","mimeType":"audio/wav","filename":name})
            )
            .await
            .is_err());
        }
        std::os::unix::fs::symlink(&source, root.join("symlink.wav")).unwrap();
        assert!(materialize(
            &root.join("output"),
            &root,
            &json!({"type":"audio","mimeType":"audio/wav","filename":"symlink.wav"})
        )
        .await
        .is_err());
        std::os::unix::fs::symlink(&root, root.with_extension("symlink")).unwrap();
        assert!(materialize(
            &root.join("output"),
            &root.with_extension("symlink"),
            &output
        )
        .await
        .is_err());
        std::fs::remove_file(root.with_extension("symlink")).unwrap();
        std::fs::remove_dir_all(root).unwrap();
    }
}
