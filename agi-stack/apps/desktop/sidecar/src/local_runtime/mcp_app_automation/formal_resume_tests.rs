//! Real Node and MCP processes cross the authenticated HTTP approval handler.
//! The LLM is scripted; continuation tools and authority are the production engine's.
use super::super::*;
use super::{payload, SERVER};
use crate::local_runtime::{
    agent_boundary_v2::AgentBoundaryV2,
    authority_store::{DesktopHitlRequest, DesktopHitlStatus, DesktopRun, DesktopRunStatus},
    authorized_tool_host::AuthorizedRunToolHost,
    cua_repl,
    execution_profile::ProfiledToolHost,
    knowledge_authority_v2::agent_access::{self, RunAuthorization},
    local_router_with_generation_required,
    mcp_agent_tool_host::{legacy_exposed_tool_name, McpAgentToolHost},
    mcp_supervisor::{McpServerDefinitionInput, McpTransport},
    now_iso,
    tool_authority::{ToolEffect, ToolMetadata},
    LocalConversation,
};
use agistack_core::{
    agent::{
        tool_policy::ToolPolicyContext,
        types::{AgentAction, HitlKind, HitlRequest, SessionState, SessionStatus, TranscriptEntry},
    },
    model::Episode,
    ports::{LlmPort, MemoryDraft, ToolDefinition, ToolHost},
};
use async_trait::async_trait;
use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use std::{
    path::PathBuf,
    sync::atomic::{AtomicU64, AtomicUsize, Ordering},
    time::Duration,
};
use tokio::{sync::Notify, task::JoinHandle};
use tower::ServiceExt;

const LAUNCH: &str = "mcp-formal-resume-launch";

#[path = "browser_value_tests.rs"]
mod browser_value_tests;
#[path = "formal_callback_error_tests.rs"]
mod callback_error_tests;
#[path = "formal_clarification_tests.rs"]
mod clarification_tests;
#[path = "formal_control_callback_tests.rs"]
mod control_callback_tests;
#[path = "formal_generic_permission_tests.rs"]
mod generic_permission_tests;
#[path = "formal_read_wait_tests.rs"]
mod read_wait_tests;

struct ResumeLlm {
    code: Option<String>,
    before_call: Option<Arc<Notify>>,
    calls: AtomicUsize,
    observed: Mutex<Vec<String>>,
    ready: Notify,
    finish: Notify,
}

#[async_trait]
impl LlmPort for ResumeLlm {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!("this fixture only resumes an agent")
    }
    async fn decide(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        unreachable!("the production engine supplies tool definitions")
    }
    async fn decide_with_tools(
        &self,
        _: &str,
        _: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst);
        if let Some(code) = self.code.as_ref().filter(|_| call == 0) {
            if let Some(before_call) = &self.before_call {
                self.ready.notify_one();
                before_call.notified().await;
            }
            assert!(tools.iter().any(|tool| tool.name == "cua_repl_js"));
            return Ok(AgentAction::CallTool {
                tool: "cua_repl_js".into(),
                input_json: json!({"code":code,"timeout_ms":15000}).to_string(),
            });
        }
        *self.observed.lock().unwrap() = transcript
            .iter()
            .map(|entry| entry.content.clone())
            .collect();
        self.ready.notify_one();
        self.finish.notified().await;
        Ok(AgentAction::Finish {
            answer: "Formal MCP continuation checked".into(),
        })
    }
}

struct FormalFixture {
    state: Arc<LocalRuntimeState>,
    conversation: LocalConversation,
    run: DesktopRun,
    root: PathBuf,
    server_id: String,
    token: String,
    authorization: Arc<RunAuthorization>,
    host: Arc<dyn ToolHost>,
    mcp: Arc<McpAgentToolHost>,
    renderer_id: String,
    handle: String,
    original_scope: ExecutionScope,
    counts_round: AtomicU64,
}

impl FormalFixture {
    async fn new() -> Self {
        Self::with_attachment(true).await
    }

