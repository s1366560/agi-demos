use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

use serde_json::json;
use uuid::Uuid;

use super::{
    mcp_supervisor::{
        McpScope, McpServerDefinitionInput, McpSupervisor, McpTransport, SupervisorLimits,
    },
    DesktopSessionStore,
};

fn test_root(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!("agistack-mcp-{label}-{}", Uuid::new_v4()))
}

fn python_executable() -> PathBuf {
    std::env::split_paths(&std::env::var_os("PATH").expect("test PATH"))
        .map(|entry| entry.join("python3"))
        .find(|candidate| candidate.is_file())
        .and_then(|candidate| candidate.canonicalize().ok())
        .expect("python3 executable")
}

fn write_mock_server(root: &Path) -> PathBuf {
    let script = root.join("mock_mcp_server.py");
    fs::create_dir_all(root).expect("create mock MCP root");
    fs::write(
        &script,
        r#"import json
import sys
import time

mode = sys.argv[1]

for raw_line in sys.stdin:
    request = json.loads(raw_line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized":
        if mode == "crash_after_initialize":
            sys.exit(23)
        continue
    if mode == "timeout" and method == "initialize":
        time.sleep(60)
        continue
    if mode == "crash" and method == "initialize":
        sys.exit(17)
    if mode == "malformed" and method == "initialize":
        sys.stdout.write("{not-json}\n")
        sys.stdout.flush()
        continue
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "mock-local-mcp", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [{
                "name": "echo",
                "description": "Echo structured input",
                "inputSchema": {"type": "object"},
                "_meta": {"ui/resourceUri": "ui://mock/index.html"},
            }]
        }
    elif method == "tools/call":
        arguments = request.get("params", {}).get("arguments", {})
        result = {
            "content": [{"type": "text", "text": json.dumps(arguments, sort_keys=True)}],
            "isError": False,
        }
    elif method == "resources/list":
        result = {
            "resources": [{
                "uri": "ui://mock/index.html",
                "name": "Mock App",
                "mimeType": "text/html;profile=mcp-app",
            }]
        }
    elif method == "resources/read":
        uri = request.get("params", {}).get("uri")
        result = {
            "contents": [{
                "uri": uri,
                "mimeType": "text/html;profile=mcp-app",
                "text": "<main>mock app</main>",
            }]
        }
    else:
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "method not found"},
        }
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        continue
    response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    sys.stdout.flush()
"#,
    )
    .expect("write mock MCP server");
    script
}

fn scope(project_id: &str) -> McpScope {
    McpScope {
        tenant_id: "local".to_string(),
        project_id: project_id.to_string(),
    }
}

fn definition(name: &str, python: &Path, script: &Path, mode: &str) -> McpServerDefinitionInput {
    McpServerDefinitionInput {
        name: name.to_string(),
        description: Some("test MCP server".to_string()),
        transport: McpTransport::Stdio,
        command: vec![
            python.to_string_lossy().into_owned(),
            script.to_string_lossy().into_owned(),
            mode.to_string(),
        ],
        cwd: Some(".".to_string()),
        vault_env_refs: BTreeMap::new(),
        enabled: true,
    }
}

fn test_limits() -> SupervisorLimits {
    SupervisorLimits {
        request_timeout: Duration::from_millis(750),
        initialize_timeout: Duration::from_millis(750),
        retry_base: Duration::from_millis(10),
        retry_max: Duration::from_millis(20),
        max_request_bytes: 128 * 1024,
        max_response_bytes: 256 * 1024,
    }
}

#[tokio::test]
async fn stdio_supervisor_round_trips_and_recovers_from_persisted_definitions() {
    let root = test_root("round-trip");
    let database = root.join("desktop.db");
    let script = write_mock_server(&root);
    let python = python_executable();
    let active_scope = scope("local-project");
    let server_id;

    {
        let store = DesktopSessionStore::open(&database).expect("session store");
        let supervisor =
            McpSupervisor::new(store, root.clone(), None, test_limits()).expect("MCP supervisor");
        let created = supervisor
            .create_server(
                &active_scope,
                definition("mock", &python, &script, "normal"),
                "create-mock",
            )
            .expect("create MCP server");
        server_id = created.id.clone();

        supervisor
            .recover_enabled(&active_scope)
            .await
            .expect("recover enabled MCP server");
        let tools = supervisor
            .list_tools(&active_scope, &server_id)
            .await
            .expect("list MCP tools");
        assert_eq!(tools[0]["name"], "echo");

        let apps = supervisor.list_apps(&active_scope).expect("list MCP apps");
        assert_eq!(apps.len(), 1);
        assert_eq!(apps[0].server_name, "mock");
        assert_eq!(
            apps[0].resource_uri.as_deref(),
            Some("ui://mock/index.html")
        );

        let first = supervisor
            .call_tool(
                &active_scope,
                &server_id,
                "echo",
                json!({"message": "hello"}),
                Some("call-echo-once"),
            )
            .await
            .expect("call MCP tool");
        assert!(!first.duplicate);
        assert_eq!(first.result["content"][0]["type"], "text");
        let replay = supervisor
            .call_tool(
                &active_scope,
                &server_id,
                "echo",
                json!({"message": "hello"}),
                Some("call-echo-once"),
            )
            .await
            .expect("replay MCP tool call");
        assert!(replay.duplicate);
        assert_eq!(replay.result, first.result);

        let resources = supervisor
            .list_resources(&active_scope, Some(&server_id))
            .await
            .expect("list MCP resources");
        assert_eq!(resources[0]["uri"], "ui://mock/index.html");
        let content = supervisor
            .read_resource(&active_scope, &server_id, "ui://mock/index.html")
            .await
            .expect("read MCP resource");
        assert_eq!(content[0]["text"], "<main>mock app</main>");

        assert!(supervisor
            .server_by_name(&scope("other-project"), "mock")
            .expect("scope lookup")
            .is_none());
    }

    {
        let reopened = DesktopSessionStore::open(&database).expect("reopen session store");
        let supervisor = McpSupervisor::new(reopened, root.clone(), None, test_limits())
            .expect("reopened MCP supervisor");
        supervisor
            .recover_enabled(&active_scope)
            .await
            .expect("restart recovery");
        let result = supervisor
            .call_tool(
                &active_scope,
                &server_id,
                "echo",
                json!({"after": "restart"}),
                None,
            )
            .await
            .expect("call after restart");
        assert_eq!(result.result["isError"], false);
    }

    fs::remove_dir_all(root).expect("remove MCP test root");
}

