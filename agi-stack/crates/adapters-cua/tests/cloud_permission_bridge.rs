//! Real Rust permission serialization through Electron and Python claim admission.
use agistack_core::ports::{
    permission_input_digest, PermissionBinding, PermissionKind, PermissionRequired,
};
use serde_json::{json, Value};
use std::{
    path::PathBuf,
    process::Stdio,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::{io::AsyncWriteExt, process::Command};

const PYTHON_CLAIM: &str = r#"
import asyncio
import json
import sys

from src.infrastructure.agent.native_computer_use.contracts import DeviceScope
from src.infrastructure.agent.native_computer_use.control import validate_control
from src.infrastructure.agent.native_computer_use.devices import device_key
from src.infrastructure.agent.native_computer_use.media import MediaTransport
from src.infrastructure.agent.native_computer_use.permission_result import decode_record
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, request_key

fixture = json.load(sys.stdin)
claim, step, result = fixture['claim'], fixture['step'], fixture['result']

class ExistingClaimTransport(MediaTransport):
    async def read(self, key):
        if key == request_key(claim['request_id']):
            return claim
        if step is not None and key == step['step_key']:
            return step
        scope = DeviceScope(**{key: claim[key] for key in
                              ('user_id', 'tenant_id', 'project_id', 'device_id')})
        if key == device_key(scope):
            return {'connection_id': claim['connection_id'],
                    'tool_definitions': [{'name': claim['tool_name']}]}
        return None

    async def members(self, key):
        if step is not None and key == request_key(claim['request_id']) + ':steps':
            return {step['step_key']}
        return set()

async def validate():
    try:
        decoded = decode_record(result.get('permission_required'))
        control, _ = validate_control(result)
        permission, _ = await ExistingClaimTransport(None)._permission_result(
            'fixture-connection', result, control)
        assert permission == decoded
    except DeviceBridgeError as error:
        return {'accepted': False, 'error_code': str(error)}
    return {'accepted': True, 'permission_present': permission is not None}

print(json.dumps(asyncio.run(validate())))
"#;

fn repository() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("repository root")
        .to_path_buf()
}