    async fn with_attachment(attached: bool) -> Self {
        let (state, conversation, run, root) = cua_repl::test_support::state(LAUNCH);
        state.mock_llm_enabled.store(1, Ordering::Release);
        state
            .ensure_authoritative_launch_checkpoint(&run)
            .await
            .unwrap();
        let wire: Value = serde_json::from_str(include_str!(
            "../../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
        ))
        .unwrap();
        let snapshot = agistack_plugin_host::parse_profile_snapshot_v2(&wire.to_string()).unwrap();
        let generation = crate::local_runtime::platform_plugin_sync_v2::desktop_loader(None, None)
            .stage(snapshot.clone())
            .await
            .unwrap();
        state
            .platform_plugin_authority_v2
            .publish_local_baseline(&snapshot, &wire, generation)
            .await;
        let (status, login) = post(&state, None, "/api/v1/auth/local-session", json!({})).await;
        assert_eq!(status, StatusCode::OK, "{login}");
        let token = login["access_token"].as_str().unwrap().to_owned();
        let auth = state
            .session_store
            .validate_session_credential(&token, chrono::Utc::now().timestamp_millis())
            .unwrap()
            .unwrap();
        let generation = Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        );
        let authorization = RunAuthorization::capture(
            auth,
            Some(generation.clone()),
            &conversation,
            &run.message_id,
            Some(&run.id),
        )
        .unwrap();

