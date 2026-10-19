//! Export an exact sealed receipt before native cleanup; repeated exports reuse IDs.
use super::*;
use rusqlite::params;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

pub(super) const SOURCE_MISSING: &str = "cua_audio_source_missing";

fn source_error(error: std::io::Error) -> &'static str {
    if error.kind() == std::io::ErrorKind::NotFound {
        SOURCE_MISSING
    } else {
        "cua_audio_source_unavailable"
    }
}

pub(super) async fn export(
    state: &LocalRuntimeState,
    record: &recordings_store::Record,
) -> Result<Vec<Value>, String> {
    let sources = record.native["artifacts"]
        .as_array()
        .ok_or("cua_recording_invalid")?;
    if sources.is_empty() {
        return Err("cua_audio_empty".into());
    }
    let destination_root = state
        .app_data_dir
        .as_ref()
        .ok_or("cua_artifact_storage_unavailable")?
        .join("computer-use-artifacts");
    tokio::fs::create_dir_all(&destination_root)
        .await
        .map_err(|_| "cua_artifact_storage_unavailable")?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        tokio::fs::set_permissions(&destination_root, std::fs::Permissions::from_mode(0o700))
            .await
            .map_err(|_| "cua_artifact_permissions_failed")?;
    }
    let root = tokio::fs::canonicalize(&record.root)
        .await
        .map_err(source_error)?;
    let id = record.receipt["recording_id"]
        .as_str()
        .ok_or("cua_recording_invalid")?;
    let mut artifacts = Vec::new();
    for (index, source) in sources.iter().enumerate() {
        if source["mime_type"] != "audio/wav" || source["kind"] != "audio" {
            return Err("cua_audio_artifact_invalid".into());
        }
        let source_path = source["url"]
            .as_str()
            .and_then(|url| url::Url::parse(url).ok())
            .and_then(|url| url.to_file_path().ok())
            .ok_or("cua_audio_artifact_invalid")?;
        let meta = tokio::fs::symlink_metadata(&source_path)
            .await
            .map_err(source_error)?;
        let source_path = tokio::fs::canonicalize(&source_path)
            .await
            .map_err(source_error)?;
        if !source_path.starts_with(&root)
            || !meta.is_file()
            || meta.file_type().is_symlink()
            || !(44..=64 * 1024 * 1024).contains(&meta.len())
        {
            return Err("cua_audio_artifact_not_owned".into());
        }
        let mut input = tokio::fs::File::open(&source_path)
            .await
            .map_err(source_error)?;
        let mut header = [0; 12];
        input
            .read_exact(&mut header)
            .await
            .map_err(|_| "cua_audio_invalid")?;
        if &header[..4] != b"RIFF" || &header[8..] != b"WAVE" {
            return Err("cua_audio_invalid".into());
        }
        // A stable artifact ID makes retry after a DB/write interruption idempotent.
        let artifact_id = format!(
            "cua-audio-{}",
            Uuid::new_v5(&Uuid::NAMESPACE_OID, format!("{id}:{index}").as_bytes())
        );
        let destination = destination_root.join(format!("{artifact_id}.wav"));
        let temporary = destination_root.join(format!(".{}.tmp", Uuid::new_v4()));
        let mut options = tokio::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            options.mode(0o600);
        }
        let mut output = options
            .open(&temporary)
            .await
            .map_err(|_| "cua_artifact_copy_failed")?;
        let written = async {
            output.write_all(&header).await?;
            tokio::io::copy(&mut input.take(64 * 1024 * 1024), &mut output).await?;
            output.sync_all().await?;
            tokio::fs::rename(&temporary, &destination).await
        }
        .await;
        if written.is_err() {
            let _ = tokio::fs::remove_file(&temporary).await;
            return Err("cua_artifact_copy_failed".into());
        }
        state
            .session_store
            .connection()?
            .execute(
                "INSERT INTO desktop_cua_artifacts_v2 VALUES(?1,?2,?3,?4,?5,?6,?7,'audio/wav')
            ON CONFLICT(id) DO NOTHING",
                params![
                    artifact_id,
                    record.owner.user_id,
                    record.owner.tenant_id,
                    record.owner.project_id,
                    record.owner.device_id,
                    record.context.conversation_id,
                    destination.to_string_lossy()
                ],
            )
            .map_err(|_| "cua_artifact_save_failed")?;
        artifacts.push(json!({"artifact_id":artifact_id,"kind":"audio","mime_type":"audio/wav",
            "source":source.get("source").cloned().unwrap_or_else(||record.receipt["source"].clone())}));
    }
    Ok(artifacts)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Error, ErrorKind};

    #[test]
    fn only_not_found_marks_a_source_missing() {
        assert_eq!(source_error(ErrorKind::NotFound.into()), SOURCE_MISSING);
        for kind in [
            ErrorKind::PermissionDenied,
            ErrorKind::Interrupted,
            ErrorKind::WouldBlock,
            ErrorKind::TimedOut,
            ErrorKind::Other,
        ] {
            // A message mentioning absence cannot turn another OS condition
            // into permanent loss of the source.
            assert_eq!(
                source_error(Error::new(kind, "not found")),
                "cua_audio_source_unavailable"
            );
        }
    }
}
