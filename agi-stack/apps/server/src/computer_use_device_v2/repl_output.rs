//! Structural projection; only a declared capability and exact stored bindings can publish media.
use super::{
    broker::{identifier, Descriptor},
    media_storage::{Binding, MAX_BYTES},
};
use agistack_core::ports::ToolDefinition;
use serde_json::{json, Value};
use std::collections::HashSet;

pub(super) fn declared(definition: &ToolDefinition) -> bool {
    definition
        .input_schema
        .as_ref()
        .and_then(|schema| schema.get("x-agistack-display-kind"))
        .and_then(Value::as_str)
        == Some("repl_output")
}

fn ordered(definition: &ToolDefinition, output: &str, bindings: &[Binding]) -> Option<Vec<Value>> {
    if !declared(definition) {
        return None;
    }
    let output: Value = serde_json::from_str(output).ok()?;
    let empty = Vec::new();
    let texts = match output.get("outputs") {
        Some(value) => value.as_array()?,
        None => &empty,
    };
    let media = match output.get("artifacts") {
        Some(value) => value.as_array()?,
        None => &empty,
    };
    let total = texts.len().checked_add(media.len())?;
    if total == 0 || total > 256 || bindings.len() != media.len() {
        return None;
    }
    let mut text_entries = Vec::new();
    let mut media_entries = Vec::new();
    for text in texts {
        if text.get("type")?.as_str()? != "text" {
            return None;
        }
        let value = text.get("text")?.as_str()?;
        text_entries.push(json!({"kind":"text", "text":value}));
    }
    let mut ids = HashSet::new();
    let mut bound_ids = HashSet::new();
    for binding in bindings {
        if !bound_ids.insert(binding.native_id.as_str()) {
            return None;
        }
    }
    for entry in media {
        if entry.as_object()?.keys().any(|key| {
            !matches!(
                key.as_str(),
                "kind" | "artifact_id" | "mime_type" | "size_bytes" | "url" | "store"
            )
        }) {
            return None;
        }
        let kind = entry.get("kind")?.as_str()?;
        let native_id = entry.get("artifact_id")?.as_str()?;
        let mime = entry.get("mime_type")?.as_str()?;
        let size = entry.get("size_bytes")?.as_u64()?;
        if !matches!(
            (kind, mime),
            ("image", "image/png" | "image/jpeg" | "image/webp")
                | (
                    "audio",
                    "audio/wav" | "audio/x-wav" | "audio/mpeg" | "audio/ogg"
                )
        ) || !identifier(native_id)
            || !ids.insert(native_id)
            || size == 0
            || size > 9_007_199_254_740_991
        {
            return None;
        }
        let binding = bindings
            .iter()
            .find(|binding| binding.native_id == native_id)?;
        if binding.mime_type != mime || binding.size_bytes != size {
            return None;
        }
        media_entries.push(json!({"kind":kind,"artifactId":binding.artifact_id,"mimeType":mime,"sizeBytes":size,"store":"conversation_tool_media","nativeId":native_id}));
    }
    if ids != bound_ids {
        return None;
    }
    let fallback;
    let order = match output.get("output_order") {
        Some(value) => value.as_array()?,
        None => {
            if !texts.is_empty() && !media.is_empty() {
                return None;
            }
            let source = if texts.is_empty() { "media" } else { "text" };
            fallback = (0..total)
                .map(|index| json!({"source":source,"index":index}))
                .collect::<Vec<_>>();
            &fallback
        }
    };
    if order.len() != total {
        return None;
    }
    let mut seen = HashSet::new();
    let mut entries = Vec::new();
    for item in order {
        if item.as_object()?.len() != 2 {
            return None;
        }
        let source = item.get("source")?.as_str()?;
        let index: usize = item.get("index")?.as_u64()?.try_into().ok()?;
        if !seen.insert((source, index)) {
            return None;
        }
        let values = match source {
            "text" => &text_entries,
            "media" => &media_entries,
            _ => return None,
        };
        entries.push(values.get(index)?.clone());
    }
    Some(entries)
}

fn bounded(mut entries: Vec<Value>, require_stored: bool) -> Option<Vec<Value>> {
    let mut media_bytes = 0u64;
    let mut text_left = 32768usize;
    for entry in &mut entries {
        if entry["kind"] == "text" {
            let text = entry["text"].as_str()?;
            let clipped = text
                .chars()
                .take_while(|character| {
                    let count = character.len_utf16();
                    if count > text_left {
                        return false;
                    }
                    text_left -= count;
                    true
                })
                .collect::<String>();
            entry["text"] = json!(clipped);
            continue;
        }
        let size = entry["sizeBytes"].as_u64()?;
        if size > MAX_BYTES || media_bytes.checked_add(size)? > 32 * 1024 * 1024 {
            *entry = json!({"kind":"unavailable", "reason":"media_size_limit"});
            continue;
        }
        if require_stored && !entry["artifactId"].as_str().is_some_and(identifier) {
            return None;
        }
        media_bytes += size;
    }
    Some(entries)
}

pub(super) fn admitted_media(
    definition: &ToolDefinition,
    output: &str,
    descriptors: &[Descriptor],
) -> Option<HashSet<String>> {
    let bindings = descriptors
        .iter()
        .map(|descriptor| Binding {
            native_id: descriptor.artifact_id.clone(),
            artifact_id: None,
            mime_type: descriptor.mime_type.clone(),
            size_bytes: descriptor.size_bytes,
        })
        .collect::<Vec<_>>();
    let entries = bounded(ordered(definition, output, &bindings)?, false)?;
    Some(
        entries
            .into_iter()
            .filter_map(|entry| entry["nativeId"].as_str().map(str::to_owned))
            .collect(),
    )
}

pub(super) fn display(
    definition: &ToolDefinition,
    output: &str,
    bindings: &[Binding],
) -> Option<Value> {
    let mut entries = bounded(ordered(definition, output, bindings)?, true)?;
    for entry in &mut entries {
        entry.as_object_mut()?.remove("nativeId");
    }
    Some(json!({"kind":"repl_output","entries":entries}))
}