#[tokio::test]
async fn stdio_supervisor_fails_closed_for_timeout_crash_malformed_and_conflicting_replay() {
    let root = test_root("failures");
    let script = write_mock_server(&root);
    let python = python_executable();
    let store = DesktopSessionStore::in_memory().expect("session store");
    let supervisor = Arc::new(
        McpSupervisor::new(
            store,
            root.clone(),
            None,
            SupervisorLimits {
                initialize_timeout: Duration::from_millis(300),
                request_timeout: Duration::from_millis(300),
                retry_base: Duration::from_millis(500),
                retry_max: Duration::from_millis(500),
                ..test_limits()
            },
        )
        .expect("MCP supervisor"),
    );
    let active_scope = scope("local-project");

    for (name, mode, expected_reason) in [
        ("timeout", "timeout", "local_mcp_request_timeout"),
        ("crash", "crash", "local_mcp_process_exited"),
        ("malformed", "malformed", "local_mcp_malformed_response"),
    ] {
        let server = supervisor
            .create_server(
                &active_scope,
                definition(name, &python, &script, mode),
                &format!("create-{name}"),
            )
            .expect("create failing server");
        let error = supervisor
            .list_tools(&active_scope, &server.id)
            .await
            .expect_err("failing MCP server");
        assert_eq!(error.reason_code(), expected_reason);
        let health = supervisor
            .health(&active_scope, &server.id)
            .expect("MCP health");
        assert_eq!(health.status, "error");
        assert_eq!(health.reason_code.as_deref(), Some(expected_reason));
    }

    let late_crash = supervisor
        .create_server(
            &active_scope,
            definition("late-crash", &python, &script, "crash_after_initialize"),
            "create-late-crash",
        )
        .expect("create late-crashing server");
    supervisor
        .recover_enabled(&active_scope)
        .await
        .expect("initial recovery continues after one server fails");
    tokio::time::sleep(Duration::from_millis(30)).await;
    let late_crash_error = supervisor
        .list_tools(&active_scope, &late_crash.id)
        .await
        .expect_err("process exiting between requests fails closed");
    assert_eq!(late_crash_error.reason_code(), "local_mcp_process_exited");
    let retry_error = supervisor
        .list_tools(&active_scope, &late_crash.id)
        .await
        .expect_err("immediate process restart is bounded");
    assert_eq!(retry_error.reason_code(), "local_mcp_restart_backoff");
    let health = supervisor
        .health(&active_scope, &late_crash.id)
        .expect("late crash health");
    assert_eq!(health.status, "error");
    assert_eq!(
        health.reason_code.as_deref(),
        Some("local_mcp_restart_backoff")
    );

    let healthy = supervisor
        .create_server(
            &active_scope,
            definition("healthy", &python, &script, "normal"),
            "create-healthy",
        )
        .expect("create healthy server");
    supervisor
        .call_tool(
            &active_scope,
            &healthy.id,
            "echo",
            json!({"value": 1}),
            Some("same-key"),
        )
        .await
        .expect("initial idempotent call");
    let conflict = supervisor
        .call_tool(
            &active_scope,
            &healthy.id,
            "echo",
            json!({"value": 2}),
            Some("same-key"),
        )
        .await
        .expect_err("conflicting idempotency replay");
    assert_eq!(conflict.reason_code(), "local_mcp_idempotency_conflict");

    let unsupported = supervisor.create_server(
        &active_scope,
        McpServerDefinitionInput {
            name: "remote".to_string(),
            description: None,
            transport: McpTransport::Http,
            command: vec!["https://example.invalid/mcp".to_string()],
            cwd: None,
            vault_env_refs: BTreeMap::new(),
            enabled: true,
        },
        "create-remote",
    );
    assert_eq!(
        unsupported
            .expect_err("HTTP remains explicit unavailable")
            .reason_code(),
        "local_mcp_http_transport_unavailable"
    );

    fs::remove_dir_all(root).expect("remove MCP failure test root");
}
