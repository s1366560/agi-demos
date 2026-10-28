use agistack_core::{agent::types::MediaAttachment, ports::ToolResult};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::path::Path;
pub(super) const MEDIA_LIMIT: usize = 10 * 1024 * 1024;

pub(super) async fn from_output(
    root: &Path,
    output: &Value,
) -> Result<Option<MediaAttachment>, String> {
    let kind = output["type"].as_str().ok_or("repl_output_type_missing")?;
    if kind == "text" {
        return Ok(None);
    }
    let mime = output["mimeType"]
        .as_str()
        .ok_or("repl_output_mime_missing")?;
    let extension = match (kind, mime) {
        ("image", "image/png") => "png",
        ("image", "image/jpeg") => "jpg",
        ("image", "image/webp") => "webp",
        ("audio", "audio/wav" | "audio/x-wav") => "wav",
        ("audio", "audio/mpeg") => "mp3",
        _ => return Err("repl_output_media_unsupported".into()),
    };
    let data = output["data"].as_str().ok_or("repl_output_data_missing")?;
    if data.len() > MEDIA_LIMIT * 4 / 3 + 4 {
        return Err("repl_output_media_too_large".into());
    }
    let bytes = STANDARD
        .decode(data)
        .map_err(|_| "repl_output_media_invalid")?;
    if bytes.len() > MEDIA_LIMIT {
        return Err("repl_output_media_too_large".into());
    }
    if kind == "image" {
        let format = image::guess_format(&bytes).map_err(|_| "repl_output_image_invalid")?;
        let expected = match mime {
            "image/png" => image::ImageFormat::Png,
            "image/jpeg" => image::ImageFormat::Jpeg,
            "image/webp" => image::ImageFormat::WebP,
            _ => return Err("repl_output_media_unsupported".into()),
        };
        if format != expected {
            return Err("repl_output_image_mime_mismatch".into());
        }
        image::load_from_memory_with_format(&bytes, format)
            .map_err(|_| "repl_output_image_invalid")?;
    }
    tokio::fs::create_dir_all(root)
        .await
        .map_err(|_| "repl_artifact_storage_failed")?;
    let path = root.join(format!("{}.{}", uuid::Uuid::new_v4(), extension));
    tokio::fs::write(&path, bytes)
        .await
        .map_err(|_| "repl_artifact_write_failed")?;
    Ok(Some(MediaAttachment {
        artifact_path: path.to_string_lossy().into_owned(),
        mime_type: mime.into(),
    }))
}

