//! Validate the actual device catalog against the cloud's production admission APIs.
use agistack_adapters_cua::{tool_effects, CuaClient, CuaToolEffect, CuaToolHost};
use agistack_core::ports::ToolHost;
use serde_json::{json, Value};
use std::{path::PathBuf, process::Stdio, sync::Arc, time::Duration};
use tokio::{io::AsyncWriteExt, process::Command};

const CLOUD_VALIDATOR: &str = r#"
import asyncio
import json
import sys

from src.infrastructure.agent.native_computer_use.catalog import validate_tool_definition
from src.infrastructure.agent.native_computer_use.contracts import DeviceScope
from src.infrastructure.agent.native_computer_use.devices import DeviceRegistry
from src.infrastructure.agent.native_computer_use.effects import argument_schema, tool_effect
from src.infrastructure.agent.native_computer_use.schema import validator
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError

payload = json.load(sys.stdin)
name = None

class ValidatedBeforeStorage(Exception):
    pass

class AdmissionOnlyRegistry(DeviceRegistry):
    async def update(self, *args, **kwargs):
        # All production catalog checks precede this first persistent mutation.
        raise ValidatedBeforeStorage

async def admit_catalog():
    definitions = [
        {key: row[key] for key in ('name', 'description', 'inputSchema') if key in row}
        for row in payload
    ]
    try:
        await AdmissionOnlyRegistry(None).register(
            DeviceScope(user_id='fixture-user', tenant_id='fixture-tenant',
                        project_id='fixture-project', device_id='fixture-device'),
            'fixture-connection', definitions,
        )
    except ValidatedBeforeStorage:
        return
    raise AssertionError('catalog validation crossed the test storage boundary')

try:
    asyncio.run(admit_catalog())
    for row in payload:
        name = row['name']
        schema = row['inputSchema']
        validate_tool_definition(name, schema)
        checked = validator(argument_schema(schema))
        if 'arguments' in row and not checked.is_valid(row['arguments']):
            raise DeviceBridgeError('computer_use_invalid_params')
        if tool_effect(name, schema, row.get('arguments', {})) != row['effect']:
            raise DeviceBridgeError('test_catalog_effect_mismatch')
except DeviceBridgeError as error:
    print(json.dumps({'ok': False, 'tool': name, 'error_code': str(error)}))
else:
    print(json.dumps({'ok': True, 'validated': len(payload)}))
"#;

fn native_catalog() -> Vec<Value> {
    // Catalog construction never starts the helper or opens a native session.
    let host = CuaToolHost::new(Arc::new(CuaClient::builder().build()));
    let effects = tool_effects();
    host.list_tools()
        .into_iter()
        .map(|name| {
            let definition = host.tool_definition(&name).expect("listed tool definition");
            let schema = definition.input_schema.expect("listed tool schema");
            let effect = match effects.get(name.as_str()).expect("declared tool effect") {
                CuaToolEffect::Read => "read",
                CuaToolEffect::Mutate => "mutate",
            };
            json!({"name":definition.name,"description":definition.description,
                "inputSchema":schema,"effect":effect})
        })
        .collect()
}

async fn validate_in_python(rows: &[Value]) -> Value {
    let repository = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("repository root")
        .to_path_buf();
    let python = std::env::var_os("AGISTACK_CUA_CONTRACT_PYTHON")
        .map(PathBuf::from)
        .unwrap_or_else(|| repository.join(".venv/bin/python"));
    let mut child = Command::new(python)
        .arg("-c")
        .arg(CLOUD_VALIDATOR)
        .current_dir(repository)
        .env_clear()
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .expect("repository Python environment with backend dependencies");
    let mut stdin = child.stdin.take().expect("Python stdin");
    stdin
        .write_all(&serde_json::to_vec(rows).expect("public catalog serialization"))
        .await
        .expect("write public catalog to Python");
    drop(stdin);
    let output = tokio::time::timeout(Duration::from_secs(20), child.wait_with_output())
        .await
        .expect("cloud catalog validator timeout")
        .expect("cloud catalog validator output");
    assert!(
        output.status.success(),
        "cloud catalog validator failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("cloud catalog validation verdict")
}

#[tokio::test]
async fn native_catalog_is_accepted_by_the_python_cloud() {
    let catalog = native_catalog();
    assert!(!catalog.is_empty());
    assert_eq!(
        validate_in_python(&catalog).await,
        json!({"ok":true,"validated":catalog.len()})
    );
}

#[tokio::test]
async fn cloud_validation_rejects_unknown_tools_missing_schemas_and_effect_drift() {
    let catalog = native_catalog();
    let read = catalog
        .iter()
        .find(|row| row["effect"] == "read")
        .expect("a native read tool");
    let mut unknown = read.clone();
    unknown["name"] = json!("computer_unknown_contract_fixture");
    let mut missing_schema = read.clone();
    missing_schema
        .as_object_mut()
        .unwrap()
        .remove("inputSchema");
    let mut invalid_schema = read.clone();
    invalid_schema["inputSchema"]["properties"] = json!([]);
    let mut remote_schema = read.clone();
    remote_schema["inputSchema"]["$ref"] = json!("https://invalid.example/schema");
    let mut changed_effect = read.clone();
    changed_effect["effect"] = json!("mutate");
    let mut missing_description = read.clone();
    missing_description["description"] = Value::Null;
    for (row, expected) in [
        (unknown, "computer_use_invalid_catalog"),
        (missing_schema, "computer_use_invalid_catalog"),
        (missing_description, "computer_use_invalid_catalog"),
        (invalid_schema, "computer_use_invalid_schema"),
        (remote_schema, "computer_use_external_schema_reference"),
        (changed_effect, "test_catalog_effect_mismatch"),
    ] {
        let result = validate_in_python(&[row]).await;
        assert_eq!(result["ok"], false);
        assert_eq!(result["error_code"], expected);
    }
    let duplicate = validate_in_python(&[read.clone(), read.clone()]).await;
    assert_eq!(duplicate["error_code"], "computer_use_invalid_catalog");
    let mut oversized = read.clone();
    oversized["description"] = json!("x".repeat(256 * 1024));
    let oversized = validate_in_python(&[oversized]).await;
    assert_eq!(oversized["error_code"], "computer_use_catalog_too_large");
}

#[tokio::test]
async fn locked_use_enable_and_release_keep_mutating_effect_and_strict_schema() {
    let row = native_catalog()
        .into_iter()
        .find(|row| row["name"] == "computer_locked_use")
        .expect("native Locked Use tool");
    assert_eq!(row["effect"], "mutate");
    for enabled in [true, false] {
        let mut call = row.clone();
        call["arguments"] = json!({"enabled":enabled});
        assert_eq!(
            validate_in_python(&[call]).await,
            json!({"ok":true,"validated":1})
        );
        let input = json!({"enabled":enabled});
        agistack_adapters_cua::validate_tool_input("computer_locked_use", &input).unwrap();
        for reserved in ["session_id", "run_id", "generation", "user_id", "device_id"] {
            let mut forged = input.clone();
            forged[reserved] = json!("foreign");
            assert!(
                agistack_adapters_cua::validate_tool_input("computer_locked_use", &forged).is_err()
            );
        }
    }
}
