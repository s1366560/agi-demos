//! Durable, conversation-owned media references, separate from native artifact IDs.
use super::{
    broker::{digest, identifier, Descriptor},
    Owner,
};
use agistack_core::ports::{CoreError, CoreResult, ObjectStore};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub(super) const MAX_BYTES: u64 = 10 * 1024 * 1024;
pub(super) const SIZE_LIMIT: &str = "computer_use_media_size_limit";
#[derive(Clone, Debug)]
pub(super) struct Binding {
    pub native_id: String,
    pub artifact_id: Option<String>,
    pub mime_type: String,
    pub size_bytes: u64,
}
#[derive(Serialize, Deserialize)]
struct Record {
    version: u8,
    owner: Owner,
    conversation_id: String,
    artifact_id: String,
    mime_type: String,
    size_bytes: u64,
    sha256: String,
}
fn invalid() -> CoreError {
    CoreError::Tool("computer_use_media_integrity_failed".into())
}
fn key(owner: &Owner, conversation: &str, id: &str) -> String {
    format!(
        "conversation-tool-media/{}/{}",
        digest(&serde_json::to_string(&(owner, conversation)).expect("serializable scope")),
        id
    )
}
pub(super) async fn save(
    objects: &dyn ObjectStore,
    owner: &Owner,
    conversation: &str,
    request: &str,
    descriptor: &Descriptor,
    bytes: &[u8],
) -> CoreResult<Binding> {
    if !matches!(
        descriptor.mime_type.as_str(),
        "image/png"
            | "image/jpeg"
            | "image/webp"
            | "audio/wav"
            | "audio/x-wav"
            | "audio/mpeg"
            | "audio/ogg"
    ) || bytes.is_empty()
        || bytes.len() as u64 != descriptor.size_bytes
        || descriptor.size_bytes > MAX_BYTES
    {
        return Err(invalid());
    }
    let artifact_id = digest(
        &serde_json::to_string(&(owner, conversation, request, &descriptor.artifact_id))
            .expect("serializable binding"),
    );
    let record = Record {
        version: 1,
        owner: owner.clone(),
        conversation_id: conversation.into(),
        artifact_id: artifact_id.clone(),
        mime_type: descriptor.mime_type.clone(),
        size_bytes: descriptor.size_bytes,
        sha256: format!("{:x}", Sha256::digest(bytes)),
    };
    let key = key(owner, conversation, &artifact_id);
    objects
        .put(
            &format!("{key}/bytes"),
            bytes.to_vec(),
            Some(&descriptor.mime_type),
        )
        .await?;
    objects
        .put(
            &format!("{key}/record"),
            serde_json::to_vec(&record).map_err(|_| invalid())?,
            Some("application/json"),
        )
        .await?;
    Ok(Binding {
        native_id: descriptor.artifact_id.clone(),
        artifact_id: Some(artifact_id),
        mime_type: descriptor.mime_type.clone(),
        size_bytes: descriptor.size_bytes,
    })
}
pub(super) async fn read(
    objects: &dyn ObjectStore,
    owner: &Owner,
    conversation: &str,
    id: &str,
) -> CoreResult<Option<(String, Vec<u8>)>> {
    if !identifier(id) {
        return Ok(None);
    }
    let key = key(owner, conversation, id);
    let record_key = format!("{key}/record");
    let Some(meta) = objects.stat(&record_key).await? else {
        return Ok(None);
    };
    if meta.size == 0 || meta.size > 8192 {
        return Err(invalid());
    }
    let Some(raw) = objects.get(&record_key).await? else {
        return Ok(None);
    };
    if raw.len() as u64 != meta.size {
        return Err(invalid());
    }
    let record: Record = serde_json::from_slice(&raw).map_err(|_| invalid())?;
    if record.version != 1
        || record.owner != *owner
        || record.conversation_id != conversation
        || record.artifact_id != id
        || record.size_bytes == 0
        || !matches!(
            record.mime_type.as_str(),
            "image/png"
                | "image/jpeg"
                | "image/webp"
                | "audio/wav"
                | "audio/x-wav"
                | "audio/mpeg"
                | "audio/ogg"
        )
    {
        return Err(invalid());
    }
    if record.size_bytes > MAX_BYTES {
        return Err(CoreError::Tool(SIZE_LIMIT.into()));
    }
    let bytes_key = format!("{key}/bytes");
    let Some(meta) = objects.stat(&bytes_key).await? else {
        return Ok(None);
    };
    if meta.size != record.size_bytes
        || meta.content_type.as_deref() != Some(record.mime_type.as_str())
    {
        return Err(invalid());
    }
    let Some(bytes) = objects.get(&bytes_key).await? else {
        return Ok(None);
    };
    if bytes.len() as u64 != record.size_bytes
        || format!("{:x}", Sha256::digest(&bytes)) != record.sha256
    {
        return Err(invalid());
    }
    Ok(Some((record.mime_type, bytes)))
}

pub(super) fn valid_bytes(bytes: &[u8], mime: &str, repl: bool) -> bool {
    match mime {
        "image/png" => bytes.starts_with(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg" => bytes.starts_with(b"\xff\xd8\xff"),
        "image/webp" => bytes.starts_with(b"RIFF") && bytes.get(8..12) == Some(b"WEBP"),
        "audio/wav" => bytes.starts_with(b"RIFF") && bytes.get(8..12) == Some(b"WAVE"),
        "audio/x-wav" if repl => bytes.starts_with(b"RIFF") && bytes.get(8..12) == Some(b"WAVE"),
        "audio/mpeg" if repl => {
            (bytes.len() >= 10 && bytes.starts_with(b"ID3"))
                || (bytes.len() >= 4
                    && bytes[0] == 0xff
                    && bytes[1] & 0xe0 == 0xe0
                    && bytes[1] & 0x18 != 0x08
                    && bytes[1] & 0x06 != 0
                    && !matches!(bytes[2] >> 4, 0 | 15)
                    && (bytes[2] >> 2) & 3 != 3)
        }
        _ => false,
    }
}