        // The fixture writes only its own marker after the real MCP effect.
        let marker = root.join("callback-complete");
        let script = root.join("server.py");
        let source = SERVER.replace("if name=='increment_main': counts['main']+=1", &format!(
            "if name=='increment_main':\n   counts['main']+=1\n   open({},'w').write(str(counts['main']))", json!(marker)
        ));
        std::fs::write(&script, source).unwrap();
        let python = std::env::split_paths(&std::env::var_os("PATH").unwrap())
            .map(|entry| entry.join("python3"))
            .find(|path| path.is_file())
            .unwrap()
            .canonicalize()
            .unwrap();
        let scope = McpScope {
            tenant_id: conversation.tenant_id.clone(),
            project_id: conversation.project_id.clone(),
        };
        let server = state
            .mcp_supervisor
            .create_server(
                &scope,
                McpServerDefinitionInput {
                    name: "formal-resume".into(),
                    description: None,
                    transport: McpTransport::Stdio,
                    command: vec![
                        python.to_string_lossy().into(),
                        script.to_string_lossy().into(),
                    ],
                    cwd: None,
                    vault_env_refs: Default::default(),
                    enabled: true,
                },
                "create-formal-resume",
            )
            .unwrap();
        state
            .mcp_supervisor
            .list_tools(&scope, &server.id)
            .await
            .unwrap();
        let mcp = Arc::new(
            McpAgentToolHost::new(
                state.mcp_supervisor.clone(),
                scope,
                run.id.clone(),
                Some(&[server.id.clone()]),
            )
            .unwrap()
            .with_app_events(
                state.clone(),
                conversation.id.clone(),
                run.message_id.clone(),
            ),
        );
        let host = agent_access::scope(Some(authorization.clone()), async {
            let profile = state.execution_profile(&conversation).unwrap();
            let boundary =
                AgentBoundaryV2::new(&state, &conversation, &run.message_id, &run.id, generation)
                    .unwrap();
            let mut metadata = mcp.authority_metadata_by_name();
            for (tool, effect) in [
                ("browser_read_operation", ToolEffect::Read),
                ("browser_write_operation", ToolEffect::Mutate),
                ("browser_cdp_operation", ToolEffect::Mutate),
            ] {
                metadata.insert(
                    tool.into(),
                    ToolMetadata {
                        name: tool.into(),
                        effect,
                        sensitive_input_fields: Default::default(),
                    },
                );
            }
            let facade =
                super::super::wrap_tools(mcp.clone(), Arc::downgrade(&state), run.id.clone());
            let profiled = Arc::new(ProfiledToolHost::new(facade, &profile));
            let authorized = Arc::new(
                AuthorizedRunToolHost::with_dynamic_metadata(
                    profiled,
                    state.session_store.clone(),
                    run.clone(),
                    metadata,
                )
                .with_permission_request_tools(mcp.list_tools())
                .with_once_permissions(state.run_once_tool_permissions.clone()),
            );
            cua_repl::wrap_tools(
                &state,
                authorized,
                &conversation,
                &run,
                &profile,
                Some(boundary),
            )
        })
        .await;
        let render = legacy_exposed_tool_name(&server.id, "render_main");
        call_identity::scope(
            &ToolPolicyContext {
                session_id: &conversation.id,
                round: 1,
                tool: &render,
            },
            mcp.call(&render, "{}"),
        )
        .await
        .unwrap();
        let event = state
            .session_store
            .timeline(&conversation.id, 100)
            .unwrap()
            .into_iter()
            .find(|event| event["type"] == "mcp_app_result")
            .unwrap();
        let renderer_id = event["payload"]["automation_tab_id"]
            .as_str()
            .unwrap()
            .to_owned();
        if attached {
            state
                .mcp_app_automation
                .renderer_operation(
                    &state,
                    json!({"tabId":renderer_id,"operation":"attach","mountNonce":"fixture-mount"}),
                )
                .await
                .unwrap();
        }
        let tab = state.mcp_app_automation.tabs.lock().unwrap()[&renderer_id].clone();
        Self {
            state,
            conversation,
            run,
            root,
            server_id: server.id,
            token,
            authorization,
            host,
            mcp,
            renderer_id,
            handle: tab.registration.unwrap_or_default(),
            original_scope: tab.scope,
            counts_round: AtomicU64::new(100),
        }
    }

    fn code(&self) -> String {
        let inspect =
            json!({"operation":"tab.url","browserId":"mcpapps","tabId":self.handle,"args":[]});
        format!("globalThis.formalStarts=(globalThis.formalStarts??0)+1; let formalBefore=await nodeRepl.rpc('browser.operation',{inspect}); let formalFs=await import('node:fs/promises'); while(!(await formalFs.stat({}).catch(()=>null))) await new Promise(resolve=>setTimeout(resolve,10)); let formalAfter=await nodeRepl.rpc('browser.operation',{inspect}); [globalThis.formalStarts,formalBefore,formalAfter]", json!(self.root.join("callback-complete")))
    }

    async fn pending(&self, code: &str) -> (Value, JoinHandle<CoreResult<Value>>) {
        self.pending_with(code, |state, input| {
            tokio::spawn(async move {
                state
                    .mcp_app_automation
                    .renderer_operation(&state, input)
                    .await
            })
        })
        .await
    }

    async fn pending_with(
        &self,
        code: &str,
        callback: impl FnOnce(Arc<LocalRuntimeState>, Value) -> JoinHandle<CoreResult<Value>>,
    ) -> (Value, JoinHandle<CoreResult<Value>>) {
        let host = self.host.clone();
        let conversation = self.conversation.id.clone();
        let input = json!({"code":code,"timeout_ms":15000}).to_string();
        let authorization = self.authorization.clone();
        let cell = tokio::spawn(async move {
            agent_access::scope(
                Some(authorization),
                call_identity::scope(
                    &ToolPolicyContext {
                        session_id: &conversation,
                        round: 2,
                        tool: "cua_repl_js",
                    },
                    host.call_with_content("cua_repl_js", &input),
                ),
            )
            .await
        });
        tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                if self
                    .state
                    .cua_repl
                    .active_context_for(&self.run.id, &self.conversation.id)
                    .is_some()
                {
                    break;
                }
                assert!(
                    !cell.is_finished(),
                    "Node must retain a live cell for the callback"
                );
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
        let callback = callback(
            self.state.clone(),
            json!({
                "tabId":self.renderer_id,"operation":"tools/call","mountNonce":"fixture-mount",
                "arguments":{"name":"increment_main","arguments":{"operation_id":"formal-once"}},
            }),
        );
        let output = tokio::time::timeout(Duration::from_secs(5), cell)
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        let output: Value = serde_json::from_str(&output.output_json).unwrap();
        assert_eq!(output["error"], "repl_tool_permission_required", "{output}");
        assert!(
            !callback.is_finished(),
            "the same callback must remain queued for approval"
        );
        (output, callback)
    }

    async fn wait_for_approval(&self, pending: &Value) -> DesktopHitlRequest {
        let mut decision = crate::local_runtime::tests::test_decision_context();
        decision.action.name = pending["tool_name"].as_str().unwrap().into();
        decision.target.kind = "repl_step".into();
        decision.target.id = pending["step_id"].as_str().unwrap().into();
        let mut checkpoint = SessionState::new(
            &self.conversation.id,
            &self.run.request_message,
            Some(&self.conversation.project_id),
        );
        checkpoint.status = SessionStatus::AwaitingInput;
        checkpoint.pending_hitl = Some(
            HitlRequest::new(
                "formal-permission",
                HitlKind::Permission,
                "Allow the exact pending callback?",
            )
            .with_decision(decision),
        );
        self.state.checkpoints.save(&checkpoint).await.unwrap();
        self.state
            .session_store
            .bind_checkpoint_authority(&self.run, &now_iso())
            .unwrap();
        let request = self
            .state
            .persist_pending_hitl(&self.conversation.id, Some(&self.run.id), &checkpoint)
            .unwrap()
            .unwrap();
        self.state
            .session_store
            .transition_run(
                &self.run.id,
                self.run.revision,
                DesktopRunStatus::NeedsApproval,
                None,
                &now_iso(),
            )
            .unwrap();
        request
    }

    fn llm(&self, code: Option<String>) -> Arc<ResumeLlm> {
        self.llm_after(code, None)
    }

    fn llm_after(&self, code: Option<String>, before_call: Option<Arc<Notify>>) -> Arc<ResumeLlm> {
        let llm = Arc::new(ResumeLlm {
            code,
            before_call,
            calls: AtomicUsize::new(0),
            observed: Mutex::new(vec![]),
            ready: Notify::new(),
            finish: Notify::new(),
        });
        *self.state.test_llm_override.lock().unwrap() = Some(llm.clone());
        llm
    }

    async fn counts(&self) -> Value {
        let tool = legacy_exposed_tool_name(&self.server_id, "inspect_counts");
        let value = call_identity::scope(
            &ToolPolicyContext {
                session_id: &self.conversation.id,
                round: self.counts_round.fetch_add(1, Ordering::SeqCst),
                tool: &tool,
            },
            self.mcp.call(&tool, "{}"),
        )
        .await
        .unwrap();
        payload(&serde_json::from_str(&value).unwrap())["counts"].clone()
    }

    async fn finish(self, llm: Option<&ResumeLlm>) {
        if let Some(llm) = llm {
            llm.finish.notify_one();
            tokio::time::timeout(Duration::from_secs(10), async {
                while self
                    .state
                    .agent_runs
                    .lock()
                    .unwrap()
                    .contains_key(&self.conversation.id)
                {
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            })
            .await
            .unwrap();
        }
        self.state.cua_repl.shutdown();
        self.state.platform_plugin_authority_v2.deactivate().await;
        let scope = McpScope {
            tenant_id: self.conversation.tenant_id.clone(),
            project_id: self.conversation.project_id.clone(),
        };
        let server = self
            .state
            .mcp_supervisor
            .server(&scope, &self.server_id)
            .unwrap()
            .unwrap();
        self.state
            .mcp_supervisor
            .delete_server(
                &scope,
                &self.server_id,
                server.revision,
                "cleanup-formal-resume",
            )
            .unwrap();
        std::fs::remove_dir_all(&self.root).unwrap();
    }
}

