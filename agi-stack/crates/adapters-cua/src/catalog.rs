//! Declarative computer-use tool contracts.
use crate::host::CuaToolEffect;
use serde_json::{json, Value};
use std::collections::BTreeMap;

pub const TOOL_LIST_APPS: &str = "computer_list_apps";
pub const TOOL_GET_APP_STATE: &str = "computer_get_app_state";
pub const TOOL_CLICK: &str = "computer_click";
pub const TOOL_TYPE_TEXT: &str = "computer_type_text";
pub const TOOL_PRESS_KEY: &str = "computer_press_key";
pub const TOOL_SCROLL: &str = "computer_scroll";
pub const TOOL_SET_VALUE: &str = "computer_set_value";
pub const TOOL_DRAG: &str = "computer_drag";
pub const TOOL_SECONDARY_ACTION: &str = "computer_secondary_action";
pub const TOOL_PASTE: &str = "computer_paste";

/// These mutations only close recordings already owned by the current native
/// session and return their receipts. They accept no destination path and must
/// remain available without a new generic mutation grant. The native host still
/// validates run/session ownership and arguments before releasing the resource.
pub const OWNED_RECORDING_RELEASE_TOOLS: &[&str] = &["computer_audio_stop"];

/// Authority-relevant effect declared per tool. The sidecar maps this onto its
/// internal `ToolMetadata` when wiring the host (mirrors
/// `authority_metadata_by_name` on the other hosts).
pub fn tool_names() -> Vec<&'static str> {
    let mut names = vec![
        TOOL_LIST_APPS,
        TOOL_GET_APP_STATE,
        TOOL_CLICK,
        TOOL_TYPE_TEXT,
        TOOL_PRESS_KEY,
        TOOL_SCROLL,
        TOOL_SET_VALUE,
        TOOL_DRAG,
        TOOL_SECONDARY_ACTION,
        TOOL_PASTE,
    ];
    names.extend(
        crate::extra_tools::contracts()
            .into_iter()
            .map(|(name, _, _)| name),
    );
    names
}

pub fn tool_effects() -> BTreeMap<&'static str, CuaToolEffect> {
    let mut effects = BTreeMap::from([
        (TOOL_LIST_APPS, CuaToolEffect::Read),
        (TOOL_GET_APP_STATE, CuaToolEffect::Read),
        (TOOL_CLICK, CuaToolEffect::Mutate),
        (TOOL_TYPE_TEXT, CuaToolEffect::Mutate),
        (TOOL_PRESS_KEY, CuaToolEffect::Mutate),
        (TOOL_SCROLL, CuaToolEffect::Mutate),
        (TOOL_SET_VALUE, CuaToolEffect::Mutate),
        (TOOL_DRAG, CuaToolEffect::Mutate),
        (TOOL_SECONDARY_ACTION, CuaToolEffect::Mutate),
        (TOOL_PASTE, CuaToolEffect::Mutate),
    ]);
    effects.extend(
        crate::extra_tools::contracts()
            .into_iter()
            .map(|(name, effect, _)| (name, effect)),
    );
    effects
}

/// Shared app-identifier property: bundle id, display name, or `pid:<n>`.
fn app_property() -> Value {
    json!({
        "type": "string",
        "description": "Target app: bundle identifier, display name, or pid:<n> \
            from computer_list_apps.",
    })
}

fn element_or_point_properties() -> Value {
    json!({
        "element_index": {
            "type": "integer",
            "description": "Element index from the latest computer_get_app_state text. \
                Element indexes are only valid against the latest observation.",
        },
        "x": { "type": "number", "description": "Window-relative X coordinate fallback." },
        "y": { "type": "number", "description": "Window-relative Y coordinate fallback." },
    })
}

