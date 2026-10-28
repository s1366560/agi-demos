//! The real UI can first mount an App while the run already awaits permission.
use super::*;

struct LateMountLlm {
    code: String,
    calls: AtomicUsize,
    gate: Notify,
    ready: Notify,
    finish: Notify,
    pending: Mutex<Option<Value>>,
    completed: Mutex<Option<Value>>,
}

#[async_trait]
impl LlmPort for LateMountLlm {
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
                self.ready.notify_one();
                self.gate.notified().await;
                Ok(AgentAction::CallTool {
                    tool: "cua_repl_js".into(),
                    input_json: json!({"code":self.code,"timeout_ms":15000}).to_string(),
                })
            }
            1 => {
                let pending = transcript
                    .iter()
                    .rev()
                    .filter_map(|entry| serde_json::from_str::<Value>(&entry.content).ok())
                    .find(|value| value["error"] == "repl_tool_permission_required")
                    .unwrap_or_else(|| panic!("expected actual pending claim: {transcript:?}"));
                let mut decision = crate::local_runtime::tests::test_decision_context();
                decision.action.name = pending["tool_name"].as_str().unwrap().into();
                decision.target.kind = "repl_step".into();
                decision.target.id = pending["step_id"].as_str().unwrap().into();
                *self.pending.lock().unwrap() = Some(pending);
                Ok(AgentAction::RequestHuman {
                    request: HitlRequest::new(
                        "late-mount-claim",
                        HitlKind::Permission,
                        "Allow the pending tab claim once?",
                    )
                    .with_decision(decision),
                })
            }
            2 => Ok(AgentAction::CallTool {
                tool: "cua_repl_js".into(),
                input_json: json!({"code":self.code,"timeout_ms":15000}).to_string(),
            }),
            3 => {
                let value = transcript
                    .iter()
                    .rev()
                    .filter_map(|entry| serde_json::from_str::<Value>(&entry.content).ok())
                    .find(|value| value.get("cell_id").is_some())
                    .unwrap_or_else(|| panic!("expected resumed cell: {transcript:?}"));
                *self.completed.lock().unwrap() = Some(value);
                self.ready.notify_one();
                self.finish.notified().await;
                Ok(AgentAction::Finish {
                    answer: "Late mount resumed".into(),
                })
            }
            _ => panic!("unexpected late mount model call"),
        }
    }
}

#[tokio::test]
async fn formal_generic_approval_allows_first_attachment_after_waiting_and_public_get_tab() {
    late_attachment(true).await;
}

#[tokio::test]
async fn formal_generic_approval_allows_strict_mode_remount_after_waiting_authority_expired() {
    late_attachment(false).await;
}

async fn late_attachment(waiting_authority_registered: bool) {
    let fixture = FormalFixture::with_attachment(false).await;
    let broker = super::cross_cell::attach_dom_bridge(&fixture).await;
    let request = generic_permission(&fixture).await;
    let registry = &fixture.state.mcp_app_automation;
    let attach =
        json!({"tabId":fixture.renderer_id,"operation":"attach","mountNonce":"late-mount"});
    if !waiting_authority_registered {
        registry.authorities.lock().unwrap().insert(
            (
                fixture.original_scope.run_id.clone(),
                fixture.original_scope.engine_session_id.clone(),
            ),
            Weak::new(),
        );
        // StrictMode can cancel the first effect before its registration arrives.
        registry
            .cancel_mount(&fixture.renderer_id, "strict-first-mount")
            .unwrap();
        assert!(registry
            .attach_mount(&fixture.state, &fixture.renderer_id, "strict-first-mount")
            .is_err());
    }
    assert_eq!(
        registry
            .renderer_operation(&fixture.state, attach.clone())
            .await
            .unwrap()["pending"],
        true
    );
    let waiting = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    assert!(!waiting.attached && waiting.registration.is_none());
    assert_eq!(waiting.mount_nonce.as_deref(), Some("late-mount"));
    assert_eq!(
        registry.list(&fixture.state, &fixture.original_scope),
        json!([])
    );
    let llm = Arc::new(LateMountLlm {
        code: "var lateTab = await cua.getTab({url:'ui://callback/main.html'}, {browser:'mcpapps'}); [lateTab.id, await lateTab.title(), await lateTab.playwright.domSnapshot()]".into(),
        calls: AtomicUsize::new(0), gate: Notify::new(), ready: Notify::new(),
        finish: Notify::new(), pending: Mutex::new(None), completed: Mutex::new(None),
    });
    *fixture.state.test_llm_override.lock().unwrap() = Some(llm.clone());
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    tokio::time::timeout(Duration::from_secs(10), llm.ready.notified())
        .await
        .unwrap();
    let before_attach = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    let attached = registry.renderer_operation(&fixture.state, attach).await;
    let handle = registry.tabs.lock().unwrap()[&fixture.renderer_id]
        .registration
        .clone();
    llm.gate.notify_one();
    let claim = tokio::time::timeout(Duration::from_secs(15), async {
        loop {
            let requests = fixture
                .state
                .session_store
                .list_hitl_requests(&fixture.conversation.id)
                .unwrap();
            if let Some(request) = requests
                .into_iter()
                .find(|request| request.status == DesktopHitlStatus::Pending)
            {
                if fixture
                    .state
                    .session_store
                    .run(&fixture.run.id)
                    .unwrap()
                    .unwrap()
                    .status
                    == DesktopRunStatus::NeedsApproval
                    && !fixture
                        .state
                        .agent_runs
                        .lock()
                        .unwrap()
                        .contains_key(&fixture.conversation.id)
                {
                    break request;
                }
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    let mut response = command(&claim, true);
    response["idempotency_key"] = json!("late-mount-claim-once");
    let (claim_status, claim_receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        response.clone(),
    )
    .await;
    assert_eq!(claim_status, StatusCode::OK, "{claim_receipt}");
    tokio::time::timeout(Duration::from_secs(15), llm.ready.notified())
        .await
        .unwrap();
    let (duplicate_status, duplicate) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        response,
    )
    .await;
    let pending = llm.pending.lock().unwrap().clone().unwrap();
    let completed = llm.completed.lock().unwrap().clone().unwrap();
    let counts = fixture.counts().await;
    let original = fixture.original_scope.clone();
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
    assert!(
        attached.is_ok(),
        "first attachment after approval: {attached:?}"
    );
    assert_eq!(before_attach.scope.run_revision, original.run_revision + 2);
    assert!(
        !before_attach.attached,
        "approval cannot fabricate an attached iframe"
    );
    assert!(
        before_attach.registration.is_none(),
        "first attach must issue the handle"
    );
    assert!(before_attach.continuation_revisions.is_empty());
    assert_eq!(pending["tool_name"], "browser_write_operation", "{pending}");
    assert_eq!(completed["ok"], true, "{completed}");
    assert_eq!(
        completed["cell_id"],
        pending["repl_continuation"]["cell_id"]
    );
    assert_eq!(
        completed["value"],
        json!([handle, "render_main", "<main>callback fixture</main>"])
    );
    assert_eq!(duplicate_status, StatusCode::OK);
    assert_eq!(duplicate["duplicate"], true);
    assert_eq!(llm.calls.load(Ordering::SeqCst), 4);
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
}

#[path = "pending_mount_tests.rs"]
mod pending_mount;
