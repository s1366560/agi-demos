use serde::Deserialize;

use agistack_core::model::Entity;
use agistack_core::ports::{CoreError, CoreResult, MemoryDraft, RelationshipDraft};

/// The draft shape we ask the model to return. Mirrors [`MemoryDraft`] but is a
/// `Deserialize` wire type; entities reuse the core [`Entity`], which is serde.
#[derive(Deserialize)]
struct DraftWire {
    title: String,
    content: String,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    entities: Vec<Entity>,
}

pub(super) fn parse_memory_draft(content: &str) -> CoreResult<MemoryDraft> {
    let wire: DraftWire = serde_json::from_str(clean_structured(content))
        .map_err(|e| CoreError::Llm(format!("bad draft json: {e}")))?;
    Ok(MemoryDraft {
        title: wire.title,
        content: wire.content,
        tags: wire.tags,
        entities: wire.entities,
    })
}

#[derive(Deserialize)]
struct RelationshipDraftWire {
    source: String,
    target: String,
    #[serde(default)]
    relation_type: Option<String>,
    #[serde(default)]
    fact: Option<String>,
    #[serde(default)]
    score: Option<f32>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum RelationshipDraftPayload {
    Wrapped {
        #[serde(default)]
        relationships: Vec<RelationshipDraftWire>,
    },
    Bare(Vec<RelationshipDraftWire>),
}

pub(super) fn parse_relationship_drafts(content: &str) -> CoreResult<Vec<RelationshipDraft>> {
    let payload: RelationshipDraftPayload = serde_json::from_str(clean_structured(content))
        .map_err(|e| CoreError::Llm(format!("bad relationship json: {e}")))?;
    let relationships = match payload {
        RelationshipDraftPayload::Wrapped { relationships } => relationships,
        RelationshipDraftPayload::Bare(relationships) => relationships,
    };
    Ok(relationships
        .into_iter()
        .map(|wire| RelationshipDraft {
            source: wire.source,
            target: wire.target,
            relation_type: wire
                .relation_type
                .filter(|value| !value.trim().is_empty())
                .unwrap_or_else(|| "RELATED_TO".to_string()),
            fact: wire.fact.unwrap_or_default(),
            score: wire.score.unwrap_or(0.8),
        })
        .collect())
}

/// Strip a leading reasoning block that "thinking" models (MiniMax-M2,
/// DeepSeek-R1, QwQ, GLM in reasoning mode...) prepend to the answer, e.g.
/// `<think> ... </think>\n\n{json}`. Returns the text after the closing tag; if
/// there is no well-formed `<think>...</think>` wrapper the input is returned
/// unchanged. This runs before [`strip_fences`] so structured JSON survives a
/// reasoning preamble.
fn strip_reasoning(s: &str) -> &str {
    let t = s.trim_start();
    let Some(rest) = t.strip_prefix("<think>") else {
        return s;
    };
    match rest.find("</think>") {
        Some(i) => rest[i + "</think>".len()..].trim_start(),
        // Unterminated reasoning block (truncated output): nothing usable after it.
        None => "",
    }
}

/// Strip a leading/trailing Markdown code fence (```json ... ```), which models
/// frequently wrap JSON in. Returns the inner text trimmed.
fn strip_fences(s: &str) -> &str {
    let t = s.trim();
    let Some(rest) = t.strip_prefix("```") else {
        return t;
    };
    // Drop the optional language tag on the first line, then the trailing fence.
    let rest = rest.split_once('\n').map(|(_, rest)| rest).unwrap_or("");
    rest.trim().strip_suffix("```").unwrap_or(rest).trim()
}

/// Clean a model's chat content into the raw structured payload: drop a leading
/// reasoning block, then any Markdown code fence.
pub(super) fn clean_structured(content: &str) -> &str {
    strip_fences(strip_reasoning(content))
}

#[cfg(test)]
mod tests {
    use super::{clean_structured, parse_relationship_drafts, strip_fences, strip_reasoning};

    #[test]
    fn strip_fences_handles_plain_and_fenced() {
        assert_eq!(strip_fences(r#"{"a":1}"#), r#"{"a":1}"#);
        assert_eq!(strip_fences("```json\n{\"a\":1}\n```"), r#"{"a":1}"#);
        assert_eq!(strip_fences("```\n{\"a\":1}\n```"), r#"{"a":1}"#);
    }

    #[test]
    fn strip_reasoning_removes_leading_think_block() {
        assert_eq!(strip_reasoning(r#"{"a":1}"#), r#"{"a":1}"#);
        assert_eq!(
            strip_reasoning("<think>let me consider</think>\n\n{\"a\":1}"),
            r#"{"a":1}"#
        );
        assert_eq!(strip_reasoning("  <think>x</think> hi"), "hi");
        assert_eq!(strip_reasoning("<think>cut off"), "");
    }

    #[test]
    fn clean_structured_strips_reasoning_then_fences() {
        assert_eq!(
            clean_structured("<think>reasoning...</think>\n```json\n{\"a\":1}\n```"),
            r#"{"a":1}"#
        );
    }

    #[test]
    fn parse_relationship_drafts_accepts_wrapped_and_defaults_optional_fields() {
        let got = parse_relationship_drafts(
            r#"{"relationships":[{"source":"Rust","target":"GraphStore"}]}"#,
        )
        .expect("parse relationships");
        assert_eq!(got.len(), 1);
        assert_eq!(got[0].relation_type, "RELATED_TO");
        assert_eq!(got[0].fact, "");
        assert_eq!(got[0].score, 0.8);
    }
}
