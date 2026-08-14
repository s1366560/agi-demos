use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm};
use agistack_core::{
    agent::{react::ReActEngine, types::AgentAction},
    ports::ToolHost,
};
use serde_json::json;
use uuid::Uuid;

use super::{
    authority_store::{
        DesktopExecutionEnvironment, DesktopExecutionEnvironmentKind, DesktopPermissionProfile,
        DesktopRun, DesktopRunStatus,
    },
    authorized_tool_host::AuthorizedRunToolHost,
    execution_profile::{ExecutionProfile, ProfiledToolHost},
    fan_out_tool_host::FanOutToolHost,
    mcp_agent_tool_host::{legacy_exposed_tool_name, McpAgentToolHost},
    mcp_supervisor::{
        McpScope, McpServerDefinitionInput, McpSupervisor, McpTransport, SupervisorLimits,
    },
    session_store::ApprovePlanStartInput,
    tool_authority::{InvocationStatus, ToolEffect},
    ConversationCapabilityMode, ConversationRunMode, DesktopSessionStore, LocalConversation,
};

fn test_root(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!("agistack-mcp-{label}-{}", Uuid::new_v4()))
}

#[tokio::test]
async fn discovered_mcp_tools_are_dispatchable_through_the_agent_tool_host() {
    let root = test_root("agent-tool-host");
    let script = write_mock_server(&root);
    let python = python_executable();
    let store = DesktopSessionStore::in_memory().expect("session store");
    let supervisor = Arc::new(
        McpSupervisor::new(store, root.clone(), None, test_limits()).expect("MCP supervisor"),
    );
    let active_scope = scope("local-project");
    let server = supervisor
        .create_server(
            &active_scope,
            definition("mock", &python, &script, "normal"),
            "create-agent-tool-host",
        )
        .expect("create MCP server");
    supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .expect("discover MCP tools");

    let host = McpAgentToolHost::new(
        Arc::clone(&supervisor),
        active_scope,
        "run-agent-tool-host".to_string(),
        None,
    )
    .expect("agent MCP tool host");
    let tools = host.list_tools();
    assert_eq!(tools.len(), 1);
    assert!(tools[0].starts_with("mcp__"));

    let output = host
        .call(&tools[0], &json!({"message": "from agent"}).to_string())
        .await
        .expect("call MCP through agent host");
    let output: serde_json::Value = serde_json::from_str(&output).expect("MCP output JSON");
    assert_eq!(output["server_name"], "mock");
    assert_eq!(output["tool_name"], "echo");
    assert_eq!(output["content"][0]["type"], "text");
    assert!(host.authority_metadata_by_name().contains_key(&tools[0]));

    fs::remove_dir_all(root).expect("remove MCP test root");
}

