//! Bounded encoding of explicit, host-authorized audio input attachments.
//!
//! The caller owns session and artifact authorization. This boundary accepts
//! typed attachments only; it never extracts paths from model or tool text.

use std::{fs::Metadata, path::Path};

use agistack_core::{
    agent::types::MediaAttachment,
    ports::{CoreError, CoreResult},
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{json, Value};
use tokio::io::AsyncReadExt;

pub(crate) const MAX_AUDIO_BYTES: u64 = 32 * 1024 * 1024;
pub(crate) const MAX_AUDIO_INPUTS: usize = 4;

pub(crate) fn is_audio(attachment: &MediaAttachment) -> bool {
    attachment.mime_type.starts_with("audio/")
}

pub(crate) fn unsupported() -> CoreError {
    CoreError::Llm("audio_input_unsupported: explicit audio input capability is unavailable".into())
}

pub(crate) async fn block(attachment: &MediaAttachment) -> CoreResult<(Value, usize)> {
    let format = match attachment.mime_type.as_str() {
        "audio/wav" | "audio/x-wav" => "wav",
        "audio/mpeg" | "audio/mp3" => "mp3",
        _ => {
            return Err(CoreError::Llm(
                "audio_input_format_unsupported: expected WAV or MP3".into(),
            ))
        }
    };
    let bytes = read_audio(attachment).await?;
    let valid = match format {
        "wav" => valid_wav(&bytes),
        "mp3" => valid_mp3(&bytes),
        _ => false,
    };
    if !valid {
        return Err(invalid());
    }
    Ok((
        json!({"type":"input_audio","input_audio":{"data":STANDARD.encode(&bytes),"format":format}}),
        bytes.len(),
    ))
}

fn invalid() -> CoreError {
    CoreError::Llm("audio_input_invalid_artifact: expected a bounded host-owned audio file".into())
}

async fn read_audio(attachment: &MediaAttachment) -> CoreResult<Vec<u8>> {
    let path = Path::new(&attachment.artifact_path);
    if !path.is_absolute() {
        return Err(invalid());
    }
    let before = tokio::fs::symlink_metadata(path)
        .await
        .map_err(|_| invalid())?;
    if !before.is_file() || before.len() == 0 || before.len() > MAX_AUDIO_BYTES {
        return Err(invalid());
    }
    let mut file = tokio::fs::File::open(path).await.map_err(|_| invalid())?;
    let opened = file.metadata().await.map_err(|_| invalid())?;
    let current = tokio::fs::symlink_metadata(path)
        .await
        .map_err(|_| invalid())?;
    if !opened.is_file()
        || !current.is_file()
        || !same_file(&before, &opened)
        || !same_file(&opened, &current)
    {
        return Err(invalid());
    }
    let mut bytes = Vec::with_capacity(opened.len() as usize);
    (&mut file)
        .take(MAX_AUDIO_BYTES + 1)
        .read_to_end(&mut bytes)
        .await
        .map_err(|_| invalid())?;
    let after = file.metadata().await.map_err(|_| invalid())?;
    if bytes.is_empty()
        || bytes.len() as u64 > MAX_AUDIO_BYTES
        || bytes.len() as u64 != opened.len()
        || !same_file(&opened, &after)
    {
        return Err(invalid());
    }
    Ok(bytes)
}

fn same_file(left: &Metadata, right: &Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if left.dev() != right.dev() || left.ino() != right.ino() {
            return false;
        }
    }
    left.len() == right.len() && left.modified().ok() == right.modified().ok()
}

fn valid_wav(bytes: &[u8]) -> bool {
    if bytes.get(..4) != Some(b"RIFF") || bytes.get(8..12) != Some(b"WAVE") {
        return false;
    }
    let Some(size) = bytes
        .get(4..8)
        .and_then(|value| <[u8; 4]>::try_from(value).ok())
    else {
        return false;
    };
    if u32::from_le_bytes(size) as u64 + 8 != bytes.len() as u64 {
        return false;
    }
    let (mut offset, mut format, mut data) = (12usize, false, false);
    while offset + 8 <= bytes.len() {
        let tag = &bytes[offset..offset + 4];
        let size = u32::from_le_bytes(
            bytes[offset + 4..offset + 8]
                .try_into()
                .expect("chunk size"),
        ) as usize;
        let Some(end) = offset
            .checked_add(8)
            .and_then(|start| start.checked_add(size))
        else {
            return false;
        };
        if end > bytes.len() {
            return false;
        }
        if tag == b"fmt " {
            if size < 16 {
                return false;
            }
            let header = &bytes[offset + 8..end];
            let encoding = u16::from_le_bytes([header[0], header[1]]);
            let channels = u16::from_le_bytes([header[2], header[3]]);
            let sample_rate = u32::from_le_bytes(header[4..8].try_into().expect("sample rate"));
            let block_align = u16::from_le_bytes([header[12], header[13]]);
            format = matches!(encoding, 1 | 3 | 0xfffe)
                && channels > 0
                && sample_rate > 0
                && block_align > 0;
        } else if tag == b"data" {
            data |= size > 0;
        }
        offset = end + size % 2;
    }
    format && data && offset == bytes.len()
}

fn valid_mp3(bytes: &[u8]) -> bool {
    let mut offset = 0;
    if bytes.get(..3) == Some(b"ID3") {
        let Some(header) = bytes.get(..10) else {
            return false;
        };
        if !matches!(header[3], 2..=4)
            || header[4] == 0xff
            || header[6..10].iter().any(|byte| byte & 0x80 != 0)
        {
            return false;
        }
        let size = header[6..10]
            .iter()
            .fold(0usize, |size, byte| (size << 7) | usize::from(*byte));
        offset = 10 + size + usize::from(header[3] == 4 && header[5] & 0x10 != 0) * 10;
    }
    let Some(frame) = bytes.get(offset..offset + 4) else {
        return false;
    };
    let version = (frame[1] >> 3) & 3;
    let bitrate = frame[2] >> 4;
    let sampling = (frame[2] >> 2) & 3;
    // MPEG Layer III frame header; reserved/free encodings are not accepted.
    frame[0] == 0xff
        && frame[1] & 0xe0 == 0xe0
        && version != 1
        && (frame[1] >> 1) & 3 == 1
        && (1..=14).contains(&bitrate)
        && sampling != 3
        && frame[3] & 3 != 2
        && bytes.len() > offset + 4
}
