use super::*;
use crate::local_runtime::{
    execution_authority::ScopedExecution,
    mcp_agent_tool_host::McpAgentToolHost,
    mcp_supervisor::{McpServerDefinitionInput, McpTransport},
};
use agistack_core::ports::{ToolHost, ToolResult};
use async_trait::async_trait;
use std::{
    collections::BTreeMap,
    sync::atomic::{AtomicBool, AtomicUsize, Ordering},
};

struct Execution {
    scope: ExecutionScope,
    allowed: Vec<String>,
    active: AtomicBool,
    permitted: AtomicBool,
    calls: AtomicUsize,
    tools: McpAgentToolHost,
}

struct NoBrowserTools;

#[async_trait]
impl ToolHost for NoBrowserTools {
    fn list_tools(&self) -> Vec<String> {
        Vec::new()
    }
    async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
        Err(denied("physical_browser_unavailable"))
    }
}
#[async_trait]
impl ScopedExecution for Execution {
    fn scope(&self) -> &ExecutionScope {
        &self.scope
    }
    fn current(&self) -> CoreResult<()> {
        if self.active.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(denied("revoked"))
        }
    }
    fn allowed_mcp_servers(&self) -> Vec<String> {
        self.allowed.clone()
    }
    async fn call(&self, tool: &str, input: &str) -> CoreResult<ToolResult> {
        assert_eq!(call_identity::active()?.engine_session_id(), "engine");
        assert!(crate::local_runtime::execution_authority::current_step_id().is_some());
        if !self.permitted.load(Ordering::SeqCst) {
            return Err(denied("approval_required"));
        }
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.tools.call_with_content(tool, input).await
    }
}

