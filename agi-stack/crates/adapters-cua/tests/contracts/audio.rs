use agistack_adapters_cua::{tool_names, validate_tool_input};
use serde_json::json;

#[test]
fn only_audio_stop_declares_owned_recording_release_and_remains_a_mutation() {
    use agistack_adapters_cua::{tool_effects, CuaToolEffect, OWNED_RECORDING_RELEASE_TOOLS};
    assert_eq!(OWNED_RECORDING_RELEASE_TOOLS, &["computer_audio_stop"]);
    assert_eq!(
        tool_effects()[OWNED_RECORDING_RELEASE_TOOLS[0]],
        CuaToolEffect::Mutate
    );
    assert!(validate_tool_input(
        "computer_audio_stop",
        &json!({"recording_id":"owned-recording", "path":"/tmp/export.wav"})
    )
    .is_err());
}

#[test]
fn audio_duration_is_bounded_and_optional_for_existing_callers() {
    for source in ["microphone", "system", "mixed"] {
        assert!(validate_tool_input("computer_audio_start", &json!({"source":source})).is_ok());
        for duration in [100, 60_000, 300_000] {
            assert!(validate_tool_input(
                "computer_audio_start",
                &json!({"source":source,"max_duration_ms":duration})
            )
            .is_ok());
        }
    }
    for duration in [
        json!(99),
        json!(300_001),
        json!(true),
        json!("100"),
        json!(100.5),
    ] {
        assert!(validate_tool_input(
            "computer_audio_start",
            &json!({"source":"system","max_duration_ms":duration})
        )
        .is_err());
    }
}

#[test]
fn audio_selection_is_optional_and_rejects_unsupported_save_policy() {
    for tool in ["computer_audio_status", "computer_audio_stop"] {
        assert!(validate_tool_input(tool, &json!({})).is_ok());
        assert!(validate_tool_input(tool, &json!({"recording_id":"owned-recording"})).is_ok());
        for invalid in [
            json!({"recording_id":""}),
            json!({"recording_id":42}),
            json!({"recording_id":null}),
            json!({"save":true}),
            json!({"save":false}),
            json!({"recording_id":"owned-recording","end_reason":"user_stopped"}),
        ] {
            assert!(
                validate_tool_input(tool, &invalid).is_err(),
                "{tool}: {invalid}"
            );
        }
    }
}

#[cfg(target_os = "macos")]
#[tokio::test]
async fn real_node_audio_facade_round_trips_exact_parameters_through_scoped_host() {
    use agistack_core::ports::ToolHost;
    use serde_json::Value;
    use std::{path::PathBuf, process::Command, sync::Arc, time::Duration};

    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let module = root
        .join("packages/cua-repl/src/native.mjs")
        .canonicalize()
        .unwrap();
    let node = root.join("apps/desktop/build/cua-repl/bin/node");
    let script = format!(
        r#"
import {{ nativeSurface }} from {};
const calls = [];
const {{ computer }} = nativeSurface({{
  rpc: async (method, parameters) => {{ calls.push({{ method, ...parameters }}); return {{ ok: true }}; }},
  write() {{}}, emitImage() {{}}, platform: 'darwin'
}});
await computer.audio.start({{ source: 'mixed', max_duration_ms: 3000 }});
await computer.audio.status({{ recording_id: 'owned-recording' }});
await computer.audio.status();
await computer.audio.stop({{ recording_id: 'owned-recording' }});
await computer.audio.stop({{ recording_id: 'owned-recording', save: true }});
await computer.audio.stop();
let rejected = false;
try {{ await computer.audio.stop({{ recording_id: 'owned-recording', save: false }}); }}
catch (error) {{ rejected = error instanceof TypeError && error.message.includes('save'); }}
process.stdout.write(JSON.stringify({{ calls, rejected }}));
"#,
        json!(url::Url::from_file_path(module).unwrap().as_str())
    );
    let output = Command::new(if node.is_file() {
        node
    } else {
        PathBuf::from("node")
    })
    .args(["--input-type=module", "--eval", &script])
    .output()
    .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["rejected"], true);
    let calls = result["calls"].as_array().unwrap();
    assert_eq!(
        calls.len(),
        6,
        "unsupported save:false must never reach the host"
    );
    let helper = super::Helper::new("audio_contract");
    let client = Arc::new(helper.client(Duration::from_secs(2)));
    let host =
        agistack_adapters_cua::CuaToolHost::new(client.clone()).with_context(super::context());
    for call in calls {
        assert_eq!(call["method"], "computer.call");
        assert!(call["arguments"].get("save").is_none());
        let tool = call["tool"].as_str().unwrap();
        let result = host
            .call_with_content(tool, &call["arguments"].to_string())
            .await
            .unwrap();
        let echoed: Value = serde_json::from_str(&result.output_json).unwrap();
        assert_eq!(
            echoed["echo"]["recording_id"],
            call["arguments"]["recording_id"]
        );
    }
    client.shutdown().await;
}

#[test]
fn continuity_renewal_is_never_exposed_as_a_model_tool() {
    assert!(validate_tool_input("computer_locked_use", &json!({"enabled":true})).is_ok());
    assert!(validate_tool_input(
        "computer_locked_use",
        &json!({"enabled":true,"generation":"model-created"})
    )
    .is_err());
    for method in [
        "locked_use_enable",
        "locked_use_renew",
        "locked_use_disable",
    ] {
        assert!(!tool_names().contains(&method));
        assert!(validate_tool_input(method, &json!({})).is_err());
    }
}
