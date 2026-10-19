//! Public native AX data. Relationships and roles are provider facts, never inferred from text.
use agistack_core::{CoreError, CoreResult};
use serde::{Deserialize, Serialize};
use serde_json::Value;

const MAX_NODES: usize = 4096;
const MAX_DEPTH: usize = 64;
const MAX_TEXT: usize = 256 * 1024;
const MAX_STRING: usize = 16384;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CuaAxTree {
    pub version: u8,
    pub source: CuaAxSource,
    pub snapshot_id: String,
    pub window_id: String,
    pub truncated: bool,
    pub nodes: Vec<CuaAxNode>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum CuaAxSource {
    AtSpi,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CuaAxNode {
    pub element_index: usize,
    pub parent_index: Option<usize>,
    pub role: String,
    pub name: Option<String>,
    pub description: Option<String>,
    pub value: Option<String>,
    pub value_redacted: bool,
    pub states: Vec<String>,
    pub actions: Vec<String>,
    pub supports_editable_text: bool,
    pub bounds: Option<CuaAxBounds>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CuaAxBounds {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
    pub space: CuaAxCoordinateSpace,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum CuaAxCoordinateSpace {
    DesktopLogical,
}
fn invalid(reason: &str) -> CoreError {
    CoreError::Tool(format!("cua_ax_tree_invalid: {reason}"))
}

pub(crate) fn validate_output(output: &Value) -> CoreResult<()> {
    let Some(raw) = output.get("ax_tree") else {
        return Ok(());
    };
    let tree: CuaAxTree = serde_json::from_value(raw.clone()).map_err(|_| invalid("schema"))?;
    if tree.version != 1
        || tree.snapshot_id.is_empty()
        || tree.window_id.is_empty()
        || output["snapshot_id"].as_str() != Some(&tree.snapshot_id)
        || output["window_id"].as_str() != Some(&tree.window_id)
    {
        return Err(invalid("snapshot/window identity"));
    }
    if tree.nodes.len() > MAX_NODES {
        return Err(invalid("node limit"));
    }
    let mut depths = Vec::with_capacity(tree.nodes.len());
    let mut budget = MAX_TEXT;
    for (index, node) in tree.nodes.iter().enumerate() {
        if node.element_index != index
            || node.value_redacted && node.value.is_some()
            || node.states.len() > 64
            || node.actions.len() > 16
        {
            return Err(invalid("node facts"));
        }
        let depth = match node.parent_index {
            None if index == 0 => 0,
            Some(parent) if parent < index => depths[parent] + 1,
            _ => return Err(invalid("parent relationship")),
        };
        if depth > MAX_DEPTH {
            return Err(invalid("depth limit"));
        }
        depths.push(depth);
        for text in std::iter::once(node.role.as_str())
            .chain(node.name.as_deref())
            .chain(node.description.as_deref())
            .chain(node.value.as_deref())
            .chain(node.states.iter().map(String::as_str))
            .chain(node.actions.iter().map(String::as_str))
        {
            if text.len() > MAX_STRING {
                return Err(invalid("string limit"));
            }
            budget = budget
                .checked_sub(text.len())
                .ok_or_else(|| invalid("text limit"))?;
        }
        if let Some(bounds) = &node.bounds {
            if ![bounds.x, bounds.y, bounds.width, bounds.height]
                .iter()
                .all(|n| n.is_finite())
                || bounds.width < 0.0
                || bounds.height < 0.0
            {
                return Err(invalid("native bounds"));
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn observation() -> Value {
        json!({"snapshot_id":"s","window_id":"w","ax_tree":{"version":1,"source":"at_spi","snapshot_id":"s","window_id":"w","truncated":false,"nodes":[
            {"element_index":0,"parent_index":null,"role":"frame","name":"Fixture","description":null,"value":null,"value_redacted":false,"states":["active"],"actions":[],"supports_editable_text":false,"bounds":{"x":0.0,"y":0.0,"width":100.0,"height":80.0,"space":"desktop_logical"}},
            {"element_index":1,"parent_index":0,"role":"password text","name":"Native label","description":null,"value":null,"value_redacted":true,"states":[],"actions":[],"supports_editable_text":true,"bounds":null}
        ]}})
    }
    #[test]
    fn public_native_ax_tree_round_trip_retains_actual_hierarchy_and_redaction() {
        let output = observation();
        validate_output(&output).unwrap();
        let decoded: CuaAxTree = serde_json::from_value(output["ax_tree"].clone()).unwrap();
        assert_eq!(decoded.nodes[1].parent_index, Some(0));
        assert!(decoded.nodes[1].value_redacted);
        assert_eq!(serde_json::to_value(decoded).unwrap(), output["ax_tree"]);
        validate_output(&json!({"text":"old text-only observation"})).unwrap();
    }
    #[test]
    fn public_native_ax_tree_rejects_private_refs_foreign_snapshot_and_unsafe_nodes() {
        for (pointer, value) in [
            ("/ax_tree/nodes/1/backend_ref", json!("private")),
            ("/ax_tree/snapshot_id", json!("foreign")),
            ("/ax_tree/window_id", json!("foreign")),
            ("/ax_tree/nodes/1/value", json!("SECRET_FIXTURE")),
            ("/ax_tree/nodes/1/parent_index", json!(1)),
            ("/ax_tree/nodes/0/bounds/width", json!(-1)),
        ] {
            let mut output = observation();
            if pointer.ends_with("backend_ref") {
                output["ax_tree"]["nodes"][1]["backend_ref"] = value;
            } else {
                *output.pointer_mut(pointer).unwrap() = value;
            }
            assert!(validate_output(&output).is_err(), "{pointer}");
        }
    }
    #[test]
    fn public_native_ax_tree_enforces_node_depth_and_aggregate_text_limits() {
        for (count, large_text) in [(4097, false), (66, false), (17, true)] {
            let mut output = observation();
            let template = output["ax_tree"]["nodes"][0].clone();
            let nodes = (0..count)
                .map(|index| {
                    let mut node = template.clone();
                    node["element_index"] = json!(index);
                    node["parent_index"] = if index == 0 {
                        Value::Null
                    } else {
                        json!(index - 1)
                    };
                    if large_text {
                        node["name"] = json!("a".repeat(MAX_STRING));
                    }
                    node
                })
                .collect::<Vec<_>>();
            output["ax_tree"]["nodes"] = json!(nodes);
            assert!(validate_output(&output).is_err());
        }
    }
}
