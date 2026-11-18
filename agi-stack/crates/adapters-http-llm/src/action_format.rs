//! Structured-output negotiation for a model action that failed strict decoding.

use serde::Serialize;
use serde_json::{json, Value};

#[derive(Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub(super) enum ResponseFormat {
    JsonObject,
    JsonSchema { json_schema: SchemaDescriptor },
}

#[derive(Serialize)]
pub(super) struct SchemaDescriptor {
    name: &'static str,
    strict: bool,
    schema: ActionUnion,
}

#[derive(Serialize)]
struct ActionUnion {
    #[serde(rename = "oneOf")]
    alternatives: Vec<ActionBranch>,
}

#[derive(Serialize)]
struct ActionBranch {
    #[serde(rename = "type")]
    json_type: &'static str,
    properties: ActionProperties,
    required: &'static [&'static str],
    #[serde(rename = "additionalProperties")]
    additional_properties: bool,
}

// Local grammar compilers can derive output order from the order of properties
// on the wire. A serde_json::Value map would put answer before kind.
#[derive(Serialize)]
struct ActionProperties {
    kind: Value,
    #[serde(flatten)]
    fields: Value,
}

fn branch(kind: &str, fields: Value, required: &'static [&'static str]) -> ActionBranch {
    ActionBranch {
        json_type: "object",
        properties: ActionProperties {
            kind: json!({"const": kind}),
            fields,
        },
        required,
        additional_properties: false,
    }
}

/// Only a rejected request may fall back. A model response is validated once.
#[derive(Clone, Copy, Default)]
pub(super) enum ActionFormat {
    #[default]
    Default,
    Schema,
    Object,
}

impl ActionFormat {
    pub(super) fn fallback(self) -> Option<Self> {
        match self {
            Self::Schema => Some(Self::Object),
            Self::Object => Some(Self::Default),
            Self::Default => None,
        }
    }

    pub(super) fn wire(self, tools: &[String]) -> Option<ResponseFormat> {
        match self {
            Self::Default => None,
            Self::Object => Some(ResponseFormat::JsonObject),
            Self::Schema => {
                let mut actions = vec![
                    branch(
                        "finish",
                        json!({"answer":{"type":"string"}}),
                        &["kind", "answer"],
                    ),
                    branch(
                        "request_human",
                        json!({"request":{
                            "type":"object","required":["id","kind","prompt"],"properties":{
                                "id":{"type":"string"},"kind":{"enum":["clarification","decision","env_var","permission","a2ui_action"]},"prompt":{"type":"string"},
                                "decision":decision_schema(),
                                "a2ui_action":{"type":"object"},"permission_invocation":{"type":"object"}
                            }
                        }}),
                        &["kind", "request"],
                    ),
                ];
                if !tools.is_empty() {
                    actions.push(branch(
                        "call_tool",
                        json!({"tool":{"enum":tools},"input_json":{"type":"object"}}),
                        &["kind", "tool", "input_json"],
                    ));
                }
                Some(ResponseFormat::JsonSchema {
                    json_schema: SchemaDescriptor {
                        name: "agent_action",
                        strict: true,
                        schema: ActionUnion {
                            alternatives: actions,
                        },
                    },
                })
            }
        }
    }
}

fn decision_schema() -> Value {
    let text = json!({"type":"string","minLength":1});
    let optional_text = json!({"type":["string","null"]});
    let strings = json!({"type":"array","items":text});
    json!({
        "type":"object","required":["action","target","data","reason","risk","reversibility","scope","evidence"],
        "properties":{
            "action":{"type":"object","required":["name","label"],"properties":{"name":text,"label":text}},
            "target":{"type":"object","required":["kind","id"],"properties":{"kind":text,"id":text,"version_id":optional_text,"path":optional_text}},
            "data":{"type":"object","required":["summary"],"properties":{"summary":text,"redacted_fields":strings}},
            "reason":text,
            "risk":{"type":"object","required":["level","rationale"],"properties":{"level":{"enum":["low","medium","high"]},"rationale":text}},
            "reversibility":{"type":"object","required":["mode"],"properties":{"mode":{"enum":["reversible","partial","irreversible"]},"recovery":optional_text}},
            "scope":{"type":"object","required":["kind","ids"],"properties":{"kind":text,"ids":{"type":"array","minItems":1,"items":text}}},
            "evidence":{"type":"array","minItems":1,"items":{"type":"object","required":["kind","id","label"],"properties":{"kind":text,"id":text,"label":text,"uri":optional_text,"digest":optional_text}}}
        }
    })
}
