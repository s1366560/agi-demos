//! Resolves only explicitly attached, host-owned image artifacts at the HTTP boundary.

use std::path::Path;

use agistack_core::{
    agent::types::MediaAttachment,
    ports::{CoreError, CoreResult},
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{json, Value};
use tokio::io::AsyncReadExt;

const MAX_IMAGE_BYTES: u64 = 8 * 1024 * 1024;
const MAX_IMAGES: usize = 20;

pub(crate) async fn openai_blocks(
    media: &[MediaAttachment],
    vision_supported: bool,
    audio_supported: bool,
) -> CoreResult<Vec<Value>> {
    let audio_count = media
        .iter()
        .filter(|item| crate::audio::is_audio(item))
        .count();
    let image_count = media.len() - audio_count;
    // Check declared capabilities before opening any attachment, including
    // mixed input batches. Model names do not participate in this decision.
    if audio_count > 0 && !audio_supported {
        return Err(crate::audio::unsupported());
    }
    if image_count > 0 && !vision_supported {
        return Err(CoreError::Llm(
            "vision_unsupported: configured model does not accept image observations".into(),
        ));
    }
    if image_count > MAX_IMAGES {
        return Err(CoreError::Llm("vision_image_limit_exceeded".into()));
    }
    if audio_count > crate::audio::MAX_AUDIO_INPUTS {
        return Err(CoreError::Llm("audio_input_limit_exceeded".into()));
    }
    let mut audio_bytes = 0usize;
    let mut blocks = Vec::with_capacity(media.len());
    for attachment in media {
        if crate::audio::is_audio(attachment) {
            let (block, size) = crate::audio::block(attachment).await?;
            audio_bytes += size;
            if audio_bytes as u64 > crate::audio::MAX_AUDIO_BYTES {
                return Err(CoreError::Llm("audio_input_limit_exceeded".into()));
            }
            blocks.push(block);
        } else {
            blocks.extend(image_blocks(std::slice::from_ref(attachment), false).await?);
        }
    }
    Ok(blocks)
}

pub(crate) async fn image_blocks(
    media: &[MediaAttachment],
    anthropic: bool,
) -> CoreResult<Vec<Value>> {
    if media.iter().any(crate::audio::is_audio) {
        return Err(crate::audio::unsupported());
    }
    if media.len() > MAX_IMAGES {
        return Err(CoreError::Llm("vision_image_limit_exceeded".into()));
    }
    let mut blocks = Vec::with_capacity(media.len());
    for attachment in media {
        let bytes = read_image(attachment).await?;
        let encoded = STANDARD.encode(bytes);
        blocks.push(if anthropic {
            json!({"type":"image","source":{"type":"base64","media_type":attachment.mime_type,"data":encoded}})
        } else {
            json!({"type":"image_url","image_url":{"url":format!("data:{};base64,{encoded}", attachment.mime_type)}})
        });
    }
    Ok(blocks)
}

async fn read_image(attachment: &MediaAttachment) -> CoreResult<Vec<u8>> {
    let invalid =
        || CoreError::Llm("vision_invalid_artifact: expected a host-owned image file".into());
    let path = Path::new(&attachment.artifact_path);
    if !path.is_absolute()
        || !matches!(
            attachment.mime_type.as_str(),
            "image/png" | "image/jpeg" | "image/webp"
        )
    {
        return Err(invalid());
    }
    let metadata = tokio::fs::symlink_metadata(path)
        .await
        .map_err(|_| invalid())?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > MAX_IMAGE_BYTES {
        return Err(invalid());
    }
    let file = tokio::fs::File::open(path).await.map_err(|_| invalid())?;
    let mut bytes = Vec::new();
    file.take(MAX_IMAGE_BYTES + 1)
        .read_to_end(&mut bytes)
        .await
        .map_err(|_| invalid())?;
    let matches_type = match attachment.mime_type.as_str() {
        "image/png" => bytes.starts_with(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg" => bytes.starts_with(b"\xff\xd8\xff"),
        "image/webp" => bytes.starts_with(b"RIFF") && bytes.get(8..12) == Some(b"WEBP"),
        _ => false,
    };
    if bytes.len() as u64 > MAX_IMAGE_BYTES || !matches_type {
        return Err(invalid());
    }
    Ok(bytes)
}

pub(crate) fn redact_payloads(value: &mut Value) {
    match value {
        Value::Array(items) => items.iter_mut().for_each(redact_payloads),
        Value::Object(object) => {
            match object.get("type").and_then(Value::as_str) {
                Some("image_url") => {
                    if let Some(url) = object.get_mut("image_url").and_then(|v| v.get_mut("url")) {
                        *url = json!("[image payload withheld]");
                    }
                }
                Some("image") => {
                    if let Some(source) = object.get_mut("source").and_then(Value::as_object_mut) {
                        if source.get("type").and_then(Value::as_str) == Some("base64") {
                            source.insert("data".into(), json!("[image payload withheld]"));
                        }
                    }
                }
                Some("input_audio") => {
                    if let Some(data) = object
                        .get_mut("input_audio")
                        .and_then(|value| value.get_mut("data"))
                    {
                        *data = json!("[audio payload withheld]");
                    }
                }
                _ => {}
            }
            object.values_mut().for_each(redact_payloads);
        }
        _ => {}
    }
}