async fn post(
    state: &Arc<LocalRuntimeState>,
    token: Option<&str>,
    path: &str,
    body: Value,
) -> (StatusCode, Value) {
    let mut request = Request::builder()
        .method("POST")
        .uri(path)
        .header("x-agistack-launch", LAUNCH)
        .header("content-type", "application/json");
    if let Some(token) = token {
        request = request.header("authorization", format!("Bearer {token}"));
    }
    let response = local_router_with_generation_required(state.clone())
        .oneshot(request.body(Body::from(body.to_string())).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), 1024 * 1024)
        .await
        .unwrap();
    (status, serde_json::from_slice(&bytes).unwrap())
}

fn command(request: &DesktopHitlRequest, granted: bool) -> Value {
    json!({"request_id":request.id,"hitl_type":"permission","expected_revision":request.authority_revision,
        "idempotency_key":"formal-permission-response","response_data":{"action":if granted { "allow" } else { "deny" },"granted":granted,"scope":"once"}})
}

#[tokio::test]
async fn formal_http_approval_resumes_real_node_callback_once_in_the_original_app() {
    let fixture = FormalFixture::new().await;
    let code = fixture.code();
    let (pending, callback) = fixture.pending(&code).await;
    let request = fixture.wait_for_approval(&pending).await;
    let llm = fixture.llm(Some(code));
    assert_eq!(
        fixture.counts().await,
        json!({"main":0,"sibling":0,"hidden":0})
    );
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    assert_eq!(receipt["execution_status"], "running");
    assert_eq!(receipt["revision"], fixture.run.revision + 2);
    tokio::time::timeout(Duration::from_secs(15), llm.ready.notified())
        .await
        .unwrap();
    let transcript = llm.observed.lock().unwrap().clone();
    let observed = transcript
        .iter()
        .filter_map(|content| serde_json::from_str::<Value>(content).ok())
        .find(|value| value["cell_id"] == pending["repl_continuation"]["cell_id"])
        .unwrap_or_else(|| {
            panic!("new engine did not resume the original Node cell: {transcript:?}")
        });
    assert_eq!(observed["ok"], true, "{observed}");
    let output = tokio::time::timeout(Duration::from_secs(2), callback)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(payload(&output)["counts"]["main"], 1);
    assert_eq!(
        observed["value"],
        json!([1, "ui://callback/main.html", "ui://callback/main.html"])
    );
    let current = fixture
        .state
        .session_store
        .run(&fixture.run.id)
        .unwrap()
        .unwrap();
    assert_eq!(current.status, DesktopRunStatus::Running);
    assert_eq!(current.revision, fixture.run.revision + 2);
    let stored = fixture
        .state
        .session_store
        .hitl_request(&request.id)
        .unwrap()
        .unwrap();
    assert_eq!(stored.status, DesktopHitlStatus::Responded);
    assert_eq!(stored.response_data.as_ref().unwrap()["granted"], true);
    assert!(fixture
        .state
        .run_once_tool_permissions
        .lock()
        .unwrap()
        .is_empty());
    let registry = &fixture.state.mcp_app_automation;
    let tab = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    assert_eq!(tab.registration.as_deref(), Some(fixture.handle.as_str()));
    assert_eq!(tab.scope.run_revision, current.revision);
    assert_eq!(
        tab.continuation_revisions,
        BTreeSet::from([fixture.run.revision])
    );
    assert!(registry
        .require_browser(&fixture.state, &fixture.handle, &fixture.original_scope)
        .is_err());
    assert_eq!(
        registry.list(&fixture.state, &tab.scope)[0]["id"],
        fixture.handle
    );
    assert_eq!(registry.tabs.lock().unwrap().len(), 1);
    assert_eq!(
        fixture
            .state
            .session_store
            .timeline(&fixture.conversation.id, 100)
            .unwrap()
            .iter()
            .filter(|event| event["type"] == "mcp_app_result")
            .count(),
        1
    );
    let repeated = registry
        .renderer_operation(
            &fixture.state,
            json!({
                "tabId":fixture.renderer_id,"operation":"tools/call","mountNonce":"fixture-mount",
                "arguments":{"name":"increment_main","arguments":{"operation_id":"formal-once"}},
            }),
        )
        .await
        .unwrap();
    assert_eq!(repeated["error"], "repl_tool_permission_required");
    let (status, duplicate) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{duplicate}");
    assert_eq!(duplicate["duplicate"], true);
    assert_eq!(
        fixture.counts().await,
        json!({"main":1,"sibling":0,"hidden":0})
    );
    assert_eq!(llm.calls.load(Ordering::SeqCst), 2);
    fixture.finish(Some(&llm)).await;
}