#[tokio::test]
async fn dynamic_mcp_tools_ignore_read_only_hints_and_redact_sensitive_audit_input() {
    let root = test_root("agent-tool-host-authority");
    let script = write_mock_server(&root);
    let python = python_executable();
    let store = DesktopSessionStore::in_memory().expect("session store");
    let supervisor = Arc::new(
        McpSupervisor::new(store.clone(), root.clone(), None, test_limits())
            .expect("MCP supervisor"),
    );
    let active_scope = scope("local-project");
    let server = supervisor
        .create_server(
            &active_scope,
            definition("Untrusted Read Hint", &python, &script, "normal"),
            "create-agent-tool-host-authority",
        )
        .expect("create MCP server");
    supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .expect("discover MCP tools");

    let mcp_host = Arc::new(
        McpAgentToolHost::new(
            Arc::clone(&supervisor),
            active_scope,
            "run-agent-tool-host-authority".to_string(),
            None,
        )
        .expect("agent MCP tool host"),
    );
    let tool = mcp_host.list_tools().pop().expect("discovered MCP tool");
    let metadata = mcp_host.authority_metadata_by_name();
    let tool_metadata = metadata.get(&tool).expect("MCP authority metadata");
    assert_eq!(tool_metadata.effect, ToolEffect::Mutate);
    for sensitive_field in [
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "password",
        "refresh_token",
        "secret",
        "token",
    ] {
        assert!(tool_metadata
            .sensitive_input_fields
            .contains(sensitive_field));
    }

    let read_run = running_run(
        &store,
        &root,
        "read-only-mcp",
        DesktopPermissionProfile::ReadOnly,
    )
    .expect("read-only run");
    let read_host = AuthorizedRunToolHost::with_dynamic_metadata(
        mcp_host.clone(),
        store.clone(),
        read_run,
        metadata.clone(),
    );
    assert!(!read_host.list_tools().contains(&tool));
    let read_error = read_host
        .call(&tool, r#"{"api_key":"fake-mcp-api-key"}"#)
        .await
        .expect_err("read-only profile must reject dynamic MCP tools");
    assert!(read_error
        .to_string()
        .contains("outside the approved permission profile"));

    let full_run = running_run(
        &store,
        &root,
        "full-access-mcp",
        DesktopPermissionProfile::FullAccess,
    )
    .expect("full-access run");
    let conversation_id = full_run.conversation_id.clone();
    let full_host =
        AuthorizedRunToolHost::with_dynamic_metadata(mcp_host, store.clone(), full_run, metadata);
    assert!(full_host.list_tools().contains(&tool));
    let input = json!({
        "api_key": "fake-mcp-api-key",
        "password": "fake-mcp-password",
        "nested": {"token": "fake-mcp-token"},
    });
    full_host
        .call(&tool, &input.to_string())
        .await
        .expect("full-access MCP call");

    let invocations = store
        .list_tool_invocations(&conversation_id)
        .expect("persisted MCP invocation");
    assert_eq!(invocations.len(), 1);
    assert_eq!(invocations[0].tool_name, tool);
    assert_eq!(invocations[0].effect, ToolEffect::Mutate);
    assert_eq!(invocations[0].status, InvocationStatus::Completed);
    assert_eq!(invocations[0].redacted_input["api_key"], "[REDACTED]");
    assert_eq!(invocations[0].redacted_input["password"], "[REDACTED]");
    assert_eq!(
        invocations[0].redacted_input["nested"]["token"],
        "[REDACTED]"
    );
    let serialized = serde_json::to_string(&invocations[0]).expect("serialize invocation");
    for secret in ["fake-mcp-api-key", "fake-mcp-password", "fake-mcp-token"] {
        assert!(!serialized.contains(secret));
    }

    fs::remove_dir_all(root).expect("remove MCP test root");
}

#[tokio::test]
async fn react_engine_dispatches_legacy_mcp_alias_without_advertising_it() {
    let root = test_root("agent-tool-host-legacy-alias");
    let script = write_mock_server(&root);
    let python = python_executable();
    let store = DesktopSessionStore::in_memory().expect("session store");
    let supervisor = Arc::new(
        McpSupervisor::new(store, root.clone(), None, test_limits()).expect("MCP supervisor"),
    );
    let active_scope = scope("local-project");
    let server = supervisor
        .create_server(
            &active_scope,
            definition("Desktop QA Echo", &python, &script, "normal"),
            "create-agent-tool-host-legacy-alias",
        )
        .expect("create MCP server");
    supervisor
        .list_tools(&active_scope, &server.id)
        .await
        .expect("discover MCP tools");

    let mcp_host = Arc::new(
        McpAgentToolHost::new(
            Arc::clone(&supervisor),
            active_scope,
            "run-agent-tool-host-legacy-alias".to_string(),
            None,
        )
        .expect("agent MCP tool host"),
    );
    let canonical = mcp_host.list_tools().pop().expect("canonical MCP tool");
    let legacy = legacy_exposed_tool_name(&server.id, "echo");
    let fan_out = Arc::new(FanOutToolHost::new(vec![mcp_host]));
    let agent = json!({
        "id": "builtin:all-access",
        "name": "Local Agent",
        "system_prompt": "Coordinate the selected resources.",
        "enabled": true,
        "status": "active",
        "allowed_tools": ["*"],
        "allowed_skills": ["*"],
        "allowed_mcp_servers": ["*"],
        "can_spawn": true,
        "spawn_policy": { "allowed_subagents": ["*"] }
    });
    let profile = ExecutionProfile::resolve("builtin:all-access", &agent, None, None)
        .expect("all-access profile");
    let profiled: Arc<dyn ToolHost> = Arc::new(ProfiledToolHost::new(fan_out, &profile));

    assert_eq!(profiled.list_tools(), [canonical]);
    assert!(!profiled.list_tools().contains(&legacy));
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![
            AgentAction::CallTool {
                tool: legacy.clone(),
                input_json: json!({"message": "legacy engine route"}).to_string(),
            },
            AgentAction::Finish {
                answer: "legacy alias completed".to_string(),
            },
        ])),
        profiled,
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(1_000)),
    );

    let state = engine
        .run(
            "session-agent-tool-host-legacy-alias",
            "Call the MCP echo tool",
            Some("local-project"),
        )
        .await
        .expect("legacy alias reaches MCP host");

    assert_eq!(state.completed_tool_calls.len(), 1);
    assert_eq!(state.completed_tool_calls[0].tool, legacy);
    assert!(state.completed_tool_calls[0]
        .output_json
        .contains("legacy engine route"));
    assert_eq!(state.answer.as_deref(), Some("legacy alias completed"));

    fs::remove_dir_all(root).expect("remove MCP test root");
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
                "annotations": {"readOnlyHint": True},
                "_meta": {"ui/resourceUri": "ui://mock/index.html"},
            }]
        }
    elif method == "tools/call":
        arguments = request.get("params", {}).get("arguments", {})
        result = {
            "content": [{"type": "text", "text": json.dumps(arguments, sort_keys=True)}],
        }
        if mode != "omit_is_error":
            result["isError"] = False
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