/// Read only explicit, trusted attachments returned by an authorized tool host.
pub(super) async fn tool_value(result: &ToolResult) -> Result<Value, String> {
    let mut value: Value = serde_json::from_str(&result.output_json)
        .unwrap_or_else(|_| json!({"text":result.output_json}));
    let mut remaining = MEDIA_LIMIT;
    let mut attachments = Vec::new();
    for media in &result.media {
        let metadata = tokio::fs::symlink_metadata(&media.artifact_path)
            .await
            .map_err(|_| "repl_attachment_missing")?;
        if !metadata.is_file() || metadata.file_type().is_symlink() {
            return Err("repl_attachment_invalid".into());
        }
        if metadata.len() > remaining as u64 {
            attachments.push(
                json!({"mimeType":media.mime_type,"sizeBytes":metadata.len(),"inline":false}),
            );
            continue;
        }
        let bytes = tokio::fs::read(&media.artifact_path)
            .await
            .map_err(|_| "repl_attachment_read_failed")?;
        if bytes.len() > remaining {
            return Err("repl_attachment_size_changed".into());
        }
        remaining -= bytes.len();
        let data = STANDARD.encode(bytes);
        if media.mime_type.starts_with("image/") && value["screenshot"].is_object() {
            value["screenshot"]["dataBase64"] = json!(data);
            value["screenshot"]["mimeType"] = json!(media.mime_type);
        } else if media.mime_type.starts_with("image/")
            && value.is_object()
            && result.media.len() == 1
        {
            value["dataBase64"] = json!(data);
            value["mimeType"] = json!(media.mime_type);
        } else {
            attachments.push(json!({"mimeType":media.mime_type,"data":data,"inline":true}));
        }
    }
    if !attachments.is_empty() && value.is_object() {
        value["media"] = json!(attachments);
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn encoded_image(format: image::ImageFormat) -> Vec<u8> {
        let mut bytes = std::io::Cursor::new(Vec::new());
        image::DynamicImage::new_rgb8(2, 2)
            .write_to(&mut bytes, format)
            .unwrap();
        bytes.into_inner()
    }

    #[tokio::test]
    async fn image_artifacts_preserve_verified_encoding_and_matching_extensions() {
        let root =
            std::env::temp_dir().join(format!("memstack-repl-image-{}", uuid::Uuid::new_v4()));
        for (mime, extension, format) in [
            ("image/png", "png", image::ImageFormat::Png),
            ("image/jpeg", "jpg", image::ImageFormat::Jpeg),
            ("image/webp", "webp", image::ImageFormat::WebP),
        ] {
            let bytes = encoded_image(format);
            let media = from_output(
                &root,
                &json!({"type":"image","mimeType":mime,"data":STANDARD.encode(&bytes)}),
            )
            .await
            .unwrap()
            .unwrap();
            assert_eq!(media.mime_type, mime);
            assert_eq!(
                Path::new(&media.artifact_path).extension().unwrap(),
                extension
            );
            assert_eq!(tokio::fs::read(&media.artifact_path).await.unwrap(), bytes);
        }
        tokio::fs::remove_dir_all(root).await.unwrap();
    }

    #[tokio::test]
    async fn mismatched_or_corrupt_image_output_is_rejected_before_artifact_creation() {
        let root =
            std::env::temp_dir().join(format!("memstack-repl-image-{}", uuid::Uuid::new_v4()));
        let jpeg = encoded_image(image::ImageFormat::Jpeg);
        let error = from_output(
            &root,
            &json!({"type":"image","mimeType":"image/png","data":STANDARD.encode(jpeg)}),
        )
        .await
        .unwrap_err();
        assert_eq!(error, "repl_output_image_mime_mismatch");
        let error = from_output(
            &root,
            &json!({"type":"image","mimeType":"image/png","data":STANDARD.encode(b"\x89PNG\r\n\x1a\ninvalid")}),
        )
        .await
        .unwrap_err();
        assert_eq!(error, "repl_output_image_invalid");
        assert!(!root.exists());
    }

    #[tokio::test]
    async fn native_screenshot_and_audio_bytes_reach_their_facade_shapes() {
        let root =
            std::env::temp_dir().join(format!("memstack-repl-media-{}", uuid::Uuid::new_v4()));
        tokio::fs::create_dir(&root).await.unwrap();
        let path = root.join("attachment");
        tokio::fs::write(&path, b"fixture").await.unwrap();
        let mut result =
            ToolResult::text(json!({"screenshot":{"url":"cua-artifact:fixture"}}).to_string());
        result.media.push(MediaAttachment {
            artifact_path: path.to_string_lossy().into(),
            mime_type: "image/png".into(),
        });
        let value = tool_value(&result).await.unwrap();
        assert_eq!(
            value["screenshot"]["dataBase64"],
            STANDARD.encode(b"fixture")
        );
        assert!(value.get("dataBase64").is_none());
        result.output_json = json!({"recordings":[]}).to_string();
        result.media[0].mime_type = "audio/wav".into();
        let value = tool_value(&result).await.unwrap();
        assert_eq!(value["media"][0]["data"], STANDARD.encode(b"fixture"));
        assert_eq!(value["media"][0]["mimeType"], "audio/wav");
        assert!(!value.to_string().contains(path.to_str().unwrap()));
        tokio::fs::remove_dir_all(root).await.unwrap();
    }
}