#[tokio::test]
async fn forged_and_expired_steps_cannot_commit_http_approval_or_renew_the_app() {
    let fixture = FormalFixture::new().await;
    let (pending, callback) = fixture.pending(&fixture.code()).await;
    let mut forged = crate::local_runtime::tests::test_decision_context();
    forged.action.name = pending["tool_name"].as_str().unwrap().into();
    forged.target.kind = "repl_step".into();
    forged.target.id = "forged-step".into();
    let mut checkpoint = SessionState::new(
        &fixture.conversation.id,
        &fixture.run.request_message,
        Some(&fixture.conversation.project_id),
    );
    checkpoint.status = SessionStatus::AwaitingInput;
    checkpoint.pending_hitl = Some(
        HitlRequest::new("forged-permission", HitlKind::Permission, "Forged step")
            .with_decision(forged),
    );
    assert!(fixture
        .state
        .persist_pending_hitl(&fixture.conversation.id, Some(&fixture.run.id), &checkpoint)
        .unwrap_err()
        .contains("repl_step_permission_expired_or_mismatched"));
    assert!(fixture
        .state
        .session_store
        .hitl_request("forged-permission")
        .unwrap()
        .is_none());
    let request = fixture.wait_for_approval(&pending).await;
    fixture.state.cua_repl.cancel_run(&fixture.run.id);
    let llm = fixture.llm(None);
    let (status, body) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");
    assert!(body
        .to_string()
        .contains("repl_step_permission_expired_or_mismatched"));
    assert_eq!(
        fixture
            .state
            .session_store
            .hitl_request(&request.id)
            .unwrap()
            .unwrap()
            .status,
        DesktopHitlStatus::Pending
    );
    assert_eq!(
        fixture
            .state
            .session_store
            .run(&fixture.run.id)
            .unwrap()
            .unwrap()
            .status,
        DesktopRunStatus::NeedsApproval
    );
    assert_eq!(llm.calls.load(Ordering::SeqCst), 0);
    assert!(fixture
        .state
        .run_once_tool_permissions
        .lock()
        .unwrap()
        .is_empty());
    assert_eq!(
        fixture.state.mcp_app_automation.tabs.lock().unwrap()[&fixture.renderer_id].scope,
        fixture.original_scope
    );
    assert_eq!(fixture.counts().await["main"], 0);
    fixture.state.cua_repl.shutdown();
    assert!(tokio::time::timeout(Duration::from_secs(2), callback)
        .await
        .unwrap()
        .unwrap()
        .is_err());
    fixture.finish(None).await;
}

