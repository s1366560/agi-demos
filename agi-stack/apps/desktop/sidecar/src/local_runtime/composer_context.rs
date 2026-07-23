use std::collections::HashSet;

use serde::{Deserialize, Serialize};
use serde_json::Value;

const MAX_CONTEXT_ITEMS: usize = 32;
const MAX_RESOURCE_ID_CHARS: usize = 512;
const MAX_LABEL_CHARS: usize = 255;
const MAX_METADATA_BYTES: usize = 4 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ComposerContextKind {
    Attachment,
    Agent,
    Skill,
    Plugin,
    Command,
    Thread,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ComposerContextItem {
    pub(super) kind: ComposerContextKind,
    pub(super) resource_id: String,
    pub(super) label: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(super) metadata: Option<Value>,
}

pub(super) fn validate_composer_context_items(
    items: &[ComposerContextItem],
) -> Result<(), &'static str> {
    if items.len() > MAX_CONTEXT_ITEMS {
        return Err("context_items cannot contain more than 32 items");
    }
    let mut identities = HashSet::new();
    for item in items {
        let resource_id = item.resource_id.trim();
        let label = item.label.trim();
        if resource_id.is_empty()
            || resource_id.chars().count() > MAX_RESOURCE_ID_CHARS
            || label.is_empty()
            || label.chars().count() > MAX_LABEL_CHARS
        {
            return Err("context item resource_id or label is invalid");
        }
        if !identities.insert((item.kind, resource_id)) {
            return Err("context_items cannot contain duplicate resources");
        }
        if item
            .metadata
            .as_ref()
            .is_some_and(|metadata| metadata.to_string().len() > MAX_METADATA_BYTES)
        {
            return Err("context item metadata is too large");
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{
        validate_composer_context_items, ComposerContextItem, ComposerContextKind,
        MAX_CONTEXT_ITEMS,
    };

    fn item(kind: ComposerContextKind, resource_id: &str) -> ComposerContextItem {
        ComposerContextItem {
            kind,
            resource_id: resource_id.to_string(),
            label: resource_id.to_string(),
            metadata: None,
        }
    }

    #[test]
    fn accepts_structured_context_with_bounded_metadata() {
        let mut attachment = item(ComposerContextKind::Attachment, "file:brief.pdf:42:7");
        attachment.metadata = Some(json!({"size_bytes": 42, "mime_type": "application/pdf"}));
        assert!(validate_composer_context_items(&[
            attachment,
            item(ComposerContextKind::Command, "/review"),
        ])
        .is_ok());
    }

    #[test]
    fn rejects_duplicates_and_oversized_collections() {
        let duplicate = item(ComposerContextKind::Skill, "review");
        assert!(validate_composer_context_items(&[duplicate.clone(), duplicate]).is_err());
        let oversized = (0..=MAX_CONTEXT_ITEMS)
            .map(|index| item(ComposerContextKind::Thread, &format!("thread-{index}")))
            .collect::<Vec<_>>();
        assert!(validate_composer_context_items(&oversized).is_err());
    }
}
