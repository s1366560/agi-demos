//! Resolves only explicitly attached, host-owned image artifacts at the HTTP boundary.

use std::path::Path;

use agistack_core::{
    agent::types::MediaAttachment,
    ports::{CoreError, CoreResult},
};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use tokio::io::AsyncReadExt;

const MAX_IMAGE_BYTES: u64 = 8 * 1024 * 1024;
const MAX_IMAGES: usize = 20;

pub(crate) async fn image_blocks(
    media: &[MediaAttachment],
    anthropic: bool,
) -> CoreResult<Vec<Value>> {
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

pub(crate) fn redact_image_payloads(value: &mut Value) {
    match value {
        Value::Array(items) => items.iter_mut().for_each(redact_image_payloads),
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
                _ => {}
            }
            object.values_mut().for_each(redact_image_payloads);
        }
        _ => {}
    }
}