#[tokio::test]
async fn denied_http_approval_commits_without_renewing_the_app_or_dispatching_callback() {
    let fixture = FormalFixture::new().await;
    let (pending, callback) = fixture.pending(&fixture.code()).await;
    let request = fixture.wait_for_approval(&pending).await;
    let llm = fixture.llm(None);
    let (status, body) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, false),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    tokio::time::timeout(Duration::from_secs(10), llm.ready.notified())
        .await
        .unwrap();
    let stored = fixture
        .state
        .session_store
        .hitl_request(&request.id)
        .unwrap()
        .unwrap();
    assert_eq!(stored.status, DesktopHitlStatus::Responded);
    assert_eq!(stored.response_data.as_ref().unwrap()["granted"], false);
    let tab = fixture.state.mcp_app_automation.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    assert_eq!(tab.scope, fixture.original_scope);
    assert!(tab.continuation_revisions.is_empty());
    assert!(fixture
        .state
        .run_once_tool_permissions
        .lock()
        .unwrap()
        .is_empty());
    assert_eq!(fixture.counts().await["main"], 0);
    assert!(!callback.is_finished());
    fixture.state.cua_repl.shutdown();
    assert!(tokio::time::timeout(Duration::from_secs(2), callback)
        .await
        .unwrap()
        .unwrap()
        .is_err());
    fixture.finish(Some(&llm)).await;
}
