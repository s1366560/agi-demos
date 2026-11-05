//! Additional declared capabilities; runtime support is reported by the helper.
use crate::host::CuaToolEffect;
use serde_json::{json, Value};

fn contract(name: &str, description: &str, properties: Value, required: &[&str]) -> Value {
    json!({"name":name,"description":description,"inputSchema":{
        "type":"object","properties":properties,"required":required,"additionalProperties":false}})
}
pub(super) fn contracts() -> Vec<(&'static str, CuaToolEffect, Value)> {
    use CuaToolEffect::{Mutate, Read};
    let app = json!({"type":"string","minLength":1});
    vec![
        (
            "computer_capabilities",
            Read,
            contract(
                "computer_capabilities",
                "Report actual native capabilities and permission requirements.",
                json!({}),
                &[],
            ),
        ),
        (
            "computer_list_windows",
            Read,
            contract(
                "computer_list_windows",
                "List exact window identities for an application.",
                json!({"app":app}),
                &["app"],
            ),
        ),
        (
            "computer_launch_app",
            Mutate,
            contract(
                "computer_launch_app",
                "Launch a declared installed application by its exact identity; does not execute shell commands.",
                json!({"app":app}),
                &["app"],
            ),
        ),
        (
            "computer_activate_app",
            Mutate,
            contract(
                "computer_activate_app",
                "Bring an application/window to the foreground only when the user explicitly requests it and device settings select foreground input. Background input does not require activation; never use this as a fallback for unsupported background input.",
                json!({"app":app}),
                &["app"],
            ),
        ),
        (
            "computer_select_text",
            Mutate,
            contract(
                "computer_select_text",
                "Select exact text in an observed editable element.",
                json!({"app":app,"element_index":{"type":"integer","minimum":0},"text":{"type":"string","minLength":1},"prefix":{"type":"string"},"suffix":{"type":"string"},"cursor":{"type":"string","enum":["select","before","after"]}}),
                &["app", "element_index", "text"],
            ),
        ),
        (
            "computer_key_down",
            Mutate,
            contract(
                "computer_key_down",
                "Hold a declared key chord until key_up or session stop.",
                json!({"app":app,"key":{"type":"string","minLength":1}}),
                &["app", "key"],
            ),
        ),
        (
            "computer_key_up",
            Mutate,
            contract(
                "computer_key_up",
                "Release a held key chord.",
                json!({"app":app,"key":{"type":"string","minLength":1}}),
                &["app", "key"],
            ),
        ),
        (
            "computer_move",
            Mutate,
            contract(
                "computer_move",
                "Move to an observed window-relative point.",
                json!({"app":app,"x":{"type":"number"},"y":{"type":"number"}}),
                &["app", "x", "y"],
            ),
        ),
        (
            "computer_drag_step",
            Mutate,
            contract(
                "computer_drag_step",
                "Begin, move, or finish a drag; stop always releases the pointer.",
                json!({"app":app,"phase":{"type":"string","enum":["begin","move","end"]},"x":{"type":"number"},"y":{"type":"number"}}),
                &["app", "phase", "x", "y"],
            ),
        ),
        (
            "computer_clipboard_read",
            Read,
            contract(
                "computer_clipboard_read",
                "Read a session-owned clipboard snapshot; requires clipboard consent.",
                json!({}),
                &[],
            ),
        ),
        (
            "computer_clipboard_write",
            Mutate,
            contract(
                "computer_clipboard_write",
                "Write a clipboard snapshot without executing arbitrary input.",
                json!({"text":{"type":"string"},"format":{"type":"string","enum":["text","md","html"]}}),
                &["text"],
            ),
        ),
        (
            "computer_clipboard_release",
            Mutate,
            contract(
                "computer_clipboard_release",
                "Restore and release the owned clipboard snapshot if the user has not replaced it.",
                json!({"handle":{"type":"string"}}),
                &["handle"],
            ),
        ),
        (
            "computer_locked_use",
            Mutate,
            contract(
                "computer_locked_use",
                "Enable or disable explicitly approved lock-screen continuity for the current active run.",
                json!({"enabled":{"type":"boolean"}}),
                &["enabled"],
            ),
        ),
        (
            "computer_audio_start",
            Mutate,
            contract(
                "computer_audio_start",
                "Start explicitly approved microphone, system, or mixed recording for this session.",
                json!({"source":{"type":"string","enum":["microphone","system","mixed"]},
                    "max_duration_ms":{"type":"integer","minimum":100,"maximum":300000}}),
                &["source"],
            ),
        ),
        (
            "computer_audio_status",
            Read,
            contract(
                "computer_audio_status",
                "Read recording state and owned artifact metadata. Optionally select one recording_id; omitting it returns recordings owned by this session.",
                json!({"recording_id":{"type":"string","minLength":1}}),
                &[],
            ),
        ),
        (
            "computer_audio_read",
            Read,
            contract(
                "computer_audio_read",
                "Read a bounded WAV chunk from an exact recording owned by the active run, native session and engine. Returns base64 data with offset, next_offset and eof; never accepts a filesystem path.",
                json!({"recording_id":{"type":"string","minLength":1},
                    "artifact_id":{"type":"string","minLength":1},
                    "offset":{"type":"integer","minimum":0}}),
                &["recording_id"],
            ),
        ),
        (
            "computer_resolve_app",
            Read,
            contract(
                "computer_resolve_app",
                "Resolve a native app's exact installed or running identity before observation or an independently authorized background launch. Resolution does not launch the app.",
                json!({"app":{"type":"string","minLength":1}}),
                &["app"],
            ),
        ),
        (
            "computer_audio_stop",
            Mutate,
            contract(
                "computer_audio_stop",
                "Stop and save recording, release devices, and return audio artifacts. Optionally select one recording_id; omitting it stops recordings owned by this session. Stopping always saves; discard is not supported.",
                json!({"recording_id":{"type":"string","minLength":1}}),
                &[],
            ),
        ),
        (
            "computer_connector_call",
            Mutate,
            contract(
                "computer_connector_call",
                "Call an explicitly declared connector operation. Select an exact account when more than one is available. Account, capability and per-action approval are required; denied access must not be bypassed through UI automation.",
                json!({"connector":{"type":"string","enum":["calendar","contacts","messages"]},"provider":{"type":"string","enum":["native","google","microsoft365","configured_mcp"]},"account_id":{"type":"string","minLength":1},"operation":{"type":"string","minLength":1},"arguments":{"type":"object"}}),
                &["connector", "operation", "arguments"],
            ),
        ),
    ]
}
pub(super) fn method(tool: &str) -> Option<&'static str> {
    Some(match tool {
        "computer_capabilities" => "capabilities",
        "computer_resolve_app" => "resolve_app",
        "computer_list_windows" => "list_windows",
        "computer_launch_app" => "launch_app",
        "computer_activate_app" => "activate_app",
        "computer_clipboard_read" => "clipboard_read",
        "computer_clipboard_write" => "clipboard_write",
        "computer_clipboard_release" => "clipboard_release",
        "computer_audio_start" => "audio_start",
        "computer_audio_status" => "audio_status",
        "computer_audio_stop" => "audio_stop",
        "computer_connector_call" => "connector_call",
        _ => return None,
    })
}