async fn execute(mut command: Command, payload: &Value) -> Value {
    let mut child = command
        .current_dir(repository())
        .env_clear()
        .env("PATH", std::env::var_os("PATH").unwrap_or_default())
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .expect("cross-language contract dependencies");
    let mut stdin = child.stdin.take().expect("fixture stdin");
    stdin
        .write_all(&serde_json::to_vec(payload).unwrap())
        .await
        .unwrap();
    drop(stdin);
    let output = tokio::time::timeout(Duration::from_secs(20), child.wait_with_output())
        .await
        .expect("cross-language fixture timeout")
        .expect("fixture output");
    assert!(
        output.status.success(),
        "cross-language fixture failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("fixture verdict")
}

async fn forward(envelope: &Value) -> Value {
    let mut command = Command::new(
        std::env::var_os("AGISTACK_CUA_CONTRACT_NODE").unwrap_or_else(|| "node".into()),
    );
    command
        .arg(
            repository()
                .join("agi-stack/crates/adapters-cua/tests/helpers/cloud_permission_bridge.mjs"),
        )
        .arg(repository());
    execute(
        command,
        &json!({"envelope":envelope,"requestId":"fixture-request"}),
    )
    .await
}

async fn claim_verdict(fixture: &Value, result: &Value) -> Value {
    let python = std::env::var_os("AGISTACK_CUA_CONTRACT_PYTHON")
        .map(PathBuf::from)
        .unwrap_or_else(|| repository().join(".venv/bin/python"));
    let mut command = Command::new(python);
    command.arg("-c").arg(PYTHON_CLAIM);
    execute(
        command,
        &json!({"claim":fixture["claim"],"step":fixture["step"],"result":result}),
    )
    .await
}

fn fixture(inner_step: bool) -> Value {
    let tool = if inner_step {
        "browser_write_operation"
    } else {
        "computer_locked_use"
    };
    let input = if inner_step {
        json!({"operation":"tab.claim","args":[1]})
    } else {
        json!({"enabled":true})
    };
    let digest = permission_input_digest(&input.to_string()).unwrap();
    let expires = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + 120;
    let claim = json!({"request_id":"fixture-request","user_id":"fixture-user",
        "tenant_id":"fixture-tenant","project_id":"fixture-project",
        "conversation_id":"fixture-conversation","run_id":"fixture-run",
        "session_id":"fixture-engine-session","device_id":"fixture-device",
        "connection_id":"fixture-connection","authorization_revision":7,
        "status":"claimed","expires_at":expires,"cancelled":false,
        "tool_name":if inner_step {"cua_repl_js"}else{tool},
        "input_json":if inner_step {json!({"code":"await cua.getState()"}).to_string()}
            else{input.to_string()}});
    let mut step = if inner_step {
        json!({"status":"pending","permission_id":"fixture-permission",
            "step_key":"fixture-step-key","current_request_id":"fixture-request",
            "authorization_revision":7,"tool_name":tool,"permission_input_digest":digest,
            "cell_id":"fixture-cell","step_id":"fixture-step",
            "target":{"kind":"browser","id":"fixture-tab"},
            "catalog_digest":"fixture-catalog","input_digest":"legacy-step-digest",
            "code_digest":"fixture-code"})
    } else {
        Value::Null
    };
    if inner_step {
        for key in [
            "user_id",
            "tenant_id",
            "project_id",
            "conversation_id",
            "run_id",
            "session_id",
            "device_id",
            "connection_id",
            "agent_id",
            "child_run_id",
            "child_owner_digest",
        ] {
            step[key] = claim[key].clone();
        }
    }
    let request = if inner_step {
        json!({"request_id":"fixture-permission","session_id":"fixture-cell",
            "engine_session_id":"fixture-engine-session","app":"fixture-tab",
            "identity_digest":"fixture-catalog","capability":"execution_step",
            "tool_name":tool,"input_digest":"legacy-step-digest",
            "execution_step":{"key":"fixture-step-key","cell_id":"fixture-cell",
                "step_id":"fixture-step","target":{"kind":"browser","id":"fixture-tab"},
                "code_digest":"fixture-code"}})
    } else {
        json!({"request_id":"fixture-native-permission","session_id":"fixture-native-session",
            "engine_session_id":"fixture-engine-session","app":"device:control",
            "identity_digest":"fixture-device","capability":"locked_use",
            "tool_name":tool,"input_digest":"different-legacy-native-digest"})
    };
    let permission = PermissionRequired::new(
        if inner_step {
            PermissionKind::CloudExecutionStep
        } else {
            PermissionKind::NativeConsent
        },
        PermissionBinding {
            tool_name: tool.into(),
            input_digest: digest,
            engine_session_id: Some("fixture-engine-session".into()),
            cell_id: inner_step.then(|| "fixture-cell".into()),
            step_id: inner_step.then(|| "fixture-step".into()),
        },
        json!({"error":"cua_permission_required","request":request,"scopes":["once"]}),
    );
    let envelope = json!({"request_id":"fixture-request","output_json":permission.demand().to_string(),
        "is_error":false,"media":[],"authorization_revision":7,"permission_required":permission});
    json!({"envelope":envelope,"claim":claim,"step":step})
}

#[tokio::test]
async fn real_rust_permission_records_survive_the_electron_bridge_and_python_claim() {
    for inner_step in [false, true] {
        let fixture = fixture(inner_step);
        let result = forward(&fixture["envelope"]).await;
        assert_eq!(
            result["permission_required"],
            fixture["envelope"]["permission_required"]
        );
        assert_eq!(result["authorization_revision"], 7);
        assert_eq!(
            claim_verdict(&fixture, &result).await,
            json!({"accepted":true,"permission_present":true})
        );
    }
}

#[tokio::test]
async fn model_visible_output_and_invalid_host_markers_cannot_create_permission() {
    let fixture = fixture(true);
    let mut text_only = fixture["envelope"].clone();
    text_only["permission_required"] = Value::Null;
    let result = forward(&text_only).await;
    assert!(!result
        .as_object()
        .unwrap()
        .contains_key("permission_required"));
    assert_eq!(
        claim_verdict(&fixture, &result).await,
        json!({"accepted":true,"permission_present":false})
    );
    for field in ["authorization_revision", "control_outcome", "request_id"] {
        let mut invalid = fixture["envelope"].clone();
        invalid[field] = match field {
            "authorization_revision" => json!(0),
            "control_outcome" => json!("user_stopped"),
            _ => json!("foreign-request"),
        };
        let result = forward(&invalid).await;
        assert_eq!(result["is_error"], true);
        assert!(!result
            .as_object()
            .unwrap()
            .contains_key("permission_required"));
    }
}

#[tokio::test]
async fn python_rechecks_exact_claim_and_inner_step_after_lossless_forwarding() {
    for inner_step in [false, true] {
        let fixture = fixture(inner_step);
        let result = forward(&fixture["envelope"]).await;
        // Inner input is witnessed by its persisted step digest; the outer cell's
        // code is checked earlier by ExecutionSteps.authorize, not result decoding.
        let fields: &[&str] = if inner_step {
            &["session_id", "authorization_revision", "tool_name"]
        } else {
            &[
                "session_id",
                "authorization_revision",
                "tool_name",
                "input_json",
            ]
        };
        for &field in fields {
            let mut changed = fixture.clone();
            changed["claim"][field] = if field == "authorization_revision" {
                json!(8)
            } else {
                json!("foreign")
            };
            assert_eq!(
                claim_verdict(&changed, &result).await["accepted"],
                false,
                "{field}"
            );
        }
        if inner_step {
            for field in [
                "cell_id",
                "step_id",
                "current_request_id",
                "permission_input_digest",
                "user_id",
            ] {
                let mut changed = fixture.clone();
                changed["step"][field] = json!("foreign");
                assert_eq!(
                    claim_verdict(&changed, &result).await["accepted"],
                    false,
                    "{field}"
                );
            }
        }
    }
}
