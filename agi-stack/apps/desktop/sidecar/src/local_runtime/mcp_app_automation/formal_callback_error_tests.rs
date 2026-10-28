//! An approved queued local callback must expose a server revocation reason.
use super::*;

#[tokio::test]
async fn formal_local_callback_preserves_disabled_reason_after_http_approval() {
    let fixture = FormalFixture::new().await;
    let release = fixture.root.join("callback-release");
    let code = format!(
        "globalThis.errorStarts=(globalThis.errorStarts??0)+1; let errorFs=await import('node:fs/promises'); while(!(await errorFs.stat({}).catch(()=>null))) await new Promise(resolve=>setTimeout(resolve,10)); globalThis.errorStarts",
        json!(release),
    );
    let (pending, callback) = fixture.pending(&code).await;
    let request = fixture.wait_for_approval(&pending).await;
    let gate = Arc::new(Notify::new());
    let llm = fixture.llm_after(Some(code), Some(gate.clone()));
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    tokio::time::timeout(Duration::from_secs(15), llm.ready.notified())
        .await
        .unwrap();
    let scope = McpScope {
        tenant_id: fixture.conversation.tenant_id.clone(),
        project_id: fixture.conversation.project_id.clone(),
    };
    let server = fixture
        .state
        .mcp_supervisor
        .server(&scope, &fixture.server_id)
        .unwrap()
        .unwrap();
    fixture
        .state
        .mcp_supervisor
        .update_server(
            &scope,
            &fixture.server_id,
            McpServerDefinitionInput {
                name: server.name,
                description: server.description,
                transport: server.transport,
                command: server.command,
                cwd: server.cwd,
                vault_env_refs: server.vault_env_refs,
                enabled: false,
            },
            server.revision,
            "disable-approved-callback",
        )
        .unwrap();
    gate.notify_one();
    let error = tokio::time::timeout(Duration::from_secs(5), callback)
        .await
        .unwrap()
        .unwrap()
        .unwrap_err();
    let dispatched = fixture.root.join("callback-complete").exists();
    // Release only the test's Node wait. Never synthesize the MCP effect marker.
    std::fs::write(&release, "release").unwrap();
    tokio::time::timeout(Duration::from_secs(15), llm.ready.notified())
        .await
        .unwrap();
    let transcript = llm.observed.lock().unwrap().clone();
    let observed = transcript
        .iter()
        .filter_map(|entry| serde_json::from_str::<Value>(entry).ok())
        .find(|value| value["cell_id"] == pending["repl_continuation"]["cell_id"])
        .expect("the original cell must resume");
    fixture.finish(Some(&llm)).await;
    assert!(!dispatched, "revoked callback reached the MCP server");
    assert_eq!(observed["ok"], true, "{observed}");
    assert_eq!(observed["value"], 1, "Node cell was restarted");
    match error {
        CoreError::Tool(reason) => assert_eq!(reason, "tool error: local_mcp_server_disabled"),
        other => panic!("unexpected error: {other}"),
    }
}
