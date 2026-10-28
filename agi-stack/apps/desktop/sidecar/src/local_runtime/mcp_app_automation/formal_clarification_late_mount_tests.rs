//! First mounts survive ordinary clarification before generic and exact consent.
use super::*;

struct ClarificationMountLlm {
    calls: AtomicUsize,
    ready: Notify,
    gate: Notify,
    finish: Notify,
    results: Mutex<Vec<Value>>,
}

const CLAIM_CODE: &str = "var clarificationTab = await cua.getTab({url:'ui://callback/main.html'}, {browser:'mcpapps'}); [clarificationTab.id, await clarificationTab.title(), await clarificationTab.playwright.domSnapshot()]";

#[async_trait]
impl LlmPort for ClarificationMountLlm {
    async fn extract_memory(&self, _: &Episode) -> CoreResult<MemoryDraft> {
        unreachable!()
    }
    async fn decide(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        unreachable!()
    }
    async fn decide_with_tools(
        &self,
        _: &str,
        _: u64,
        transcript: &[TranscriptEntry],
        _: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        match self.calls.fetch_add(1, Ordering::SeqCst) {
            0 => {
                let mut decision = crate::local_runtime::tests::test_decision_context();
                decision.action.name = "cua_repl_js".into();
                decision.target.kind = "tool".into();
                decision.target.id = "cua_repl_js".into();
                Ok(AgentAction::RequestHuman {
                    request: HitlRequest::new(
                        "clarification-generic-permission",
                        HitlKind::Permission,
                        "Allow the CUA tool once?",
                    )
                    .with_decision(decision),
                })
            }
            1 => {
                self.ready.notify_one();
                self.gate.notified().await;
                Ok(AgentAction::CallTool {
                    tool: "cua_repl_js".into(),
                    input_json: json!({"code":CLAIM_CODE,"timeout_ms":15000}).to_string(),
                })
            }
            call @ (2 | 4) => {
                let result = transcript
                    .iter()
                    .rev()
                    .filter_map(|entry| serde_json::from_str::<Value>(&entry.content).ok())
                    .find(|value| {
                        value.get("cell_id").is_some()
                            || value["error"] == "repl_tool_permission_required"
                    })
                    .unwrap_or_else(|| panic!("expected public CUA result: {transcript:?}"));
                self.results.lock().unwrap().push(result.clone());
                if call == 2 && result["error"] == "repl_tool_permission_required" {
                    let mut decision = crate::local_runtime::tests::test_decision_context();
                    decision.action.name = result["tool_name"].as_str().unwrap().into();
                    decision.target.kind = "repl_step".into();
                    decision.target.id = result["step_id"].as_str().unwrap().into();
                    Ok(AgentAction::RequestHuman {
                        request: HitlRequest::new(
                            "clarification-claim-permission",
                            HitlKind::Permission,
                            "Allow this exact pending tab claim once?",
                        )
                        .with_decision(decision),
                    })
                } else {
                    self.ready.notify_one();
                    self.finish.notified().await;
                    Ok(AgentAction::Finish {
                        answer: "Clarification mount checked".into(),
                    })
                }
            }
            3 => Ok(AgentAction::CallTool {
                tool: "cua_repl_js".into(),
                input_json: json!({"code":CLAIM_CODE,"timeout_ms":15000}).to_string(),
            }),
            _ => panic!("unexpected clarification mount model call"),
        }
    }
}