pub fn tool_definitions() -> BTreeMap<&'static str, Value> {
    let mut definitions: BTreeMap<_,_> = BTreeMap::from([
        (
            TOOL_LIST_APPS,
            json!({
                "name": TOOL_LIST_APPS,
                "description": "List native running applications and declared installed \
                    application identities (read-only). Use exact IDs for launch and exact \
                    process/window IDs for control. Returns {apps: [{id, display_name, \
                    is_running, installed_id?, process_id?, identity_digest}]}.",
                "inputSchema": { "type": "object", "properties": {}, "additionalProperties": false },
            }),
        ),
        (
            TOOL_GET_APP_STATE,
            json!({
                "name": TOOL_GET_APP_STATE,
                "description": "Capture an app's accessibility tree text plus a window \
                    screenshot in one observation (read-only). The text uses [index] element \
                    markers; by default it is a diff against the previous observation. Call \
                    this again after every action before choosing the next element index. \
                    Returns {app, text, screenshot: {url, width, height, mime_type} | null}, \
                    with optional ax_tree containing native parent indices and protected-value \
                    redaction for the same snapshot/window. Screenshots are private artifact files. Use coordinate_space: screenshot \
                    for actions whose coordinates were read from the image.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "app": app_property(),
                        "disable_diff": {
                            "type": "boolean",
                            "description": "Return the full tree instead of the diff (default false).",
                        },
                    },
                    "required": ["app"],
                    "additionalProperties": false,
                },
            }),
        ),
        (
            TOOL_CLICK,
            json!({
                "name": TOOL_CLICK,
                "description": "Click an element by index from the latest app state, or a \
                    window-relative coordinate as fallback. Mutating.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "app": app_property(),
                        "element_index": element_or_point_properties()["element_index"].clone(),
                        "x": element_or_point_properties()["x"].clone(),
                        "y": element_or_point_properties()["y"].clone(),
                        "mouse_button": {
                            "type": "string",
                            "enum": ["left", "right", "middle"],
                            "description": "Defaults to left.",
                        },
                        "click_count": { "type": "integer", "minimum": 1, "maximum": 3 },
                        "key": {
                            "type": "string",
                            "description": "Optional modifier chord held during the click, \
                                e.g. 'ctrl' or 'ctrl+shift'.",
                        },
                    },
                    "required": ["app"],
                    "additionalProperties": false,
                },
            }),
        ),
    ])
    .into_iter()
    .chain([
        (
            TOOL_TYPE_TEXT,
            json!({
                "name": TOOL_TYPE_TEXT,
                "description": "Type text into the current keyboard focus of the target app. \
                    Mutating. Prefer computer_set_value or computer_paste for long content.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "app": app_property(),
                        "text": { "type": "string" },
                    },
                    "required": ["app", "text"],
                    "additionalProperties": false,
                },
            }),
        ),
        (
            TOOL_PRESS_KEY,
            json!({
                "name": TOOL_PRESS_KEY,
                "description": "Press a key or '+'-separated chord (xdotool-style names: \
                    'Return', 'Tab', 'ctrl+c', 'super+v', 'Up', 'KP_0'). Mutating.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "app": app_property(),
                        "key": { "type": "string" },
                    },
                    "required": ["app", "key"],
                    "additionalProperties": false,
                },
            }),
        ),
        (
            TOOL_SCROLL,
            json!({
                "name": TOOL_SCROLL,
                "description": "Scroll at an element index or window coordinate. Mutating.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "app": app_property(),
                        "element_index": element_or_point_properties()["element_index"].clone(),
                        "x": element_or_point_properties()["x"].clone(),
                        "y": element_or_point_properties()["y"].clone(),
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down", "left", "right"],
                            "description": "Defaults to down.",
                        },
                        "pages": { "type": "number", "minimum": 0.1, "description": "Defaults to 1." },
                    },
                    "required": ["app"],
                    "additionalProperties": false,
                },
            }),
        ),
        (
            TOOL_SET_VALUE,
            json!({
                "name": TOOL_SET_VALUE,
                "description": "Replace the value of an editable element through the \
                    accessibility API (no keystrokes). Mutating.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "app": app_property(),
                        "element_index": { "type": "integer" },
                        "value": { "type": "string" },
                    },
                    "required": ["app", "element_index", "value"],
                    "additionalProperties": false,
                },
            }),
        ),
        (
            TOOL_DRAG,
            json!({
                "name": TOOL_DRAG,
                "description": "Drag from one window-relative coordinate to another. Mutating.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "app": app_property(),
                        "from_x": { "type": "number" },
                        "from_y": { "type": "number" },
                        "to_x": { "type": "number" },
                        "to_y": { "type": "number" },
                    },
                    "required": ["app", "from_x", "from_y", "to_x", "to_y"],
                    "additionalProperties": false,
                },
            }),
        ),
        (
            TOOL_SECONDARY_ACTION,
            json!({
                "name": TOOL_SECONDARY_ACTION,
                "description": "Invoke a named accessibility action an element exposes besides \
                    press (listed in the element's actions={...}). Never guess action names. Mutating.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "app": app_property(),
                        "element_index": { "type": "integer" },
                        "action": { "type": "string" },
                    },
                    "required": ["app", "element_index", "action"],
                    "additionalProperties": false,
                },
            }),
        ),
        (
            TOOL_PASTE,
            json!({
                "name": TOOL_PASTE,
                "description": "Paste formatted or multiline content into the target app via \
                    the system pasteboard, then restore the previous clipboard contents. \
                    Mutating.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "app": app_property(),
                        "text": { "type": "string" },
                        "format": {
                            "type": "string",
                            "enum": ["text", "md", "html"],
                            "description": "Defaults to text.",
                        },
                    },
                    "required": ["app", "text"],
                    "additionalProperties": false,
                },
            }),
        ),
    ])
    .collect();
    definitions.extend(
        crate::extra_tools::contracts()
            .into_iter()
            .map(|(name, _, contract)| (name, contract)),
    );
    for (name, contract) in &mut definitions {
        let schema = &mut contract["inputSchema"];
        if let Some(props) = schema["properties"].as_object_mut() {
            if ["x", "y", "from_x", "from_y", "to_x", "to_y"]
                .into_iter()
                .any(|key| props.contains_key(key))
            {
                props.insert("coordinate_space".into(),json!({"type":"string","enum":["window","screenshot"],"default":"window","description":"Use screenshot for coordinates read from the image attachment. The host maps actual image pixels to this scoped window observation."}));
            }
            if props.contains_key("app") {
                props.insert("window_id".into(), json!({"type":"string"}));
            }
            if matches!(
                *name,
                TOOL_CLICK
                    | TOOL_TYPE_TEXT
                    | TOOL_PRESS_KEY
                    | TOOL_SCROLL
                    | TOOL_SET_VALUE
                    | TOOL_DRAG
                    | TOOL_SECONDARY_ACTION
                    | TOOL_PASTE
                    | "computer_select_text"
                    | "computer_key_down"
                    | "computer_key_up"
                    | "computer_move"
                    | "computer_drag_step"
            ) {
                props.insert("snapshot_id".into(),json!({"type":"string","minLength":1,"description":"Observation identity returned by the latest computer_get_app_state."}));
                schema["required"]
                    .as_array_mut()
                    .expect("static required")
                    .push(json!("snapshot_id"));
            }
        }
    }
    definitions
}