#[tokio::test]
async fn app_calls_reauthorize_exact_tool_and_expire_with_scope_catalog_or_run() {
    for cloud in [false, true] {
        let root = std::env::temp_dir().join(format!("mcp-app-authority-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        let script = root.join("app.py");
        std::fs::write(&script, r#"import json,sys
for line in sys.stdin:
 r=json.loads(line)
 if 'id' not in r: continue
 m=r['method']; p=r.get('params',{})
 if m=='initialize': result={'protocolVersion':'2024-11-05','capabilities':{'tools':{},'resources':{}},'serverInfo':{'name':'owned-app','version':'1'}}
 elif m=='tools/list': result={'tools':[{'name':'render','inputSchema':{'type':'object'},'_meta':{'ui/resourceUri':'ui://owned/app.html'}},{'name':'write','inputSchema':{'type':'object'},'annotations':{'readOnlyHint':True},'_meta':{'ui/resourceUri':'ui://owned/app.html','visibility':['app']}},{'name':'hidden','inputSchema':{'type':'object'}}]}
 elif m=='tools/call': result={'content':[{'type':'text','text':json.dumps({'name':p['name'],'arguments':p['arguments']})}]}
 elif m=='resources/read': result={'contents':[{'uri':'ui://owned/app.html','mimeType':'text/html','text':'<button>owned</button>'}]}
 else: result={}
 print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)
"#).unwrap();
        let python = std::env::split_paths(&std::env::var_os("PATH").unwrap())
            .map(|entry| entry.join("python3"))
            .find(|path| path.is_file())
            .unwrap()
            .canonicalize()
            .unwrap();
        let state = crate::local_runtime::tests::test_state("mcp-app-authority");
        let scope = McpScope {
            tenant_id: "local-tenant".into(),
            project_id: "local-project".into(),
        };
        let definition = McpServerDefinitionInput {
            name: "owned-app".into(),
            description: None,
            transport: McpTransport::Stdio,
            command: vec![
                python.to_string_lossy().into(),
                script.to_string_lossy().into(),
            ],
            cwd: None,
            vault_env_refs: BTreeMap::new(),
            enabled: true,
        };
        let server = state
            .mcp_supervisor
            .create_server(&scope, definition.clone(), "create")
            .unwrap();
        state
            .mcp_supervisor
            .list_tools(&scope, &server.id)
            .await
            .unwrap();
        let app = state
            .mcp_supervisor
            .list_apps(&scope)
            .unwrap()
            .into_iter()
            .find(|app| app.tool_name == "render")
            .unwrap();
        let execution = Arc::new(Execution {
            scope: ExecutionScope {
                tenant_id: scope.tenant_id.clone(),
                project_id: scope.project_id.clone(),
                conversation_id: "conversation".into(),
                run_id: "run".into(),
                run_revision: 1,
                engine_session_id: "engine".into(),
                device_id: Some("device".into()),
                connection_epoch: cloud.then_some(7),
                generation: 1,
            },
            allowed: vec![server.id.clone()],
            active: AtomicBool::new(true),
            permitted: AtomicBool::new(false),
            calls: AtomicUsize::new(0),
            tools: McpAgentToolHost::new(
                state.mcp_supervisor.clone(),
                scope.clone(),
                "run".into(),
                None,
            )
            .unwrap(),
        });
        let authority = Arc::new(if cloud {
            ExecutionAuthority::CloudClaim(execution.clone())
        } else {
            ExecutionAuthority::LocalRun(execution.clone())
        });
        let registry = &state.mcp_app_automation;
        registry.register_authority(authority.clone());
        assert!(registry
            .open(&state, "run", "other-conversation", &app)
            .is_err());
        let tab = call_identity::scope(
            &agistack_core::agent::tool_policy::ToolPolicyContext {
                session_id: "engine",
                round: 1,
                tool: "render",
            },
            async { registry.open(&state, "run", "conversation", &app) },
        )
        .await
        .unwrap();
        let call = json!({"tabId":tab,"operation":"tools/call","mountNonce":"fixture-mount","arguments":{"name":"write","arguments":{"record":"exact-owned-value"}}});
        assert!(registry
            .renderer_operation(&state, call.clone())
            .await
            .is_err());
        registry
            .renderer_operation(
                &state,
                json!({"tabId":tab,"operation":"attach","mountNonce":"fixture-mount"}),
            )
            .await
            .unwrap();
        assert_eq!(
            registry
                .list(&state, &execution.scope)
                .as_array()
                .unwrap()
                .len(),
            1
        );
        let model_tab = registry.list(&state, &execution.scope)[0]["id"]
            .as_str()
            .unwrap()
            .to_string();
        assert_ne!(model_tab, tab, "renderer slots are never browser handles");
        assert!(registry
            .require_browser(&state, &tab, &execution.scope)
            .is_err());
        call_identity::scope(
            &agistack_core::agent::tool_policy::ToolPolicyContext {
                session_id: "engine",
                round: 2,
                tool: "browser_read_operation",
            },
            async {
                let tab = model_tab.as_str();
                // An attached MCP app must remain discoverable when Chrome, Edge
                // and IAB tab hosts are absent from the underlying tool surface.
                assert!(state.connected_browser_tool_host().is_none());
                let host = wrap_tools(
                    Arc::new(NoBrowserTools),
                    Arc::downgrade(&state),
                    "run".into(),
                );
                for tool in [
                    "browser_read_operation",
                    "browser_write_operation",
                    "browser_cdp_operation",
                ] {
                    assert!(host.can_dispatch(tool));
                    assert!(host.tool_definition(tool).is_some());
                }
                let inventory: Value = serde_json::from_str(
                    &host
                        .call("browser_read_operation", r#"{"operation":"browsers.list"}"#)
                        .await
                        .unwrap(),
                )
                .unwrap();
                assert_eq!(
                    inventory,
                    json!([{"id":"mcpapps","type":"mcpapps","backend":"mcpapps"}])
                );
                let listed: Value = serde_json::from_str(
                    &host
                        .call(
                            "browser_read_operation",
                            r#"{"operation":"tabs.list","browserId":"mcpapps"}"#,
                        )
                        .await
                        .unwrap(),
                )
                .unwrap();
                assert_eq!(listed["tabs"][0]["id"], tab);
                let title = host
                    .call(
                        "browser_read_operation",
                        &json!({
                            "operation":"tab.title","browserId":"mcpapps","tabId":tab,
                        })
                        .to_string(),
                    )
                    .await
                    .unwrap();
                assert_eq!(serde_json::from_str::<Value>(&title).unwrap(), "render");
                assert!(host
                    .call(
                        "browser_write_operation",
                        &json!({
                            "operation":"tab.goto","browserId":"mcpapps","tabId":tab,
                            "args":["https://unrelated.example/"],
                        })
                        .to_string()
                    )
                    .await
                    .unwrap_err()
                    .to_string()
                    .contains("unsupported"));
                assert!(host
                    .call(
                        "browser_cdp_operation",
                        &json!({
                            "operation":"capability.cdp.send","browserId":"mcpapps","tabId":tab,
                            "args":["Runtime.evaluate",{"expression":"1"}],
                        })
                        .to_string()
                    )
                    .await
                    .is_err());
                assert!(host
                    .call(
                        "browser_read_operation",
                        &json!({
                            "operation":"tab.title","browserId":"mcpapps","tabId":"foreign",
                        })
                        .to_string()
                    )
                    .await
                    .is_err());
                execution.active.store(false, Ordering::SeqCst);
                assert!(host
                    .call(
                        "browser_read_operation",
                        &json!({
                            "operation":"tab.title","browserId":"mcpapps","tabId":tab,
                        })
                        .to_string()
                    )
                    .await
                    .is_err());
                execution.active.store(true, Ordering::SeqCst);
                registry
                    .validate_operation_for_run(&state, "run", &json!({"operation":"tabs.list"}))
                    .unwrap();
                registry
                    .validate_operation_for_run(
                        &state,
                        "run",
                        &json!({"operation":"tab.title","tabId":tab}),
                    )
                    .unwrap();
                assert!(registry
                    .validate_operation_for_run(
                        &state,
                        "run",
                        &json!({"operation":"tab.title","tabId":"foreign"})
                    )
                    .is_err());
                assert!(registry
                    .validate_operation_for_run(
                        &state,
                        "run",
                        &json!({"operation":"tab.goto","tabId":tab})
                    )
                    .is_err());
            },
        )
        .await;
        call_identity::scope(
            &agistack_core::agent::tool_policy::ToolPolicyContext {
                session_id: "sibling-engine",
                round: 2,
                tool: "browser_read_operation",
            },
            async {
                assert!(registry
                    .validate_operation_for_run(&state, "run", &json!({"operation":"tabs.list"}))
                    .is_err());
            },
        )
        .await;
        let mut other = execution.scope.clone();
        other.run_revision += 1;
        assert!(registry.list(&state, &other).as_array().unwrap().is_empty());
        assert!(registry.require(&state, &tab, Some(&other)).is_err());
        let denied_call = registry
            .renderer_operation(&state, call.clone())
            .await
            .unwrap_err();
        assert!(denied_call.to_string().contains("approval_required"));
        assert_eq!(execution.calls.load(Ordering::SeqCst), 0);
        execution.permitted.store(true, Ordering::SeqCst);
        let result = registry
            .renderer_operation(&state, call.clone())
            .await
            .unwrap();
        assert!(result["content"][0]["text"]
            .as_str()
            .unwrap()
            .contains("exact-owned-value"));
        assert_eq!(execution.calls.load(Ordering::SeqCst), 1);
        let mut hidden = call.clone();
        hidden["arguments"]["name"] = json!("hidden");
        assert!(registry.renderer_operation(&state, hidden).await.is_err());
        assert_eq!(execution.calls.load(Ordering::SeqCst), 1);
        registry
            .renderer_operation(
                &state,
                json!({"tabId":tab,"operation":"detach","mountNonce":"fixture-mount"}),
            )
            .await
            .unwrap();
        assert!(registry
            .renderer_operation(&state, call.clone())
            .await
            .is_err());
        assert!(registry
            .browser_operation(&state, &authority, &model_tab, "tab.title", json!([]))
            .await
            .unwrap_err()
            .to_string()
            .contains("frame_expired"));
        registry
            .renderer_operation(
                &state,
                json!({"tabId":tab,"operation":"attach","mountNonce":"fixture-remount"}),
            )
            .await
            .unwrap();
        let new_model_tab = registry.list(&state, &execution.scope)[0]["id"]
            .as_str()
            .unwrap()
            .to_string();
        assert_ne!(new_model_tab, model_tab);
        assert!(registry
            .browser_operation(&state, &authority, &model_tab, "tab.title", json!([]))
            .await
            .unwrap_err()
            .to_string()
            .contains("frame_expired"));
        assert_eq!(
            registry
                .browser_operation(&state, &authority, &new_model_tab, "tab.title", json!([]))
                .await
                .unwrap(),
            "render"
        );
        // Duplicate attach for the same live registration is idempotent.
        registry
            .renderer_operation(
                &state,
                json!({"tabId":tab,"operation":"attach","mountNonce":"fixture-remount"}),
            )
            .await
            .unwrap();
        assert_eq!(
            registry.list(&state, &execution.scope)[0]["id"],
            new_model_tab
        );
        execution.active.store(false, Ordering::SeqCst);
        assert!(registry
            .renderer_operation(&state, call.clone())
            .await
            .is_err());
        execution.active.store(true, Ordering::SeqCst);
        let changed = state
            .mcp_supervisor
            .update_server(&scope, &server.id, definition, server.revision, "replace")
            .unwrap();
        assert!(registry.renderer_operation(&state, call).await.is_err());
        assert!(registry
            .browser_operation(&state, &authority, &new_model_tab, "tab.title", json!([]))
            .await
            .is_err());
        let mut reset_scope = execution.scope.clone();
        reset_scope.generation += 1;
        reset_scope.run_revision += 1;
        let reset_execution = Arc::new(Execution {
            scope: reset_scope.clone(),
            allowed: vec![server.id.clone()],
            active: AtomicBool::new(true),
            permitted: AtomicBool::new(true),
            calls: AtomicUsize::new(0),
            tools: McpAgentToolHost::new(
                state.mcp_supervisor.clone(),
                scope.clone(),
                "run".into(),
                None,
            )
            .unwrap(),
        });
        let reset_authority = Arc::new(if cloud {
            ExecutionAuthority::CloudClaim(reset_execution)
        } else {
            ExecutionAuthority::LocalRun(reset_execution)
        });
        registry.register_authority(reset_authority.clone());
        assert!(registry
            .require_browser(&state, &new_model_tab, &reset_scope)
            .err()
            .unwrap()
            .to_string()
            .contains("scope_mismatch"));
        assert_eq!(execution.calls.load(Ordering::SeqCst), 1);
        drop(authority);
        drop(execution);
        state
            .mcp_supervisor
            .delete_server(&scope, &server.id, changed.revision, "cleanup")
            .unwrap();
        std::fs::remove_dir_all(root).unwrap();
    }
}