async fn pending_request(fixture: &FormalFixture) -> DesktopHitlRequest {
    tokio::time::timeout(Duration::from_secs(15), async {
        loop {
            let request = fixture
                .state
                .session_store
                .list_hitl_requests(&fixture.conversation.id)
                .unwrap()
                .into_iter()
                .find(|request| request.status == DesktopHitlStatus::Pending);
            let waiting = fixture
                .state
                .session_store
                .run(&fixture.run.id)
                .unwrap()
                .unwrap();
            if let Some(request) = request {
                if waiting.status == DesktopRunStatus::NeedsApproval
                    && !fixture
                        .state
                        .agent_runs
                        .lock()
                        .unwrap()
                        .contains_key(&fixture.conversation.id)
                {
                    return request;
                }
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap()
}

async fn approve(fixture: &FormalFixture, request: &DesktopHitlRequest, key: &str) {
    let mut response = command(request, true);
    response["idempotency_key"] = json!(key);
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        response,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
}

#[tokio::test]
async fn formal_clarification_first_mount_without_cancel_survives_generic_approval() {
    clarification_first_mount(false).await;
}

#[tokio::test]
async fn formal_clarification_first_mount_after_strict_cleanup_survives_generic_approval() {
    clarification_first_mount(true).await;
}

async fn clarification_first_mount(cancel_old: bool) {
    let fixture = FormalFixture::with_attachment(false).await;
    let broker = cross_cell::attach_dom_bridge(&fixture).await;
    let request = super::super::clarification_tests::clarification(&fixture).await;
    let registry = &fixture.state.mcp_app_automation;
    registry.authorities.lock().unwrap().insert(
        (
            fixture.original_scope.run_id.clone(),
            fixture.original_scope.engine_session_id.clone(),
        ),
        Weak::new(),
    );
    if cancel_old {
        registry
            .cancel_mount(&fixture.renderer_id, "strict-old")
            .unwrap();
    }
    let attach =
        json!({"tabId":fixture.renderer_id,"operation":"attach","mountNonce":"clarification-new"});
    let waiting_attach = registry
        .renderer_operation(&fixture.state, attach.clone())
        .await;
    if cancel_old {
        registry
            .cancel_mount(&fixture.renderer_id, "strict-old")
            .unwrap();
    }
    let old_nonce_rejected = registry
        .attach_mount(&fixture.state, &fixture.renderer_id, "strict-old")
        .is_err();
    let waiting_tab = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    let waiting_call_rejected = registry.renderer_operation(&fixture.state, json!({
        "tabId":fixture.renderer_id,"operation":"resources/list","mountNonce":"clarification-new",
    })).await.is_err();
    let llm = Arc::new(ClarificationMountLlm {
        calls: AtomicUsize::new(0),
        ready: Notify::new(),
        gate: Notify::new(),
        finish: Notify::new(),
        results: Mutex::new(vec![]),
    });
    *fixture.state.test_llm_override.lock().unwrap() = Some(llm.clone());
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        super::super::clarification_tests::answer(&request, json!("The original App is mounted.")),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    let generic = pending_request(&fixture).await;
    let after_clarification = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    let generic_waiting_attach = registry
        .renderer_operation(&fixture.state, attach.clone())
        .await;
    let clarification_permissions = fixture
        .state
        .run_once_tool_permissions
        .lock()
        .unwrap()
        .len();
    approve(&fixture, &generic, "clarification-generic-once").await;
    tokio::time::timeout(Duration::from_secs(15), llm.ready.notified())
        .await
        .unwrap();
    let current_attach = registry.renderer_operation(&fixture.state, attach).await;
    let current_tab = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    llm.gate.notify_one();
    tokio::time::timeout(Duration::from_secs(15), async {
        loop {
            if !llm.results.lock().unwrap().is_empty() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    let first = llm.results.lock().unwrap()[0].clone();
    if first["error"] == "repl_tool_permission_required" {
        let exact = pending_request(&fixture).await;
        approve(&fixture, &exact, "clarification-exact-claim-once").await;
    }
    tokio::time::timeout(Duration::from_secs(15), llm.ready.notified())
        .await
        .unwrap();
    let results = llm.results.lock().unwrap().clone();
    let completed = results.last().unwrap().clone();
    let counts = fixture.counts().await;
    let original_revision = fixture.original_scope.run_revision;
    fixture
        .state
        .browser_bridge
        .lock()
        .unwrap()
        .take()
        .unwrap()
        .stop();
    broker.abort();
    llm.finish.notify_one();
    tokio::time::timeout(Duration::from_secs(10), async {
        while fixture
            .state
            .agent_runs
            .lock()
            .unwrap()
            .contains_key(&fixture.conversation.id)
        {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    fixture.finish(None).await;
    println!(
        "clarification_mount_probe {}",
        json!({
            "cancel_old":cancel_old,
            "waiting_attach_ok":waiting_attach.is_ok(),
            "waiting_cancelled":waiting_tab.mount_cancelled,
            "waiting_nonce":waiting_tab.mount_nonce,
            "clarification_revision_delta":after_clarification.scope.run_revision-original_revision,
            "generic_waiting_attach_ok":generic_waiting_attach.is_ok(),
            "current_attach_ok":current_attach.is_ok(),
            "generic_revision_delta":current_tab.scope.run_revision-original_revision,
            "first_public_error":first["error"],
            "completed_ok":completed["ok"],
            "counts":counts,
        })
    );
    assert_eq!(
        completed["ok"], true,
        "public getTab must survive: {completed}"
    );
    assert_eq!(
        completed["value"],
        json!([
            current_tab.registration,
            "render_main",
            "<main>callback fixture</main>"
        ])
    );
    assert_eq!(waiting_attach.unwrap()["pending"], true);
    assert!(!waiting_tab.attached && waiting_tab.registration.is_none());
    assert!(!waiting_tab.mount_cancelled);
    assert_eq!(
        waiting_tab.mount_nonce.as_deref(),
        Some("clarification-new")
    );
    assert!(old_nonce_rejected && waiting_call_rejected);
    assert_eq!(clarification_permissions, 0);
    assert_eq!(
        after_clarification.scope.run_revision,
        original_revision + 2
    );
    assert_eq!(current_tab.scope.run_revision, original_revision + 4);
    assert_eq!(first["tool_name"], "browser_write_operation");
    assert_eq!(completed["cell_id"], first["repl_continuation"]["cell_id"]);
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
}
