//! Exercise the connector boundary with a real JSON-RPC server process.
use super::*;
use crate::local_runtime::mcp_supervisor::{McpServerDefinitionInput, McpTransport};
use std::{collections::BTreeMap, fs, path::PathBuf};

struct FixtureRoot(PathBuf);
impl Drop for FixtureRoot {
    fn drop(&mut self) {
        if let Err(error) = fs::remove_dir_all(&self.0) {
            eprintln!("connector fixture cleanup failed: {error}");
        }
    }
}

#[tokio::test]
async fn mcp_business_failure_and_success_survive_connector_dispatch() {
    let root = FixtureRoot(std::env::temp_dir().join(format!(
        "agistack-cua-connector-result-{}",
        uuid::Uuid::new_v4()
    )));
    fs::create_dir_all(&root.0).unwrap();
    let script = root.0.join("server.py");
    fs::write(
        &script,
        r#"import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "connector-result-fixture", "version": "1",
                "computer_use_connector": {
                    "provider": "configured_mcp", "capabilities": {"calendar": ["inspect"]}
                }
            }
        }
    elif method == "tools/list":
        result = {"tools": [{"name": "inspect", "description": "Fixture inspection",
            "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]}
    elif method == "tools/call":
        failed = request["params"]["arguments"].get("failed", False)
        result = {"isError": failed, "content": [{"type": "text",
            "text": "fixture rejected" if failed else "error count: 0"}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
"#,
    )
    .unwrap();
    let python = std::env::split_paths(&std::env::var_os("PATH").unwrap())
        .map(|entry| entry.join("python3"))
        .find(|path| path.is_file())
        .and_then(|path| path.canonicalize().ok())
        .expect("python3 fixture runtime");
    let state = crate::local_runtime::tests::test_state("cua-connector-result");
    let owner = super::super::tests::owner(&state);
    let scope = McpScope {
        tenant_id: owner.tenant_id.clone(),
        project_id: owner.project_id.clone(),
    };
    let server = state
        .mcp_supervisor
        .create_server(
            &scope,
            McpServerDefinitionInput {
                name: "cua-result-fixture".into(),
                description: Some("Structured connector result fixture".into()),
                transport: McpTransport::Stdio,
                command: vec![
                    python.to_string_lossy().into_owned(),
                    script.to_string_lossy().into_owned(),
                ],
                cwd: Some(".".into()),
                vault_env_refs: BTreeMap::new(),
                enabled: true,
            },
            "create-cua-result-fixture",
        )
        .unwrap();
    state.mcp_supervisor.recover_enabled(&scope).await.unwrap();
    state
        .mcp_supervisor
        .list_tools(&scope, &server.id)
        .await
        .unwrap();
    let mut input = json!({
        "provider":"configured_mcp", "account_id":server.id,
        "connector":"calendar", "operation":"inspect", "arguments":{"failed":true}
    });
    let connector = select(&state, &owner, &input).unwrap().unwrap();
    for duplicate in [false, true] {
        let result = call(&state, &owner, &connector, &input, "failed-call").await;
        let Err(CoreError::Tool(error)) = result else {
            panic!("JSON-RPC success must not hide isError=true");
        };
        let error: Value = serde_json::from_str(&error).unwrap();
        assert_eq!(error["isError"], true);
        assert_eq!(error["duplicate"], duplicate);
        assert_eq!(error["content"][0]["text"], "fixture rejected");
    }
    input["arguments"]["failed"] = json!(false);
    let result = call(&state, &owner, &connector, &input, "successful-call")
        .await
        .unwrap();
    let output: Value = serde_json::from_str(&result.output_json).unwrap();
    assert_eq!(output["isError"], false);
    assert_eq!(output["content"][0]["text"], "error count: 0");
    assert!(result.control_outcome.is_none());
    state
        .mcp_supervisor
        .delete_server(
            &scope,
            &server.id,
            server.revision,
            "delete-cua-result-fixture",
        )
        .unwrap();
}
