//! Model-facing view of a successful single-text MCP response. The checkpoint
//! and UI retain the original wire envelope. Rich results and errors retain
//! their full envelope, including extension metadata and all content blocks.

use serde_json::Value;

/// Return structured data only when the entire envelope represents one JSON object
/// or array. Keep data strings (including filenames) inside JSON string values.
pub fn structured_observation(raw: &str) -> Option<Value> {
    let outer: Value = serde_json::from_str(raw).ok()?;
    let envelope = outer.as_object()?;
    if envelope.get("isError") != Some(&Value::Bool(false)) || envelope.len() != 2 {
        return None;
    }
    let [block] = envelope.get("content")?.as_array()?.as_slice() else {
        return None;
    };
    let block = block.as_object()?;
    if block.len() != 2 || block.get("type")?.as_str()? != "text" {
        return None;
    }
    let inner: Value = serde_json::from_str(block.get("text")?.as_str()?).ok()?;
    (inner.is_object() || inner.is_array()).then_some(inner)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn preserves_errors_metadata_mixed_blocks_and_plain_text() {
        let block = json!({"type":"text","text":"{}"});
        for value in [
            json!({"isError":true,"content":[block]}),
            json!({"isError":false,"content":[block],"_meta":{"count":1}}),
            json!({"isError":false,"content":[block,block]}),
            json!({"isError":false,"content":[{"type":"text","text":"plain"}]}),
            json!({"isError":false,"content":[{"type":"text","text":"{}","annotations":{}}]}),
        ] {
            assert!(structured_observation(&value.to_string()).is_none());
        }
    }
}