fn running_run(
    store: &DesktopSessionStore,
    workspace_root: &Path,
    label: &str,
    permission_profile: DesktopPermissionProfile,
) -> Result<DesktopRun, String> {
    let conversation = LocalConversation {
        id: format!("conversation-{label}-{}", Uuid::new_v4()),
        project_id: "local-project".to_string(),
        tenant_id: "local".to_string(),
        title: "MCP authority regression".to_string(),
        workspace_id: Some("local-workspace".to_string()),
        capability_mode: ConversationCapabilityMode::Code,
        current_mode: ConversationRunMode::Plan,
        created_at: super::now_iso(),
        updated_at: super::now_iso(),
    };
    store.insert_conversation(&conversation)?;
    store.replace_agent_plan_tasks(
        &conversation.id,
        &[json!({
            "id": format!("task-{label}-{}", Uuid::new_v4()),
            "conversation_id": conversation.id,
            "content": "Exercise MCP authorization",
            "status": "pending",
            "priority": "high",
            "order_index": 0,
            "created_at": super::now_iso(),
            "updated_at": super::now_iso(),
        })],
    )?;
    let plan = store
        .latest_draft_plan(&conversation.id)?
        .ok_or_else(|| "plan not found".to_string())?;
    let now = super::now_iso();
    let outcome = store
        .approve_plan_and_start_in_environment(ApprovePlanStartInput {
            conversation_id: &conversation.id,
            project_id: "local-project",
            plan_version_id: &plan.id,
            expected_plan_version: plan.version,
            idempotency_key: label,
            message_id: label,
            request_message: "Run approved MCP tool",
            environment: Some(DesktopExecutionEnvironment {
                id: format!("environment-{label}"),
                kind: DesktopExecutionEnvironmentKind::Local,
                label: "Authorized local environment".to_string(),
                workspace_path: workspace_root.to_string_lossy().into_owned(),
                repository_root: None,
                branch: None,
                base_commit: None,
                source_run_id: None,
                created_at: now.clone(),
            }),
            requested_environment_kind: DesktopExecutionEnvironmentKind::Local,
            permission_profile,
            now: &now,
        })
        .map_err(|error| error.to_string())?;
    let run = store
        .prepare_run_for_execution(&outcome.run.id, &super::now_iso())?
        .ok_or_else(|| "run did not start".to_string())?;
    if run.status != DesktopRunStatus::Running {
        return Err("run is not active".to_string());
    }
    Ok(run)
}

fn test_limits() -> SupervisorLimits {
    SupervisorLimits {
        request_timeout: Duration::from_millis(750),
        initialize_timeout: Duration::from_millis(750),
        retry_base: Duration::from_millis(10),
        retry_max: Duration::from_millis(20),
        max_request_bytes: 128 * 1024,
        max_response_bytes: 256 * 1024,
        max_frame_bytes: 256 * 1024,
        max_aggregate_bytes: 512 * 1024,
        tool_call_lease_duration: Duration::from_secs(4),
        tool_call_wait_timeout: Duration::from_millis(500),
        tool_call_poll_interval: Duration::from_millis(10),
    }
}

#[tokio::test]
async fn tool_call_without_is_error_defaults_to_success_and_replays_receipt() {
    let root = test_root("tool-call-optional-is-error");
    let script = write_mock_server(&root);
    let python = python_executable();
    let store = DesktopSessionStore::in_memory().expect("session store");
    let supervisor =
        McpSupervisor::new(store, root.clone(), None, test_limits()).expect("MCP supervisor");
    let active_scope = scope("local-project");
    let server = supervisor
        .create_server(
            &active_scope,
            definition("optional-is-error", &python, &script, "omit_is_error"),
            "create-optional-is-error",
        )
        .expect("create MCP server");

    let first = supervisor
        .call_tool(
            &active_scope,
            &server.id,
            "echo",
            json!({"message": "optional isError"}),
            "call-optional-is-error",
        )
        .await
        .expect("call MCP tool without isError");
    assert!(!first.is_error);
    assert!(!first.duplicate);
    assert!(first.result.get("isError").is_none());
    assert_eq!(first.content[0]["type"], "text");

    let replay = supervisor
        .call_tool(
            &active_scope,
            &server.id,
            "echo",
            json!({"message": "optional isError"}),
            "call-optional-is-error",
        )
        .await
        .expect("replay persisted MCP tool receipt");
    assert!(!replay.is_error);
    assert!(replay.duplicate);
    assert_eq!(replay.result, first.result);

    fs::remove_dir_all(root).expect("remove MCP test root");
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
                "call-echo-once",
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
                "call-echo-once",
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
                "call-echo-after-restart",
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
                initialize_timeout: Duration::from_secs(1),
                request_timeout: Duration::from_secs(1),
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
            "same-key",
        )
        .await
        .expect("initial idempotent call");
    let conflict = supervisor
        .call_tool(
            &active_scope,
            &healthy.id,
            "echo",
            json!({"value": 2}),
            "same-key",
        )
        .await
        .expect_err("conflicting idempotency replay");
    assert_eq!(conflict.reason_code(), "local_mcp_idempotency_conflict");

    let remote = supervisor
        .create_server(
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
        )
        .expect("HTTP definition is accepted before runtime resolution");
    assert_eq!(remote.runtime_status, "stopped");

    fs::remove_dir_all(root).expect("remove MCP failure test root");
}
